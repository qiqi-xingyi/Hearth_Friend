"""Reading feeds.

Deliberately small: fetch a few sources, keep title and summary, store the URL.
No article bodies, no crawling, no search. What she needs is to genuinely have
seen something, not to be an index.

Everything that comes back is text written by strangers. It is data she has
read, never instruction, and the prompt says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
import urllib.error
import urllib.request
from xml.etree import ElementTree

MAX_ITEMS_PER_SOURCE = 8
MAX_SUMMARY_CHARS = 220
FETCH_TIMEOUT = 15.0


@dataclass(frozen=True)
class Item:
    title: str
    url: str
    summary: str
    published: str


@dataclass(frozen=True)
class Source:
    name: str
    url: str


def _text(value: str | None) -> str:
    """Feeds carry HTML in fields that are supposed to be text."""
    if not value:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def parse_feed(body: str, source: str) -> list[Item]:
    """RSS or Atom, without taking a dependency for two element names."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return []

    items: list[Item] = []
    # RSS puts entries at channel/item; Atom uses entry in its own namespace.
    nodes = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    for node in nodes[:MAX_ITEMS_PER_SOURCE]:
        title = _text(_find(node, "title"))
        url = _link(node)
        if not title or not url:
            continue
        summary = _text(
            _find(node, "description")
            or _find(node, "summary")
            or _find(node, "content")
        )[:MAX_SUMMARY_CHARS]
        items.append(
            Item(
                title=title[:200],
                url=url,
                summary=summary,
                published=_text(_find(node, "pubDate") or _find(node, "published")),
            )
        )
    return items


def _find(node: ElementTree.Element, tag: str) -> str | None:
    for candidate in (tag, f"{{http://www.w3.org/2005/Atom}}{tag}"):
        found = node.find(candidate)
        if found is not None and (found.text or "").strip():
            return found.text
    return None


def _link(node: ElementTree.Element) -> str:
    link = node.find("link")
    if link is not None:
        if (link.text or "").strip():
            return link.text.strip()
        href = link.get("href")
        if href:
            return href.strip()
    atom = node.find("{http://www.w3.org/2005/Atom}link")
    if atom is not None and atom.get("href"):
        return atom.get("href", "").strip()
    guid = node.find("guid")
    if guid is not None and (guid.text or "").startswith("http"):
        return guid.text.strip()
    return ""


class Unreachable(RuntimeError):
    """Reading is not possible at all, as opposed to one source being down."""


def fetch_source(source: Source, *, timeout: float = FETCH_TIMEOUT) -> list[Item]:
    """One source.

    A source being down is silent: it means she has not read it, which is true
    rather than exceptional. Being unable to make a request at all is not the
    same thing and is raised, because an earlier version swallowed a missing
    import here and five working feeds looked like a network outage.
    """
    request = urllib.request.Request(
        source.url, headers={"User-Agent": "hearth-friend/0.0.1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, OSError)) and not isinstance(
            exc, urllib.error.HTTPError
        ):
            raise Unreachable(f"{source.url}: {reason}") from exc
        return []
    except Exception:
        return []
    return parse_feed(body, source.name)
