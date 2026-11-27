"""Score prospects, enforce max-2-per-company, and write + validate the XLSX/CSV deliverables.

Run: python -m ffresearch.build_outputs
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .db import ROOT, connect
from .ingest import ingest
from .scoring import (QUALIFY_THRESHOLD, company_fit, dm_fit, mode_label, pilot_fit, rationale, tier)

OUT = ROOT / "output"
XLSX = OUT / "European_Freight_Forwarding_Prospects.xlsx"
CSV = OUT / "European_Freight_Forwarding_Prospects.csv"
METHOD = ROOT / "data" / "methodology.json"

S1_COLS = ["Name", "Designation", "Company", "Website", "Country", "City", "Employee Count",
           "Freight Specialisation", "Air Freight Capability", "Ocean Freight Capability",
           "Professional Email", "Email Verification Status", "LinkedIn URL", "Company Fit Score",
           "Decision-Maker Fit Score", "Pilot Suitability Score", "Overall Score",
           "Qualification Rationale", "Company Source", "Contact Source"]
S1_EXTRA = ["Tier"]  # helper column kept at the end for filtering
S2_COLS = ["Name", "Company", "Designation"]
S3_COLS = ["Company", "Website", "Country", "City", "Employee Estimate", "Freight-Forwarding Specialisation",
           "Air Freight", "Ocean Freight", "Agent Network Evidence", "Apollo Enriched", "Email Stack (Apollo)",
           "Decision-Makers Shortlisted", "Notes", "Company Source"]
S5_COLS = ["Company", "Website / Domain", "Country", "Reason for Exclusion"]

EMAIL_STATUS = ("Not enriched - Apollo person enrichment (people/match, bulk_match) is not included "
                "in the connected Apollo Free plan (API_INACCESSIBLE)")


def build() -> dict:
    ingest()
    con = connect()
    companies = {r["domain"]: dict(r) for r in con.execute("SELECT * FROM companies")}
    reviews = {r["domain"]: dict(r) for r in con.execute("SELECT * FROM reviews")}
    people = [dict(r) for r in con.execute("SELECT * FROM people ORDER BY discovered_seq")]

    # ---- score prospects -------------------------------------------------
    scored, post_credit = [], []
    for p in people:
        c, rev = companies.get(p["domain"]), reviews.get(p["domain"])
        if not c or not rev or rev["status"] != "qualified":
            continue
        if (p["batch"] or "").startswith("pc"):
            post_credit.append({"Name": p["name"], "Company": c["name"], "Designation": p["title"]})
            continue
        cf = company_fit(rev, c["employees"], c.get("email_stack"))
        df = dm_fit(p["title"])
        pf = pilot_fit(rev, c["employees"], p["title"], p["location"])
        total = cf + df + pf
        scored.append({
            "Name": p["name"], "Designation": p["title"], "Company": c["name"],
            "Website": f"https://{p['domain']}", "Country": c["country"], "City": c["city"],
            "Employee Count": c["employees"], "Freight Specialisation": rev["specialisation"],
            "Air Freight Capability": mode_label(rev["air"]), "Ocean Freight Capability": mode_label(rev["ocean"]),
            "Professional Email": "", "Email Verification Status": EMAIL_STATUS,
            "LinkedIn URL": p["linkedin_url"], "Company Fit Score": cf, "Decision-Maker Fit Score": df,
            "Pilot Suitability Score": pf, "Overall Score": total,
            "Qualification Rationale": rationale(c, rev, p["title"], cf, df, pf),
            "Company Source": c["company_source"] + ("; Apollo Organization Enrichment" if c.get("apollo_enriched") else ""),
            "Contact Source": p["contact_source"], "Tier": f"Tier {tier(p['title'])}",
            "_domain": p["domain"]})

    # ---- max two per company (best two), threshold ------------------------
    by_co = defaultdict(list)
    for s in scored:
        by_co[s["_domain"]].append(s)
    shortlist, below = [], []
    for dom, rows in by_co.items():
        rows.sort(key=lambda r: (-r["Overall Score"], r["Tier"]))
        for r in rows[:2]:
            (shortlist if r["Overall Score"] >= QUALIFY_THRESHOLD else below).append(r)
    shortlist.sort(key=lambda r: (-r["Overall Score"], r["Company"]))

    # ---- workbook -----------------------------------------------------------
    OUT.mkdir(exist_ok=True)
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Enriched Prospects"
    _write(ws1, S1_COLS + S1_EXTRA, [[r[c] for c in S1_COLS + S1_EXTRA] for r in shortlist])

    ws2 = wb.create_sheet("Post-Credit People Search")
    _write(ws2, S2_COLS, [[r[c] for c in S2_COLS] for r in post_credit])

    ws3 = wb.create_sheet("Company Research")
    dm_count = Counter(r["_domain"] for r in shortlist)
    s3 = []
    for dom, rev in sorted(reviews.items(), key=lambda kv: (companies.get(kv[0], {}).get("country") or "", kv[0])):
        if rev["status"] != "qualified":
            continue
        c = companies[dom]
        s3.append([c["name"], f"https://{dom}", c["country"], c["city"], c["employees"], rev["specialisation"],
                   mode_label(rev["air"]), mode_label(rev["ocean"]),
                   {2: "Strong", 1: "Some", 0: "None found"}.get(rev["agent_network"], ""),
                   "Yes" if c.get("apollo_enriched") else "No", c.get("email_stack") or "",
                   dm_count.get(dom, 0), rev["reason"] or "", c["company_source"]])
    _write(ws3, S3_COLS, s3)

    ws4 = wb.create_sheet("Research Methodology")
    meth = json.loads(METHOD.read_text()) if METHOD.exists() else {}
    credits = [dict(r) for r in con.execute("SELECT * FROM credit_log ORDER BY id")]
    rows4 = [[k, v] for k, v in meth.items()]
    rows4 += [["Credit log", f"{c['ts']} | {c['action']} | used {c['credits_used']} | balance {c['balance_after']} | {c['note']}"]
              for c in credits]
    searches = [dict(r) for r in con.execute("SELECT * FROM searches ORDER BY id")]
    rows4 += [["Apollo search", f"{s['tool']}: {s['query']} -> {s['results']} results, {s['credits']} credits"] for s in searches]
    _write(ws4, ["Item", "Detail"], rows4)

    ws5 = wb.create_sheet("Excluded Prospects")
    s5 = []
    for dom, rev in sorted(reviews.items()):
        if rev["status"] == "excluded":
            c = companies.get(dom, {})
            s5.append([c.get("name") or dom, "" if dom.startswith("noname:") else dom, c.get("country") or "",
                       rev["reason"]])
    # prospects that fell below threshold are reported too
    for r in below:
        s5.append([f"{r['Company']} - {r['Name']} ({r['Designation']})", r["_domain"], r["Country"],
                   f"Contact scored {r['Overall Score']} < {QUALIFY_THRESHOLD} threshold"])
    _write(ws5, S5_COLS, s5)
    wb.save(XLSX)

    with open(CSV, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(S1_COLS + S1_EXTRA)
        for r in shortlist:
            w.writerow([r[c] for c in S1_COLS + S1_EXTRA])

    stats = {
        "companies_discovered": len(companies),
        "companies_screened": len(reviews),
        "qualified_companies": sum(1 for r in reviews.values() if r["status"] == "qualified"),
        "qualified_companies_with_dm": len(dm_count),
        "decision_makers_shortlisted": len(shortlist),
        "below_threshold": len(below),
        "post_credit_people": len(post_credit),
        "by_country": dict(Counter(r["Country"] for r in shortlist)),
        "by_tier": dict(Counter(r["Tier"] for r in shortlist)),
        "apollo_enriched_companies": sum(1 for c in companies.values() if c.get("apollo_enriched")),
    }
    validate(stats)
    return stats


def _write(ws, header, rows):
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    for i, h in enumerate(header, 1):
        width = max([len(str(h))] + [min(len(str(r[i - 1] or "")), 60) for r in rows]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 62)
    if rows:
        ws.auto_filter.ref = ws.dimensions


def validate(stats: dict) -> None:
    wb = load_workbook(XLSX)
    assert wb.sheetnames == ["Enriched Prospects", "Post-Credit People Search", "Company Research",
                             "Research Methodology", "Excluded Prospects"], wb.sheetnames
    ws1 = wb["Enriched Prospects"]
    hdr = [c.value for c in ws1[1]]
    assert hdr[:len(S1_COLS)] == S1_COLS
    rows = list(ws1.iter_rows(min_row=2, values_only=True))
    per_co = Counter(r[2] for r in rows)
    assert all(v <= 2 for v in per_co.values()), "more than two contacts for a company"
    assert all(r[16] >= QUALIFY_THRESHOLD for r in rows), "row below threshold"
    names = [(r[0], r[2]) for r in rows]
    assert len(names) == len(set(names)), "duplicate prospects"
    assert [c.value for c in wb["Post-Credit People Search"][1]] == S2_COLS
    with open(CSV, encoding="utf-8-sig") as fh:
        assert sum(1 for _ in csv.reader(fh)) - 1 == len(rows)
    stats["validation"] = "passed"


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
