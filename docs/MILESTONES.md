# TrendScout Milestone and Task Plan
Version 0.1 | Depends on: PRD v0.1, Architecture v0.1 (both approved)

## Amendment A1 (this version)
Product surfaces three opportunity feeds instead of one:
1. **Emerging**: demand change point within 21d, momentum > 1.1, anomaly filtered. Early and higher risk. Pro tier.
2. **Hot Now**: Demand ≥ 70, momentum ≥ 1.0, Competition ≤ 65. Validated demand with entry room remaining. Starter tier and up. This is the "capitalize on what is working right now" feed.
3. **Trending** (broad): top Opportunity ranked list, all tiers (Free sees ranges).
Niches with high demand but momentum < 0.9 and Competition > 75 are labeled **Saturated** in all views. Warning users off crowded plays is part of the value proposition.
Implementation cost: one task (M3.T8). No schema or architecture changes required.

## Ground rules
- One task ≈ one pull request ≈ half a day to two days of focused work.
- Every task has acceptance criteria. A task is done when criteria pass, tests exist, and docs are updated. Then we stop for your approval.
- Estimates assume solo, part time (~15 h/week). Total: roughly 16 to 20 weeks to paid launch. Full time roughly halves it.
- External dependencies (API approvals) are started in M0 regardless of when their milestone lands.

---

## M0: Foundations (week 1)
Goal: deployable skeleton, CI, credentials pipeline started.

| Task | Description | Acceptance criteria |
|---|---|---|
| M0.T1 | Monorepo scaffold: `apps/api` (FastAPI), `apps/web` (Next.js 15 + TS + Tailwind + shadcn), `packages/shared`, docker compose (Postgres 16 + pgvector, Redis), env config pattern | `docker compose up` gives working local stack; health endpoint returns 200; web renders shell |
| M0.T2 | CI: GitHub Actions running ruff + mypy + pytest (api), eslint + tsc + build (web), on every PR | Green pipeline on main; failing test blocks merge |
| M0.T3 | Database baseline: SQLAlchemy 2 models + Alembic migration for users, sources, api_keys; UUIDv7 helper; migration check in CI | `alembic upgrade head` idempotent; CI fails on model/migration drift |
| M0.T4 | Deploy pipeline: Railway (api + Postgres + Redis), Vercel (web), Cloudflare DNS, staging + production environments | Production URL serves the app; push to main auto deploys staging |
| M0.T5 | External applications day one: Etsy developer app (commercial access request), Reddit API registration, YouTube Data API project + quota extension request, licensed trends provider trial account | All applications submitted and tracked in a DEPENDENCIES.md with status |
| M0.T6 | Auth: Clerk integration, JWT verification middleware in FastAPI, `users` row provisioning via Clerk webhook, `/me` endpoint | Sign up → user row exists → authenticated API call succeeds; unauthenticated returns 401 |

## M1: Etsy Ingestion (weeks 2 to 3)
Goal: reliable daily Etsy data flowing into normalized tables.

| Task | Description | Acceptance criteria |
|---|---|---|
| M1.T1 | SourceAdapter interface, `raw_ingest_archive` (partitioned) and `ingest_runs` tables, archival wrapper | Contract tests pass against a fake adapter; every fetch archived before transform |
| M1.T2 | Etsy adapter: keyword and category listing search, shop fetch; token bucket at 80% of quota; VCR cassette tests | Recorded response tests pass with zero live calls in CI; quota budget enforced and logged |
| M1.T3 | Normalization stage: raw → `listings`, `shops`, `listing_snapshots`; USD conversion; dedup on (source, external_id) | Re running the same batch produces zero duplicate rows; snapshots append one row per listing per day |
| M1.T4 | Celery + Beat: queues (ingest, compute, notify), retry with exponential backoff, dead letter table, failure rate alerting | Kill the worker mid batch → restart → no data loss or duplication; poisoned message lands in DLQ |
| M1.T5 | Seed niches: curated ~150 seed keyword list across 8 Etsy categories; tracked niche crawl scheduling with priority ordering | Daily crawl completes within quota; per niche listing coverage report generated |
| M1.T6 | Data quality CLI report: row counts, null rates, snapshot gaps, price outliers, per source freshness | `make dq-report` outputs pass/fail against thresholds; wired into daily Beat schedule with alert on fail |

## M2: Semantic Layer (weeks 4 to 5)
Goal: listings organized into named niches with daily aggregated signals.

| Task | Description | Acceptance criteria |
|---|---|---|
| M2.T1 | Embedding worker: bge-small-en-v1.5 on CPU, batch embed title+tags, pgvector column, HNSW index | 10k listings embedded < 15 min on one worker; nearest neighbor query < 50 ms |
| M2.T2 | Clustering job: nightly HDBSCAN per category over unassigned embeddings; noise handling; min cluster size tuning documented | On fixture data, produces stable clusters across reruns (adjusted Rand index > 0.9); noise rate < 30% |
| M2.T3 | Niche persistence: create/merge/archive logic, centroid maintenance, listing→niche assignment, slug generation | Re clustering does not orphan listings; merge preserves history via merged_into_id |
| M2.T4 | LLM cluster labeling: grounding payload (top titles, tags), schema validated label + keywords output, `llm_generations` cache | 50 fixture clusters labeled; human spot check ≥ 90% sensible; zero uncached repeat calls |
| M2.T5 | Daily aggregation job: `niche_daily_signals` computed from snapshots (deltas, HHI, young listing share, top20 review median, price stats) | Golden file test: fixture snapshots → exact expected signal rows; job idempotent per (niche, date) |
| M2.T6 | Keyword layer: keyword embedding, keyword↔niche similarity mapping, `search_trends` table ready for provider data | Querying a keyword returns its mapped niches ranked by similarity |

## M3: Scoring Engine (weeks 6 to 7)
Goal: the product's core numbers, tested, versioned, backtestable. Pure functions over `niche_daily_signals`.

| Task | Description | Acceptance criteria |
|---|---|---|
| M3.T1 | Preprocessing: STL decomposition, seasonally adjusted series, seasonal profile extraction; robust z score anomaly filter | Synthetic series with injected spike: spike excluded from growth calc; sustained shift retained |
| M3.T2 | Demand subscores: within category percentile normalization, log transforms, all six factors, weights from architecture 5.1 | Golden vector tests for every factor and the composite; components stored in scores.components JSONB |
| M3.T3 | Competition subscores per architecture 5.2 | Golden vector tests; HHI and young listing share validated against hand computed fixtures |
| M3.T4 | Opportunity: geometric base, momentum multiplier, confidence factor; `algo_version` stamping; formula documented in /docs/scoring.md | Golden tests; changing any weight without version bump fails CI |
| M3.T5 | Change point detection (ruptures PELT) + trend labels (Rising/Stable/Declining/Emerging per 5.4) | Labeled fixture library (20 synthetic + 10 real series) ≥ 85% label accuracy |
| M3.T6 | Revenue estimation with bands + methodology doc page content | Golden tests; output always a range, never a point |
| M3.T7 | Backtest harness: replay historical signals, compute Emerging/Hot Now precision vs naive baseline, emit CI artifact report | `make backtest` produces metrics report; runs in CI weekly; baseline comparison included |
| M3.T8 | **Feeds (A1):** Emerging, Hot Now, Trending queries + Saturated labeling; `(date, opportunity DESC)` index verified with EXPLAIN | Each feed returns correct fixtures; Hot Now excludes momentum < 1.0; Saturated label applied per A1 thresholds; p95 query < 100 ms on 50k niche synthetic dataset |

## M4: Web Application Core (weeks 8 to 10)
Goal: the product is usable end to end with Etsy only data.

| Task | Description | Acceptance criteria |
|---|---|---|
| M4.T1 | App shell: nav, layout, dark mode default, theming tokens, empty states, loading skeletons | Lighthouse ≥ 90 performance/accessibility on shell |
| M4.T2 | Explore page: ranked niche table (virtualized), filter panel (category, score ranges, trend label, feed tabs Emerging/Hot Now/Trending), sparklines, sort | Filters compose correctly; URL reflects state (shareable); p95 interaction < 200 ms |
| M4.T3 | Niche detail page: score gauges with confidence badge, history charts, top listings table, seasonality strip, Saturated warning banner where applicable | All PRD section 6 card elements render from live API |
| M4.T4 | Search: hybrid tsvector + pgvector endpoint and UI with grouped results | "mossy wall decor" finds the moss wall art niche (semantic match test suite) |
| M4.T5 | Watchlist: save/remove, watchlist page with score change deltas since save | Persisted per user; delta since saved date correct |
| M4.T6 | AI explanation panel: `/niches/{id}/explanation` wired, cache behavior, regenerate on material score change | Numeric consistency check passes on 100 fixture generations; cached second view < 100 ms |
| M4.T7 | Public SEO pages `/n/[slug]`: SSG, score ranges only, signup gate, sitemap generation | 500 niche pages build in < 5 min; indexed sitemap valid; exact scores gated |
| M4.T8 | Playwright smoke suite: signup → explore → filter → detail → save | Green in CI on staging |

## M5: Multi Signal + Prediction (weeks 11 to 13)
Goal: the differentiator — social and search signals fused into demand, forecasts live.

| Task | Description | Acceptance criteria |
|---|---|---|
| M5.T1 | Reddit adapter: subreddit + keyword monitors, mention/engagement extraction into `social_signals`, quota compliance | Cassette tests; 6h cadence stable for 7 days; niche mapping via keyword layer |
| M5.T2 | YouTube adapter: search velocity sampling by niche priority, quota cost accounting | Daily run stays under quota with headroom; cost per niche logged |
| M5.T3 | Trends provider adapter (licensed): weekly full + daily top 500 refresh, hard monthly budget cap in code | Budget cap provably halts calls in test; interest series populate `search_trends` |
| M5.T4 | Demand formula upgrade: activate S_level, S_growth, V_social, V_social_growth, B_breadth with real inputs; algo_version bump; backtest rerun | Golden tests updated under new version; backtest report shows breadth factor reduces false Emerging labels vs prior version |
| M5.T5 | Prophet forecasts for top 2,000 niches, EWMA fallback for tail; forecast bands on detail page charts | Backtest MAPE beats seasonal naive on ≥ 60% of top niches, else naive is served; UI renders uncertainty bands |
| M5.T6 | Seasonality heat map page (category × month demand intensity) | Renders from stored seasonal profiles; known seasonal fixtures (ornaments) peak correctly |

## M6: Monetization and Launch (weeks 14 to 16)
Goal: money in, launch out.

| Task | Description | Acceptance criteria |
|---|---|---|
| M6.T1 | Stripe: checkout, customer portal, webhook handling, plan state on user, downgrade/cancel flows | Test clock scenarios pass (upgrade, fail payment, cancel); plan changes reflect in < 5 s |
| M6.T2 | Plan gating + rate limiting middleware per architecture section 8; usage metering on niche detail views | Free user hits 3 view cap and sees upgrade prompt; limits configurable without deploy |
| M6.T3 | Alerts engine: condition evaluation job over daily scores, `alert_events`, email delivery via Resend | Threshold crossing fires exactly once; no duplicate sends on rerun (idempotency key) |
| M6.T4 | Weekly digest email: top movers in user's watchlist + top Emerging/Hot Now per user categories | Renders in major clients (Litmus check); unsubscribe honored |
| M6.T5 | Onboarding flow: category interests → seeded watchlist → first aha in under 2 minutes | Activation event (first save) instrumented in PostHog |
| M6.T6 | Launch hardening: Sentry release tracking, load test (k6: 200 concurrent users on explore/detail), security pass (headers, webhook signatures, dependency audit), status page, LAUNCH.md checklist | k6 p95 < 500 ms; zero critical findings; checklist complete |

## External dependency tracker (start M0, monitor throughout)
| Dependency | Blocks | Fallback if denied/delayed |
|---|---|---|
| Etsy commercial API approval | Public launch (not development: personal access suffices for building) | Launch delayed or pivot to eBay+social first product; decision point end of M3 |
| Reddit commercial approval | M5.T1 at scale | Reduce cadence under free tier |
| YouTube quota extension | M5.T2 breadth | Sample fewer niches daily |
| Trends provider contract | M5.T3 | Second provider quoted in parallel |

## Milestone gates (your approval checkpoints beyond per task approval)
- Gate A after M1: inspect real Etsy data quality together before building semantics on top of it.
- Gate B after M3: review backtest report; if Emerging precision does not beat naive, we fix the engine before building UI on it.
- Gate C after M5: go/no go on launch pricing given data costs observed in practice.

## Next step
On your approval, we begin M0.T1 and proceed one task at a time.
