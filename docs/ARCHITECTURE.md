# TrendScout System Architecture
Version 0.1 | Depends on: PRD v0.1 (approved)

Assumptions carried into this design: solo founder, ~$150/mo external data budget at MVP, Etsy first beachhead approved, target scale 5,000 registered / 500 paying users in year one.

---

## 1. Architecture Overview

**Pattern: modular monolith.** One Python backend containing three modules (API, ingestion workers, ML pipeline) sharing one database, deployed as separate processes from one repo. Not microservices.

Why: a solo founder cannot operate a distributed system. A modular monolith gives clean seams (each module can become a service later) with none of the operational cost. Every boundary below is a Python package boundary today and a network boundary only if scale demands it.

```
                          ┌─────────────────────────────┐
  Next.js (Vercel) ──────►│  FastAPI (api module)       │
  Cloudflare in front     └──────┬──────────────────────┘
                                 │
      ┌─────────────┬────────────┼───────────────┐
      ▼             ▼            ▼               ▼
  PostgreSQL     Redis      Celery workers   Celery beat
  + pgvector   (cache,      (ingestion,      (scheduler)
  (Railway)     queues,      ML pipeline,
                rate         alerts, email)
                limits)
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
                Etsy API     eBay/Reddit/   Licensed
                             YouTube APIs   trends feed
```

**Deliberate omissions at v1** (each is a real recommendation, not an oversight):
- **No Elasticsearch/OpenSearch.** Postgres full text search (tsvector) handles keyword search at this scale; pgvector handles semantic search. One database, not two. Add OpenSearch only when search latency or relevance measurably fails.
- **No Kafka/event bus.** Celery over Redis covers all async needs.
- **No Kubernetes.** Railway (or Fly.io) runs the containers.

## 2. Technology Stack and Rationale

| Layer | Choice | Why this over alternatives |
|---|---|---|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind, shadcn/ui | Server components for fast dashboard loads, Vercel deploy is zero ops, shadcn gives the Linear/Stripe aesthetic without a design system project. React alternatives (Vite SPA) lose SSR for the programmatic SEO pages, which are the acquisition strategy |
| Data fetching/state | TanStack Query | Cache invalidation and background refetch for dashboard data; avoids Redux ceremony |
| Charts | Recharts (+ lightweight sparkline component) | Good enough, themeable, small. Upgrade path: visx if custom viz needed |
| Backend API | FastAPI (Python 3.12) | The ML pipeline must be Python (sentence transformers, XGBoost, Prophet). One language across API and pipeline means shared models, shared validation, one deployment toolchain. NestJS would split the codebase in two for zero benefit |
| ORM/migrations | SQLAlchemy 2 + Alembic | Standard, typed, async capable |
| Validation | Pydantic v2 | Shared schemas between API and pipeline |
| Database | PostgreSQL 16 + pgvector extension | Relational core + vector search + full text search + JSONB in one system. Time series tables use native declarative partitioning (monthly); TimescaleDB deferred as it constrains hosting choices |
| Cache/queue | Redis 7 | Celery broker, API response cache, rate limit counters, hot score cache |
| Task queue | Celery + Celery Beat | Battle tested scheduling, retries, rate limiting per queue. ARQ is lighter but weaker retry/routing semantics; ingestion is the riskiest subsystem, so choose boring |
| Embeddings | sentence-transformers, bge-small-en-v1.5, self hosted on CPU workers | 384 dims, fast on CPU, free at our volume. API embeddings (OpenAI) would cost more and add a dependency for a commodity capability |
| Clustering | HDBSCAN (via scikit-learn ecosystem) | Density based: finds variable size niches and labels noise, no need to guess k |
| Classical ML | scikit-learn, LightGBM | LightGBM over XGBoost: faster training, native categorical handling; interchangeable if preferences differ |
| Forecasting | statsmodels (STL, EWMA), Prophet, ruptures (change points) | Covered in section 6 |
| LLM | Claude API (Sonnet class) for explanations and idea generation | Structured JSON grounding contract, section 7. Provider abstracted behind one interface so models are swappable |
| Auth | Clerk (frontend components + JWT verified in FastAPI) | Auth is undifferentiated heavy lifting; Clerk saves ~2 weeks solo. Cost acceptable until ~2k MAU, revisit then |
| Billing | Stripe (Checkout + Customer Portal + webhooks) | Industry default |
| Email | Resend + React Email templates | Digests and alerts |
| Hosting | Railway: API, workers, Postgres, Redis. Vercel: frontend. Cloudflare: DNS, CDN, WAF | Railway = push to deploy for all backend processes from one repo. Fly.io is the fallback if Railway pricing degrades. AWS deferred: real capability, real ops tax |
| CI/CD | GitHub Actions | Lint, typecheck, tests, migrations check, deploy |
| Observability | Sentry (errors), Railway metrics, structured JSON logs, PostHog (product analytics) | Minimal viable observability |

## 3. Data Pipeline Design

Five stages, each idempotent and independently retryable. All raw API responses are archived before transformation (reprocessing insurance).

### Stage 1: Ingestion (per source adapter)
Each source implements a common `SourceAdapter` interface: `fetch_batch(cursor) -> RawRecords`. Celery Beat schedules per source respecting quota budgets:

| Source | Cadence | Quota strategy |
|---|---|---|
| Etsy | Listings for tracked niches daily; discovery crawl of category new listings 2x/day | Token bucket capped at 80% of daily quota; priority queue: watchlisted niches first |
| eBay Browse | Daily per tracked niche | Generous quota, low risk |
| Reddit | Subreddit and keyword monitors, every 6h | Stay under free tier QPM; commercial approval application filed at launch |
| YouTube | Search velocity checks daily per tracked niche; quota heavy (100 units/search) so niches are sampled by priority score | Quota extension application early |
| Trends feed (licensed) | Weekly full refresh + daily for top 500 niches | Cost cap enforced in code: hard monthly budget |

Failures: exponential backoff, dead letter queue table, alerting on adapter failure rate >5%.

### Stage 2: Normalization
Raw records → canonical `listings`, `shops`, `social_signals`, `search_trends` rows. Currency normalization to USD (daily FX snapshot). Dedup on (source, external_id).

### Stage 3: Entity resolution (niche assignment)
1. Embed listing title + tags (bge-small, 384d) → stored in pgvector.
2. Nightly HDBSCAN over new/unassigned embeddings (per top level category to keep cluster quality high).
3. Clusters persisted as `niches`; new clusters get LLM generated labels ("Moss wall art", not "cluster_4812") plus 3 to 8 representative keywords.
4. Listings map to niches via cluster membership; keywords map to niches via embedding similarity threshold. A listing can belong to one primary niche and multiple keyword sets.
5. Human readable niches that never came from a user query = the "hidden niches" feature, for free.

### Stage 4: Daily aggregation
For each active niche, one row per day in `niche_daily_signals`: listing count, new listings, median price, price IQR, favorites delta, review delta, HHI, search interest, Reddit mentions, YouTube video count/views delta. This table is the single input to everything downstream — scores, forecasts, charts. Materialized once, read everywhere.

### Stage 5: Compute (scores, forecasts, labels)
Runs after aggregation. Writes `scores`, `forecasts`, trend labels, and refreshes the Redis hot cache for the top ~2,000 niches. Score algorithm is versioned (`algo_version` on every row) so formula changes never silently rewrite history.

## 4. Database Schema

Conventions: `id` = UUIDv7 PK, `created_at/updated_at` timestamptz on all tables, FKs indexed. Time series tables are monthly range partitioned on `date`.

```sql
-- ===== Identity & billing =====
users (
  id, clerk_id UNIQUE, email UNIQUE, plan TEXT DEFAULT 'free',
  stripe_customer_id, settings JSONB
)
subscriptions (
  id, user_id FK, stripe_subscription_id UNIQUE, plan, status,
  current_period_end
)
api_keys (
  id, user_id FK, key_hash UNIQUE, name, scopes TEXT[],
  last_used_at, revoked_at
)

-- ===== Catalog =====
sources ( id, code UNIQUE, name )   -- etsy, ebay, reddit, youtube, trends

shops (
  id, source_id FK, external_id, name, url, country,
  total_sales_est INT, first_seen_at,
  UNIQUE (source_id, external_id)
)

listings (
  id, source_id FK, external_id, shop_id FK,
  title TEXT, description_snippet TEXT, url,
  price_usd NUMERIC(10,2), currency_orig,
  tags TEXT[], category TEXT,
  listing_created_at,           -- listing age input to Competition
  status,                        -- active / ended / removed
  review_count INT, favorites_count INT,   -- latest values
  embedding VECTOR(384),
  niche_id FK NULL,
  search_tsv TSVECTOR GENERATED,
  UNIQUE (source_id, external_id)
)
-- Indexes: GIN(tags), GIN(search_tsv), HNSW(embedding),
--          (niche_id, status), (shop_id)

listing_snapshots (            -- PARTITIONED BY RANGE (date)
  listing_id FK, date DATE,
  price_usd, review_count, favorites_count, est_rank INT,
  PRIMARY KEY (listing_id, date)
)
-- BRIN(date) per partition; deltas computed at read/aggregation time

-- ===== Semantic layer =====
keywords (
  id, phrase UNIQUE, embedding VECTOR(384), category
)
niches (
  id, label TEXT, slug UNIQUE, category,
  centroid VECTOR(384), status,          -- active / merged / archived
  discovered_via,                        -- clustering / user_query / seed
  merged_into_id FK NULL
)
niche_keywords ( niche_id FK, keyword_id FK, similarity REAL,
                 PRIMARY KEY (niche_id, keyword_id) )

-- ===== Signals (all partitioned by month on date) =====
search_trends (
  keyword_id FK, geo, date DATE, interest REAL, provider,
  PRIMARY KEY (keyword_id, geo, date)
)
social_signals (
  id, source_id FK, niche_id FK, date DATE,
  mentions INT, engagement BIGINT,       -- upvotes+comments / views
  top_urls JSONB,
  UNIQUE (source_id, niche_id, date)
)
niche_daily_signals (
  niche_id FK, date DATE,
  active_listings INT, new_listings INT,
  median_price NUMERIC, price_iqr NUMERIC,
  favorites_delta INT, reviews_delta INT,
  hhi REAL, top20_median_reviews INT, young_listing_share REAL,
  search_interest REAL, social_mentions INT, social_engagement BIGINT,
  PRIMARY KEY (niche_id, date)
)

-- ===== Computed =====
scores (
  niche_id FK, date DATE,
  demand REAL, competition REAL, opportunity REAL,
  momentum REAL, confidence REAL,
  trend_label TEXT,        -- rising / stable / declining / emerging
  components JSONB,        -- every subscore, for explainability
  algo_version TEXT,
  PRIMARY KEY (niche_id, date)
)
-- Index: (date, opportunity DESC) → powers the Trending/Emerging feeds

forecasts (
  niche_id FK, run_date DATE, horizon_days INT,
  yhat REAL[], yhat_lower REAL[], yhat_upper REAL[],
  model TEXT, PRIMARY KEY (niche_id, run_date, model)
)
revenue_estimates (
  niche_id FK, date DATE,
  monthly_revenue_est NUMERIC, monthly_sales_est INT,
  low NUMERIC, high NUMERIC, method TEXT,
  PRIMARY KEY (niche_id, date)
)

-- ===== User features =====
watchlist_items (
  id, user_id FK, niche_id FK, notes TEXT,
  UNIQUE (user_id, niche_id)
)
saved_searches (
  id, user_id FK, name, query JSONB      -- filters serialized
)
alerts (
  id, user_id FK, niche_id FK NULL, saved_search_id FK NULL,
  condition JSONB,        -- e.g. {"metric":"opportunity","op":">=","value":80}
  channel TEXT DEFAULT 'email', active BOOL
)
alert_events (
  id, alert_id FK, fired_at, payload JSONB, delivered BOOL
)

-- ===== Ops =====
raw_ingest_archive ( id, source_id, fetched_at, payload JSONB )  -- monthly partitions, 90 day retention
ingest_runs ( id, source_id, started_at, finished_at, status, records INT, error TEXT )
llm_generations ( id, niche_id, kind, input_hash, output JSONB, model, created_at )  -- LLM cache
```

Retention: `listing_snapshots` and `raw_ingest_archive` partitions dropped after 18 and 3 months respectively; `niche_daily_signals` and `scores` kept forever (they are the product's long term asset).

## 5. Scoring Algorithms

All subscores are normalized to 0 to 100 via **percentile rank within category** (a demand level that is mediocre for jewelry may be exceptional for macrame; cross category comparability requires within category normalization). Volume metrics are log transformed first. Time windows: level = trailing 28d mean; growth = trailing 28d vs prior 28d, on seasonally adjusted series (STL decomposition removes yearly seasonality so Christmas ornaments do not read as "emerging" every October — seasonality is reported separately as its own profile).

### 5.1 Demand Score

`D = 0.20·S_level + 0.15·S_growth + 0.25·E_velocity + 0.10·V_social + 0.15·V_social_growth + 0.15·B_breadth`

| Factor | Definition | Why this weight |
|---|---|---|
| S_level, search interest level (0.20) | Trend feed interest, 28d mean | The most direct buyer intent proxy available |
| S_growth, search growth (0.15) | 28d vs prior 28d, seasonally adjusted | Direction matters as much as level for early detection |
| E_velocity, marketplace engagement (0.25) | Favorites delta + reviews delta per active listing | Highest weight because it is closest to actual purchases (reviews trail sales at a roughly stable per category rate) and it is per listing, so it measures demand intensity, not just niche size |
| V_social, social volume (0.10) | Reddit mentions + YouTube activity, log | Leading but noisy; volume alone gets low weight |
| V_social_growth (0.15) | Social velocity | The leading indicator term: social chatter inflects weeks before marketplace metrics |
| B_breadth (0.15) | Count of independent sources showing above median activity (0 to 4 scaled) | Confirmation across uncorrelated sources sharply reduces false positives; a signal appearing only on Reddit is a conversation, on Reddit + search + favorites it is demand |

### 5.2 Competition Score (higher = more crowded = worse)

`C = 0.25·N_listings + 0.20·A_young + 0.20·R_moat + 0.15·(100−H_frag) + 0.10·P_tight + 0.10·G_supply`

| Factor | Definition | Why |
|---|---|---|
| N_listings (0.25) | Active listing count percentile | Raw crowdedness; biggest single factor |
| A_young, young listing share (0.20) | Share of listings created in last 90d | Many young listings = the gold rush already started = the exact situation the product exists to help users avoid; heavily weighted |
| R_moat, review moat (0.20) | Median reviews of top 20 listings | Entrenched incumbents with thousands of reviews make entry hard even in small niches |
| H_frag, fragmentation (0.15, inverted) | 100 − HHI percentile of seller concentration | Fragmented markets (no dominant shop) are easier to enter than markets one shop owns |
| P_tight, price tightness (0.10) | Inverse of price IQR / median | Tight price dispersion = commoditized, price competition only; wide dispersion = room for differentiated positioning |
| G_supply, supply growth (0.10) | New listings 28d growth | Complements A_young with a faster signal |

### 5.3 Opportunity Score

```
base       = 100 · (D/100)^0.6 · (1 − C/100)^0.4
momentum   = clamp(1 + 0.5·(g_demand − g_supply), 0.80, 1.30)
Opportunity = clamp(base · momentum · confidence_factor, 0, 100)
```

- **Geometric, not additive:** an additive formula would let zero demand + zero competition score 50. Geometric means weak demand cannot be rescued by an empty market (empty markets are usually empty for a reason). Demand exponent 0.6 > competition 0.4: demand existence matters more than competition absence.
- **Momentum multiplier** is the early detection core: g_demand and g_supply are normalized 28d growth rates of the demand composite and of listing count. Demand accelerating while supply lags → up to +30%. Supply flooding in faster than demand → down to −20%. This is what surfaces "moss wall art" in week 3 instead of month 6.
- **Confidence factor** (0.75 to 1.0) scales down scores built on sparse data: fewer than 20 listings, under 60 days of history, or only one signal source. Shown to the user as a confidence badge; sparse but exciting niches appear in the Emerging feed with an explicit low confidence label rather than a falsely precise 91.

### 5.4 Trend labels
- **Emerging:** change point detected in demand composite within last 21d, positive direction, momentum > 1.1, anomaly filter passed (section 6).
- **Rising:** g_demand > +15% without a discrete change point. **Declining:** < −15%. **Stable:** otherwise.

### 5.5 Revenue estimation (method published to users)
`monthly_sales_est = reviews_delta_30d ÷ review_rate_category`, where review_rate defaults to 0.20 to 0.25 for handmade (calibrated later against any ground truth users share). `monthly_revenue_est = monthly_sales_est × median_price`. Bands: review_rate ± 40%. Always displayed as a range with "how we estimate this" linked. False precision is the fastest way to lose trust in this product category.

## 6. Forecasting and Early Detection System

Input: `niche_daily_signals`. Per niche daily run, cheapest to most expensive:

1. **Preprocessing:** STL decomposition → trend + seasonal + residual. All downstream logic runs on the seasonally adjusted series; the seasonal component becomes the niche's seasonality profile (heat map feature).
2. **Anomaly filter:** robust z score (median/MAD) on residuals. A single day spike (one viral Reddit post) with no follow through is flagged and excluded from growth calculations — this is the main defense against chasing noise. Sustained elevation (5+ days above threshold) is not an anomaly; it is a signal.
3. **Change point detection:** `ruptures` (PELT, RBF kernel) on the adjusted demand composite, minimum segment 14d. A recent positive change point is the trigger condition for Emerging.
4. **Momentum indicators:** EWMA(7) vs EWMA(28) crossover, 28d rate of change — cheap features feeding both the momentum multiplier and the UI sparkline annotations.
5. **Forecasting:** Prophet per niche for top ~2,000 niches (yearly + weekly seasonality, 90d horizon, uncertainty intervals shown in UI). Long tail niches get EWMA extrapolation only — Prophet on 50,000 niches would be wasted compute for scores nobody views. Every model is benchmarked against seasonal naive; if it cannot beat naive on backtest MAPE, ship naive (honesty over sophistication).
6. **Emergence classifier (v2, after data accrues):** LightGBM binary classifier: given a niche's feature vector at time T, did demand grow ≥50% over the following 60d while supply growth lagged? Trained on our own accumulated history with realized outcomes. Until ~6 months of outcome data exist, the heuristic rules in 5.4 stand in. This classifier and its training data become the compounding moat.

## 7. LLM Layer

**Grounding contract:** the LLM never computes or estimates numbers. Every call receives a structured JSON payload of computed signals (scores, components, growth rates, top listings, seasonal profile) and generates only language: explanations, ideas, positioning angles, keyword expansions. Outputs are schema validated (Pydantic); any numeric claim in the output is checked against the input payload and regenerated on mismatch.

Cost control: generation on first view, cached in `llm_generations` keyed by (niche, kind, input_hash), invalidated when scores shift materially (>5 points). Explanations use a small fast model; business idea generation (Pro feature, lower volume) uses a stronger model. Estimated LLM cost at 500 paying users: under $200/mo.

## 8. API Design

Base `/api/v1`, JSON, cursor pagination (`?cursor=&limit=`), errors as RFC 7807 problem+json.

**Auth:** web app → Clerk JWT (verified via JWKS in FastAPI middleware). Programmatic (Agency+) → `Authorization: Bearer ts_live_...` API keys, hashed at rest, scoped read only at launch.

**Rate limiting:** Redis sliding window, keyed by user/API key, headers `X-RateLimit-*`. Free 30 req/min & 3 niche detail views/day; Starter 60/min & 50/day; Pro 120/min unlimited views; Agency API 10k req/day. Enforced in middleware, limits stored per plan in config not code.

```
GET  /search?q=&type=niches|keywords|listings     # tsvector + pgvector hybrid
GET  /niches?sort=opportunity&trend=emerging&category=&min_demand=&cursor=
GET  /niches/{id}                                  # full card
GET  /niches/{id}/history?metric=&from=&to=
GET  /niches/{id}/forecast
GET  /niches/{id}/listings?sort=reviews
GET  /niches/{id}/explanation                      # LLM, cached
POST /niches/{id}/ideas                            # LLM, Pro+
GET  /keywords/{id} , GET /keywords/{id}/trends
GET  /feeds/trending , GET /feeds/emerging         # Pro+ for emerging
GET/POST/DELETE /watchlist , /saved-searches , /alerts
GET  /me , GET /me/usage
POST /billing/checkout , POST /billing/portal , POST /webhooks/stripe , POST /webhooks/clerk
```

**GraphQL:** not at v1. Becomes worth it only if third party API consumers (Agency tier) demand flexible joins across niches/listings/history; revisit on evidence. REST + a few composed endpoints covers the first party UI cheaper.

## 9. Frontend Architecture

Routes: `/dashboard`, `/explore` (niche explorer: filter panel + ranked table + sparklines), `/niche/[slug]` (detail: score gauges, history charts with forecast bands, top listings, AI panel), `/keywords`, `/watchlist`, `/alerts`, `/settings`, plus public `/n/[slug]` SEO pages (SSG, ranges only, signup gate for exact scores — the acquisition engine).

Server components fetch initial data (fast first paint); TanStack Query handles interactive refetch. Dark mode default via CSS variables (shadcn theming). Tables virtualized past 100 rows. Design language: Linear density, Stripe restraint — one accent color, score color scale (red→amber→green) as the only strong color in the UI.

## 10. Security and Compliance

- Secrets in Railway/Vercel env vaults; never in repo. Separate staging environment.
- PII minimized: email + Stripe customer id only; no marketplace credentials ever requested from users.
- Source ToS compliance enforced structurally: adapters only exist for Green/Yellow sources per the PRD matrix; Etsy attribution requirements rendered in UI; per source caching rules encoded in adapter config.
- SQL injection surface: SQLAlchemy bound parameters everywhere; user supplied filter JSON validated against a whitelist schema.
- Webhooks (Stripe, Clerk) signature verified.

## 11. Testing and Quality Strategy

- Unit: scoring functions are pure and exhaustively tested against fixture vectors (golden files); any formula change that alters golden outputs requires an `algo_version` bump.
- Adapters: recorded API responses (VCR style cassettes) so tests never hit live APIs.
- Integration: docker compose Postgres+Redis in CI; pipeline stages run end to end on synthetic fixtures.
- Backtesting harness: replay historical signal data through the scoring/labeling pipeline and measure Emerging label precision vs naive baseline — this is a permanent CI artifact, not a one off notebook.
- Frontend: Playwright smoke on the money paths (signup → explore → save → upgrade).

## 12. Cost Estimate (MVP, monthly)

Railway (API + 2 workers + Postgres + Redis) ~$40–70, Vercel free→$20, Clerk free→$25, licensed trends feed ~$100–150 (capped in code), LLM ~$50 pre scale, Resend/Sentry/PostHog ~$0–30. **Total ≈ $210–300/mo** before revenue. First ~10 Starter customers cover infrastructure.

## 13. Scaling Path (write once, execute only when triggered)

| Trigger | Change |
|---|---|
| Aggregation window >2h | Split worker pools by queue; scale horizontally |
| Search latency >300ms p95 or relevance complaints | Introduce OpenSearch fed by CDC |
| >20k niches with Prophet demand | Move forecasting to batch GPU/spot compute or trim with the classifier |
| Postgres >200GB | Move `listing_snapshots` to cheap columnar storage (DuckDB/Parquet on object storage) with Postgres keeping 90d hot |
| Team grows | Module seams become service boundaries; contracts already exist |

## 14. Next Step

Step 3 per process: milestone plan. Preview — M0 repo/CI/infra skeleton and Etsy app application; M1 Etsy ingestion + normalization; M2 niche clustering + daily aggregation; M3 scoring engine + backtest harness; M4 web app core; M5 social signals + trends feed + labels/forecasts; M6 billing, alerts, digests, launch. Each will be decomposed into approval gated tasks.
