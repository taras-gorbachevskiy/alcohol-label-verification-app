# Production acceptance record

This record contains aggregate results only. It does not include image data,
application values, or extracted label text.

Captured during Phase 6 hardening against the deployed Railway service.

## Automated coverage

The committed test matrix covers valid labels, single and multiple mismatches,
case-only non-warning matches, ABV and volume normalization, missing/wrong-case/
exact warning behavior, deterministic image degradation, wrong file types,
empty submissions, mixed batch summaries, strict response validation, focus and
announcements, contrast, sizing, reduced motion, and responsive reflow.

## Production tuning decision

The deployed profile is pinned `gpt-4.1-mini-2025-04-14`, high image detail,
1280 px maximum long side, and JPEG quality 82. It keeps zero retries, a
four-second provider timeout, and a six-second browser safety timeout.

The initial candidate exposed two warning-OCR problems: printed line wrapping
was inconsistently emitted as newline characters, and imperfect warning areas
could yield altered non-null text. The final hardening treats visual line wraps
as reading-order spaces while preserving every other character for exact
comparison. Any non-exact warning extraction is degraded to `null` rather than
presented as reconstructed text. The case-sensitive comparator itself remains
unchanged: casing, punctuation, wording, and substantive whitespace differences
still fail.

The pinned `gpt-5.4-nano-2026-03-17` snapshot was unavailable to the configured
provider account. Its available alias and compact-prompt candidates failed clean
correctness and were rejected.

## Deployed checklist

Tested against
`https://ttb-label-verification-production-c242.up.railway.app` using the public
sample and deterministic derivatives:

| Checklist item | Live result |
|---|---|
| Valid label | `PASS`; seven of seven fields passed; browser rendered `APPROVED` |
| Mismatches | Single brand and combined brand/country mismatches returned only the expected failed fields and `NEEDS_REVIEW` |
| Case-only | Title-case brand versus uppercase label passed; warning casing remained strict |
| ABV/units normalization | Bare ABV, ABV/proof, cL, L, and fl oz equivalents all returned `PASS` |
| Warning missing | Warning-area crop returned warning `null`, field FAIL, and `NEEDS_REVIEW` |
| Warning wrong caps | Mixed-case expected warning returned warning FAIL and `NEEDS_REVIEW` |
| Warning correct | Exact warning returned PASS |
| Imperfect image | Rotation, blur, perspective, glare, shadow/low-light, compression, and crop all returned typed results; warning was exact or `null`; crop had zero false PASS |
| Wrong file type | Browser focused the photo control, retained entries, and showed readable guidance; direct API returned `415 UNSUPPORTED_IMAGE_TYPE` before provider admission |
| Empty submit | Browser focused the photo control and showed eight missing items without a result; direct API returned readable `422 MISSING_SUBMISSION` before provider admission |
| Batch summary | API returned exact 1 PASS / 1 NEEDS_REVIEW / 1 UNABLE_TO_VERIFY counts, indexes, order, and filenames; deployed UI rendered correct 1/1/2 counts and accurate drill-down values |
| Single-label speed | 30 warm and five cold browser runs all rendered `APPROVED` below five seconds |

The paced API checklist had no failures. Successful public-sample and degraded
request times ranged from 1.515 to 3.176 seconds; the mixed three-item batch was
1.977 seconds from the test client and 1.907 seconds in the app.

## Deployed latency evidence

| Measure | p50 | p95 | Maximum | Target |
|---|---:|---:|---:|---:|
| Browser click-to-render, 30 warm runs | 1.759s | 2.677s | 3.203s | p50 ≤3.5s, p95 ≤4.5s, all <5s |
| Server total, same 30 runs | 1.692s | 2.526s | 3.148s | all <5s |
| Vision provider, same 30 runs | 1.673s | 2.505s | 3.124s | p95 ≤3.6s |
| Server preprocessing | 11.60ms | 14.54ms | 15.76ms | p95 ≤250ms |
| Comparison | 0.14ms | 0.18ms | 0.19ms | p95 ≤50ms |
| Combined client resize/upload/render overhead | 62.90ms | 150.67ms | 156.65ms | p95 ≤500ms |
| Processed image payload | 50,384 bytes | 50,384 bytes | 50,384 bytes | p95 ≤1 MiB |

The five cold-container click-to-render measurements were 2.507s, 2.156s,
2.075s, 2.825s, and 1.929s; all rendered `APPROVED` and all were below five
seconds.

## Accessibility evidence

- Automated axe scans pass empty, error, loading, single-result, batch, and
  drill-down states.
- At a deployed 320 CSS px viewport, page scroll width equals viewport width,
  body text is 18 px, result drill-down targets are at least 128 px high, and
  visible action buttons are 60 px high.
- Deployed empty and wrong-file errors focused the photo control and retained
  entered values. Single and batch results received programmatic focus and used
  non-color status text.
- A human VoiceOver/Safari spot check is still recommended because the in-app
  browser cannot emulate VoiceOver speech output.

The private 12-label corpus was not present in the workspace. This acceptance
therefore establishes the complete brief checklist and latency gate on the
committed public sample and deterministic degradation matrix; it does not claim
private-corpus coverage.
