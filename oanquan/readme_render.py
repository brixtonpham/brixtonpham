"""Render the O an quan section inside README.md between marker comments."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .engine import INDEX_TO_PIT, SIDE_INDICES, net_score

START_MARKER = "<!-- OANQUAN:START -->"
END_MARKER = "<!-- OANQUAN:END -->"
DEFAULT_REPO = "brixtonpham/brixtonpham"


def _issue_url(repo: str, title: str, body: str) -> str:
    return (
        f"https://github.com/{repo}/issues/new"
        f"?title={quote(title, safe='')}&body={quote(body, safe='')}"
    )


def render_readme_block(state: dict[str, Any], repo: str = DEFAULT_REPO) -> str:
    game_id = int(state["game_id"])
    turn = int(state["turn"])
    active = str(state["active_side"])
    game_over = bool(state["game_over"])
    winner = state.get("winner")
    ver = f"g{game_id}-t{turn}"

    dark_src = f"https://raw.githubusercontent.com/{repo}/game-state/board-dark.svg?v={ver}"
    light_src = f"https://raw.githubusercontent.com/{repo}/game-state/board-light.svg?v={ver}"
    alt = (
        f"Ô ăn quan board — Game {game_id}, Turn {turn} "
        f"({'Game Over' if game_over else f'{active.title()} to move'})"
    )

    lines = [
        '<div align="center">',
        "",
        "<picture>",
        f'  <source media="(prefers-color-scheme: dark)" srcset="{dark_src}" />',
        f'  <img alt="{alt}" src="{light_src}" />',
        "</picture>",
        "",
    ]

    if game_over:
        n_net = net_score(state, "north")
        s_net = net_score(state, "south")
        outcome = "It's a draw!" if winner == "draw" else f"**{str(winner).title()} wins!**"
        new_url = _issue_url(
            repo,
            f"oanquan|new|g{game_id}",
            f"Click Create to start Ô ăn quan Game #{game_id + 1}. No edit needed.",
        )
        lines.append(
            f"🏆 Game #{game_id} finished — {outcome} (North {n_net} — South {s_net}) · "
            f"[**Start Game #{game_id + 1}**]({new_url})"
        )
    else:
        row_label = "bottom row" if active == "south" else "top row"
        lines.append(
            f"**{active.title()}'s turn ({row_label})** — click a pit & direction, then press **Create** on the prefilled issue:"
        )
        lines.append("")

        headers = []
        controls = []
        for idx in SIDE_INDICES[active]:
            name = INDEX_TO_PIT[idx]
            dan = int(state["pits"][idx]["dan"])
            headers.append(f"{name} ({dan})")
            if dan > 0:
                left_url = _issue_url(
                    repo,
                    f"oanquan|g{game_id}|t{turn}|{name}|L",
                    f"Click Create to sow {name} left. No edit needed.",
                )
                right_url = _issue_url(
                    repo,
                    f"oanquan|g{game_id}|t{turn}|{name}|R",
                    f"Click Create to sow {name} right. No edit needed.",
                )
                controls.append(f"[←]({left_url}) · [→]({right_url})")
            else:
                controls.append("*empty*")

        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join([":---:"] * len(headers)) + " |")
        lines.append("| " + " | ".join(controls) + " |")

    lines.extend([
        "",
        "</div>",
        "",
        "<details>",
        "<summary>How to play (3 lines) · Recent moves · Top players</summary>",
        "",
        "1. Pick one of the active side's 5 pits (`←` left or `→` right) to drop 1 stone per pit around the ring.",
        "2. Land before a non-empty *dân* pit to keep sowing; land before an empty pit followed by a full pit to **capture** it (chain captures allowed; non-empty **Quan** stops sowing).",
        "3. Game ends when both big **Quan** bowls (10 pts each) are empty. Remaining *dân* go to their owner's side; highest score wins.",
        "",
    ])

    recent = state.get("recent_moves", [])
    if recent:
        lines.append("**Last 5 moves**")
        lines.append("")
        lines.append("| Turn | Player | Side | Move | Captured |")
        lines.append("| ---: | :--- | :--- | :---: | ---: |")
        for r in recent[:5]:
            cap = f"+{r['captured']}" if r.get("captured", 0) > 0 else "—"
            u = r["user"]
            lines.append(
                f"| {r['turn']} | [@{u}](https://github.com/{u}) | {r.get('side', '').title()} | `{r['move']}` | {cap} |"
            )
        lines.append("")

    lb = state.get("leaderboard", {})
    if lb:
        ranked = sorted(
            lb.items(),
            key=lambda kv: (-int(kv[1].get("wins", 0)), -int(kv[1].get("captured", 0)), -int(kv[1].get("moves", 0)), kv[0].lower()),
        )[:10]
        lines.append("**Top players**")
        lines.append("")
        lines.append("| Player | Moves | Captured | Wins |")
        lines.append("| :--- | ---: | ---: | ---: |")
        for u, stats in ranked:
            lines.append(
                f"| [@{u}](https://github.com/{u}) | {stats['moves']} | {stats['captured']} | {stats['wins']} |"
            )
        lines.append("")

    lines.append("</details>")
    return "\n".join(lines)


def update_readme_text(readme_text: str, block: str) -> str:
    if START_MARKER not in readme_text or END_MARKER not in readme_text:
        raise ValueError(f"Missing {START_MARKER} / {END_MARKER} markers in README.md")
    before, rest = readme_text.split(START_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)
    return f"{before}{START_MARKER}\n{block}\n{END_MARKER}{after}"
