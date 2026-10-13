# External Dependencies Tracker

Status of every third party approval, credential, and contract the product
depends on. Update the Status column as things move. Review weekly; the Etsy
row is the launch critical path.

| # | Dependency | Blocks | Status | Applied | Decision due |
|---|---|---|---|---|---|
| 1 | Etsy app registration (personal access) | M1 development | TODO | | |
| 2 | Etsy commercial access | Public launch | TODO (apply after #1 approved and app is functional) | | End of M3 (fallback decision point) |
| 3 | Reddit API registration | M5.T1 | TODO | | |
| 4 | YouTube Data API project | M5.T2 | TODO | | |
| 5 | YouTube quota extension | M5.T2 at scale | TODO (apply once baseline usage exists) | | |
| 6 | Google Trends API alpha application | Nice to have | TODO | | |
| 7 | Licensed trends provider (primary plan) | M5.T3 | TODO (trial) | | Before M5 |
| 8 | Stripe account | M6.T1 | TODO | | |
| 9 | Clerk account | Already needed at M0.T6 | TODO | | |
| 10 | Resend account + domain verification | M6.T3 | TODO | | |

---

## 1 + 2. Etsy Open API v3

Where: https://www.etsy.com/developers/register then manage at
https://www.etsy.com/developers/your-apps
Docs: https://developers.etsy.com/documentation/

How access works: registration grants an API keystring with **personal
access** (connects up to 5 shops, full development capability). A general
purpose app serving any seller requires **commercial access**, granted by
review. Strategy: register now, build all of M1 to M4 on personal access,
then request commercial access with a working product to show.

Etsy's published review criteria, and how we satisfy each:
- API Terms of Use compliance, including Section 1 caching policies →
  encode cache TTLs in the Etsy adapter config (M1.T2)
- Clear distinction from Etsy → display verbatim in app footer and site:
  "The term 'Etsy' is a trademark of Etsy, Inc. This application uses the
  Etsy API but is not endorsed or certified by Etsy, Inc."
- No screen scraping or API sidestepping → we never scrape; adapters only
- OAuth for private member data → we do not request private member data at
  all (public listing and shop endpoints only), which simplifies review
- Trademark policy for name/artwork → do not use "Etsy" in the product name,
  logo, or domain

### Drafted application answers (edit to taste, keep the substance)

**App name:** TrendScout (never include "Etsy" in the name)

**What does your application do?**
"TrendScout is a market research tool for handmade sellers. It helps
sellers discover product niches with growing buyer demand and reasonable
competition, so they can decide what to make and list next. The app
analyzes public listing metadata (titles, tags, categories, prices, review
and favorite counts) retrieved exclusively through the Open API v3,
combines it with public search and social interest data from other
licensed sources, and presents sellers with demand and competition
analytics for product categories. The app is read only with respect to
Etsy: it does not create, edit, or manage listings, does not process
transactions, does not access private member or buyer data, and does not
direct buyers away from Etsy. It complies with the API Terms of Use
caching policy and displays the required Etsy trademark attribution."

**Who uses it?** "Etsy sellers researching what to make and sell next."

Rejection risks seen in the developer community: vague descriptions, and
anything that reads like circumventing Etsy checkout or building a
competing marketplace. Our description addresses both explicitly. If
rejected: the response often lacks detail; reply asking which criterion
failed, revise, and reapply. Fallback if commercial access is ultimately
denied: launch as an eBay + social trend product (PRD risk table) and keep
Etsy personal access for internal research only.

Operational notes: an app with no successful API request in 6 months is
marked dormant and banned, so keep a weekly ping job alive from day one
(M1 scheduling covers this).

## 3. Reddit Data API

Where: https://www.reddit.com/prefs/apps (create "script" or "web app") and
review https://www.redditinc.com/policies/data-api-terms
Registration is immediate. Free tier rate limits (on the order of 100
queries per minute with OAuth) are sufficient for M5 cadence (6 hour
monitor cycles). Commercial use above free thresholds requires contacting
Reddit (r/redditdev and the data API support form). Apply for commercial
terms once the product is revenue generating; until then stay under free
tier limits by design. User agent string must identify the app and a
contact, per API rules.

## 4 + 5. YouTube Data API v3

Where: https://console.cloud.google.com → create project "trendscout" →
enable YouTube Data API v3 → create API key credential.
Default quota: 10,000 units/day (search costs 100 units/call → ~100
searches/day baseline, which M5.T2's priority sampling is designed
around). Quota extension: the YouTube API Services audit form
(https://support.google.com/youtube/contact/yt_api_form), which asks for a
working product, screenshots, and a use case description. Apply after
M5.T2 runs at baseline for a couple of weeks so real usage exists to show.

## 6. Google Trends API (official alpha)

Where: https://developers.google.com/search/apis/trends → apply as alpha
tester. Status: alpha since July 2025, limited testers, restricted quotas,
not production dependable yet. Treat as a free option on the future, not a
plan. Apply now (costs nothing), design M5.T3 around a licensed provider.

## 7. Licensed trends provider (primary plan for search interest data)

Candidates to trial, in order:
1. **Glimpse API** (meetglimpse.com): calibrated to match Google Trends,
   real time. Get a trial and a quote at our volume (~500 daily keywords +
   weekly full refresh).
2. **DataForSEO** (dataforseo.com): pay as you go trends and search volume
   endpoints; typically the cheapest entry point.
3. **SerpApi**: structured trends data, plans starting around $75/mo.

Selection criteria: per query cost at our volume, historical depth (need
12+ months for seasonality), terms permitting storage of derived data, and
data latency. Budget guardrail: $150/mo cap enforced in the adapter
(M5.T3 acceptance criterion). Note: providers that scrape Google's
endpoints carry ToS gray risk on Google's side; this is a vendor risk we
accept knowingly at MVP with the official alpha as the eventual clean path.
Decision recorded here before M5 begins.

## 8 to 10. Stripe, Clerk, Resend

Standard signups, no approval risk. Clerk is needed first (M0.T6). Stripe:
activate the account early since business verification can take days;
products/prices get created in M6.T1. Resend: verify the sending domain
(DNS records via Cloudflare) before M6.T3 so deliverability is warmed.
