"""Pure, deterministic rules engine for Vietnamese O an quan (Mandarin Square Capturing).

Board topology (12-cell clockwise ring, indices 0..11):
    0: West Quan (semicircle, starts with quan=True [10 pts], dan=0)
    1..5: North side N1..N5 left-to-right (each starts with dan=5)
    6: East Quan (semicircle, starts with quan=True [10 pts], dan=0)
    7..11: South side S5..S1 right-to-left (visually S1(11)..S5(7) left-to-right, each dan=5)

Visual direction mapping (L = left on screen, R = right on screen):
    North (1..5): R -> +1 mod 12 (clockwise), L -> -1 mod 12 (counter-clockwise)
    South (11..7): R -> -1 mod 12 (counter-clockwise), L -> +1 mod 12 (clockwise)
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

QUAN_VALUE = 10
QUAN_INDICES = (0, 6)
NORTH_PITS = {"N1": 1, "N2": 2, "N3": 3, "N4": 4, "N5": 5}
SOUTH_PITS = {"S1": 11, "S2": 10, "S3": 9, "S4": 8, "S5": 7}
PIT_TO_INDEX = {**NORTH_PITS, **SOUTH_PITS}
INDEX_TO_PIT = {idx: name for name, idx in PIT_TO_INDEX.items()}
SIDE_INDICES = {
    "north": (1, 2, 3, 4, 5),
    "south": (11, 10, 9, 8, 7),
}
MAX_SOW_STEPS = 500


def new_game_state(
    game_id: int = 1,
    leaderboard: dict[str, dict[str, int]] | None = None,
    rate_limit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a fresh 70-point O an quan state."""
    pits = []
    for i in range(12):
        if i in QUAN_INDICES:
            pits.append({"quan": True, "dan": 0})
        else:
            pits.append({"quan": False, "dan": 5})
    return {
        "game_id": game_id,
        "turn": 0,
        "active_side": "south",
        "game_over": False,
        "winner": None,
        "pits": pits,
        "scores": {
            "north": 0,
            "south": 0,
            "debt_north": 0,
            "debt_south": 0,
        },
        "last_move": None,
        "recent_moves": [],
        "leaderboard": deepcopy(leaderboard) if leaderboard else {},
        "rate_limit": deepcopy(rate_limit)
        if rate_limit
        else {"last_mover": None, "last_move_at": None, "user_hourly": {}},
    }


def pit_points(pit: dict[str, Any]) -> int:
    return (QUAN_VALUE if pit["quan"] else 0) + int(pit["dan"])


def is_empty_pit(pit: dict[str, Any]) -> bool:
    return (not pit["quan"]) and int(pit["dan"]) == 0


def board_points(state: dict[str, Any]) -> int:
    return sum(pit_points(p) for p in state["pits"])


def net_score(state: dict[str, Any], side: str) -> int:
    return int(state["scores"][side]) - int(state["scores"][f"debt_{side}"])


def legal_pits(state: dict[str, Any]) -> list[str]:
    if state["game_over"]:
        return []
    side = state["active_side"]
    return [
        INDEX_TO_PIT[idx]
        for idx in SIDE_INDICES[side]
        if state["pits"][idx]["dan"] > 0
    ]


def step_delta(side: str, direction: str) -> int:
    if direction not in ("L", "R"):
        raise ValueError(f"Invalid direction: {direction!r}")
    if side == "north":
        return 1 if direction == "R" else -1
    if side == "south":
        return -1 if direction == "R" else 1
    raise ValueError(f"Invalid side: {side!r}")


def _both_quans_empty(pits: list[dict[str, Any]]) -> bool:
    return all(is_empty_pit(pits[i]) for i in QUAN_INDICES)


def _refill_side_if_empty(state: dict[str, Any], side: str) -> bool:
    """Traditional rai dan: if all 5 pits of `side` are empty, seed 1 stone each."""
    indices = SIDE_INDICES[side]
    if any(state["pits"][i]["dan"] > 0 for i in indices):
        return False

    available = int(state["scores"][side])
    if available >= 5:
        state["scores"][side] = available - 5
    else:
        shortfall = 5 - available
        state["scores"][side] = 0
        state["scores"][f"debt_{side}"] = int(state["scores"][f"debt_{side}"]) + shortfall

    for i in indices:
        state["pits"][i]["dan"] = 1
    return True


def apply_move(
    state: dict[str, Any],
    pit_name: str,
    direction: str,
    user: str,
    now_iso: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a legal move and return (new_state, move_summary). Raises ValueError if illegal."""
    if state["game_over"]:
        raise ValueError("Game is already over.")

    side = state["active_side"]
    valid_map = SOUTH_PITS if side == "south" else NORTH_PITS
    if pit_name not in valid_map:
        raise ValueError(f"Pit {pit_name} does not belong to {side}.")

    start_idx = valid_map[pit_name]
    next_state = deepcopy(state)
    pits = next_state["pits"]

    if pits[start_idx]["dan"] <= 0:
        raise ValueError(f"Pit {pit_name} is empty.")

    delta = step_delta(side, direction)
    hand = pits[start_idx]["dan"]
    pits[start_idx]["dan"] = 0
    pos = start_idx
    steps = 0
    captured = 0
    captured_quan = 0

    while True:
        while hand > 0:
            steps += 1
            if steps > MAX_SOW_STEPS:
                raise RuntimeError("Exceeded maximum sow steps.")
            pos = (pos + delta) % 12
            pits[pos]["dan"] += 1
            hand -= 1

        nxt = (pos + delta) % 12
        if is_empty_pit(pits[nxt]):
            # Chain-capture across alternating empty -> occupied pits
            while True:
                after = (nxt + delta) % 12
                if is_empty_pit(pits[after]):
                    break
                pts = pit_points(pits[after])
                if pits[after]["quan"]:
                    captured_quan += 1
                captured += pts
                pits[after]["quan"] = False
                pits[after]["dan"] = 0
                nxt = (after + delta) % 12
                if not is_empty_pit(pits[nxt]):
                    break
            break

        if nxt in QUAN_INDICES:
            # Non-empty Quan pit stops sowing immediately
            break

        # Non-empty dan pit: pick up and keep sowing
        hand = pits[nxt]["dan"]
        pits[nxt]["dan"] = 0
        pos = nxt

    next_state["scores"][side] = int(next_state["scores"][side]) + captured
    next_state["turn"] = int(next_state["turn"]) + 1

    refilled_side: str | None = None
    if _both_quans_empty(pits):
        for s in ("north", "south"):
            sweep = sum(pits[i]["dan"] for i in SIDE_INDICES[s])
            for i in SIDE_INDICES[s]:
                pits[i]["dan"] = 0
            next_state["scores"][s] = int(next_state["scores"][s]) + sweep
        next_state["game_over"] = True
        n_net = net_score(next_state, "north")
        s_net = net_score(next_state, "south")
        if s_net > n_net:
            next_state["winner"] = "south"
        elif n_net > s_net:
            next_state["winner"] = "north"
        else:
            next_state["winner"] = "draw"
    else:
        other = "north" if side == "south" else "south"
        next_state["active_side"] = other
        if _refill_side_if_empty(next_state, other):
            refilled_side = other

    arrow = "←" if direction == "L" else "→"
    move_record = {
        "turn": next_state["turn"],
        "user": user,
        "side": side,
        "pit": pit_name,
        "dir": direction,
        "move": f"{pit_name} {arrow}",
        "captured": captured,
        "captured_quan": captured_quan,
        "refilled": refilled_side,
        "at": now_iso,
    }
    next_state["last_move"] = move_record
    recent = list(next_state.get("recent_moves", []))
    recent.insert(
        0,
        {
            "turn": next_state["turn"],
            "user": user,
            "side": side,
            "move": f"{pit_name} {arrow}",
            "captured": captured,
        },
    )
    next_state["recent_moves"] = recent[:5]

    lb = next_state.setdefault("leaderboard", {})
    entry = lb.setdefault(user, {"moves": 0, "captured": 0, "wins": 0})
    entry["moves"] = int(entry["moves"]) + 1
    entry["captured"] = int(entry["captured"]) + captured
    if next_state["game_over"] and next_state["winner"] == side:
        entry["wins"] = int(entry["wins"]) + 1

    return next_state, move_record
