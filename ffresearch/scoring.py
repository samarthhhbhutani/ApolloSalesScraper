"""Deterministic qualification scoring (0-100) for prospect = (company, decision-maker).

Company fit (40) + Decision-maker fit (35) + Pilot suitability (25).
Only prospects scoring >= 65 are shortlisted.
"""
from __future__ import annotations

import re

QUALIFY_THRESHOLD = 65

EUROPE_HINTS = ("NL", "Netherlands", "DE", "Germany", "UK", "United Kingdom", "CH", "Switzerland",
                "Randstad", "Amsterdam", "Rotterdam", "Luxembourg", "Antwerp", "PL", "Warsaw", "Europe")

TIER1 = re.compile(r"\b(founder|co-?founder|gr[üu]nder|owner|eigenaar|inhaber|co-owner|mede-eigenaar|"
                   r"ceo|chief executive|managing director|managing partner|gesch[äa]ftsf[üu]hrer|"
                   r"gesch[äa]ftsf[üu]hrender|directeur|dga|president|chairman)\b", re.I)
OPS = re.compile(r"\b(coo|chief operating|operations|general manager|gm|head of|commercial director|"
                 r"kaufm[äa]nnischer direktor|director projects|director of projects|industrial projects|"
                 r"agencies|deputy director|prokurist|country director)\b", re.I)
FREIGHT_MGR = re.compile(r"(sea ?freight|ocean freight|air ?freight|seafreight)", re.I)
SALES = re.compile(r"\b(sales|business development|cmso|cco|marketing)\b", re.I)
LOW_REL = re.compile(r"(warehousing|landverkehr|road freight)", re.I)


def tier(title: str) -> int:
    t = title or ""
    if re.search(r"deputy director", t, re.I):
        return 2
    if re.search(r"managing director", t, re.I) and re.search(r"\b(germany|ukraine)\b", t, re.I):
        return 1
    if re.search(r"gesch[äa]ftsf[üu]hr", t, re.I):
        return 1
    if TIER1.search(t) and not re.search(r"\b(general manager|creative)\b", t, re.I):
        return 1
    return 2


def dm_fit(title: str) -> int:
    t = title or ""
    if tier(t) == 1:
        if re.search(r"(owner|founder|gr[üu]nder|eigenaar|inhaber|gesellschafter|managing partner|ceo|dga)", t, re.I):
            return 35
        return 33  # MD / Geschäftsführer without explicit ownership
    if LOW_REL.search(t):
        return 10  # road/warehousing-only role: not responsible for air/ocean RFQ & agent workflows
    if FREIGHT_MGR.search(t):
        return 25
    if OPS.search(t):
        return 29
    if SALES.search(t):
        return 25
    if re.search(r"\bdirector\b", t, re.I):
        return 28
    return 18


def _emp_num(emp):
    if isinstance(emp, (int, float)):
        return int(emp)
    if isinstance(emp, str):
        m = re.match(r"(\d+)\s*-\s*(\d+)", emp)
        if m:
            return (int(m.group(1)) + int(m.group(2))) // 2
        if emp.isdigit():
            return int(emp)
    return None


def company_fit(rev: dict, emp, email_stack: str | None) -> int:
    score = 0
    indep = rev.get("independent")
    score += 10 if indep == 1 else 4
    n = _emp_num(emp)
    if n is None:
        score += 5
    elif 3 <= n <= 50:
        score += 8
    elif n <= 100:
        score += 7
    else:
        score += 2
    air, ocean = rev.get("air"), rev.get("ocean")
    if air == 1 and ocean == 1:
        score += 8
    elif 1 in (air, ocean) and -1 in (air, ocean):
        score += 7
    elif 1 in (air, ocean):
        score += 6
    else:
        score += 4
    score += {2: 7, 1: 5}.get(rev.get("agent_network"), 2)
    # email-heavy operations: inherent to forwarding RFQ/agent work; confirmed mail stack adds points
    score += 7 if email_stack else 5
    return min(score, 40)


def pilot_fit(rev: dict, emp, title: str, location: str) -> int:
    n = _emp_num(emp)
    lean = 6 if n is None else 10 if n <= 20 else 8 if n <= 50 else 5
    air, ocean = rev.get("air"), rev.get("ocean")
    complexity = 8 if (air == 1 and ocean == 1) else 6 if 1 in (air, ocean) else 4
    if rev.get("agent_network") == 2:
        complexity = min(complexity + 1, 8)
    in_europe = any(h in (location or "") for h in EUROPE_HINTS)
    if LOW_REL.search(title or ""):
        willing = 2
    elif not in_europe:
        willing = 3
    elif tier(title) == 1:
        willing = 7 if (n is None or n <= 50) else 6
    else:
        willing = 5
    return min(lean + complexity + willing, 25)


def mode_label(v) -> str:
    return {1: "Yes", 0: "No", -1: "Unconfirmed"}.get(v, "Unconfirmed")


def rationale(company: dict, rev: dict, title: str, cf: int, df: int, pf: int) -> str:
    n = _emp_num(company.get("employees"))
    size = f"~{n} staff" if n else "size n/a"
    modes = []
    if rev.get("air") == 1:
        modes.append("air")
    if rev.get("ocean") == 1:
        modes.append("ocean")
    modes_s = "+".join(modes) if modes else "modes unconfirmed"
    agents = {2: "documented global agent/partner network", 1: "international partners"}.get(
        rev.get("agent_network"), "limited agent evidence")
    t = "Tier 1" if tier(title) == 1 else "Tier 2"
    stack = f"; mail stack: {company['email_stack']}" if company.get("email_stack") else ""
    return (f"Independent {company.get('country')} forwarder ({size}, {modes_s}, {agents}{stack}). "
            f"{t} contact ({title}) with authority over quoting/agent workflows. "
            f"Scores C{cf}/D{df}/P{pf}.")
