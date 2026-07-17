from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from .config import PROJECT_ROOT, resolve_project_path
from .models import DataSourceStatus, IntelItem

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_DESC_RE = re.compile(
    r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"'][^>]*>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
LINK_RE = re.compile(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
HEADING_RE = re.compile(r"<h[1-3][^>]*>(.*?)</h[1-3]>", re.IGNORECASE | re.DOTALL)
DATE_RE = re.compile(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?|\d{1,2}-\d{1,2})")


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


def _source_name(source: dict[str, Any]) -> str:
    return str(source.get("name") or source.get("url") or "unknown")


def parse_rss(source: dict[str, Any]) -> list[IntelItem]:
    text = _fetch_text(str(source["url"]))
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items: list[IntelItem] = []
    source_name = _source_name(source)
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


def parse_listing_page(source: dict[str, Any]) -> list[IntelItem]:
    url = str(source["url"])
    text = _fetch_text(url)
    if not text:
        return []
    source_name = _source_name(source)
    tags = [str(tag) for tag in source.get("tags", [])]
    include_keywords = [str(keyword).lower() for keyword in source.get("include_keywords", [])]
    exclude_keywords = [str(keyword).lower() for keyword in source.get("exclude_keywords", [])]
    include_href_keywords = [str(keyword).lower() for keyword in source.get("include_href_keywords", [])]
    max_items = int(source.get("max_items", 30))
    seen: set[str] = set()
    items: list[IntelItem] = []
    for match in LINK_RE.finditer(text):
        href, raw_title = match.group(1), match.group(2)
        absolute_url = urllib.parse.urljoin(url, href)
        heading_match = HEADING_RE.search(raw_title)
        title = _clean_text(heading_match.group(1) if heading_match else raw_title, 180)
        title_lower = title.lower()
        if len(title) < 8 or title in seen:
            continue
        if include_href_keywords and not any(keyword in absolute_url.lower() for keyword in include_href_keywords):
            continue
        if include_keywords and not any(keyword in title_lower for keyword in include_keywords):
            continue
        if exclude_keywords and any(keyword in title_lower for keyword in exclude_keywords):
            continue
        date_match = DATE_RE.search(_clean_text(text[match.end() : match.end() + 120], 120))
        published_at = date_match.group(1).replace("年", "-").replace("月", "-").replace("日", "") if date_match else None
        seen.add(title)
        items.append(
            IntelItem(
                source=source_name,
                title=title,
                url=absolute_url,
                published_at=published_at or datetime.now(timezone.utc).date().isoformat(),
                tags=tags,
            )
        )
        if len(items) >= max_items:
            break
    return items


def read_local_reports(paths: list[str]) -> list[IntelItem]:
    items: list[IntelItem] = []
    for raw_path in paths:
        path = resolve_project_path(raw_path)
        if not path.exists():
            continue
        for file_path in sorted(path.glob("**/*")):
            if file_path.suffix.lower() not in {".md", ".txt", ".html"} or not file_path.is_file():
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


def collect_intelligence_with_status(
    intel_config: dict[str, Any],
    keywords_by_theme: dict[str, list[str]],
    limit: int = 80,
) -> tuple[list[IntelItem], list[DataSourceStatus]]:
    items: list[IntelItem] = []
    statuses: list[DataSourceStatus] = []
    for source in intel_config.get("rss_feeds", []):
        name = _source_name(source)
        try:
            parsed = parse_rss(source)
        except Exception as exc:  # pragma: no cover - defensive around external sources
            statuses.append(DataSourceStatus(name=name, kind="rss", status="error", message=str(exc)))
            continue
        items.extend(parsed)
        statuses.append(
            DataSourceStatus(
                name=name,
                kind="rss",
                status="ok" if parsed else "empty",
                items=len(parsed),
                message=None if parsed else "No RSS items parsed",
            )
        )
    for source in intel_config.get("web_pages", []):
        name = _source_name(source)
        try:
            parsed = parse_web_page(source)
        except Exception as exc:  # pragma: no cover - defensive around external sources
            statuses.append(DataSourceStatus(name=name, kind="web_page", status="error", message=str(exc)))
            continue
        items.extend(parsed)
        statuses.append(
            DataSourceStatus(
                name=name,
                kind="web_page",
                status="ok" if parsed else "empty",
                items=len(parsed),
                message=None if parsed else "Page fetch failed or no title parsed",
            )
        )
    for source in intel_config.get("listing_pages", []):
        name = _source_name(source)
        try:
            parsed = parse_listing_page(source)
        except Exception as exc:  # pragma: no cover - defensive around external sources
            statuses.append(DataSourceStatus(name=name, kind="listing_page", status="error", message=str(exc)))
            continue
        items.extend(parsed)
        statuses.append(
            DataSourceStatus(
                name=name,
                kind="listing_page",
                status="ok" if parsed else "empty",
                items=len(parsed),
                message=None if parsed else "No listing titles matched filters",
            )
        )
    local_dirs = [str(path) for path in intel_config.get("local_report_dirs", [])]
    local_items = read_local_reports(local_dirs)
    items.extend(local_items)
    statuses.append(
        DataSourceStatus(
            name="local research inbox",
            kind="local_reports",
            status="ok" if local_items else "empty",
            items=len(local_items),
            message=", ".join(local_dirs) if local_dirs else "No local report dirs configured",
        )
    )
    tagged = tag_intel_items(items, keywords_by_theme)
    return tagged[:limit], statuses
def intel_match_index(items: list[IntelItem]) -> dict[str, list[str]]:
    return {f"{item.source}:{item.title}": item.matched_themes for item in items if item.matched_themes}
