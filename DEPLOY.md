# Deployment Runbook

Topology: Railway runs the backend (API, Postgres, Redis, later workers).
Vercel runs the web app. Cloudflare fronts both with DNS, CDN, and WAF.
Deploys happen through each platform's git integration; there is no custom
deploy code to maintain.

## Branch and environment model

| Git ref | Railway environment | Vercel target | URL |
|---|---|---|---|
| `main` | staging (auto deploy) | preview, aliased to staging domain | staging.yourdomain.com / api-staging.yourdomain.com |
| `production` branch | production (auto deploy) | production | yourdomain.com / api.yourdomain.com |

Release flow: PRs merge to `main` (CI must be green) → staging deploys
automatically → verify → fast forward `production` to the release commit:

    git checkout production && git merge --ff-only main && git push

Both platforms deploy production from that push. Rollback = push the previous
commit to `production`.

## One time setup

### 1. GitHub
1. Create the repo, push this codebase to `main`.
2. Create the `production` branch from `main`.
3. Branch protection on `main`: require the two CI checks (see M0.T2 notes).
4. Branch protection on `production`: require CI checks; restrict pushes to yourself.

### 2. Railway (backend)
1. New project → Deploy from GitHub repo → select the repo.
2. Set the service **root directory to `apps/api`** (Settings → Source).
   Railway then uses `apps/api/railway.json` and the Dockerfile automatically.
3. Add plugins to the project: **PostgreSQL** (choose the pgvector template or
   run `CREATE EXTENSION IF NOT EXISTS vector;` once in M2) and **Redis**.
4. Service variables (Settings → Variables):

   | Variable | Value |
   |---|---|
   | DATABASE_URL | `${{Postgres.DATABASE_URL}}` (Railway reference) |
   | REDIS_URL | `${{Redis.REDIS_URL}}` |
   | ENVIRONMENT | `staging` |
   | API_CORS_ORIGINS | `https://staging.yourdomain.com` |

5. Environments: rename the default environment to `staging`, set its trigger
   branch to `main`. Create a `production` environment (duplicate services),
   set trigger branch to `production`, and set its variables:
   `ENVIRONMENT=production`, `API_CORS_ORIGINS=https://yourdomain.com`.
   Postgres and Redis are separate instances per environment; staging never
   shares a database with production.
6. Networking: generate a domain per environment, then add custom domains
   `api-staging.yourdomain.com` (staging) and `api.yourdomain.com` (production).
7. The container entrypoint (`start.sh`) runs `alembic upgrade head` before
   serving. This is correct while replicas = 1. If you ever scale the API to
   multiple replicas: move the migration to Settings → Deploy → Pre deploy
   command (`alembic upgrade head`) and change the Dockerfile CMD to uvicorn
   only, so exactly one runner migrates.

### 3. Vercel (web)
1. New project → import the GitHub repo.
2. **Root directory: `apps/web`.** Framework preset: Next.js (auto detected).
3. Environment variables:

   | Variable | Production | Preview |
   |---|---|---|
   | NEXT_PUBLIC_API_URL | `https://api.yourdomain.com` | `https://api-staging.yourdomain.com` |

4. Git: production branch = `production`. Every PR and push to `main` gets a
   preview deployment automatically.
5. Domains: add `yourdomain.com` (production) and `staging.yourdomain.com`
   assigned to the `main` branch preview.

### 3b. Clerk (auth)
1. Create the application at dashboard.clerk.com. Two Clerk instances map
   to our environments: Development instance → staging, Production
   instance → production.
2. Backend variables (Railway, per environment):

   | Variable | Value |
   |---|---|
   | CLERK_ISSUER | The instance Frontend API URL (Clerk dashboard → API keys), e.g. https://your-instance.clerk.accounts.dev |
   | CLERK_WEBHOOK_SECRET | Created in step 4 below |
   | CLERK_AUTHORIZED_PARTIES | The web origin for that environment, e.g. https://yourdomain.com |

3. Frontend variables (Vercel): NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY and
   CLERK_SECRET_KEY from the matching Clerk instance (production keys to
   Production, development keys to Preview).
4. Webhook: Clerk dashboard → Webhooks → Add endpoint →
   `https://api.yourdomain.com/webhooks/clerk` (and the staging URL on the
   dev instance), subscribe to user.created, user.updated, user.deleted.
   Copy the signing secret into CLERK_WEBHOOK_SECRET.
5. Verify: sign up on the site → Railway logs show POST /webhooks/clerk
   200 → /dashboard shows your email and plan "free".

### 4. Cloudflare
1. Add your domain, point registrar nameservers at Cloudflare.
2. DNS records (all proxied except where noted):

   | Record | Type | Target | Proxy |
   |---|---|---|---|
   | yourdomain.com | CNAME | cname.vercel-dns.com | DNS only (Vercel requirement; Vercel provides its own CDN/SSL) |
   | staging | CNAME | cname.vercel-dns.com | DNS only |
   | api | CNAME | (Railway production domain) | Proxied |
   | api-staging | CNAME | (Railway staging domain) | Proxied |

3. SSL/TLS mode: Full (strict).
4. WAF: enable the free managed ruleset; add a rate limiting rule on
   `api.yourdomain.com/*` as a coarse outer guard (the precise per plan
   limits are application level, M6.T2).

## Verification checklist (run after setup, and after any infra change)

- [ ] `https://api-staging.yourdomain.com/health` → 200, `environment: staging`
- [ ] `https://api-staging.yourdomain.com/health/ready` → 200, postgres and redis `ok`
- [ ] `https://staging.yourdomain.com` renders with green "API connected"
- [ ] Merge a trivial PR to `main` → staging redeploys automatically
- [ ] Fast forward `production` → both production deploys update
- [ ] Same three health checks on production URLs
- [ ] Railway deploy logs show `[start] applying migrations` before serve

## Cost note

This topology at MVP traffic: Railway ~$10 to $20/mo for staging + production
(staging services can be sized minimal), Vercel free tier, Cloudflare free
tier. Scale up only on the triggers in architecture section 13.
