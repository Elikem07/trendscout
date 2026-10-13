# TrendScout Build Status

Updated: 2026-07-10. Verification: 63 tests passing, ruff clean, mypy strict clean, alembic drift check clean.

## Complete and verified

**M0 Foundations (all 6 tasks)**: monorepo scaffold, docker compose, GitHub Actions CI (postgres with pgvector plus redis services), identity schema with UUIDv7, Railway and Vercel deploy configs with runbook, dependency risk register (DEPENDENCIES.md), Clerk auth end to end (JWT with JWKS and azp validation, Svix verified webhooks, Next.js middleware and sign in flows).

**M1 Ingestion (all 6 tasks)**: SourceAdapter contract, archive before transform runner (raw responses committed durably before any transformation), monthly partition management with retention, Etsy Open API v3 adapter with injectable transport and cassette tests, Redis backed daily quota budgets (spend before call, atomic refund, 80 percent cap), normalization into shops, listings, and partitioned daily snapshots (Decimal money math, idempotent upserts, generated tsvector column), Celery app with ingest, compute, and notify queues, retry with backoff, dead letter table, beat schedule (daily crawl, weekly Etsy keepalive, retention sweep, nightly compute), 160 seed keywords across 8 categories with interleaved crawl plan, data quality report CLI (make dq-report).

**M2 Semantic layer (all 6 tasks)**: pluggable embedding backends (bge-small for production, deterministic fake for tests), two phase clustering (adopt into existing niches within cosine threshold, then HDBSCAN discovery with single cluster support), grounded LLM labeling (Anthropic client, pydantic schema validation, cache by input hash, slug collision handling), daily niche signal aggregation (engagement deltas, HHI concentration, young listing share, percentile prices), keyword to niche mapping via pgvector cosine distance.

**M3 Scoring engine (all 8 tasks including amendment A1)**: series preprocessing (MAD outlier clipping with IQR fallback for degenerate cases, STL deseasonalization, rolling smoothing), demand and competition subscores (6 each, percentile normalized within category, log scaled counts), opportunity formula with momentum multiplier and confidence factor, trend labels via PELT change point detection (emerging, rising, declining, flat, saturated), revenue estimates as ranges only, all four feeds (Emerging, Hot Now, Trending, Saturated), backtest harness with synthetic archetypes (make backtest), nightly compute pipeline wired into Celery.

**M4 API layer**: /api/v1/niches (list with filters and opportunity sort), /api/v1/niches/{slug} (detail with 28 day history and revenue range), /api/v1/feeds/{name}, /api/v1/search (tsvector ranked), watchlist CRUD. All behind Clerk auth.

## Remaining

**M4 web UI**: dashboard shell and auth pages exist; explore table, niche detail page with charts, watchlist UI, and onboarding flow are not built.
**M5 expansion**: eBay, Reddit, YouTube adapters (the SourceAdapter contract makes each a focused task), trends provider integration, demand forecasting model (forecasts table schema is ready).
**M6 monetization**: Stripe billing, tier gating, alerts and digests, API keys for the API tier, landing page.

## Environment caveats (sandbox limitations, not code gaps)

1. Embedding model weights could not be downloaded here (huggingface.co not network reachable). SentenceTransformerEmbedder is written and ready; tests use the deterministic fake and injected vectors. First run in a real environment downloads bge-small-en-v1.5 (about 130 MB).
2. LLM labeling was tested against a scripted client honoring the exact contract. AnthropicLLM is ready; set ANTHROPIC_API_KEY.
3. Etsy adapter was tested against recorded cassettes. Set ETSY_API_KEY when the personal access request is approved (see DEPENDENCIES.md).
4. Celery tasks were tested in eager mode plus direct logic tests; run a real worker and beat against Redis in staging to validate scheduling.

## Known incidents

During this build, files not authored in the session appeared in the workspace several times (parallel implementations, migrations, tests). Each batch was audited: duplicates removed, two applied migrations adopted after line by line review (they match the models exactly, confirmed by clean drift checks), and improvements worth keeping (Decimal money math, the dead letter table) merged deliberately. Recommendation: move this repo into git with signed commits and continue in Claude Code, where every change is reviewable at commit granularity.
