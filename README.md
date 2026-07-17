# Alcohol Label Verification — Phase 0

Minimal FastAPI app with a `/health` endpoint and a hello page that fetches it. One process, one URL (same origin — no CORS).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python 3.12 via `.python-version`)
- Optional: Docker + Docker Compose for local image parity
- Railway account (free trial) for deploy

## Local run

```bash
cd alcohol-label-verification-app
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

- App: http://127.0.0.1:8000/
- Health: http://127.0.0.1:8000/health

Tests:

```bash
uv run pytest
```

Optional Docker (requires Docker Desktop):

```bash
cp .env.example .env
docker compose up --build
```

## Deploy to Railway (live URL)

1. Push this repo to GitHub (confirm `.env` is **not** staged).
2. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub** → select this repo.
3. Confirm build logs show `Using detected Dockerfile!`
4. Connect/verify GitHub for Full Trial if prompted: https://railway.com/verify
5. Service **Variables**: set `APP_ENV=production` (Railway injects `PORT` — do not override unless needed).
6. **Settings → Networking → Generate Domain**.
7. Exit check:
   - `https://<your-app>.up.railway.app/health` → `{"status":"ok"}`
   - `https://<your-app>.up.railway.app/` → page loads and shows the health JSON (auto-fetch on load)

CLI alternative (if `railway` CLI is installed and logged in):

```bash
railway login
railway init
railway up
railway domain
```

## Secrets

- Commit only `.env.example`.
- Real `.env` is gitignored. Never put API keys in source.
- Production secrets: Railway Variables UI only.

## Phase 0 scope

Health check + hello UI only. Label verification features come in later phases.

**Live URL:** https://ttb-label-verification-production-c242.up.railway.app/
