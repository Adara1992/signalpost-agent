"""Dated public-activity discovery via Google News RSS.

Design (precision-first, no API key, no model):

1. Query Google News RSS for the exact legal name (``"Name" when:2y``).
2. Headline gate: the distinctive name tokens (legal-form tokens dropped,
   Norwegian possessive -s tolerated) must appear as a consecutive sequence
   in the headline. For a single-token distinctive name, the token after
   the match must be lowercase (a verb/preposition) — a capitalised word
   after it means the headline names a longer company ("Aneo Roan Vind
   Holding AS" is not "Aneo AS").
3. Publish the gated items with title, publisher, publication date and the
   Google News article URL as the source, marked honestly as
   ``verification: "rss_headline"`` — the headline, publisher and date as
   reported by Google News. The claim is exactly that: Google News reported
   this headline about the company on this date. No article body is
   claimed, because Google News article links do not resolve reliably to
   the publisher page from an automated fetcher (they return an interstitial
   or HTTP 400); fetching them would burn the request budget for zero
   evidence. The claim span is the headline itself.

One RSS request per company; no per-article requests.
"""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from .evidence import evidence, utc_now
from .website import USER_AGENT

LEGAL_TOKENS = {"as", "asa", "sa", "ba", "da", "ans", "enk", "nuf", "sti"}
RSS_URL = "https://news.google.com/rss/search?q={query}&hl=no&gl=NO&ceid=NO:no"
MAX_ITEMS = 3
LOOKBACK_YEARS = 2


def _tokens(value: Any) -> list[str]:
    return re.findall(r"[a-z0-9æøå]+", str(value or "").casefold())


def _name_tokens(name: str) -> list[str]:
    return [t for t in _tokens(name) if t not in LEGAL_TOKENS]


def _stem(token: str, distinctive: list[str]) -> str:
    """Norwegian possessive: 'Equinors' in a headline means 'Equinor'."""
    if token in distinctive:
        return token
    if len(token) > 3 and token.endswith("s") and token[:-1] in distinctive:
        return token[:-1]
    return token


def exact_title_match(company_name: str, title: str) -> bool:
    """Distinctive name tokens as a consecutive sequence in the headline.

    Legal-form tokens are dropped (headlines write "Equinor", not
    "Equinor ASA"), and a trailing possessive -s is tolerated. For a
    single-token distinctive name, the token after the match must be
    lowercase: a capitalised word after it means the headline names a
    longer company ("Aneo Roan Vind Holding AS" is not "Aneo AS").
    """
    company_tokens = _name_tokens(company_name)
    headline = str(title or "").rsplit(" - ", 1)[0]
    raw_tokens = re.findall(r"[A-Za-z0-9æøåÆØÅ]+", headline)
    title_tokens = [_stem(t, company_tokens) for t in _tokens(headline)]
    if not company_tokens or not title_tokens or len(company_tokens) > len(title_tokens):
        return False
    allowed_predecessors = {"av", "for", "fra", "hos", "i", "med", "om", "på", "til", "og", "kjøper", "velger"}
    for index in range(len(title_tokens) - len(company_tokens) + 1):
        if title_tokens[index:index + len(company_tokens)] != company_tokens:
            continue
        if index != 0 and title_tokens[index - 1] not in allowed_predecessors:
            continue
        if len(company_tokens) == 1:
            after = index + 1
            if after < len(raw_tokens):
                nxt = raw_tokens[after]
                if nxt[:1].isupper() and nxt.casefold() not in LEGAL_TOKENS:
                    continue
        return True
    return False


def fetch_news(profile: dict[str, Any], *, limit: int = MAX_ITEMS, years: int = LOOKBACK_YEARS) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the news evidence record and request metrics for one company."""
    org = str(profile.get("organisation_number") or "")
    name = str(profile.get("name") or "")
    source_url = RSS_URL.format(query=urllib.parse.quote(f'"{name}" when:{years}y'))
    requests = 0
    if not org or not name:
        return evidence("news", "not_found", "public_news_rss", source_url, note="Missing organisation number or name"), {"requests": 0, "bytes": 0}
    try:
        request = urllib.request.Request(
            source_url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"}
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(2_000_000)
        requests += 1
        root = ET.fromstring(raw)
    except Exception as exc:
        return (
            evidence("news", "source_error", "public_news_rss", source_url, note=f"RSS fetch failed: {type(exc).__name__}"),
            {"requests": requests, "bytes": 0},
        )
    retrieved_at = utc_now()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates = 0
    for item in root.findall(".//item"):
        title = str(item.findtext("title") or "").strip()
        link = str(item.findtext("link") or "").strip()
        publisher = str(item.findtext("source") or "").strip()
        if not link or not exact_title_match(name, title):
            continue
        candidates += 1
        key = (title.casefold(), publisher.casefold())
        if key in seen or len(items) >= limit:
            continue
        seen.add(key)
        published = item.findtext("pubDate")
        try:
            published_at = parsedate_to_datetime(published).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            published_at = None
        items.append(
            {
                "id": "news-" + hashlib.sha256(f"{org}|{title}|{publisher}".encode()).hexdigest()[:24],
                "title": title,
                "publisher": publisher,
                "published_at": published_at,
                "source_url": link,
                "retrieved_at": retrieved_at,
                "content_sha256": hashlib.sha256(raw + title.encode("utf-8")).hexdigest(),
                "claim_span": title,
                "source_class": "public_news",
                "verification": "rss_headline",
            }
        )
    metrics = {"requests": requests, "bytes": len(raw)}
    if items:
        return (
            evidence(
                "news",
                "available",
                "public_news_rss_headline",
                source_url,
                value={"items": items, "rss_candidates": candidates, "verified": len(items)},
                note=f"{len(items)} dated headline(s) passed the exact-name gate; verification=rss_headline (headline, publisher and date as reported by Google News)",
            ),
            metrics,
        )
    return (
        evidence(
            "news",
            "not_found",
            "public_news_rss",
            source_url,
            value={"items": [], "rss_candidates": candidates, "verified": 0},
            note="No dated headline passed the exact-name gate in the last 2 years",
        ),
        metrics,
    )
