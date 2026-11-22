"""Camo-safe light & dark SVG renderer for O an quan board state.

Emits strictly static XML (<rect>, <path>, <circle>, <text>, <g>, <defs>) using
system font stacks only — zero <script>, <foreignObject>, @import, or external hrefs.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from .engine import INDEX_TO_PIT, PIT_TO_INDEX, net_score

PALETTES = {
    "light": {
        "bg": "#FAF6EE",
        "card_border": "#D8C8AE",
        "board_fill": "#F2E7D3",
        "board_stroke": "#B89B72",
        "pit_fill": "#FDFBF7",
        "pit_active_fill": "#FFF8EA",
        "pit_stroke": "#C9B390",
        "pit_active_stroke": "#B45309",
        "pit_last_stroke": "#D97706",
        "quan_fill": "#F8E9CA",
        "quan_stone": "#B45309",
        "quan_stone_hi": "#F59E0B",
        "dan_stone": "#3B5B6B",
        "dan_stone_hi": "#5C8396",
        "ink": "#1F2937",
        "muted": "#6B7280",
        "pill_bg": "#FEF3C7",
        "pill_ink": "#92400E",
        "win_bg": "#DCFCE7",
        "win_ink": "#166534",
        "badge_bg": "#EFE5D2",
    },
    "dark": {
        "bg": "#0D1117",
        "card_border": "#30363D",
        "board_fill": "#161B22",
        "board_stroke": "#3B434D",
        "pit_fill": "#0D1117",
        "pit_active_fill": "#18202C",
        "pit_stroke": "#30363D",
        "pit_active_stroke": "#D29922",
        "pit_last_stroke": "#F0B429",
        "quan_fill": "#1D2430",
        "quan_stone": "#D29922",
        "quan_stone_hi": "#F4C95D",
        "dan_stone": "#58A6FF",
        "dan_stone_hi": "#8CC2FF",
        "ink": "#E6EDF3",
        "muted": "#8B949E",
        "pill_bg": "#2B2412",
        "pill_ink": "#F2CC60",
        "win_bg": "#122A1B",
        "win_ink": "#56D364",
        "badge_bg": "#21262D",
    },
}

# Deterministic pebble offsets inside a 92x74 dan pit (centered around pit midpoint)
PEBBLE_OFFSETS = [
    (-22, -10), (0, -12), (22, -10),
    (-11, 2), (11, 2),
    (-24, 14), (0, 14), (24, 14),
    (-28, 2), (28, 2), (-12, -18), (12, -18),
]

QUAN_DAN_OFFSETS = [
    (-12, 16), (0, 19), (12, 16),
    (-14, 29), (0, 31), (14, 29),
    (-10, -28), (10, -28), (0, -32),
]

FONT_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
FONT_MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"


def _render_dan_pit(
    x: int,
    y: int,
    w: int,
    h: int,
    pit_idx: int,
    dan: int,
    is_active_row: bool,
    is_last_origin: bool,
    last_arrow: str,
    p: dict[str, str],
) -> list[str]:
    label = INDEX_TO_PIT[pit_idx]
    fill = p["pit_active_fill"] if is_active_row else p["pit_fill"]
    stroke = p["pit_last_stroke"] if is_last_origin else (p["pit_active_stroke"] if is_active_row else p["pit_stroke"])
    stroke_w = "2.2" if is_last_origin else ("1.5" if is_active_row else "1.1")

    lines = [
        f'  <g id="pit-{label}">',
        f'    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}" />',
        f'    <text x="{x + 8}" y="{y + 16}" font-family="{FONT_MONO}" font-size="11" font-weight="600" fill="{p["muted"]}">{label}</text>',
        f'    <text x="{x + w - 8}" y="{y + 17}" text-anchor="end" font-family="{FONT_MONO}" font-size="13" font-weight="700" fill="{p["ink"] if dan > 0 else p["muted"]}">{dan}</text>',
    ]
    if is_last_origin and last_arrow:
        lines.append(
            f'    <text x="{x + w // 2}" y="{y + 16}" text-anchor="middle" font-family="{FONT_SANS}" font-size="12" font-weight="700" fill="{p["pit_last_stroke"]}">{escape(last_arrow)}</text>'
        )

    cx, cy = x + w // 2, y + h // 2 + 9
    shown = min(dan, len(PEBBLE_OFFSETS))
    for i in range(shown):
        dx, dy = PEBBLE_OFFSETS[i]
        lines.append(
            f'    <circle cx="{cx + dx}" cy="{cy + dy}" r="4.6" fill="{p["dan_stone"]}" />'
        )
        lines.append(
            f'    <circle cx="{cx + dx - 1.3}" cy="{cy + dy - 1.3}" r="1.4" fill="{p["dan_stone_hi"]}" />'
        )
    if dan > len(PEBBLE_OFFSETS):
        extra = dan - len(PEBBLE_OFFSETS)
        lines.append(
            f'    <rect x="{cx - 16}" y="{cy - 8}" width="32" height="16" rx="8" fill="{p["badge_bg"]}" stroke="{p["pit_stroke"]}" stroke-width="1" />'
        )
        lines.append(
            f'    <text x="{cx}" y="{cy + 4}" text-anchor="middle" font-family="{FONT_MONO}" font-size="10" font-weight="700" fill="{p["ink"]}">+{extra}</text>'
        )
    lines.append("  </g>")
    return lines


def _render_quan_bowl(
    side_name: str,
    path_d: str,
    cx: int,
    cy: int,
    label_y: int,
    pit: dict[str, Any],
    p: dict[str, str],
) -> list[str]:
    has_quan = bool(pit["quan"])
    dan = int(pit["dan"])
    pts_text = f"10+{dan}" if (has_quan and dan > 0) else ("10" if has_quan else str(dan))
    lines = [
        f'  <g id="quan-{side_name}">',
        f'    <path d="{path_d}" fill="{p["quan_fill"]}" stroke="{p["board_stroke"]}" stroke-width="1.6" />',
        f'    <text x="{cx}" y="{label_y}" text-anchor="middle" font-family="{FONT_MONO}" font-size="9.5" font-weight="600" fill="{p["muted"]}">{side_name.upper()} QUAN</text>',
    ]
    if has_quan:
        lines.append(
            f'    <ellipse cx="{cx}" cy="{cy - 4}" rx="16" ry="12" fill="{p["quan_stone"]}" />'
        )
        lines.append(
            f'    <ellipse cx="{cx - 4}" cy="{cy - 8}" rx="5.5" ry="3.2" fill="{p["quan_stone_hi"]}" opacity="0.65" />'
        )
    shown = min(dan, len(QUAN_DAN_OFFSETS))
    for i in range(shown):
        dx, dy = QUAN_DAN_OFFSETS[i]
        lines.append(
            f'    <circle cx="{cx + dx}" cy="{cy + dy}" r="4.0" fill="{p["dan_stone"]}" />'
        )
    lines.append(
        f'    <rect x="{cx - 22}" y="{cy + 40}" width="44" height="20" rx="10" fill="{p["badge_bg"]}" stroke="{p["pit_stroke"]}" stroke-width="1" />'
    )
    lines.append(
        f'    <text x="{cx}" y="{cy + 54}" text-anchor="middle" font-family="{FONT_MONO}" font-size="11" font-weight="700" fill="{p["ink"] if (has_quan or dan > 0) else p["muted"]}">{pts_text}</text>'
    )
    lines.append("  </g>")
    return lines


def render_board_svg(state: dict[str, Any], theme: str = "light") -> str:
    """Render the current board state as a self-contained static SVG string."""
    p = PALETTES[theme]
    game_id = int(state["game_id"])
    turn = int(state["turn"])
    active = str(state["active_side"])
    game_over = bool(state["game_over"])
    winner = state.get("winner")
    n_score = net_score(state, "north")
    s_score = net_score(state, "south")

    if game_over:
        if winner == "draw":
            status_text = "Game Over · Draw"
        else:
            status_text = f"Game Over · {str(winner).title()} wins!"
        pill_bg, pill_ink = p["win_bg"], p["win_ink"]
    else:
        row_hint = "Bottom" if active == "south" else "Top"
        status_text = f"{active.title()}'s turn ({row_hint})"
        pill_bg, pill_ink = p["pill_bg"], p["pill_ink"]

    last_move = state.get("last_move")
    last_pit_idx = PIT_TO_INDEX.get(last_move["pit"]) if last_move else None
    last_arrow = ("←" if last_move["dir"] == "L" else "→") if last_move else ""

    if last_move:
        cap = int(last_move.get("captured", 0))
        cap_txt = f" (+{cap} pts)" if cap > 0 else ""
        refill_txt = (
            f" · {last_move['refilled'].title()} refilled"
            if last_move.get("refilled")
            else ""
        )
        footer_text = f"Last: @{last_move['user']} played {last_move['move']}{cap_txt}{refill_txt}"
    else:
        footer_text = "Fresh game — click any South pit (S1–S5) below to make the opening move."

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 284" width="760" height="284" role="img" aria-label="O an quan game board">',
        f'  <rect x="1" y="1" width="758" height="282" rx="14" fill="{p["bg"]}" stroke="{p["card_border"]}" stroke-width="1.5" />',
        # Header
        f'  <text x="24" y="30" font-family="{FONT_SANS}" font-size="15" font-weight="700" fill="{p["ink"]}">Ô ăn quan · Game #{game_id}</text>',
        f'  <text x="206" y="30" font-family="{FONT_MONO}" font-size="12" fill="{p["muted"]}">Turn {turn}</text>',
        f'  <rect x="284" y="12" width="192" height="26" rx="13" fill="{pill_bg}" />',
        f'  <text x="380" y="29" text-anchor="middle" font-family="{FONT_SANS}" font-size="12" font-weight="700" fill="{pill_ink}">{escape(status_text)}</text>',
        f'  <text x="736" y="30" text-anchor="end" font-family="{FONT_MONO}" font-size="13" font-weight="700" fill="{p["ink"]}">North {n_score}  —  South {s_score}</text>',
        # Outer capsule board frame
        f'  <rect x="24" y="50" width="712" height="190" rx="95" fill="{p["board_fill"]}" stroke="{p["board_stroke"]}" stroke-width="2" />',
    ]

    # West Quan (idx 0) and East Quan (idx 6) semicircular bowls
    west_path = "M 124 62 A 83 83 0 0 0 124 228 Z"
    east_path = "M 636 62 A 83 83 0 0 1 636 228 Z"
    lines.extend(_render_quan_bowl("West", west_path, 92, 145, 106, state["pits"][0], p))
    lines.extend(_render_quan_bowl("East", east_path, 668, 145, 106, state["pits"][6], p))

    # Row labels
    lines.append(
        f'  <text x="380" y="61" text-anchor="middle" font-family="{FONT_MONO}" font-size="10" font-weight="600" fill="{p["muted"]}">NORTH</text>'
    )
    lines.append(
        f'  <text x="380" y="236" text-anchor="middle" font-family="{FONT_MONO}" font-size="10" font-weight="600" fill="{p["muted"]}">SOUTH</text>'
    )

    # 10 dan pits: top N1..N5 (1..5), bottom S1..S5 (11..7)
    pit_w, pit_h, gap = 94, 74, 8
    start_x = 130
    top_y, bot_y = 66, 148

    for col, idx in enumerate((1, 2, 3, 4, 5)):
        px = start_x + col * (pit_w + gap)
        lines.extend(
            _render_dan_pit(
                px, top_y, pit_w, pit_h, idx, int(state["pits"][idx]["dan"]),
                is_active_row=(not game_over and active == "north"),
                is_last_origin=(last_pit_idx == idx),
                last_arrow=last_arrow,
                p=p,
            )
        )

    for col, idx in enumerate((11, 10, 9, 8, 7)):
        px = start_x + col * (pit_w + gap)
        lines.extend(
            _render_dan_pit(
                px, bot_y, pit_w, pit_h, idx, int(state["pits"][idx]["dan"]),
                is_active_row=(not game_over and active == "south"),
                is_last_origin=(last_pit_idx == idx),
                last_arrow=last_arrow,
                p=p,
            )
        )

    # Footer
    lines.append(
        f'  <text x="380" y="268" text-anchor="middle" font-family="{FONT_SANS}" font-size="12" fill="{p["muted"]}">{escape(footer_text)}</text>'
    )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"
