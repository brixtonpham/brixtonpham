"""Unit, invariant, Camo-SVG, CLI anti-spam, and OSS-activity tests."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oanquan.cli import MAX_MOVES_PER_HOUR, process_issue, write_artifacts
from oanquan.engine import (
    SIDE_INDICES,
    apply_move,
    board_points,
    legal_pits,
    net_score,
    new_game_state,
)
from oanquan.readme_render import END_MARKER, START_MARKER, render_readme_block, update_readme_text
from oanquan.svg_render import render_board_svg
from scripts.update_oss_activity import filter_and_sort_prs, render_oss_block, update_readme


def _total_invariant(state: dict) -> int:
    return board_points(state) + net_score(state, "north") + net_score(state, "south")


class TestOAnQuanEngine(unittest.TestCase):
    def test_initial_board_conservation_and_legal_pits(self) -> None:
        st = new_game_state()
        self.assertEqual(board_points(st), 70)
        self.assertEqual(_total_invariant(st), 70)
        self.assertEqual(st["active_side"], "south")
        self.assertEqual(legal_pits(st), ["S1", "S2", "S3", "S4", "S5"])

    def test_visual_directions_and_relay_stop_at_quan(self) -> None:
        st = new_game_state()
        for i in range(12):
            st["pits"][i] = {"quan": i in (0, 6), "dan": 0}
        st["pits"][11]["dan"] = 1  # S1
        st["pits"][0]["quan"] = True  # West Quan
        st["pits"][1]["dan"] = 0  # N1 empty
        st["pits"][2]["dan"] = 3  # N2 has 3 -> captured across empty N1
        st["pits"][5]["dan"] = 2  # N5 keeps North non-empty (no refill)
        # Moving S1 Left (+1 mod 12): drops 1 in idx 0 (West Quan), next is idx 1 (empty), after is idx 2 (3) -> capture 3!
        nxt, summary = apply_move(st, "S1", "L", "alice", "2026-11-22T00:00:00Z")
        self.assertEqual(summary["captured"], 3)
        self.assertIsNone(summary["refilled"])
        self.assertEqual(nxt["pits"][0]["dan"], 1)
        self.assertEqual(nxt["pits"][2]["dan"], 0)
        self.assertEqual(nxt["scores"]["south"], 3)

    def test_stop_before_non_empty_quan(self) -> None:
        st = new_game_state()
        for i in range(12):
            st["pits"][i] = {"quan": i in (0, 6), "dan": 0}
        st["pits"][10]["dan"] = 1  # S2
        st["pits"][11]["dan"] = 0  # S1 empty
        st["pits"][5]["dan"] = 2  # Keep North non-empty
        # Moving S2 Left (+1): drops in idx 11 (S1), next is idx 0 (non-empty West Quan) -> stops, no capture!
        nxt, summary = apply_move(st, "S2", "L", "alice", "2026-11-22T00:00:00Z")
        self.assertEqual(summary["captured"], 0)
        self.assertTrue(nxt["pits"][0]["quan"])
        self.assertEqual(nxt["pits"][11]["dan"], 1)

    def test_chain_capture_including_quan(self) -> None:
        st = new_game_state()
        for i in range(12):
            st["pits"][i] = {"quan": False, "dan": 0}
        st["pits"][0] = {"quan": True, "dan": 2}  # West Quan = 12 pts
        st["pits"][6] = {"quan": True, "dan": 0}  # East Quan keeps game alive
        st["pits"][9]["dan"] = 1   # S3
        st["pits"][10]["dan"] = 0  # S2 -> receives 1 stone
        st["pits"][11]["dan"] = 0  # S1 empty
        st["pits"][1]["dan"] = 0   # N1 empty
        st["pits"][2]["dan"] = 4   # N2 = 4 pts
        st["pits"][5]["dan"] = 2   # N5 keeps North non-empty (no refill)
        # S3 Left (+1): drops in 10 (S2), next 11 empty -> captures 0 (12 pts), next 1 empty -> captures 2 (4 pts) = 16 pts!
        nxt, summary = apply_move(st, "S3", "L", "bob", "2026-11-22T00:00:00Z")
        self.assertEqual(summary["captured"], 16)
        self.assertEqual(summary["captured_quan"], 1)
        self.assertFalse(nxt["pits"][0]["quan"])
        self.assertEqual(nxt["pits"][0]["dan"], 0)
        self.assertEqual(nxt["pits"][2]["dan"], 0)
        self.assertFalse(nxt["game_over"])

    def test_double_empty_stops_without_capture(self) -> None:
        st = new_game_state()
        for i in range(12):
            st["pits"][i] = {"quan": i in (0, 6), "dan": 0}
        st["pits"][1]["dan"] = 1  # N1
        st["pits"][4]["dan"] = 5  # N4 (unreachable past empty N3 & N2? Let's set N1 R -> drops in N2, N3 & N4 empty, N5 has 5)
        st["pits"][4]["dan"] = 0
        st["pits"][5]["dan"] = 5
        st["active_side"] = "north"
        nxt, summary = apply_move(st, "N1", "R", "alice", "2026-11-22T00:00:00Z")
        self.assertEqual(summary["captured"], 0)
        self.assertEqual(nxt["pits"][5]["dan"], 5)

    def test_empty_side_refill_with_debt_and_game_over_sweep(self) -> None:
        st = new_game_state()
        for i in range(12):
            st["pits"][i] = {"quan": False, "dan": 0}
        st["pits"][0] = {"quan": True, "dan": 0}
        st["pits"][11]["dan"] = 1  # S1
        # South moves S1 Right (-1): drops in 10 (S2). North has 0 stones and 0 score -> North refills 5 with debt_north=5!
        nxt, summary = apply_move(st, "S1", "R", "alice", "2026-11-22T00:00:00Z")
        self.assertEqual(summary["refilled"], "north")
        self.assertEqual(nxt["scores"]["north"], 0)
        self.assertEqual(nxt["scores"]["debt_north"], 5)
        self.assertEqual([nxt["pits"][i]["dan"] for i in SIDE_INDICES["north"]], [1, 1, 1, 1, 1])

        # Now capture the last Quan (idx 0) from North N3 Left (-1): drops in N2(2), N1(1) empty -> captures 0 (Quan), stops because S1(11) is non-empty!
        nxt["pits"][1]["dan"] = 0
        nxt["pits"][2]["dan"] = 0
        nxt["pits"][3]["dan"] = 1
        nxt["pits"][4]["dan"] = 2
        nxt["pits"][5]["dan"] = 0
        nxt["pits"][11]["dan"] = 1  # S1 non-empty stops chain capture
        nxt["pits"][10]["dan"] = 3
        end_st, end_sum = apply_move(nxt, "N3", "L", "bob", "2026-11-22T00:01:00Z")
        self.assertTrue(end_st["game_over"])
        self.assertEqual(end_sum["captured"], 10)
        # North captured 10 + swept remaining North stones (N2 has 1 + N4 has 2 = 3) = 13, minus debt 5 = net 8
        self.assertEqual(net_score(end_st, "north"), 8)
        # South swept S1(11)=1 + S2(10)=3 -> net 4
        self.assertEqual(net_score(end_st, "south"), 4)
        self.assertEqual(end_st["winner"], "north")

    def test_100_random_games_conservation_invariant(self) -> None:
        rng = random.Random(42)
        for gid in range(1, 101):
            st = new_game_state(game_id=gid)
            self.assertEqual(_total_invariant(st), 70)
            for step in range(300):
                if st["game_over"]:
                    break
                pits = legal_pits(st)
                self.assertTrue(pits, f"No legal pits on non-over game {gid} turn {step}")
                pit = rng.choice(pits)
                direction = rng.choice(["L", "R"])
                st, _ = apply_move(st, pit, direction, f"u{step % 3}", "2026-11-22T00:00:00Z")
                self.assertEqual(_total_invariant(st), 70)
            if st["game_over"]:
                self.assertEqual(board_points(st), 0)
                self.assertEqual(net_score(st, "north") + net_score(st, "south"), 70)


class TestSvgAndReadme(unittest.TestCase):
    def test_svgs_are_valid_xml_and_camo_safe(self) -> None:
        st = new_game_state(game_id=3)
        st, _ = apply_move(st, "S3", "R", 'evil<script>"&', "2026-11-22T00:00:00Z")
        forbidden = ("<script", "<foreignObject", "javascript:", "@import", "onload=")
        for theme in ("light", "dark"):
            svg = render_board_svg(st, theme)
            root = ET.fromstring(svg)
            self.assertTrue(root.tag.endswith("svg"))
            lowered = svg.lower()
            for bad in forbidden:
                self.assertNotIn(bad.lower(), lowered)
            self.assertIn("&lt;script&gt;", svg)

    def test_readme_render_and_marker_replacement(self) -> None:
        st = new_game_state(game_id=1)
        block = render_readme_block(st)
        self.assertIn("board-light.svg?v=g1-t0", block)
        self.assertIn("oanquan%7Cg1%7Ct0%7CS1%7CL", block)
        self.assertIn("oanquan%7Cg1%7Ct0%7CS5%7CR", block)
        template = f"Header\n{START_MARKER}\nold\n{END_MARKER}\nFooter\n"
        updated = update_readme_text(template, block)
        self.assertTrue(updated.startswith("Header\n"))
        self.assertTrue(updated.endswith("\nFooter\n"))
        self.assertNotIn("\nold\n", updated)


class TestCliAntiSpam(unittest.TestCase):
    def setUp(self) -> None:
        self.t0 = datetime(2026, 11, 22, 4, 0, 0, tzinfo=timezone.utc)

    def test_valid_move_then_stale_and_consecutive_guards(self) -> None:
        st = new_game_state(game_id=1)
        st1, res1 = process_issue(st, title="oanquan|g1|t0|S1|R", user="alice", user_type="User", now=self.t0)
        self.assertTrue(res1["changed"])
        self.assertEqual(res1["close_reason"], "completed")
        self.assertEqual(st1["turn"], 1)

        # Stale turn rejected with 0 changes
        st_stale, res_stale = process_issue(st1, title="oanquan|g1|t0|S2|R", user="bob", user_type="User", now=self.t0 + timedelta(seconds=10))
        self.assertFalse(res_stale["changed"])
        self.assertEqual(res_stale["close_reason"], "not planned")
        self.assertEqual(st_stale["turn"], 1)

        # Consecutive move by alice blocked within 24h
        _, res_consec = process_issue(st1, title="oanquan|g1|t1|N1|L", user="alice", user_type="User", now=self.t0 + timedelta(minutes=5))
        self.assertFalse(res_consec["changed"])
        self.assertEqual(res_consec["close_reason"], "not planned")

        # Consecutive move by alice allowed after 24h idle
        st2, res_idle = process_issue(st1, title="oanquan|g1|t1|N1|L", user="alice", user_type="User", now=self.t0 + timedelta(hours=24, minutes=1))
        self.assertTrue(res_idle["changed"])
        self.assertEqual(st2["turn"], 2)

    def test_bot_malformed_wrong_side_and_hourly_limit(self) -> None:
        st = new_game_state(game_id=1)
        _, res_bot = process_issue(st, title="oanquan|g1|t0|S1|R", user="my-bot", user_type="Bot", now=self.t0)
        self.assertFalse(res_bot["changed"])

        _, res_bad = process_issue(st, title="oanquan|garbage", user="alice", user_type="User", now=self.t0)
        self.assertFalse(res_bad["changed"])

        _, res_wrong_side = process_issue(st, title="oanquan|g1|t0|N1|R", user="alice", user_type="User", now=self.t0)
        self.assertFalse(res_wrong_side["changed"])

        # Seed hourly rate limit to MAX_MOVES_PER_HOUR
        st["rate_limit"]["user_hourly"]["alice"] = [
            (self.t0 - timedelta(minutes=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            for i in range(MAX_MOVES_PER_HOUR)
        ]
        _, res_rl = process_issue(st, title="oanquan|g1|t0|S1|R", user="alice", user_type="User", now=self.t0)
        self.assertFalse(res_rl["changed"])
        self.assertIn("Rate limit", res_rl["comment"])

    def test_new_game_command_and_artifact_write(self) -> None:
        st = new_game_state(game_id=1)
        # Non-owner cannot reset active game
        _, res_no = process_issue(st, title="oanquan|new|g1", user="stranger", user_type="User", now=self.t0)
        self.assertFalse(res_no["changed"])

        # Finished game can be restarted by anyone, preserving leaderboard
        st["game_over"] = True
        st["leaderboard"] = {"alice": {"moves": 5, "captured": 20, "wins": 1}}
        st_new, res_ok = process_issue(st, title="oanquan|new|g1", user="stranger", user_type="User", now=self.t0)
        self.assertTrue(res_ok["changed"])
        self.assertEqual(st_new["game_id"], 2)
        self.assertEqual(st_new["turn"], 0)
        self.assertEqual(st_new["leaderboard"]["alice"]["wins"], 1)

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            readme = Path(tmp) / "README.md"
            readme.write_text(f"Intro\n{START_MARKER}\n{END_MARKER}\n", encoding="utf-8")
            write_artifacts(st_new, state_dir, readme)
            self.assertTrue((state_dir / "state.json").exists())
            self.assertTrue((state_dir / "board-light.svg").exists())
            self.assertTrue((state_dir / "board-dark.svg").exists())
            self.assertIn("board-light.svg?v=g2-t0", readme.read_text(encoding="utf-8"))


class TestOssActivityUpdater(unittest.TestCase):
    def test_filter_sort_and_noop_readme_update(self) -> None:
        sample = [
            {
                "repository_url": "https://api.github.com/repos/brixtonpham/muse2api-cli",
                "number": 1,
                "title": "own repo PR should be ignored",
                "html_url": "https://github.com/brixtonpham/muse2api-cli/pull/1",
                "state": "closed",
                "pull_request": {"merged_at": "2026-11-20T00:00:00Z"},
                "updated_at": "2026-11-20T00:00:00Z",
            },
            {
                "repository_url": "https://api.github.com/repos/org/closed-unmerged",
                "number": 2,
                "title": "closed unmerged should be ignored",
                "html_url": "https://github.com/org/closed-unmerged/pull/2",
                "state": "closed",
                "pull_request": {"merged_at": None},
                "updated_at": "2026-11-21T00:00:00Z",
            },
            {
                "repository_url": "https://api.github.com/repos/org/open-repo",
                "number": 10,
                "title": "fix: open bug",
                "html_url": "https://github.com/org/open-repo/pull/10",
                "state": "open",
                "pull_request": {},
                "updated_at": "2026-11-22T01:00:00Z",
            },
            {
                "repository_url": "https://api.github.com/repos/org/merged-repo",
                "number": 5,
                "title": "fix: merged bug",
                "html_url": "https://github.com/org/merged-repo/pull/5",
                "state": "closed",
                "pull_request": {"merged_at": "2026-11-21T12:00:00Z"},
                "updated_at": "2026-11-21T12:00:00Z",
            },
        ]
        prs = filter_and_sort_prs(sample, "brixtonpham")
        self.assertEqual(len(prs), 2)
        self.assertTrue(prs[0]["merged"])
        self.assertEqual(prs[0]["repo"], "org/merged-repo")
        self.assertFalse(prs[1]["merged"])

        block = render_oss_block(prs)
        self.assertIn("Merged upstream in", block)
        self.assertIn(">merged-repo</a>", block)
        self.assertNotIn("open-repo", block)

        many = [
            {
                "repo": f"org/repo-{i}",
                "number": i,
                "title": f"fix: item {i}",
                "url": f"https://github.com/org/repo-{i}/pull/{i}",
                "merged": True,
                "updated_at": f"2026-11-{10 + i:02d}T00:00:00Z",
            }
            for i in range(8)
        ]
        big_block = render_oss_block(many, "brixtonpham")
        self.assertIn("Merged upstream in", big_block)
        self.assertIn(">2 more</a>", big_block)

        open_only = [
            {
                "repo": "org/open-only",
                "number": 1,
                "title": "fix: open",
                "url": "https://github.com/org/open-only/pull/1",
                "merged": False,
                "updated_at": "2026-11-22T00:00:00Z",
            }
        ]
        self.assertIn("Contributing to", render_oss_block(open_only, "brixtonpham"))

        with tempfile.TemporaryDirectory() as tmp:
            readme = Path(tmp) / "README.md"
            readme.write_text("Top\n<!-- OSS-WORK:START -->\n<!-- OSS-WORK:END -->\n", encoding="utf-8")
            self.assertTrue(update_readme(readme, block))
            self.assertFalse(update_readme(readme, block))  # No-op on identical content


if __name__ == "__main__":
    unittest.main()
