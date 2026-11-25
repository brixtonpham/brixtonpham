"""Update <!-- OSS-WORK:START/END --> in README.md from public GitHub activity.

Pure Python stdlib (no pip dependencies). Uses GITHUB_TOKEN when available and
falls back to unauthenticated public REST read if Search returns 401/403.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

START_MARKER = "<!-- OSS-WORK:START -->"
END_MARKER = "<!-- OSS-WORK:END -->"
DEFAULT_USER = "brixtonpham"
MIN_CREATED_DATE = "2026-01-01"
MAX_NAMED_REPOS = 6


def _fetch_json(url: str, token: str | None) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{DEFAULT_USER}-profile-updater",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if token and exc.code in (401, 403):
            return _fetch_json(url, None)
        raise


def fetch_upstream_prs(username: str, token: str | None) -> list[dict[str, Any]]:
    query = f"author:{username} is:pr is:public created:>={MIN_CREATED_DATE}"
    url = (
        "https://api.github.com/search/issues?"
        + urllib.parse.urlencode({"q": query, "sort": "updated", "per_page": 100})
    )
    data = _fetch_json(url, token)
    return list(data.get("items", []))


def filter_and_sort_prs(items: list[dict[str, Any]], username: str) -> list[dict[str, Any]]:
    """Keep only merged or open upstream PRs (excluding own repos & closed-unmerged)."""
    kept = []
    owner_prefix = f"{username.lower()}/"
    for item in items:
        repo_url = str(item.get("repository_url", ""))
        parts = repo_url.rstrip("/").split("/")
        if len(parts) < 2:
            continue
        repo = f"{parts[-2]}/{parts[-1]}"
        if repo.lower().startswith(owner_prefix):
            continue
        pr_meta = item.get("pull_request") or {}
        is_merged = bool(pr_meta.get("merged_at"))
        is_open = item.get("state") == "open"
        if not (is_merged or is_open):
            continue
        kept.append(
            {
                "repo": repo,
                "number": int(item["number"]),
                "title": str(item["title"]).strip(),
                "url": str(item["html_url"]),
                "merged": is_merged,
                "updated_at": str(item.get("updated_at", "")),
            }
        )
    merged = sorted([r for r in kept if r["merged"]], key=lambda r: r["updated_at"], reverse=True)
    opened = sorted([r for r in kept if not r["merged"]], key=lambda r: r["updated_at"], reverse=True)
    return merged + opened


def _repo_link(repo: str, username: str) -> str:
    short = repo.split("/", 1)[-1]
    q = urllib.parse.quote(f"is:pr author:{username}", safe=":")
    return f'<a href="https://github.com/{repo}/pulls?q={q}">{short}</a>'


def _join_links(links: list[str]) -> str:
    if len(links) == 1:
        return links[0]
    return f"{', '.join(links[:-1])} and {links[-1]}"


def render_oss_block(prs: list[dict[str, Any]], username: str = DEFAULT_USER) -> str:
    merged = [pr for pr in prs if pr["merged"]]
    opened = [pr for pr in prs if not pr["merged"]]

    target = merged if merged else opened
    if not target:
        return "Contributing to open-source agent tools"

    prefix = "Merged upstream in" if merged else "Contributing to"
    seen: list[str] = []
    for pr in target:
        if pr["repo"] not in seen:
            seen.append(pr["repo"])

    named = [_repo_link(r, username) for r in seen[:MAX_NAMED_REPOS]]
    extra = len(seen) - len(named)
    if extra > 0:
        state_q = "+is%3Amerged" if merged else "+is%3Aopen"
        more_url = (
            f"https://github.com/pulls?q=is%3Apr+author%3A{urllib.parse.quote(username)}"
            f"{state_q}+-user%3A{urllib.parse.quote(username)}"
        )
        named.append(f'<a href="{more_url}">{extra} more</a>')

    return f"{prefix} {_join_links(named)}"


def update_readme(readme_path: Path, block: str) -> bool:
    current = readme_path.read_text(encoding="utf-8")
    if START_MARKER not in current or END_MARKER not in current:
        raise ValueError(f"Missing {START_MARKER} / {END_MARKER} markers in {readme_path}")
    before, rest = current.split(START_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)
    updated = f"{before}{START_MARKER}\n    {block}\n    {END_MARKER}{after}"
    if updated == current:
        return False
    readme_path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Update Recent Open-Source Work in README.md.")
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--user", default=DEFAULT_USER)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    raw_items = fetch_upstream_prs(args.user, token)
    prs = filter_and_sort_prs(raw_items, args.user)
    changed = update_readme(args.readme, render_oss_block(prs, args.user))
    print(f"oss-work updated={changed} count={len(prs)}")


if __name__ == "__main__":
    main()
