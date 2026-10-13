# TrendScout

AI product intelligence platform for marketplace sellers. Detects demand across
social and search signals before it becomes marketplace saturation, and scores
niches with explainable Demand, Competition, and Opportunity metrics.

Project documents — PRD, Architecture and Milestones — live in `/docs`.

## Status

Backend is complete and verified through M4: ingestion, semantic clustering,
the scoring engine and the API layer, with 63 tests passing, ruff clean, mypy
strict clean and no Alembic drift. The web UI is partially built — dashboard
shell and auth pages exist; the explore table, niche detail charts, watchlist
UI and onboarding are not. `STATUS.md` has the task-level breakdown.

Notable engineering choices: archive-before-transform ingestion (raw responses
are committed durably before any transformation), Redis-backed daily quota
budgets with atomic refund, two-phase clustering (adopt into existing niches
within a cosine threshold, then HDBSCAN discovery), PELT change-point detection
for trend labels, and revenue reported only as ranges rather than point
estimates.

## Repository layout

```
apps/
  api/        FastAPI backend (API + workers + ML pipeline modules)
  web/        Next.js 15 frontend
packages/
  shared/     Cross app contracts (OpenAPI generated types land here later)
```

## Quick start

Prerequisites: Docker, Node 22+, Python 3.12+.

Option A, everything in Docker:

    cp .env.example .env
    make dev

Option B, infra in Docker, apps native (faster feedback):

    cp .env.example .env
    make infra
    cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
    make api        # terminal 1
    cd apps/web && npm install
    make web        # terminal 2

Web: http://localhost:3000
API: http://localhost:8000 (health: /health, readiness: /health/ready, docs: /docs)

## Verification

    make test       # API unit tests
    make lint       # ruff

## External dependencies

`DEPENDENCIES.md` tracks every third party approval and credential the
product needs (Etsy API access, data providers, quotas), with drafted
application answers. The Etsy commercial access row is the launch
critical path; review weekly.

## Deployment

See `DEPLOY.md` for the Railway + Vercel + Cloudflare runbook, the
staging/production branch model, and the release flow.

## Environment configuration

All configuration flows through environment variables. `.env.example` is the
single source of truth for what exists; `apps/api/app/config.py` (pydantic
settings) validates API side values at startup and fails fast on missing
required config.

## Secrets

No credentials are committed. `.env.example` lists every variable that exists
with placeholder values only; `.env` and `.env.*` are gitignored.
`apps/api/app/config.py` (pydantic settings) validates values at startup and
fails fast on anything missing.

The `whsec_MDAw...` values in `apps/api/tests/` are intentional test fixtures —
they base64-decode to all zeros and exist to exercise webhook signature
verification. They are not live secrets.

Credentials you will need to supply: Clerk (publishable key, secret key,
webhook signing secret, issuer), a Postgres URL, a Redis URL, an Anthropic API
key for LLM labeling, and an Etsy API key once commercial access is approved.
See `DEPENDENCIES.md` and `DEPLOY.md`.

## License

No license granted. All rights reserved.
