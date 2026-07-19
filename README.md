# Alcohol Label Verification

TTB-style proof of concept that checks whether a label photo matches the seven
values typed from an application. One FastAPI process serves a same-origin
plain HTML/JS UI (no CORS, no database). Single-label results target **under
five seconds**. Batch upload (up to five labels) is a first-class path, not an
afterthought.

Hardened production profile: pinned OpenAI `gpt-4.1-mini-2025-04-14`, JPEG
preprocess ≤1280px at quality 82, measured warm click-to-result p95 about
2.7 seconds on Railway (see [docs/acceptance.md](docs/acceptance.md)).

## Live demo

**Deployed URL:** [https://ttb-label-verification-production-c242.up.railway.app/](https://ttb-label-verification-production-c242.up.railway.app/)

Try:

1. Open the site → **Load 3 demo labels** (under the intro) → **Check 3 Labels** → read the
   summary and per-label drill-down (plus “Checked N labels in X seconds”).
2. Or choose a label photo and enter the seven expected values → **Add to
   Queue** → **Check 1 Label** → read PASS/FAIL per field.
3. Add several labels to the queue (up to five) → **Check N Labels** → confirm
   each item stays independently viewable in the summary.
4. Choose a non-image file → you should get plain-language guidance (not a
   stack trace).

Public abuse controls may return HTTP `429` with a wait message if you submit
quickly; that is expected. Demo photos and expected values live under
[`app/static/demo/`](app/static/demo/). For a separate local sample image, use
[`samples/sample_label.jpg`](samples/sample_label.jpg).

## What it checks

| Field | Matching |
|-------|----------|
| Brand, class/type, producer | Fuzzy / normalized |
| Country | Canonicalized synonyms |
| ABV, net contents | Normalized numeric units |
| Government warning | **Exact, case-sensitive** string match |

Any field FAIL ⇒ overall verdict `NEEDS_REVIEW` (UI: Needs review). All fields
PASS ⇒ overall `PASS` (UI: APPROVED).

**Batch:** one to five ordered images + applications. Each label is validated
and verified independently; a bad sibling becomes `UNABLE_TO_VERIFY` without
blocking the rest. Response order and counts are preserved.

## Approach

```text
photo + application text
  → validate upload / rate limits
  → preprocess (orient, bound ≤1280 JPEG q82; skip re-encode if already bounded)
  → OpenAI structured vision extraction
  → postprocess (blank→null; warning line-wraps→spaces; non-exact warning→null)
  → compare_labels
  → same-origin UI result
```

Stateless and in-memory (rate limits reset on deploy). Logs record status,
latency, and error codes only—never application values, image bytes, or
extracted label text. Measured stage and browser timings are in
[docs/acceptance.md](docs/acceptance.md).

## Design decisions

- **Queue-only UI (not separate Single + Batch screens).** Compose → Add to
  Queue → Check Labels; the browser always calls `POST /verify/batch` with one
  to five items (a single label is just a one-item queue). *Why:* Batch is a
  hard product requirement; one flow is simpler for non-technical users than
  mode switching, and still covers the single-label case.
- **Edit pulls into compose, with dirty guards.** Edit removes a queued label
  into the open form until Update Queue or Cancel (Cancel puts the original
  item back); Check is blocked while the form is dirty or mid-edit. *Why:*
  Prevents silently dropping a label; keeps one large form on screen for
  senior-friendly use.
- **Inline demo seed.** “Load 3 demo labels” asks for confirmation, then fills
  the queue from [`app/static/demo/`](app/static/demo/) (JSON + JPEGs). *Why:*
  Zero-instruction live demo without silently wiping a queue in progress; assets
  ship with the Docker image (`COPY app`), while local `samples/` stay out of
  production.
- **Independent batch items.** A bad sibling becomes `UNABLE_TO_VERIFY`; other
  labels still verify; response order and summary counts stay aligned. *Why:*
  One bad photo must not block the rest of the batch.
- **Concurrent batch under a shared deadline.** Labels are prepared and
  vision-extracted in parallel with a ~4.8s shared processing budget. *Why:*
  The whole request—not each label in series—must stay under the five-second
  product target.
- **Exact warning vs fuzzy/normalized fields.** Government warning uses
  case-sensitive string equality; brand/class/producer are fuzzy (≥85); country
  uses synonyms; ABV (±0.05) and net contents use numeric/unit normalization.
  *Why:* The warning is regulatory-strict; OCR and layout noise on other
  fields should not force false FAILs.
- **Conservative warning exactness.** Comparison is full case-sensitive
  equality on the post-processed string (newlines → spaces only—not a looser
  whitespace collapse). If the model is uncertain, or the extracted warning is
  not an exact match to the expected TTB text, extraction stores `null`
  (never invented wording). *Why:* Prefer “missing” / FAIL over a near-miss
  that could false-PASS an exact match.
- **Slim extracted payload.** `ExtractedLabel` carries only the seven compared
  fields—no `raw_text` dump and no `extraction_confidence` score. *Why:* Keeps
  the API and UI focused on field-level PASS/FAIL; confidence is already
  reflected by nulls and per-field status, and raw OCR text is not needed for
  the PoC decision.
- **Latency-first vision stack.** Pinned `gpt-4.1-mini` with structured
  outputs, JPEG preprocess ≤1280px at quality 82 (client and server; skip
  redundant re-encode when already bounded), ~4s provider timeout, no retries.
  *Why:* Meet the under-five-seconds budget; fail fast rather than retry into
  the deadline. Measured evidence:
  [docs/acceptance.md](docs/acceptance.md).
- **In-memory abuse controls.** Per-process rate and concurrency limits; a
  batch charges one unit per label. *Why:* Protect free-tier vision spend
  without a database (limits reset on deploy; one replica assumed).
- **Stateless slim runtime.** No database; API keys only from environment /
  Railway Variables; Docker image copies `app/` only. *Why:* Small free-tier
  footprint and no secrets or demo packs outside `app/` in the image.

## Tools

- Python 3.12, [uv](https://docs.astral.sh/uv/), FastAPI, Pydantic, Pillow
- OpenAI Chat Completions structured outputs (`gpt-4.1-mini-2025-04-14`)
- Plain HTML / CSS / JavaScript UI
- pytest + Node (jsdom) UI behavior tests
- Docker / Dockerfile; deploy on Railway

## Setup and run

Prerequisites: [uv](https://docs.astral.sh/uv/) (Python 3.12), Node.js 20.19+
for frontend tests only, optional Docker Desktop.

```bash
cd alcohol-label-verification-app
uv sync
cp .env.example .env
# Put your OpenAI key in .env as OPENAI_API_KEY=... (never commit .env)
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Open:

- App: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- Health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

Tests:

```bash
uv run pytest
npm ci
npm test
npm run check
```

Optional Docker:

```bash
cp .env.example .env
docker compose up --build
```

## Deploy

1. Push to GitHub (confirm `.env` is **not** staged).
2. Railway → New Project → Deploy from GitHub → this repo (Dockerfile build).
3. Set Variables: `APP_ENV=production`, the `VERIFY_*` limits from
   `.env.example`, then `OPENAI_API_KEY` (server-only). Do not put the key in
   frontend code or git.
4. Generate a public domain; confirm `/health` and `/`.

Railway injects `PORT`; do not override it unless needed. Limits are
per-process and in-memory—fine for one replica; use a shared store before
scaling replicas.

## Assumptions

- Labels are US alcohol beverage labels with the usual mandatory fields.
- The seven application strings are what the reviewer expects; the photo is
  checked against that text.
- Government warning comparison is **text only** (casing/punctuation/wording);
  bold/typography are not verified.
- The host can reach the OpenAI API (outbound HTTPS).
- This is a standalone prototype, not integrated with COLA or federal IdP.
- Rate limits assume a single Railway replica.

## Limitations

- **Batch scale.** The UI and API accept at most five labels per request so
  the shared latency budget and free-tier vision spend stay viable. Dumps of
  hundreds of applications would need a different intake model (queues, async
  jobs, or multi-request workflows)—out of scope.
- **Outbound cloud vision.** Extraction calls the OpenAI API over the public
  internet. That works on Railway; a locked-down agency network that blocks
  those endpoints would need a private/VNet path or an on-prem model before
  agents could use the tool.
- Imperfect warning areas often extract as `null` → warning FAIL /
  `NEEDS_REVIEW` rather than a guessed string.
- Accuracy and latency depend on the cloud vision model and network.
- Public defaults throttle heavy use (`429`).
- Cold starts or provider failures return readable `503
  VERIFICATION_UNAVAILABLE`, never a fake compliance PASS.
- Optional private benchmark corpus is gitignored (`benchmark-private/`).

## Secrets

- Commit only [`.env.example`](.env.example) (with `OPENAI_API_KEY=` empty).
- Real `.env` is gitignored—never stage it.
- Production secrets live in the Railway Variables UI only.
- The browser never receives `OPENAI_API_KEY`; the UI only calls same-origin
  `POST /verify/batch` (the single-label `POST /verify` API remains available).

## Project layout

| Path | Role |
|------|------|
| `app/` | FastAPI app, comparison, vision, rate limits, static UI |
| `app/api/` | `/verify` and `/verify/batch` |
| `app/static/` | HTML, CSS, JS |
| `tests/` | pytest + UI behavior tests |
| `scripts/` | Live sample / acceptance helpers |
| `docs/acceptance.md` | Deployed latency and checklist evidence |
| `samples/` | Example label image and benchmark manifest shape |
