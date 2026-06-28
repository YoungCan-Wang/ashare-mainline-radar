from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, resolve_project_path
from .models import IntelItem


TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_DESC_RE = re.compile(
    r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"'][^>]*>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(value: str | None, limit: int = 500) -> str:
    if not value:
        return ""
    value = html.unescape(value)
    value = TAG_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def _fetch_text(url: str, timeout: float = 12.0) -> str | None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ashare-mainline-radar/0.1",
            "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _find_child_text(element: ET.Element, names: tuple[str, ...]) -> str | None:
    for child in list(element):
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names and child.text:
            return child.text
    return None


def parse_rss(source: dict[str, Any]) -> list[IntelItem]:
    text = _fetch_text(str(source["url"]))
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items: list[IntelItem] = []
    source_name = str(source.get("name") or source["url"])
    tags = [str(tag) for tag in source.get("tags", [])]
    candidates = [item for item in root.iter() if item.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    for element in candidates[:30]:
        title = _clean_text(_find_child_text(element, ("title",)), 160)
        if not title:
            continue
        summary = _clean_text(_find_child_text(element, ("description", "summary", "content")), 320)
        link = _find_child_text(element, ("link",))
        if link is None:
            for child in list(element):
                if child.tag.rsplit("}", 1)[-1].lower() == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        published = _clean_text(_find_child_text(element, ("pubdate", "published", "updated")), 120)
        items.append(IntelItem(source=source_name, title=title, url=link, published_at=published, summary=summary, tags=tags))
    return items


def parse_web_page(source: dict[str, Any]) -> list[IntelItem]:
    url = str(source["url"])
    text = _fetch_text(url)
    if not text:
        return []
    title_match = TITLE_RE.search(text)
    meta_match = META_DESC_RE.search(text)
    title = _clean_text(title_match.group(1) if title_match else str(source.get("name") or url), 180)
    summary = _clean_text(meta_match.group(1) if meta_match else "", 320)
    return [
        IntelItem(
            source=str(source.get("name") or url),
            title=title,
            url=url,
            published_at=datetime.now(timezone.utc).date().isoformat(),
            summary=summary,
            tags=[str(tag) for tag in source.get("tags", [])],
        )
    ]


def read_local_reports(paths: list[str]) -> list[IntelItem]:
    items: list[IntelItem] = []
    for raw_path in paths:
        path = resolve_project_path(raw_path)
        if not path.exists():
            continue
        for file_path in sorted(path.glob("**/*")):
            if file_path.suffix.lower() not in {".md", ".txt"} or not file_path.is_file():
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            title = file_path.stem.replace("_", " ").replace("-", " ")
            first_line = next((line.strip() for line in text.splitlines() if line.strip()), title)
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc).date().isoformat()
            items.append(
                IntelItem(
                    source=f"local:{file_path.relative_to(PROJECT_ROOT)}",
                    title=_clean_text(first_line or title, 180),
                    url=str(file_path),
                    published_at=mtime,
                    summary=_clean_text(text, 600),
                    tags=["research", "local"],
                )
            )
    return items


def tag_intel_items(items: list[IntelItem], keywords_by_theme: dict[str, list[str]]) -> list[IntelItem]:
    for item in items:
        text = f"{item.title} {item.summary or ''}".lower()
        matches: list[str] = []
        for theme, keywords in keywords_by_theme.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    matches.append(theme)
                    break
        item.matched_themes = matches
    return items


def collect_intelligence(intel_config: dict[str, Any], keywords_by_theme: dict[str, list[str]], limit: int = 80) -> list[IntelItem]:
    items: list[IntelItem] = []
    for source in intel_config.get("rss_feeds", []):
        items.extend(parse_rss(source))
    for source in intel_config.get("web_pages", []):
        items.extend(parse_web_page(source))
    items.extend(read_local_reports([str(path) for path in intel_config.get("local_report_dirs", [])]))
    tagged = tag_intel_items(items, keywords_by_theme)
    return tagged[:limit]


def intel_match_index(items: list[IntelItem]) -> dict[str, list[str]]:
    return {f"{item.source}:{item.title}": item.matched_themes for item in items if item.matched_themes}
