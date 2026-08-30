"""Reading.

Deliberately small: fetch a few sources, keep titles and summaries, store the
link. No article bodies, no crawling, no search. What she needs is to genuinely
have seen something, not to be an index.

The boundary that matters is not "which pages are safe to read". It is that a
URL never comes from anywhere except the persona file and the table below.
Nothing she says and nothing she reads can introduce a host, and no request is
ever built from the conversation. That is what makes this safe to widen later:
letting her choose which source to read, or what to keep from it, never becomes
the ability to reach somewhere new.

Everything that comes back is text written by strangers. It is material she has
read, never instruction, and the prompt says so.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html import unescape
from xml.etree import ElementTree

MAX_ITEMS_PER_SOURCE = 8
MAX_SUMMARY_CHARS = 220
FETCH_TIMEOUT = 15.0

# Sources with no feed of their own. The persona names the source; the address
# lives here, so that adding one is a change to this file and not something a
# configuration string can do.
KNOWN_SOURCES = {
    "bilibili": "https://api.bilibili.com/x/web-interface/popular",
}


class Unreachable(RuntimeError):
    """Reading is not possible at all, as opposed to one source being down."""


@dataclass(frozen=True)
class Item:
    title: str
    url: str
    summary: str
    published: str


@dataclass(frozen=True)
class Source:
    name: str
    url: str = ""
    kind: str = "rss"


def source_url(source: Source) -> str:
    if source.kind == "rss":
        if not source.url.startswith(("http://", "https://")):
            raise ValueError(f"refusing a non-http address: {source.url!r}")
        return source.url
    try:
        return KNOWN_SOURCES[source.kind]
    except KeyError:
        raise ValueError(f"unknown source kind: {source.kind!r}") from None


# ------------------------------------------------------------------ parsing


def _text(value: str | None) -> str:
    """Feeds put HTML in fields that are supposed to be text."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


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
        if link.get("href"):
            return link.get("href", "").strip()
    atom = node.find("{http://www.w3.org/2005/Atom}link")
    if atom is not None and atom.get("href"):
        return atom.get("href", "").strip()
    guid = node.find("guid")
    if guid is not None and (guid.text or "").startswith("http"):
        return guid.text.strip()
    return ""


def parse_feed(body: str, source: str) -> list[Item]:
    """RSS or Atom, without taking a dependency for two element names."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return []

    items: list[Item] = []
    nodes = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    for node in nodes[:MAX_ITEMS_PER_SOURCE]:
        title = _text(_find(node, "title"))
        url = _link(node)
        if not title or not url:
            continue
        summary = _text(
            _find(node, "description") or _find(node, "summary") or _find(node, "content")
        )
        items.append(
            Item(
                title=title[:200],
                url=url,
                summary=summary[:MAX_SUMMARY_CHARS],
                published=_text(_find(node, "pubDate") or _find(node, "published")),
            )
        )
    return items


def parse_bilibili(body: str, source: str) -> list[Item]:
    """The popular list: titles and descriptions. No comments, no bodies."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []

    items: list[Item] = []
    for entry in (payload.get("data") or {}).get("list") or []:
        bvid = str(entry.get("bvid") or "").strip()
        title = _text(entry.get("title"))
        if not bvid or not re.fullmatch(r"[A-Za-z0-9]+", bvid) or not title:
            continue
        owner = _text((entry.get("owner") or {}).get("name"))
        desc = _text(entry.get("desc"))
        summary = "" if desc in ("", "-") else desc
        if owner:
            summary = f"UP主 {owner}" + (f"：{summary}" if summary else "")
        items.append(
            Item(
                title=title[:200],
                url=f"https://www.bilibili.com/video/{bvid}",
                summary=summary[:MAX_SUMMARY_CHARS],
                published="",
            )
        )
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break
    return items


_PARSERS = {"rss": parse_feed, "bilibili": parse_bilibili}


# ----------------------------------------------------------------- fetching


def fetch_source(source: Source, *, timeout: float = FETCH_TIMEOUT) -> list[Item]:
    """One source.

    A source being down is silent: it means she has not read it, which is true
    rather than exceptional. Being unable to make a request at all is not the
    same thing and is raised -- an earlier version swallowed a missing import
    here and four working feeds looked like a network outage.
    """
    try:
        url = source_url(source)
    except ValueError:
        return []

    request = urllib.request.Request(
        url, headers={"User-Agent": "hearth-friend/0.0.1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError:
        return []
    except urllib.error.URLError as exc:
        raise Unreachable(f"{url}: {getattr(exc, 'reason', exc)}") from exc
    except Exception:
        return []

    return _PARSERS[source.kind](body, source.name)
