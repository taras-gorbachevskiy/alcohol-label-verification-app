# Alcohol Label Verification

TTB label verification proof-of-concept. One FastAPI process, same-origin UI (no CORS).

## Current status

| Layer | Status |
|-------|--------|
| HTTP `/health` + hello page at `/` | Live (Phase 0 scaffold) |
| Comparison library (`compare_labels`) | Done (Phase 1) — unit-tested, not wired to HTTP/UI |
| Vision extraction (`VisionService`) | Done (Phase 2) — library + unit tests (mocked); not wired to HTTP/UI |
| Verify API, batch upload UI | Not built yet |

**Phase 1 library:** compare typed application data vs an extracted label across brand, class/type, producer, country, ABV, net contents, and government warning. Fuzzy/normalized matching for most fields; **government warning is an exact, case-sensitive match**. Any field `FAIL` ⇒ overall verdict `NEEDS_REVIEW`.

Entry points: `from app.comparison import compare_labels`, `from app.vision import VisionService`.

**Phase 2 library:** orient, bound, and preprocess an image (JPEG ≤1536px) → OpenAI `gpt-4o-mini` typed structured output → `ExtractedLabel`. Bad photos, transient API failures, refusals, and parse errors soft-fail to all-null; configuration failures raise. Tests use an injected mock or `FakeVisionService` (no live API).

```bash
# Live smoke against samples/sample_label.jpg (needs OPENAI_API_KEY in .env)
uv run python scripts/extract_sample.py

# Full opt-in accuracy/latency check, including degraded variants
uv run python scripts/extract_sample.py --runs 3 --variants
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python 3.12 via `.python-version`)
- Optional: Docker + Docker Compose for local image parity
- Railway account for deploy

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

**Live URL:** https://ttb-label-verification-production-c242.up.railway.app/
