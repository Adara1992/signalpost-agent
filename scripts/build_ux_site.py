"""Build the static UX demo site from a smoke-test run.

Reads out/smoke-profiles.jsonl + out/smoke-envelopes.jsonl and writes a
single self-contained site/index.html: search a company by name or
organisation number, view its profile with every fact linked to its
source and date, compare two companies side by side, and verify any
source (URL, retrieval time, content hash). No build step, no external
dependencies — open the file in a browser.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
SITE = ROOT / "site"


def load() -> list[dict]:
    profiles = {}
    for line in (OUT / "smoke-profiles.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            profiles[row["organisation_number"]] = row
    companies = []
    for line in (OUT / "smoke-envelopes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        env = json.loads(line)
        org = env["organisation_number"]
        prof = profiles.get(org, {})
        ev = prof.get("evidence", {})
        fin = ev.get("financials", {}).get("value", {})
        records = fin.get("records", []) if isinstance(fin, dict) else []
        roles = ev.get("roles", {}).get("value", {})
        news = ev.get("news", {}).get("value", {})
        site = ev.get("website", {})
        synth = ev.get("synthesis", {}).get("value", {})
        companies.append(
            {
                "org": org,
                "name": prof.get("name") or env.get("name") or org,
                "legal_form": (ev.get("registry_live", {}).get("value", {}) or {}).get("legal_form"),
                "municipality": (ev.get("registry_live", {}).get("value", {}) or {}).get("municipality"),
                "industry": (ev.get("registry_live", {}).get("value", {}) or {}).get("industry"),
                "status": env.get("entity_state"),
                "financials": records[:3],
                "roles": (roles.get("items", []) if isinstance(roles, dict) else [])[:8],
                "locations": (ev.get("locations", {}).get("value", {}) or {}).get("count"),
                "website": site.get("source_url") if site.get("status") == "available" else None,
                "website_status": site.get("status"),
                "news": (news.get("items", []) if isinstance(news, dict) else []),
                "summary": synth.get("summary"),
                "unknowns": synth.get("unknowns", []),
                "sources": [
                    {
                        "field": k,
                        "status": v.get("status"),
                        "source": v.get("source_url"),
                        "retrieved": v.get("retrieved_at"),
                        "hash": (v.get("content_sha256") or "")[:16],
                    }
                    for k, v in ev.items()
                    if isinstance(v, dict)
                ],
            }
        )
    return companies


HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Signalpost — Company Research Agent (demo)</title>
<style>
body{font-family:system-ui,sans-serif;max-width:960px;margin:0 auto;padding:24px;color:#1a1a1a}
h1{font-size:22px}h2{font-size:18px;margin-top:28px}h3{font-size:15px}
input,select{padding:8px;font-size:15px;width:100%;box-sizing:border-box;margin:6px 0}
.card{border:1px solid #ccc;border-radius:8px;padding:16px;margin:12px 0}
.fact{margin:6px 0}.src{font-size:12px;color:#555}.src a{color:#0645ad}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:6px 8px;text-align:left;font-size:14px}
.badge{display:inline-block;background:#eef;border-radius:4px;padding:2px 8px;font-size:12px;margin-right:6px}
.muted{color:#666;font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.unknown{color:#8a6d00}
</style></head><body>
<h1>Signalpost — Company Research Agent</h1>
<p class="muted">Deterministic research agent for Norwegian companies. Every fact links to its
source and date. Demo data: 100 companies from the smoke-test run (run smoke-002).
No model, no API keys, $0 per run.</p>

<h2>Find a company</h2>
<input id="q" placeholder="Search by name or 9-digit organisation number…" oninput="search()">
<div id="results"></div>
<div id="profile"></div>

<h2>Compare two companies</h2>
<div class="grid">
<div><select id="cmpA" onchange="compare()"></select><div id="cmpABox"></div></div>
<div><select id="cmpB" onchange="compare()"></select><div id="cmpBBox"></div></div>
</div>

<h2>Verify a source</h2>
<p class="muted">Every fact below carries its source URL, retrieval time and content hash.
Open the source link to check the fact against the original.</p>
<div id="verify"></div>

<script>
const DATA = __DATA__;
const byOrg = Object.fromEntries(DATA.map(c => [c.org, c]));
const sel = (id) => document.getElementById(id);
DATA.forEach(c => {
  for (const id of ["cmpA", "cmpB"]) {
    const o = document.createElement("option");
    o.value = c.org; o.textContent = c.name + " (" + c.org + ")";
    sel(id).appendChild(o);
  }
});
sel("cmpB").selectedIndex = 1;

function money(n){ return n == null ? "—" : Number(n).toLocaleString("en-US") + " NOK"; }
function factHTML(c){
  const f = c.financials[0] || {};
  return `<div class="fact"><b>Latest accounts:</b> ${f.period || "—"} — revenue ${money(f.revenue)}, result ${money(f.annual_result)}, assets ${money(f.total_assets)}</div>
  <div class="fact"><b>Leadership:</b> ${(c.roles||[]).map(r => r.name + " (" + (r.role||"") + ")").join("; ") || "not reported"}</div>
  <div class="fact"><b>Workplaces:</b> ${c.locations ?? "—"} &nbsp; <b>Website:</b> ${c.website ? `<a href="${c.website}" target="_blank">${c.website}</a>` : c.website_status}</div>
  ${c.news.length ? `<div class="fact"><b>Dated news:</b><ul>${c.news.map(n => `<li><a href="${n.source_url}" target="_blank">${n.title}</a> — ${n.publisher}, ${n.published_at || ""}</li>`).join("")}</ul></div>` : ""}
  ${c.unknowns.length ? `<div class="fact unknown"><b>Unknowns (stated, not guessed):</b><ul>${c.unknowns.map(u => `<li>${u}</li>`).join("")}</ul></div>` : ""}`;
}
function profileHTML(c){
  return `<div class="card"><h3>${c.name} <span class="badge">${c.org}</span><span class="badge">${c.legal_form || ""}</span><span class="badge">${c.municipality || ""}</span></h3>
  <p>${c.summary || ""}</p>${factHTML(c)}
  <h3>Sources</h3>${c.sources.map(s => `<div class="src">• <b>${s.field}</b> — ${s.status} — <a href="${s.source}" target="_blank">${s.source}</a><br>&nbsp;&nbsp;retrieved ${s.retrieved || "—"} · sha ${s.hash || "—"}</div>`).join("")}</div>`;
}
function search(){
  const q = sel("q").value.trim().toLowerCase();
  const box = sel("results");
  if (!q) { box.innerHTML = ""; return; }
  const hits = DATA.filter(c => c.name.toLowerCase().includes(q) || c.org.includes(q)).slice(0, 8);
  box.innerHTML = hits.map(c => `<div class="card" style="cursor:pointer" onclick="show('${c.org}')"><b>${c.name}</b> <span class="muted">${c.org} · ${c.municipality || ""} · ${c.industry || ""}</span></div>`).join("") || "<p class='muted'>No match in this 100-company demo set.</p>";
  if (hits.length === 1) show(hits[0].org);
}
function show(org){ sel("profile").innerHTML = profileHTML(byOrg[org]); renderVerify(byOrg[org]); window.scrollTo(0, sel("profile").offsetTop); }
function renderVerify(c){
  sel("verify").innerHTML = `<div class="card"><b>${c.name}</b><br>` + c.sources.map(s => `<div class="src">• <b>${s.field}</b>: <a href="${s.source}" target="_blank">${s.source}</a> — ${s.status}, retrieved ${s.retrieved || "—"}, sha ${s.hash || "—"}</div>`).join("") + "</div>";
}
function compare(){
  sel("cmpABox").innerHTML = profileHTML(byOrg[sel("cmpA").value]);
  sel("cmpBBox").innerHTML = profileHTML(byOrg[sel("cmpB").value]);
}
compare();
</script></body></html>
"""


def main() -> None:
    companies = load()
    if not companies:
        print("no companies found in out/", file=sys.stderr)
        raise SystemExit(1)
    SITE.mkdir(parents=True, exist_ok=True)
    html = HTML.replace("__DATA__", json.dumps(companies, ensure_ascii=False))
    (SITE / "index.html").write_text(html, encoding="utf-8")
    print(f"wrote {SITE / 'index.html'} ({len(companies)} companies, {len(html)} bytes)")


if __name__ == "__main__":
    main()
