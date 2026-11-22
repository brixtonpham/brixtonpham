"""CLI entrypoint for processing O an quan move issues and bootstrapping board state."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .engine import apply_move, net_score, new_game_state
from .readme_render import DEFAULT_REPO, render_readme_block, update_readme_text
from .svg_render import render_board_svg

MOVE_RE = re.compile(r"^oanquan\|g([1-9]\d*)\|t(\d+)\|([NS][1-5])\|([LR])$")
NEW_RE = re.compile(r"^oanquan\|new\|g([1-9]\d*)$")
MAX_MOVES_PER_HOUR = 10
CONSECUTIVE_EXEMPT_HOURS = 24
OWNER_LOGIN = "brixtonpham"


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _format_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _prune_hourly(timestamps: list[str], now: datetime) -> list[str]:
    cutoff = now - timedelta(hours=1)
    kept = []
    for ts in timestamps:
        dt = _parse_iso(ts)
        if dt is not None and dt > cutoff:
            kept.append(ts)
    return kept


def process_issue(
    state: dict[str, Any],
    *,
    title: str,
    user: str,
    user_type: str,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate and process one issue title against `state`.

    Returns (updated_state, result_dict) where result_dict has:
      - changed: bool
      - close_reason: "completed" | "not_planned"
      - comment: str
    """
    now_iso = _format_iso(now)
    profile_url = f"https://github.com/{OWNER_LOGIN}"

    if user_type != "User":
        return state, {
            "changed": False,
            "close_reason": "not_planned",
            "comment": f"Moves must be submitted by human GitHub accounts. Back to board: {profile_url}",
        }

    clean_title = title.strip()

    # Check new-game command first
    m_new = NEW_RE.match(clean_title)
    if m_new:
        req_gid = int(m_new.group(1))
        cur_gid = int(state["game_id"])
        if req_gid != cur_gid:
            return state, {
                "changed": False,
                "close_reason": "not_planned",
                "comment": f"Stale new-game request (currently on Game #{cur_gid}). Check the live board: {profile_url}",
            }
        if not state["game_over"] and user != OWNER_LOGIN:
            return state, {
                "changed": False,
                "close_reason": "not_planned",
                "comment": f"Game #{cur_gid} is still in progress! Make a move on the live board: {profile_url}",
            }
        rl = state.get("rate_limit", {})
        fresh_rl = {
            "last_mover": None,
            "last_move_at": None,
            "user_hourly": rl.get("user_hourly", {}),
        }
        next_state = new_game_state(
            game_id=cur_gid + 1,
            leaderboard=state.get("leaderboard"),
            rate_limit=fresh_rl,
        )
        return next_state, {
            "changed": True,
            "close_reason": "completed",
            "comment": f"Started **Ô ăn quan Game #{cur_gid + 1}**! South moves first: {profile_url}",
        }

    m_move = MOVE_RE.match(clean_title)
    if not m_move:
        return state, {
            "changed": False,
            "close_reason": "not_planned",
            "comment": f"Unrecognized move format. Please click a legal move link directly on the board: {profile_url}",
        }

    req_gid, req_turn, pit_name, direction = (
        int(m_move.group(1)),
        int(m_move.group(2)),
        m_move.group(3),
        m_move.group(4),
    )

    if state["game_over"]:
        return state, {
            "changed": False,
            "close_reason": "not_planned",
            "comment": f"Game #{state['game_id']} has already finished! Start a new game from {profile_url}",
        }

    if req_gid != int(state["game_id"]) or req_turn != int(state["turn"]):
        return state, {
            "changed": False,
            "close_reason": "not_planned",
            "comment": (
                f"Someone already played before this move (board is now Game #{state['game_id']}, "
                f"Turn {state['turn']}). Pick a fresh move at {profile_url}"
            ),
        }

    rl = state.get("rate_limit", {})
    last_mover = rl.get("last_mover")
    last_move_at = _parse_iso(rl.get("last_move_at"))
    if last_mover == user and last_move_at is not None:
        idle_hours = (now - last_move_at).total_seconds() / 3600.0
        if idle_hours < CONSECUTIVE_EXEMPT_HOURS:
            return state, {
                "changed": False,
                "close_reason": "not_planned",
                "comment": (
                    f"Thanks @{user}! To keep it a community game, please let someone else take the next turn "
                    f"(or come back if the board stays quiet for 24h). Live board: {profile_url}"
                ),
            }

    user_hourly = dict(rl.get("user_hourly", {}))
    recent_user_moves = _prune_hourly(list(user_hourly.get(user, [])), now)
    if len(recent_user_moves) >= MAX_MOVES_PER_HOUR:
        return state, {
            "changed": False,
            "close_reason": "not_planned",
            "comment": (
                f"Rate limit reached ({MAX_MOVES_PER_HOUR} moves/hour per player). "
                f"Try again a bit later! Live board: {profile_url}"
            ),
        }

    try:
        next_state, summary = apply_move(state, pit_name, direction, user, now_iso)
    except ValueError as exc:
        return state, {
            "changed": False,
            "close_reason": "not_planned",
            "comment": f"Illegal move ({exc}). Pick a highlighted move at {profile_url}",
        }

    # Prune all users' stale timestamps so state.json never grows unboundedly
    cleaned_hourly: dict[str, list[str]] = {}
    for login, stamps in user_hourly.items():
        pruned = _prune_hourly(list(stamps), now)
        if pruned:
            cleaned_hourly[login] = pruned
    cleaned_hourly.setdefault(user, []).append(now_iso)

    next_state["rate_limit"] = {
        "last_mover": user,
        "last_move_at": now_iso,
        "user_hourly": cleaned_hourly,
    }

    cap = int(summary["captured"])
    cap_msg = f" and captured **+{cap} pts**" if cap > 0 else ""
    refill_msg = (
        f" {summary['refilled'].title()} had no stones left and automatically refilled 5 stones (*rải dân*)."
        if summary.get("refilled")
        else ""
    )
    n_net = net_score(next_state, "north")
    s_net = net_score(next_state, "south")

    if next_state["game_over"]:
        winner = next_state["winner"]
        end_msg = (
            f"Both Quan bowls are empty — **draw ({n_net}–{s_net})**!"
            if winner == "draw"
            else f"Both Quan bowls are empty — **{str(winner).title()} wins (North {n_net} — South {s_net})**!"
        )
        comment = (
            f"@{user} played **`{summary['move']}`**{cap_msg}. {end_msg} "
            f"View the final board or start the next game: {profile_url}"
        )
    else:
        comment = (
            f"@{user} played **`{summary['move']}`**{cap_msg} "
            f"(Score: North {n_net} — South {s_net}).{refill_msg} "
            f"Now **{next_state['active_side'].title()}'s turn**: {profile_url}"
        )

    return next_state, {
        "changed": True,
        "close_reason": "completed",
        "comment": comment,
    }


def write_artifacts(
    state: dict[str, Any],
    state_dir: Path,
    readme_path: Path,
    repo: str = DEFAULT_REPO,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (state_dir / "board-light.svg").write_text(
        render_board_svg(state, "light"), encoding="utf-8"
    )
    (state_dir / "board-dark.svg").write_text(
        render_board_svg(state, "dark"), encoding="utf-8"
    )
    readme_text = readme_path.read_text(encoding="utf-8")
    updated = update_readme_text(readme_text, render_readme_block(state, repo=repo))
    readme_path.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Process an O an quan GitHub issue move.")
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--readme", required=True, type=Path)
    parser.add_argument("--result-json", type=Path)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--init", action="store_true", help="Bootstrap Game #1 artifacts.")
    args = parser.parse_args()

    state_file = args.state_dir / "state.json"
    if args.init:
        state = new_game_state(game_id=1)
        write_artifacts(state, args.state_dir, args.readme, repo=args.repo)
        return

    state = (
        json.loads(state_file.read_text(encoding="utf-8"))
        if state_file.exists()
        else new_game_state(game_id=1)
    )

    title = os.environ.get("ISSUE_TITLE", "")
    user = os.environ.get("ISSUE_USER", "")
    user_type = os.environ.get("ISSUE_USER_TYPE", "User")
    now = datetime.now(timezone.utc)

    next_state, result = process_issue(
        state, title=title, user=user, user_type=user_type, now=now
    )
    if result["changed"]:
        write_artifacts(next_state, args.state_dir, args.readme, repo=args.repo)

    if args.result_json:
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
