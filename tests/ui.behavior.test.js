const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const HTML = fs.readFileSync(path.join(ROOT, "app/static/index.html"), "utf8");
const SCRIPT = fs.readFileSync(path.join(ROOT, "app/static/app.js"), "utf8");
const FIELD_KEYS = [
  "brand",
  "class_type",
  "producer",
  "country",
  "abv",
  "net_contents",
  "government_warning",
];

function response(body, { status = 200, headers = {} } = {}) {
  const normalizedHeaders = new Map(
    Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]),
  );
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return body;
    },
    headers: {
      get(name) {
        return normalizedHeaders.get(name.toLowerCase()) ?? null;
      },
    },
  };
}

function verificationPayload({ verdict = "PASS", failedField = null } = {}) {
  return {
    verdict,
    latency_ms: 321,
    fields: FIELD_KEYS.map((field) => ({
      field,
      status: field === failedField ? "FAIL" : "PASS",
      expected: `expected ${field}`,
      actual: field === failedField ? `found ${field}` : `expected ${field}`,
      score: field === failedField ? 0.2 : 1,
      detail: null,
    })),
  };
}

function createPage(fetchImpl, { captureTimeout = false } = {}) {
  const dom = new JSDOM(HTML, {
    url: "https://labels.example.test/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const timeoutCallbacks = [];

  window.fetch = fetchImpl;
  window.URL.createObjectURL = () => "blob:test-label";
  window.URL.revokeObjectURL = () => {};
  window.HTMLElement.prototype.scrollIntoView = () => {};
  window.scrollTo = () => {};
  if (captureTimeout) {
    window.setTimeout = (callback) => {
      timeoutCallbacks.push(callback);
      return timeoutCallbacks.length;
    };
    window.clearTimeout = () => {};
  }

  window.eval(SCRIPT);
  return {
    dom,
    window,
    document: window.document,
    runTimeout(index = 0) {
      assert.ok(timeoutCallbacks[index], "request timeout was scheduled");
      timeoutCallbacks[index]();
    },
  };
}

function batchPayload(items) {
  const counts = { PASS: 0, NEEDS_REVIEW: 0, UNABLE_TO_VERIFY: 0 };
  for (const item of items) {
    counts[item.status] += 1;
  }
  return {
    summary: {
      passed: counts.PASS,
      needs_review: counts.NEEDS_REVIEW,
      unable_to_verify: counts.UNABLE_TO_VERIFY,
      total: items.length,
    },
    items: items.map((item, index) => ({
      index,
      filename: `batch-label-${index + 1}.jpg`,
      status: item.status,
      result:
        item.status === "UNABLE_TO_VERIFY"
          ? null
          : verificationPayload({
              verdict: item.status,
              failedField: item.status === "NEEDS_REVIEW" ? "brand" : null,
            }),
      error:
        item.status === "UNABLE_TO_VERIFY"
          ? {
              code: item.code || "VERIFICATION_UNAVAILABLE",
              message: "safe item error",
              field: null,
            }
          : null,
    })),
    latency_ms: 640,
  };
}

function openBatch(page) {
  page.document.getElementById("batch-mode-button").click();
  return [...page.document.querySelectorAll(".batch-card")];
}

function fillBatchCard(page, card, index) {
  const cardId = card.dataset.cardId;
  for (const key of FIELD_KEYS) {
    page.document.getElementById(`batch-${cardId}-${key}`).value =
      `batch ${index} ${key}`;
  }
  const file = new page.window.File([`jpeg-${index}`], `batch-label-${index}.jpg`, {
    type: "image/jpeg",
  });
  const image = page.document.getElementById(`batch-${cardId}-image`);
  Object.defineProperty(image, "files", {
    configurable: true,
    value: [file],
  });
  image.dispatchEvent(new page.window.Event("change", { bubbles: true }));
}

function fillForm(page) {
  for (const key of FIELD_KEYS) {
    page.document.getElementById(key).value = `entered ${key}`;
  }
  const file = new page.window.File(["jpeg-data"], "label.jpg", {
    type: "image/jpeg",
  });
  const image = page.document.getElementById("image");
  Object.defineProperty(image, "files", {
    configurable: true,
    value: [file],
  });
  image.dispatchEvent(new page.window.Event("change", { bubbles: true }));
  return file;
}

function submit(page) {
  page.document.getElementById("verification-form").dispatchEvent(
    new page.window.Event("submit", { bubbles: true, cancelable: true }),
  );
}

async function waitFor(predicate, message = "condition was not met") {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (predicate()) {
      return;
    }
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.fail(message);
}

test("successful verification replaces the form with one clear result action", async () => {
  let request = null;
  const page = createPage(async (url, options) => {
    request = { url, options };
    return response(
      verificationPayload({ verdict: "NEEDS_REVIEW", failedField: "brand" }),
    );
  });
  fillForm(page);

  submit(page);
  await waitFor(() => !page.document.getElementById("results").hidden);

  const form = page.document.getElementById("verification-form");
  const results = page.document.getElementById("results");
  assert.equal(form.hidden, true);
  assert.equal(results.hidden, false);
  assert.equal(page.document.activeElement, results);
  assert.match(results.textContent, /NEEDS REVIEW/);
  assert.match(results.textContent, /Brand name/);
  assert.match(results.textContent, /brand name does not match/i);
  assert.match(results.textContent, /Should say/);
  assert.match(results.textContent, /expected brand/);
  assert.match(results.textContent, /Label says/);
  assert.match(results.textContent, /found brand/);
  assert.equal(page.document.querySelectorAll("#start-over-button").length, 1);
  assert.equal(request.url, "/verify");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.body.get("image").name, "label.jpg");
  assert.equal(
    JSON.parse(request.options.body.get("application")).brand,
    "entered brand",
  );

  page.document.getElementById("start-over-button").click();
  assert.equal(form.hidden, false);
  assert.equal(results.hidden, true);
  assert.equal(page.document.getElementById("brand").value, "");
  assert.equal(page.document.activeElement, page.document.getElementById("image"));
  page.dom.window.close();
});

test("all matching fields render a prominent approved verdict", async () => {
  const page = createPage(async () => response(verificationPayload()));
  fillForm(page);

  submit(page);
  await waitFor(() => !page.document.getElementById("results").hidden);

  const results = page.document.getElementById("results");
  assert.match(results.textContent, /APPROVED/);
  assert.match(results.textContent, /All 7 items match/);
  assert.equal(results.querySelectorAll(".result-item.pass").length, 7);
  assert.equal(page.document.getElementById("verification-form").hidden, true);
  page.dom.window.close();
});

for (const testCase of [
  {
    name: "per-client rate limit",
    status: 429,
    code: "RATE_LIMITED",
    retryAfter: "42",
    message: /wait about 42 seconds/i,
  },
  {
    name: "busy verifier",
    status: 429,
    code: "VERIFICATION_BUSY",
    retryAfter: "5",
    message: /busy.*wait about 5 seconds/i,
  },
  {
    name: "provider outage",
    status: 503,
    code: "VERIFICATION_UNAVAILABLE",
    retryAfter: null,
    message: /information is still here/i,
  },
  {
    name: "oversized request",
    status: 413,
    code: "REQUEST_TOO_LARGE",
    retryAfter: null,
    message: /photo smaller than 20 MB/i,
  },
]) {
  test(`${testCase.name} is readable and preserves the complete form`, async () => {
    const page = createPage(async () =>
      response(
        {
          error: {
            code: testCase.code,
            message: "server-safe-message",
            field: null,
          },
        },
        {
          status: testCase.status,
          headers: testCase.retryAfter
            ? { "Retry-After": testCase.retryAfter }
            : {},
        },
      ),
    );
    const selectedFile = fillForm(page);

    submit(page);
    const errorSummary = page.document.getElementById("error-summary");
    await waitFor(() => !errorSummary.hidden);

    assert.match(errorSummary.textContent, testCase.message);
    assert.equal(page.document.getElementById("verification-form").hidden, false);
    assert.equal(page.document.getElementById("brand").value, "entered brand");
    assert.equal(page.document.getElementById("image").files[0], selectedFile);
    assert.equal(page.document.activeElement, errorSummary);
    page.dom.window.close();
  });
}

test("request timeout is readable and preserves entries", async () => {
  const page = createPage(
    (_url, options) =>
      new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          reject(new page.window.DOMException("timed out", "AbortError"));
        });
      }),
    { captureTimeout: true },
  );
  const selectedFile = fillForm(page);

  submit(page);
  await waitFor(() => page.document.getElementById("submit-button").disabled);
  page.runTimeout();
  const errorSummary = page.document.getElementById("error-summary");
  await waitFor(() => !errorSummary.hidden);

  assert.match(errorSummary.textContent, /taking longer than expected/i);
  assert.equal(page.document.getElementById("brand").value, "entered brand");
  assert.equal(page.document.getElementById("image").files[0], selectedFile);
  page.dom.window.close();
});

test("field validation error focuses the field and preserves the form", async () => {
  const page = createPage(async () =>
    response(
      {
        error: {
          code: "APPLICATION_FIELD_TOO_LONG",
          message: "Use 2,000 characters or fewer.",
          field: "application.brand",
        },
      },
      { status: 422 },
    ),
  );
  fillForm(page);

  submit(page);
  await waitFor(
    () => !page.document.getElementById("brand-error").hidden,
  );

  assert.match(page.document.getElementById("brand-error").textContent, /2,000/);
  assert.equal(page.document.activeElement, page.document.getElementById("brand"));
  assert.equal(page.document.getElementById("brand").value, "entered brand");
  page.dom.window.close();
});

const invalidPayloads = {
  "missing field": (() => {
    const payload = verificationPayload();
    payload.fields.pop();
    return payload;
  })(),
  "duplicate field": (() => {
    const payload = verificationPayload();
    payload.fields[6] = { ...payload.fields[0] };
    return payload;
  })(),
  "unknown field": (() => {
    const payload = verificationPayload();
    payload.fields[6].field = "unknown";
    return payload;
  })(),
  "invalid actual value": (() => {
    const payload = verificationPayload();
    payload.fields[0].actual = { unsafe: true };
    return payload;
  })(),
  "invalid score value": (() => {
    const payload = verificationPayload();
    payload.fields[0].score = "high";
    return payload;
  })(),
  "invalid detail value": (() => {
    const payload = verificationPayload();
    payload.fields[0].detail = ["unexpected"];
    return payload;
  })(),
  "invalid latency value": {
    ...verificationPayload(),
    latency_ms: "fast",
  },
  "verdict inconsistent with fields": {
    ...verificationPayload(),
    verdict: "NEEDS_REVIEW",
  },
};

for (const [name, payload] of Object.entries(invalidPayloads)) {
  test(`invalid response (${name}) renders a generic error`, async () => {
    const page = createPage(async () => response(payload));
    fillForm(page);

    submit(page);
    const errorSummary = page.document.getElementById("error-summary");
    await waitFor(() => !errorSummary.hidden);

    assert.match(errorSummary.textContent, /information is still here/i);
    assert.equal(page.document.getElementById("verification-form").hidden, false);
    assert.equal(page.document.getElementById("results").hidden, true);
    page.dom.window.close();
  });
}

test("batch mode starts with two cards and is bounded at five", () => {
  const page = createPage(async () => response({}));
  let cards = openBatch(page);

  assert.equal(page.document.getElementById("verification-form").hidden, true);
  assert.equal(page.document.getElementById("batch-form").hidden, false);
  assert.equal(cards.length, 2);
  assert.equal(page.document.querySelectorAll(".remove-label-button:not([hidden])").length, 0);

  page.document.getElementById("add-label-button").click();
  page.document.getElementById("add-label-button").click();
  page.document.getElementById("add-label-button").click();
  cards = [...page.document.querySelectorAll(".batch-card")];
  assert.equal(cards.length, 5);
  assert.equal(page.document.getElementById("add-label-button").hidden, true);

  cards[2].querySelector(".remove-label-button").click();
  cards = [...page.document.querySelectorAll(".batch-card")];
  assert.equal(cards.length, 4);
  assert.deepEqual(
    cards.map((card) => card.querySelector(".batch-card-title").textContent),
    ["Label 1", "Label 2", "Label 3", "Label 4"],
  );
  page.dom.window.close();
});

test("batch submission preserves pairing and renders every drill-down", async () => {
  let request = null;
  const payload = batchPayload([
    { status: "PASS" },
    { status: "UNABLE_TO_VERIFY", code: "INVALID_IMAGE" },
  ]);
  const page = createPage(async (url, options) => {
    request = { url, options };
    return response(payload);
  });
  const cards = openBatch(page);
  cards.forEach((card, index) => fillBatchCard(page, card, index + 1));

  page.document.getElementById("batch-form").dispatchEvent(
    new page.window.Event("submit", { bubbles: true, cancelable: true }),
  );
  await waitFor(() => !page.document.getElementById("batch-results").hidden);

  assert.equal(request.url, "/verify/batch");
  assert.equal(request.options.body.getAll("images").length, 2);
  assert.equal(
    JSON.parse(request.options.body.get("applications"))[1].brand,
    "batch 2 brand",
  );
  assert.match(page.document.getElementById("batch-summary").textContent, /Passed\s*1/);
  assert.match(
    page.document.getElementById("batch-summary").textContent,
    /Unable to verify\s*1/,
  );
  const details = page.document.querySelectorAll(".batch-result-item");
  assert.equal(details.length, 2);
  assert.equal(details[0].open, true);
  assert.match(details[0].textContent, /Label 2/);
  assert.match(details[1].textContent, /Label 1/);
  assert.equal(page.document.activeElement, page.document.getElementById("batch-results"));

  page.document.getElementById("edit-batch-button").click();
  assert.equal(page.document.getElementById("batch-form").hidden, false);
  assert.equal(cards[0].querySelector('input[type="file"]').files.length, 1);
  page.dom.window.close();
});

test("batch progress appears only after the delay", async () => {
  let resolveFetch;
  const page = createPage(
    () =>
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    { captureTimeout: true },
  );
  const cards = openBatch(page);
  cards.forEach((card, index) => fillBatchCard(page, card, index + 1));

  page.document.getElementById("batch-form").dispatchEvent(
    new page.window.Event("submit", { bubbles: true, cancelable: true }),
  );
  await waitFor(() => page.document.getElementById("batch-submit-button").disabled);
  assert.equal(page.document.getElementById("batch-progress").hidden, true);
  page.runTimeout(1);
  assert.equal(page.document.getElementById("batch-progress").hidden, false);
  assert.match(page.document.getElementById("batch-progress").textContent, /Checking 2 labels/);

  resolveFetch(response(batchPayload([{ status: "PASS" }, { status: "PASS" }])));
  await waitFor(() => !page.document.getElementById("batch-results").hidden);
  assert.equal(page.document.getElementById("batch-progress").hidden, true);
  page.dom.window.close();
});
