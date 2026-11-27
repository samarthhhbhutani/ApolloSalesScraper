"""Idempotently load all raw checkpoints (data/raw/*.json) into SQLite.

Run: python -m ffresearch.ingest
Safe to re-run at any time (resume after interruption): rows are upserted.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from .db import ROOT, connect, load_json, upsert

RAW = ROOT / "data" / "raw"


def _norm_emp(v):
    if v is None or v == "":
        return None
    return v  # int, or a size-band string such as "11-50 (band)"


def ingest() -> dict:
    con = connect()
    stats = {"lookup_files": 0, "clay_batches": 0, "apollo_enrich_files": 0}

    # 1) Apollo lookup checkpoints: candidate domains + pre-screen exclusions
    for f in sorted(glob.glob(str(RAW / "apollo_look*.json"))):
        d = load_json(Path(f))
        stats["lookup_files"] += 1
        queries = d.get("queries") or [d.get("query")]
        for q in queries:
            if q:
                exists = con.execute("SELECT 1 FROM searches WHERE source=? AND query=?",
                                     ("Apollo", json.dumps(q, sort_keys=True))).fetchone()
                if not exists:
                    con.execute("INSERT INTO searches (source, tool, query, results, credits, ts) VALUES (?,?,?,?,?,?)",
                                ("Apollo", "organizations_lookup", json.dumps(q, sort_keys=True),
                                 q.get("results", 100), 0, "2026-11-27"))
        for country, domains in (d.get("candidates") or {}).items():
            for dom in domains:
                upsert(con, "companies", "domain", {"domain": dom, "country": country,
                                                    "company_source": "Apollo Organization Lookup"})
        for name, dom, reason in d.get("prescreen_excluded", []):
            key = dom or f"noname:{name}"
            upsert(con, "companies", "domain", {"domain": key, "name": name,
                                                "company_source": "Apollo Organization Lookup"})
            if not con.execute("SELECT 1 FROM reviews WHERE domain=?", (key,)).fetchone():
                upsert(con, "reviews", "domain", {"domain": key, "status": "excluded",
                                                  "reason": f"Pre-screen: {reason}"})

    # 2) Clay people-search batches: company profile, qualification review, contacts
    seq = 0
    for f in sorted(glob.glob(str(RAW / "clay_b*.json"))):
        d = load_json(Path(f))
        stats["clay_batches"] += 1
        for (dom, name, country, city, emp, spec, air, ocean, agent, indep, status, note) in d["companies"]:
            src = con.execute("SELECT company_source FROM companies WHERE domain=?", (dom,)).fetchone()
            upsert(con, "companies", "domain", {
                "domain": dom, "name": name, "country": country, "city": city,
                "employees": _norm_emp(emp), "description": spec,
                "company_source": (src["company_source"] if src and src["company_source"]
                                   else "Apollo Organization Lookup")})
            reason = note
            upsert(con, "reviews", "domain", {
                "domain": dom, "status": status, "reason": reason, "independent": indep,
                "air": air, "ocean": ocean, "agent_network": agent, "specialisation": spec})
        for (pname, title, li, dom, loc) in d["contacts"]:
            seq += 1
            existing = con.execute("SELECT discovered_seq FROM people WHERE linkedin_url=?", (li,)).fetchone()
            upsert(con, "people", "linkedin_url", {
                "linkedin_url": li, "name": pname, "title": title, "domain": dom, "location": loc,
                "contact_source": "Clay people search (public professional profiles)",
                "batch": d["batch"],
                "discovered_seq": existing["discovered_seq"] if existing else seq})

    # 3) Apollo organization enrichment results (credit-consuming)
    for f in sorted(glob.glob(str(RAW / "apollo_enrich_*.json"))):
        d = load_json(Path(f))
        stats["apollo_enrich_files"] += 1
        for dom, rec in d["orgs"].items():
            upsert(con, "companies", "domain", {
                "domain": dom, "apollo_enriched": 1,
                "apollo_org_id": rec.get("id"),
                "employees": rec.get("employees") or None,
                "city": rec.get("city") or None,
                "linkedin_url": rec.get("linkedin_url") or None,
                "apollo_keywords": rec.get("keywords"),
                "email_stack": rec.get("email_stack"),
                "founded_year": rec.get("founded_year")})
            ov = {k: rec[k] for k in ("status", "independent", "air", "ocean") if k in rec}
            if ov:
                sets = ",".join(f"{k}=?" for k in ov)
                con.execute(f"UPDATE reviews SET {sets} WHERE domain=?", list(ov.values()) + [dom])
            if rec.get("note"):
                r = con.execute("SELECT reason FROM reviews WHERE domain=?", (dom,)).fetchone()
                prev = (r["reason"] if r and r["reason"] else "")
                if rec["note"] not in prev:
                    con.execute("UPDATE reviews SET reason=? WHERE domain=?",
                                ((prev + "; " if prev else "") + rec["note"], dom))
        for entry in d.get("credit_log", []):
            if not con.execute("SELECT 1 FROM credit_log WHERE ts=? AND action=?",
                               (entry["ts"], entry["action"])).fetchone():
                con.execute("INSERT INTO credit_log (ts, action, credits_used, balance_after, note) VALUES (?,?,?,?,?)",
                            (entry["ts"], entry["action"], entry["credits_used"], entry["balance_after"], entry.get("note", "")))
    con.commit()
    return stats


if __name__ == "__main__":
    print(ingest())
