# Alcohol Label Verification

TTB label verification proof-of-concept. One FastAPI process, same-origin UI (no CORS).

## Current status

| Layer | Status |
|-------|--------|
| HTTP `/health` | Live (Phase 0 scaffold) |
| Comparison library (`compare_labels`) | Done (Phase 1) — unit-tested and wired to `/verify` |
| Vision extraction (`VisionService`) | Done (Phase 2) — mocked tests and wired to `/verify` |
| HTTP `POST /verify` | Done (Phase 3) — validated multipart orchestration |
| Single-label UI at `/` | Done (Phase 4) — accessible upload, results, errors, and abuse protection |
| Batch API and UI | Done (Phase 5) — isolated, concurrent verification for up to five labels |
| Hardening | Done (Phase 6) — deployed checklist passed; 30 warm runs p95 2.677s, maximum 3.203s |

**Phase 1 library:** compare typed application data vs an extracted label across brand, class/type, producer, country, ABV, net contents, and government warning. Fuzzy/normalized matching for most fields; **government warning is an exact, case-sensitive match**. Any field `FAIL` ⇒ overall verdict `NEEDS_REVIEW`.

Entry points: `from app.comparison import compare_labels`, `from app.vision import VisionService`.

**Phase 2 library:** orient, bound, and preprocess an image (JPEG ≤1280px,
quality 82) → pinned OpenAI `gpt-4.1-mini-2025-04-14` typed structured
output → `ExtractedLabel`. Locally invalid photos return an all-null extraction
for library callers. Provider outages, refusals, and malformed provider
responses raise `VisionUnavailableError` so the HTTP API cannot mistake a
failed extraction for seven missing label fields. Tests use an injected mock or
`FakeVisionService` (no live API).

**Phase 3 API:** `POST /verify` accepts a JPEG, PNG, or WebP `image` plus an
`application` JSON multipart field. All seven application fields are required
and limited to 2,000 characters each. The full multipart request is limited to
21 MiB, including the 20 MiB image allowance and multipart overhead.
The response includes the overall verdict, all expected-vs-found field results,
and measured `latency_ms`. Client upload errors return stable, human-readable
4xx responses; stack traces are never returned. A temporary vision-provider or
extraction failure returns HTTP `503` with `VERIFICATION_UNAVAILABLE`, never a
misleading compliance verdict.

```bash
curl -X POST http://127.0.0.1:8000/verify \
  -F 'image=@samples/sample_label.jpg;type=image/jpeg' \
  -F 'application={"brand":"OLD TOM DISTILLERY","class_type":"Kentucky Straight Bourbon Whiskey","producer":"Old Tom Distillery","country":"USA","abv":"45%","net_contents":"750 mL","government_warning":"GOVERNMENT WARNING: Example warning text"}'
```

Each `/verify` request writes a completion log containing the status, verdict or
error code, measured latency, and whether it stayed below the 5-second budget.
No application values, image bytes, or extracted label text are logged.

**Phase 4 UI:** `/` provides a large, high-contrast single-label workflow for a
label photo and the seven expected values. It posts the existing multipart
contract to `/verify`, then shows an `APPROVED` or `NEEDS REVIEW` verdict and a
plain-language PASS/FAIL result for every field. Failed fields show what the
label should say and what was found. A successful response replaces the form
and fixed submit control with the result and one “Check Another Label” action,
preventing accidental duplicate paid calls. Upload, network, timeout, and
service errors keep the user's entries in place and render as readable guidance.

**Phase 5 batch verification:** `POST /verify/batch` accepts one to five ordered
`images` parts plus an `applications` JSON array in the same order. Each label is
validated and verified independently: a bad image, invalid application, timeout,
or provider failure becomes an `UNABLE_TO_VERIFY` item while valid siblings
continue. The response preserves input order and includes server-derived counts
for passed, needs-review, unable-to-verify, and total items. The UI exposes this
through a large Single label / Batch choice, numbered label cards, a delayed
progress indicator, a batch summary, and an accessible drill-down for every item.

Eligible labels run concurrently under a shared five-label process cap and a
4.8-second server-processing deadline. There are no provider retries. A locally
valid batch with at least one completed verification returns `200`; all-local
item errors return a batch-shaped `422`, and a total provider/extraction failure
returns a batch-shaped `503`. Structurally malformed batches use the normal error
response. Each image remains limited to 20 MiB and a batch request is limited to
101 MiB.

### Abuse protection

`POST /verify` is always rate-limited before it can use the server-side OpenAI
key. The defaults are conservative for this public proof-of-concept:

| Variable | Default | Purpose |
|----------|---------|---------|
| `VERIFY_RATE_LIMIT_PER_MINUTE` | `5` | Maximum attempts per client IP in a rolling minute |
| `VERIFY_RATE_LIMIT_PER_HOUR` | `30` | Maximum attempts per client IP in a rolling hour |
| `VERIFY_GLOBAL_RATE_LIMIT_PER_HOUR` | `100` | Maximum validated vision attempts across the process in a rolling hour |
| `VERIFY_MAX_CONCURRENT` | `5` | Maximum active label-processing slots in the process |

Client limits run before multipart parsing. The global and concurrency limits
run after validation but before `VisionService`, so bad submissions cannot use
the paid-call allowance. The 21 MiB total request guard checks declared and
streamed sizes before paid work; oversized requests return `413 REQUEST_TOO_LARGE`.
A rejected rate-limit request returns HTTP `429`, the normal
`ErrorResponse` JSON, and an integer `Retry-After` header. `RATE_LIMITED` means a
client or global window is full; `VERIFICATION_BUSY` means both vision slots are
active. The UI keeps the selected photo and entered values while explaining how
long to wait.

Limits are held in memory, reset on deploy, and apply per process. Production is
currently one Railway replica. Before adding replicas, replace the limiter with
a shared Redis-backed limit or put an application-layer WAF in front of Railway.
Batch requests charge client quota per submitted label and global paid-call quota
only for labels that reach the vision provider.

```bash
# Live smoke against samples/sample_label.jpg (needs OPENAI_API_KEY in .env)
uv run python scripts/extract_sample.py

# Sample accuracy/latency check, including deterministic degraded variants
uv run python scripts/extract_sample.py --runs 3 --variants

# Private corpus check (benchmark-private/ is gitignored)
uv run python scripts/extract_sample.py --corpus benchmark-private --variants \
  --json-output benchmark-reports/final.json

# Screen the three image profiles, two prompts, and pinned model candidates
uv run python scripts/extract_sample.py --corpus benchmark-private --matrix
```

The private corpus directory contains `manifest.json` following
`samples/benchmark-manifest.example.json` and 10–20 permissioned label images.
The benchmark prints only aggregate timings, byte counts, null flags, and field
match statuses—never image data or extracted/expected label text. Its gates are:
provider p95 ≤3.6 seconds, every local extraction under 5 seconds, processed
payload p95 ≤1 MiB, 100% clean-label/warning correctness, ≥95% readable
non-warning accuracy on mild degradations, exact-or-null degraded warnings, and
zero false passes on the severe crop case. Deployed browser acceptance remains
the authoritative speed check: 30 warm click-to-result runs at p95 ≤4.5 seconds
with every run under 5 seconds, plus five cold-start runs under 5 seconds.
Successful single-label submissions expose the privacy-safe duration as the
`single-label-click-to-result` browser performance measure and the numeric
`data-click-to-result-ms` attribute on the result region.

The deployed checklist, tuning decision, and measured stage/browser percentiles
are recorded in [`docs/phase6-acceptance.md`](docs/phase6-acceptance.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python 3.12 via `.python-version`)
- Node.js 20.19+ and npm (development tests only; not included in production)
- Optional: Docker + Docker Compose for local image parity
- Railway account for deploy

## Local run

```bash
cd alcohol-label-verification-app
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Open:

- App: http://127.0.0.1:8000/
- Health: http://127.0.0.1:8000/health

Tests:

```bash
uv run pytest
npm ci
npm test
npm run check
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
5. Service **Variables**: set `APP_ENV=production` and the four `VERIFY_*`
   limits above. Railway injects `PORT`; do not override it unless needed.
6. Leave `OPENAI_API_KEY` unset for the first deployment. Deploy the limiter,
   then confirm the sixth `/verify` attempt inside one minute returns `429` and
   a `Retry-After` header:

   ```bash
   for attempt in 1 2 3 4 5 6; do
     curl -sS -o /dev/null -w "attempt $attempt: %{http_code}\n" \
       -X POST https://<your-app>.up.railway.app/verify
   done

   # While limited, inspect the 429 body and Retry-After header.
   curl -i -X POST https://<your-app>.up.railway.app/verify
   ```

7. After throttling is verified, add `OPENAI_API_KEY` in Railway Variables. It
   is a server-only secret and must never appear in frontend code or responses.
8. **Settings → Networking → Generate Domain** if the service has no domain.
9. Exit check:
   - `https://<your-app>.up.railway.app/health` → `{"status":"ok"}`
   - `https://<your-app>.up.railway.app/` → Single label and Batch modes load
   - Submit a label photo and all seven values → verdict and seven field results appear
   - Submit an unsupported or unreadable file → a plain-language error appears
   - Provider/extraction outage → readable `503 VERIFICATION_UNAVAILABLE`, not a verdict
   - Upload above the total request limit → readable `413 REQUEST_TOO_LARGE`
   - Exceed a limit → entries remain and a readable wait message appears
   - Submit two batch labels with one unreadable image → the readable label still
     receives a result and both labels remain individually viewable

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
- Configure and verify rate limiting before adding `OPENAI_API_KEY`.
- The browser never receives `OPENAI_API_KEY`; it only calls the protected
  same-origin `/verify` endpoint.

**Live URL:** https://ttb-label-verification-production-c242.up.railway.app/
