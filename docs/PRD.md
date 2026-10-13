# Product Requirements Document
## TrendScout (working name): AI Product Intelligence Platform

Version 0.1 | Status: Draft for founder review

---

## 1. Vision

Sellers on handmade and resale marketplaces discover products by intuition or by copying what is already saturated. TrendScout detects demand signals across social platforms and search weeks before they show up as marketplace competition, and translates them into a ranked, explainable list of product opportunities with estimated economics.

One sentence: **Bloomberg Terminal for micro ecommerce niches, with a prediction engine instead of a rearview mirror.**

## 2. Problem

1. Existing tools (eRank, EverBee, Alura, Sale Samurai) report what is already selling on Etsy. By the time a product ranks in their "trending" lists, hundreds of sellers have copied it and margins are gone.
2. Trend signals exist earlier elsewhere: Reddit threads, YouTube video velocity, search interest inflections, Pinterest saves. No tool fuses these with marketplace supply data.
3. Sellers cannot quantify "is this niche worth entering." They need a single decision grade number with an explanation, not fifteen raw metrics.

## 3. Target Users

**Primary (beachhead): Active Etsy and handmade sellers, $500 to $10,000 monthly revenue.** They already pay $10 to $30/mo for eRank or EverBee. Pain: product selection risk. Willingness to pay is proven.

**Secondary:** Print on demand sellers, dropshippers testing TikTok Shop products, resellers (Depop, eBay).

**Tertiary (Agency/Enterprise tiers):** Ecommerce agencies managing multiple client shops; brands doing product line planning.

Explicit non target for v1: Amazon FBA sellers (Jungle Scout and Helium 10 own that market and Amazon data is not accessible compliantly).

## 4. Competitive Landscape

| Tool | Focus | Weakness we exploit |
|---|---|---|
| eRank | Etsy SEO and stats | Backward looking, no prediction, dated UI |
| EverBee | Etsy revenue estimates | Single platform, no social signals |
| Alura | Etsy research suite | Same as above |
| Glimpse | Google Trends enrichment | No marketplace supply data, no economics |
| Exploding Topics | Broad trend discovery | Not actionable for sellers, no competition or revenue data |

**Differentiation:** cross signal early detection + supply side competition scoring + explainable AI recommendations, in one workflow.

## 5. Data Source Reality Matrix

This section governs everything downstream. Sources are classified as Green (official API, commercially usable), Yellow (compliant alternative exists with constraints), Red (not feasible without ToS violations or licensing).

### Green: build on these for v1

| Source | Access path | Constraints |
|---|---|---|
| Etsy Open API v3 | Official API. Personal access is immediate; commercial access requires Etsy app approval | ~10k requests/day default, caching rules in ToS, approval process is a launch dependency. Apply early |
| eBay Browse API | Official, free developer program | Active listing data only. Sold data (Marketplace Insights API) is limited access and requires a separate business application |
| Reddit Data API | Official OAuth API | Free tier at low volume; commercial use above thresholds requires Reddit approval and possibly paid access |
| YouTube Data API v3 | Official, free | 10,000 units/day quota per project; search calls are expensive (100 units). Quota extension application available |

### Yellow: compliant alternatives with tradeoffs

| Source | Compliant path | Non compliant path we will NOT take |
|---|---|---|
| Google Trends | (a) Official Trends API alpha (apply for access), (b) licensed resellers such as DataForSEO or Glimpse API, (c) manual CSV export tooling for internal research | pytrends and similar unofficial libraries violate Google ToS and break frequently |
| Pinterest | Pinterest API v5 with standard access (requires app review); ads keyword volume via Ads API requires an ad account | Scraping pinterest.com/trends |
| TikTok | Creative Center trend data is viewable but has no API; TikTok Commercial Content API covers ads only. Realistic path: licensed social listening data (e.g., Brandwatch tier providers) at Agency price points, or treat TikTok as a later phase | Scraping TikTok |
| Instagram | Graph API hashtag search: 30 unique hashtags per 7 days per account, business account required. Useful for spot checks, not bulk collection | Scraping |
| Shopify stores | The public products.json endpoint exists but bulk collection is legally gray and blocked by many stores. Defer; if pursued, only via licensed datasets | Bulk crawling storefronts |

### Red: excluded from roadmap until conditions change

| Source | Why |
|---|---|
| Amazon Handmade | No market intelligence API. Product Advertising API requires an Associates account with qualifying sales and restricts data use to driving Amazon traffic. Scraping violates ToS |
| Facebook Marketplace | No API, aggressive anti scraping, high legal risk |
| Depop | No public API |

**Strategic conclusion:** v1 = Etsy (supply and demand proxies) + eBay Browse (supply) + Reddit + YouTube (leading social signals) + one licensed search trend feed. This is enough to build the prediction engine. Every additional source is an accuracy upgrade, not a blocker.

## 6. Core Product: The Three Scores

All scores are 0 to 100, computed per **keyword/niche entity** (e.g., "moss wall art"), refreshed daily. Full algorithm specification lives in the architecture document; this defines product behavior.

### Demand Score
What buyers want right now. Inputs: search interest level and 90 day growth, social mention volume and velocity (Reddit, YouTube), marketplace engagement proxies (Etsy favorites velocity, review velocity on matching listings), seasonally adjusted.

### Competition Score
How crowded the supply side is. Inputs: active listing count matching the niche, listing age distribution (many young listings = gold rush already started), seller concentration (HHI: is one shop dominating or fragmented), review moat of top 20 listings, price dispersion (tight pricing = commoditized).

### Opportunity Score
The headline number. Not a simple average: computed so that weak demand cannot be rescued by low competition (a geometric combination), then adjusted by a **momentum multiplier** (rate of change of demand vs rate of change of supply — the core "early detection" term) and a **confidence penalty** when underlying data is sparse.

### Per niche output card
- Demand, Competition, Opportunity scores with 30 day sparklines
- Trend direction: Rising / Stable / Declining / Emerging (change point detected)
- Estimated monthly revenue and sales velocity for the niche and for top listings, always labeled as estimates with a stated confidence band (derived from review velocity × category review rates + favorites signals; this is inference, and we say so — trust is a feature)
- Seasonality profile (12 month shape)
- AI explanation: WHY this scores well, citing the specific signals ("Reddit mentions up 240% in 6 weeks while Etsy listing count grew only 12%")
- AI recommendations: positioning angle, pricing band, keyword/tag suggestions, product variation ideas

## 7. AI/ML System (summary; full spec in architecture doc)

Layered, with LLMs at the edges and classical ML in the core:

1. **Entity resolution and clustering:** sentence transformer embeddings over listing titles/tags/descriptions; HDBSCAN clustering to discover niches nobody typed into a search box (the "hidden niches" feature). LLM labels clusters with human readable names.
2. **Time series layer per niche:** daily signal vectors (search, social, supply, engagement). Forecasting with statistical baselines + gradient boosted models on engineered features (momentum, moving average crossovers, volatility); Prophet class models for seasonality decomposition. Change point detection (e.g., Bayesian online change point or ruptures) to flag regime shifts = "Emerging" tag. Anomaly detection to filter one off spikes (a viral post that won't persist) from durable trends.
3. **Scoring layer:** deterministic, versioned, explainable formulas over model outputs. Scores must be reproducible and auditable; no LLM in the scoring path.
4. **LLM layer (Claude/GPT class models):** natural language explanations grounded in the computed signals (the LLM is given the numbers, never asked to invent them), business idea generation, product improvement suggestions, keyword expansion. Every LLM output cites its input signals.
5. **Feedback loop (post v1):** track which flagged opportunities actually grew; retrain the momentum classifier on realized outcomes. This becomes the long term moat.

## 8. Features by Release

### V1 (MVP, paid launch)
- Auth, billing (Stripe), onboarding
- Niche/keyword explorer with the three scores, filters, sorting
- Niche detail page: full card as specified in section 6
- Trending and Emerging feeds (daily refresh)
- Watchlist (save niches, track score changes)
- Weekly email digest
- Dark mode, responsive, Linear/Stripe grade UI

### V1.5
- Competitor/shop analysis (Etsy shop level metrics)
- Saved searches with configurable email alerts (score threshold crossings)
- Demand heat map (seasonality × category matrix)
- AI business idea generator
- CSV export

### V2
- Public REST API (Agency+)
- Daily trend reports (PDF/email)
- eBay and additional platform coverage surfaced in UI
- Team seats

### Later
- Chrome extension (overlay scores while browsing Etsy)
- TikTok Shop coverage via licensed data
- GraphQL API if third party integrators demand flexible queries

### Non goals for v1
- Amazon anything. Multi platform UI. Mobile app. Automated listing creation. Ad management.

## 9. Monetization

| Tier | Price (indicative) | Included |
|---|---|---|
| Free | $0 | 3 niche lookups/day, scores shown as ranges not exact numbers, 1 watchlist slot. Purpose: lead gen and SEO pages |
| Starter | $19/mo | 50 lookups/day, full scores, 25 watchlist slots, weekly digest |
| Pro | $49/mo | Unlimited lookups, Emerging feed (the early detection product — this is the tier driver), alerts, AI recommendations, competitor analysis, CSV export |
| Agency | $149/mo | 5 seats, API access (rate limited), daily reports, priority data refresh |
| Enterprise | Custom | SSO, custom data feeds, SLA, dedicated support |

Rationale: the Emerging feed and alerts are the differentiated value, so they gate Pro. Free tier exists to feed programmatic SEO pages ("moss wall art demand score") which is the primary acquisition channel.

## 10. Success Metrics

- North star: weekly active researchers (users running ≥3 lookups/week)
- Activation: % of signups who save a niche within first session (target 40%)
- Prediction quality: of niches flagged Emerging, % whose demand signal grows ≥50% over the next 60 days with supply growth lagging (target: beat a naive baseline by 2x; measured continuously)
- Revenue: 500 paying users within 6 months of paid launch; churn <6% monthly
- Data health: signal freshness <24h for all Green sources

## 11. Key Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Etsy commercial API approval delayed or denied | Critical | Apply in week 1. Build against personal access meanwhile. Fallback: launch as eBay + social trend tool (weaker but viable) |
| Revenue estimates are wrong and users notice | High | Publish methodology, show confidence bands, never show false precision |
| Trend data licensing cost eats margin | High | Start with cheapest licensed feed at low query volume; cache aggressively; Trends alpha application in parallel |
| eRank/EverBee copy the prediction feature | Medium | Speed + the outcome feedback dataset (section 7.5) which compounds and cannot be copied |
| Reddit/YouTube quota ceilings | Medium | Quota extension applications early; prioritized crawl scheduling; degrade gracefully |
| One founder, large surface area | High | Ruthless v1 scope (this document), managed infrastructure, boring technology choices |

## 12. Open Questions for Founder Decision

1. Approve Etsy first beachhead? (This decision shapes everything downstream.)
2. Budget ceiling for licensed data (search trends) at MVP stage: is ~$100 to $300/mo acceptable?
3. Working name / domain.
4. Solo build or planning to bring in contractors? (Affects architecture choices: monolith vs services.)

## 13. What Comes Next (per agreed process)

1. ~~PRD~~ ← this document
2. System architecture: full stack selection with rationale, data pipeline design, complete database schema with indexes, scoring algorithm specification with every factor weight explained, forecasting system design, API design with auth and rate limiting
3. Milestones (roughly: M0 foundations → M1 Etsy ingestion → M2 scoring engine → M3 web app → M4 social signals + prediction → M5 billing + launch)
4. Task breakdown per milestone
5. Implementation, one approved task at a time
