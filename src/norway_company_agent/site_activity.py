"""Dated activity and hiring signals from the company's own website.

Works only on pages the website module already fetched (homepage + up to 4
priority pages), so it adds zero requests. Publication requires the website
identity gate to have passed (same-domain, exact-entity site); otherwise the
whole module returns ``not_found``.

Two conservative extractors:

* News/activity: on pages whose URL or title matches news/press terms,
  lines that carry an explicit date (DD.MM.YYYY, YYYY-MM-DD or a Norwegian
  month name) plus headline text become dated items.
* Hiring: on pages whose URL or title matches careers/jobs terms, short
  non-sentence lines are treated as candidate job titles. At least two
  candidates are required before anything is published, so a lone page
  heading such as "Ledige stillinger" never becomes a job claim on its own.

Every item carries its source page URL, the page content hash and the exact
line as the claim span, so each claim is independently verifiable. Anything
that does not match these strict shapes is reported as not found, never
guessed.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .evidence import evidence

NEWS_TERMS = ("nyhet", "news", "press", "aktuelt", "media", "blogg")
CAREER_TERMS = ("karriere", "stilling", "jobb", "job", "career", "vacanc", "ledig")

_DATE_PATTERNS = (
    r"\b\d{1,2}\.\d{1,2}\.\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}\.\s*(januar|februar|mars|april|mai|juni|juli|august|september|oktober|november|desember)\s+\d{4}\b",
    r"\b\d{1,2}\.\s*(jan|feb|mar|apr|mai|jun|jul|aug|sep|okt|nov|des)\.?\s+\d{4}\b",
)
_DATE_RE = re.compile("|".join(_DATE_PATTERNS), re.IGNORECASE)
_MONTH_RE = re.compile(
    r"(januar|februar|mars|april|mai|juni|juli|august|september|oktober|november|desember)",
    re.IGNORECASE,
)


def _matches_terms(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in terms)


def _news_items(page: dict[str, Any]) -> list[dict[str, Any]]:
    url = str(page.get("url") or "")
    title = str(page.get("title") or "")
    if not _matches_terms(url + " " + title, NEWS_TERMS):
        return []
    excerpt = str(page.get("main_text_excerpt") or "")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in excerpt.splitlines():
        clean = " ".join(line.split())
        if len(clean) < 20 or len(clean) > 200:
            continue
        match = _DATE_RE.search(clean)
        if not match:
            continue
        headline = _DATE_RE.sub("", clean).strip(" -–—:·•")
        if len(headline) < 10 or headline.casefold() in seen:
            continue
        seen.add(headline.casefold())
        items.append(
            {
                "id": "site-news-" + hashlib.sha256(f"{url}|{headline}".encode()).hexdigest()[:24],
                "title": headline,
                "date_text": match.group(0),
                "source_url": url,
                "content_sha256": page.get("content_sha256"),
                "claim_span": clean,
                "source_class": "company_owned",
            }
        )
        if len(items) >= 5:
            break
    return items


def _job_titles(page: dict[str, Any]) -> list[str]:
    url = str(page.get("url") or "")
    title = str(page.get("title") or "")
    if not _matches_terms(url + " " + title, CAREER_TERMS):
        return []
    excerpt = str(page.get("main_text_excerpt") or "")
    titles: list[str] = []
    seen: set[str] = set()
    for line in excerpt.splitlines():
        clean = " ".join(line.split())
        words = clean.split()
        if not (2 <= len(words) <= 8 and 10 <= len(clean) <= 60):
            continue
        if clean[-1] in ".!?" or ":" in clean:
            continue
        if _DATE_RE.search(clean) or _MONTH_RE.search(clean):
            continue
        lowered = clean.casefold()
        if lowered in seen or lowered in {"ledige stillinger", "karriere", "jobs", "careers", "våre stillinger"}:
            continue
        seen.add(lowered)
        titles.append(clean)
        if len(titles) >= 10:
            break
    return titles


def fetch_site_activity(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the site-activity evidence record and (zero-request) metrics."""
    org = str(profile.get("organisation_number") or "")
    website = (profile.get("evidence") or {}).get("website") or {}
    value = website.get("value") or {}
    source_url = str(value.get("final_url") or website.get("source_url") or "")
    publishable = (value.get("identity_assessment") or {}).get("publishable", False)
    pages = value.get("pages") or []
    if website.get("status") != "available" or not publishable or not pages:
        return (
            evidence(
                "site_activity",
                "not_found",
                "company_owned_site_activity",
                source_url or f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}",
                note="No publishable company website with fetched pages",
            ),
            {"requests": 0, "bytes": 0},
        )
    news_items: list[dict[str, Any]] = []
    careers_pages: list[dict[str, Any]] = []
    job_titles: list[str] = []
    for page in pages:
        news_items.extend(_news_items(page))
        titles = _job_titles(page)
        if titles:
            job_titles.extend(titles)
            careers_pages.append(
                {
                    "url": page.get("url"),
                    "content_sha256": page.get("content_sha256"),
                    "titles": titles,
                }
            )
    found = bool(news_items) or len(job_titles) >= 2
    if not found:
        return (
            evidence(
                "site_activity",
                "not_found",
                "company_owned_site_activity",
                source_url,
                value={"news_items": [], "job_titles": [], "careers_pages": []},
                note="Checked company site pages; no dated news items or job titles matched",
            ),
            {"requests": 0, "bytes": 0},
        )
    return (
        evidence(
            "site_activity",
            "available",
            "company_owned_site_activity",
            source_url,
            value={
                "news_items": news_items[:5],
                "job_titles": sorted(set(job_titles))[:10],
                "careers_pages": careers_pages,
            },
            note=f"{len(news_items)} dated site news item(s), {len(set(job_titles))} job title(s) on company pages",
        ),
        {"requests": 0, "bytes": 0},
    )
