# ApolloSalesScraper - European freight-forwarder design-partner research

This repo holds the research pipeline and deliverables for finding decision-makers at independent
European freight forwarders (NL > DE > UK > CH, 3-100 staff, air/ocean, agent networks). They are
candidate design partners for a free 4-6 week AI freight-forwarding co-pilot pilot.
**No prospect has been contacted.**

## Deliverables
- `output/European_Freight_Forwarding_Prospects.xlsx`, with five sheets: Enriched Prospects, Post-Credit
  People Search, Company Research, Research Methodology, Excluded Prospects.
- `output/European_Freight_Forwarding_Prospects.csv`, which holds Sheet 1 (Enriched Prospects).

## Pipeline
```
ffresearch/
  db.py            SQLite schema + idempotent upserts (data/research.db, git-ignored)
  apollo_client.py Official Apollo REST client (APOLLO_API_KEY env var; retry, 429/Retry-After, pagination)
  ingest.py        Loads raw checkpoints in data/raw/*.json (Apollo lookups/enrichments, Clay people batches)
  scoring.py       Deterministic 100-point scoring (company 40 / decision-maker 35 / pilot 25), threshold 65
  build_outputs.py Scores prospects, keeps at most 2 per company, writes XLSX + CSV, validates
data/methodology.json  Filters, sources, scoring, limitations, credit summary
```
Rebuild from the checkpoints (resume-safe, no API calls):
```bash
pip install openpyxl requests
rm -f data/research.db && python3 -m ffresearch.build_outputs
```

## Credentials
Credentials come only from environment variables (`export APOLLO_API_KEY=...`). Nothing secret is
stored in the repo, and `.env` files are git-ignored. This research run used Apollo's official MCP
(OAuth) integration.

## Known limitations
- The connected Apollo account is on the **Free plan**. People search, person enrichment
  (`people/match`, `people/bulk_match`) and the AI agent return `API_INACCESSIBLE`. As a result:
  - No emails could be revealed or verified.
  - Decision-makers were found with Clay's free public-profile people search.
  - Apollo credits (171 of 200) were spent on company validation enrichment.
- To add emails, run `ApolloClient.people_bulk_match` with a paid-plan key on the Sheet 1 contacts.
- Credits were not exhausted, so the Post-Credit People Search sheet is empty.
