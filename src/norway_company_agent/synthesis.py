"""Decision-useful synthesis, generated deterministically from verified facts.

No model is used: every sentence is assembled from evidence records that
already passed the registry or identity gates, and every sentence names its
source module. Nothing is inferred beyond what the evidence states. Unknowns
are listed explicitly instead of filled in.

The synthesis covers: what the company does, its latest filed numbers, who
leads it, where it operates, hiring/public-activity signals, what changed
(first run: no prior snapshot), and what remains unknown.
"""

from __future__ import annotations

from typing import Any

from .evidence import evidence


def _latest_financials(profile: dict[str, Any]) -> dict[str, Any] | None:
    records = ((profile.get("evidence") or {}).get("financials", {}).get("value") or {}).get("records") or []
    if not records:
        return None
    # Records are stored newest-first (see official.normalize_financials).
    return records[0]


def _fmt_nok(value: Any) -> str:
    if value is None:
        return "not reported"
    try:
        return f"{float(value):,.0f} NOK".replace(",", " ")
    except (TypeError, ValueError):
        return "not reported"


def build_synthesis(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the synthesis evidence record and (zero-request) metrics."""
    org = str(profile.get("organisation_number") or "")
    name = str(profile.get("name") or "")
    evidence_map = profile.get("evidence") or {}
    source_url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}"

    sentences: list[str] = []
    sources: list[str] = []
    unknowns: list[str] = []

    industry = profile.get("industry_label") or ""
    legal_form = profile.get("legal_form") or ""
    municipality = profile.get("municipality") or ""
    if industry:
        sentences.append(
            f"{name} is {'an' if str(legal_form or '').strip()[:1].upper() in 'AEIOU' else 'a'} "
            f"{legal_form or 'registered'} entity in {municipality or 'Norway'}, "
            f"registered for {industry}."
        )
        sources.append("registry_live")
    employees = profile.get("employees")
    if employees is not None:
        sentences.append(f"The registry reports {employees} employee(s).")
        sources.append("registry_live")
    else:
        unknowns.append("Registry employee count is not reported for this company.")

    financials = _latest_financials(profile)
    if financials:
        period = (financials.get("period") or {})
        sentences.append(
            "Latest filed annual accounts cover "
            f"{period.get('fraDato', '?')} to {period.get('tilDato', '?')}: revenue "
            f"{_fmt_nok(financials.get('revenue'))}, annual result "
            f"{_fmt_nok(financials.get('annual_result'))}, total assets "
            f"{_fmt_nok(financials.get('assets'))}, total debt "
            f"{_fmt_nok(financials.get('debt'))}."
        )
        sources.append("financials")
    else:
        unknowns.append("No normalized annual-account record was returned; absence is not zero.")

    roles = ((evidence_map.get("roles", {}).get("value") or {}).get("roles") or [])
    active = [r for r in roles if not r.get("inactive")]
    if active:
        leaders = "; ".join(
            f"{r.get('name')} ({r.get('role') or r.get('group') or 'role'})" for r in active[:3]
        )
        sentences.append(f"Registered leadership includes: {leaders}.")
        sources.append("roles")
    else:
        unknowns.append("No active public role holder was returned.")

    locations = ((evidence_map.get("locations", {}).get("value") or {}).get("locations") or [])
    if locations:
        places = sorted({(item.get("address") or {}).get("kommune") or item.get("name") or "" for item in locations} - {""})
        sentences.append(
            f"Registered workplaces: {len(locations)} subunit(s)"
            + (f", in {', '.join(places)}." if places else ".")
        )
        sources.append("locations")
    else:
        unknowns.append("No registered subunit was returned; this does not prove the company has no physical presence.")

    website = evidence_map.get("website") or {}
    website_value = website.get("value") or {}
    if website.get("status") == "available" and (website_value.get("identity_assessment") or {}).get("publishable", False):
        sentences.append(
            f"Verified official website: {website_value.get('final_url')}"
            + (f" — {website_value.get('description')}" if website_value.get("description") else "")
        )
        sources.append("website")
    else:
        unknowns.append("No verified official website could be confirmed from the registry link.")

    news = evidence_map.get("news") or {}
    news_items = ((news.get("value") or {}).get("items") or []) if news.get("status") == "available" else []
    if news_items:
        latest = news_items[0]
        sentences.append(
            f"Dated public activity: {len(news_items)} verified news mention(s); most recent "
            f"\"{latest.get('title')}\" ({latest.get('publisher')}, {latest.get('published_at') or 'date unknown'})."
        )
        sources.append("news")
    else:
        unknowns.append("No verified dated news mention was found in the last 2 years.")

    activity = evidence_map.get("site_activity") or {}
    activity_value = activity.get("value") or {}
    job_titles = activity_value.get("job_titles") or []
    if job_titles:
        sentences.append(f"Company site lists open roles, including: {', '.join(job_titles[:5])}.")
        sources.append("site_activity")
    site_news = activity_value.get("news_items") or []
    if site_news:
        sentences.append(
            f"Company site publishes dated news; latest item: \"{site_news[0].get('title')}\" ({site_news[0].get('date_text')})."
        )
        sources.append("site_activity")
    if not job_titles and not site_news:
        unknowns.append("No hiring or dated activity could be verified from the company site.")

    group = ((evidence_map.get("group", {}).get("value") or {}).get("relations") or []) if isinstance(
        (evidence_map.get("group", {}).get("value") or {}), dict
    ) else []
    if group:
        sentences.append(f"Official group structure lists {len(group)} relation(s).")
        sources.append("group")

    sentences.append("Changes since the previous run: first profile in this run; no prior snapshot to compare.")
    summary = " ".join(sentences)
    value = {
        "summary": summary,
        "sentences": sentences,
        "source_modules": sorted(set(sources)),
        "unknowns": unknowns,
        "changes": ["first_run_no_prior_snapshot"],
    }
    return (
        evidence(
            "synthesis",
            "available",
            "deterministic_template_synthesis",
            source_url,
            value=value,
            note="Template synthesis from verified evidence only; no model inference.",
        ),
        {"requests": 0, "bytes": 0},
    )
