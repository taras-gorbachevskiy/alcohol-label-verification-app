const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const { JSDOM } = require("jsdom");
const axe = require("axe-core");

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
      filename: `label-${index + 1}.jpg`,
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

function fillCompose(page, index = 1) {
  for (const key of FIELD_KEYS) {
    page.document.getElementById(key).value = `label ${index} ${key}`;
  }
  const file = new page.window.File(
    [`jpeg-${index}`],
    `label-${index}.jpg`,
    { type: "image/jpeg" },
  );
  const image = page.document.getElementById("image");
  Object.defineProperty(image, "files", {
    configurable: true,
    value: [file],
  });
  image.dispatchEvent(new page.window.Event("change", { bubbles: true }));
  return file;
}

function addToQueue(page, index = 1) {
  const file = fillCompose(page, index);
  page.document.getElementById("add-to-queue-button").click();
  return file;
}

function checkLabels(page) {
  page.document.getElementById("queue-form").dispatchEvent(
    new page.window.Event("submit", { bubbles: true, cancelable: true }),
  );
}

const DEMO_SCENARIOS = [
  {
    id: "01-clean-exact-match",
    image: "01-clean-exact-match.jpg",
    application: Object.fromEntries(
      FIELD_KEYS.map((key) => [key, `demo-1 ${key}`]),
    ),
  },
  {
    id: "03-brand-mismatch",
    image: "01-clean-exact-match.jpg",
    application: Object.fromEntries(
      FIELD_KEYS.map((key) => [
        key,
        key === "brand" ? "NOT THE LABEL BRAND" : `demo-2 ${key}`,
      ]),
    ),
  },
  {
    id: "07-imperfect-blur",
    image: "03-imperfect-blur.jpg",
    application: Object.fromEntries(
      FIELD_KEYS.map((key) => [key, `demo-3 ${key}`]),
    ),
  },
];

function demoAwareFetch(verifyImpl) {
  return async (url, options) => {
    if (url === "/static/demo/scenarios.json") {
      return response(DEMO_SCENARIOS);
    }
    if (String(url).startsWith("/static/demo/")) {
      return {
        ok: true,
        status: 200,
        async blob() {
          return new Blob([`bytes-for-${url}`], { type: "image/jpeg" });
        },
        async json() {
          return {};
        },
        headers: {
          get() {
            return null;
          },
        },
      };
    }
    return verifyImpl(url, options);
  };
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

async function assertNoAxeViolations(page, state) {
  page.window.eval(axe.source);
  const result = await page.window.axe.run(page.document, {
    rules: {
      // JSDOM does not calculate layout or loaded stylesheet colors. Explicit
      // color-pair tests in test_ui.py cover the committed palette instead.
      "color-contrast": { enabled: false },
    },
  });
  const violations = result.violations.map((violation) => ({
    id: violation.id,
    targets: violation.nodes.map((node) => node.target),
  }));
  assert.equal(
    JSON.stringify(violations),
    "[]",
    `${state} has automated accessibility violations`,
  );
}

test("one queued label checks through batch and shows timing", async () => {
  let request = null;
  const page = createPage(async (url, options) => {
    request = { url, options };
    return response(
      batchPayload([{ status: "NEEDS_REVIEW" }]),
    );
  });
  addToQueue(page, 1);

  assert.equal(page.document.querySelectorAll(".queue-item").length, 1);
  assert.match(
    page.document.getElementById("check-button-text").textContent,
    /Check 1 Label/,
  );
  assert.equal(page.document.getElementById("check-button").disabled, false);

  checkLabels(page);
  await waitFor(() => !page.document.getElementById("results").hidden);

  const form = page.document.getElementById("queue-form");
  const results = page.document.getElementById("results");
  assert.equal(form.hidden, true);
  assert.equal(results.hidden, false);
  assert.equal(page.document.activeElement, results);
  assert.match(results.dataset.clickToResultMs, /^\d+$/);
  assert.match(results.textContent, /Needs review/);
  assert.match(results.textContent, /Checked in \d+\.\d+ seconds\./);
  assert.match(results.textContent, /Brand name/);
  assert.match(results.textContent, /brand name does not match/i);
  assert.equal(request.url, "/verify/batch");
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.body.getAll("images").length, 1);
  assert.equal(
    JSON.parse(request.options.body.get("applications"))[0].brand,
    "label 1 brand",
  );

  page.document.getElementById("new-queue-button").click();
  assert.equal(form.hidden, false);
  assert.equal(results.hidden, true);
  assert.equal(page.document.querySelectorAll(".queue-item").length, 0);
  assert.equal(page.document.getElementById("brand").value, "");
  assert.equal(page.document.activeElement, page.document.getElementById("image"));
  page.dom.window.close();
});

test("load demo labels fills the queue for batch check", async () => {
  let request = null;
  const page = createPage(
    demoAwareFetch(async (url, options) => {
      request = { url, options };
      return response(
        batchPayload([
          { status: "PASS" },
          { status: "NEEDS_REVIEW" },
          { status: "PASS" },
        ]),
      );
    }),
  );

  page.document.getElementById("load-demo-button").click();
  await waitFor(
    () => page.document.querySelectorAll(".queue-item").length === 3,
  );

  assert.match(
    page.document.getElementById("demo-load-status").textContent,
    /Loaded 3 demo labels/i,
  );
  assert.match(
    page.document.getElementById("check-button-text").textContent,
    /Check 3 Labels/,
  );
  assert.equal(page.document.activeElement, page.document.getElementById("check-button"));

  checkLabels(page);
  await waitFor(() => !page.document.getElementById("results").hidden);

  assert.equal(request.url, "/verify/batch");
  assert.equal(request.options.body.getAll("images").length, 3);
  assert.equal(
    JSON.parse(request.options.body.get("applications"))[1].brand,
    "NOT THE LABEL BRAND",
  );
  assert.match(
    page.document.getElementById("results").textContent,
    /Checked 3 labels in \d+\.\d+ seconds\./,
  );
  page.dom.window.close();
});

test("load demo labels shows a readable error when assets fail", async () => {
  const page = createPage(async () =>
    response({ error: { code: "MISSING", message: "gone", field: null } }, { status: 404 }),
  );

  page.document.getElementById("load-demo-button").click();
  const errorSummary = page.document.getElementById("error-summary");
  await waitFor(() => !errorSummary.hidden);

  assert.match(errorSummary.textContent, /Could not load demo labels/i);
  assert.equal(page.document.querySelectorAll(".queue-item").length, 0);
  page.dom.window.close();
});

test("three mixed labels render summary and drill-down", async () => {
  let request = null;
  const page = createPage(async (url, options) => {
    request = { url, options };
    return response(
      batchPayload([
        { status: "PASS" },
        { status: "NEEDS_REVIEW" },
        { status: "UNABLE_TO_VERIFY", code: "INVALID_IMAGE" },
      ]),
    );
  });
  addToQueue(page, 1);
  addToQueue(page, 2);
  addToQueue(page, 3);

  assert.match(
    page.document.getElementById("check-button-text").textContent,
    /Check 3 Labels/,
  );

  checkLabels(page);
  await waitFor(() => !page.document.getElementById("results").hidden);

  assert.equal(request.url, "/verify/batch");
  assert.equal(request.options.body.getAll("images").length, 3);
  assert.equal(
    JSON.parse(request.options.body.get("applications"))[2].brand,
    "label 3 brand",
  );
  assert.match(page.document.getElementById("summary").textContent, /Passed\s*1/);
  assert.match(page.document.getElementById("summary").textContent, /Needs review\s*1/);
  assert.match(
    page.document.getElementById("summary").textContent,
    /Unable to verify\s*1/,
  );
  const results = page.document.getElementById("results");
  assert.match(results.textContent, /Checked 3 labels in \d+\.\d+ seconds\./);
  const details = page.document.querySelectorAll(".batch-result-item");
  assert.equal(details.length, 3);
  assert.equal(details[0].open, true);
  assert.match(details[0].textContent, /Unable to verify|Label 3/i);

  page.document.getElementById("return-button").click();
  assert.equal(page.document.getElementById("queue-form").hidden, false);
  assert.equal(page.document.querySelectorAll(".queue-item").length, 3);
  page.dom.window.close();
});

test("queue starts empty with one compose card and caps at five", () => {
  const page = createPage(async () => response({}));

  assert.equal(page.document.getElementById("queue-panel").hidden, true);
  assert.equal(page.document.getElementById("compose-card").hidden, false);
  assert.equal(page.document.getElementById("check-button").disabled, true);
  assert.equal(page.document.querySelectorAll(".queue-item").length, 0);

  for (let index = 1; index <= 5; index += 1) {
    addToQueue(page, index);
  }

  assert.equal(page.document.querySelectorAll(".queue-item").length, 5);
  assert.equal(page.document.getElementById("compose-card").hidden, true);
  assert.equal(page.document.getElementById("queue-limit-note").hidden, false);
  assert.match(
    page.document.getElementById("check-button-text").textContent,
    /Check 5 Labels/,
  );

  page.document.querySelector(".queue-remove").click();
  assert.equal(page.document.querySelectorAll(".queue-item").length, 4);
  assert.equal(page.document.getElementById("compose-card").hidden, false);
  page.dom.window.close();
});

test("edit moves a queued label back into compose", () => {
  const page = createPage(async () => response({}));
  addToQueue(page, 1);
  addToQueue(page, 2);

  page.document.querySelector(".queue-edit").click();

  assert.equal(page.document.querySelectorAll(".queue-item").length, 1);
  assert.equal(page.document.getElementById("compose-card").hidden, false);
  assert.equal(page.document.getElementById("brand").value, "label 1 brand");
  assert.match(
    page.document.getElementById("compose-heading").textContent,
    /Edit label/i,
  );
  assert.match(
    page.document.getElementById("add-to-queue-button").textContent,
    /Update Queue/i,
  );

  page.document.getElementById("brand").value = "updated brand";
  const file = new page.window.File(["jpeg-edit"], "edited.jpg", {
    type: "image/jpeg",
  });
  const image = page.document.getElementById("image");
  Object.defineProperty(image, "files", {
    configurable: true,
    value: [file],
  });
  page.document.getElementById("add-to-queue-button").click();

  assert.equal(page.document.querySelectorAll(".queue-item").length, 2);
  assert.match(page.document.getElementById("queue-list").textContent, /edited\.jpg/);
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
    message: /queue is still here/i,
  },
  {
    name: "oversized request",
    status: 413,
    code: "REQUEST_TOO_LARGE",
    retryAfter: null,
    message: /photo smaller than 20 MB/i,
  },
]) {
  test(`${testCase.name} is readable and preserves the queue`, async () => {
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
    addToQueue(page, 1);

    checkLabels(page);
    const errorSummary = page.document.getElementById("error-summary");
    await waitFor(() => !errorSummary.hidden);

    assert.match(errorSummary.textContent, testCase.message);
    assert.equal(page.document.getElementById("queue-form").hidden, false);
    assert.equal(page.document.querySelectorAll(".queue-item").length, 1);
    assert.equal(page.document.activeElement, errorSummary);
    page.dom.window.close();
  });
}

test("request timeout is readable and preserves the queue", async () => {
  let fetchStarted = false;
  const page = createPage(
    (_url, options) => {
      fetchStarted = true;
      return new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          reject(new page.window.DOMException("timed out", "AbortError"));
        });
      });
    },
    { captureTimeout: true },
  );
  addToQueue(page, 1);

  checkLabels(page);
  await waitFor(() => fetchStarted);
  page.runTimeout();
  const errorSummary = page.document.getElementById("error-summary");
  await waitFor(() => !errorSummary.hidden);

  assert.match(errorSummary.textContent, /taking longer than expected/i);
  assert.equal(page.document.querySelectorAll(".queue-item").length, 1);
  page.dom.window.close();
});

test("API field error shows a readable summary and keeps the queue", async () => {
  const page = createPage(async () =>
    response(
      {
        error: {
          code: "APPLICATION_FIELD_TOO_LONG",
          message: "Use 2,000 characters or fewer.",
          field: "applications[0].brand",
        },
      },
      { status: 422 },
    ),
  );
  addToQueue(page, 1);

  checkLabels(page);
  const errorSummary = page.document.getElementById("error-summary");
  await waitFor(() => !errorSummary.hidden);

  assert.match(errorSummary.textContent, /2,000/);
  assert.equal(page.document.querySelectorAll(".queue-item").length, 1);
  page.dom.window.close();
});

const invalidPayloads = {
  "missing field": (() => {
    const payload = batchPayload([{ status: "PASS" }]);
    payload.items[0].result.fields.pop();
    return payload;
  })(),
  "duplicate field": (() => {
    const payload = batchPayload([{ status: "PASS" }]);
    payload.items[0].result.fields[6] = {
      ...payload.items[0].result.fields[0],
    };
    return payload;
  })(),
  "unknown field": (() => {
    const payload = batchPayload([{ status: "PASS" }]);
    payload.items[0].result.fields[6].field = "unknown";
    return payload;
  })(),
  "invalid actual value": (() => {
    const payload = batchPayload([{ status: "PASS" }]);
    payload.items[0].result.fields[0].actual = { unsafe: true };
    return payload;
  })(),
  "invalid score value": (() => {
    const payload = batchPayload([{ status: "PASS" }]);
    payload.items[0].result.fields[0].score = "high";
    return payload;
  })(),
  "invalid detail value": (() => {
    const payload = batchPayload([{ status: "PASS" }]);
    payload.items[0].result.fields[0].detail = ["unexpected"];
    return payload;
  })(),
  "invalid latency value": (() => {
    const payload = batchPayload([{ status: "PASS" }]);
    payload.latency_ms = "fast";
    return payload;
  })(),
  "verdict inconsistent with fields": (() => {
    const payload = batchPayload([{ status: "PASS" }]);
    payload.items[0].result.verdict = "NEEDS_REVIEW";
    payload.items[0].status = "NEEDS_REVIEW";
    return payload;
  })(),
  "fields out of order": (() => {
    const payload = batchPayload([{ status: "PASS" }]);
    const fields = payload.items[0].result.fields;
    [fields[0], fields[1]] = [fields[1], fields[0]];
    return payload;
  })(),
};

for (const [name, payload] of Object.entries(invalidPayloads)) {
  test(`invalid response (${name}) renders a generic error`, async () => {
    const page = createPage(async () => response(payload));
    addToQueue(page, 1);

    checkLabels(page);
    const errorSummary = page.document.getElementById("error-summary");
    await waitFor(() => !errorSummary.hidden);

    assert.match(errorSummary.textContent, /queue is still here/i);
    assert.equal(page.document.getElementById("queue-form").hidden, false);
    assert.equal(page.document.getElementById("results").hidden, true);
    page.dom.window.close();
  });
}

test("check progress appears only after the delay", async () => {
  let resolveFetch;
  let fetchStarted = false;
  const page = createPage(
    () => {
      fetchStarted = true;
      return new Promise((resolve) => {
        resolveFetch = resolve;
      });
    },
    { captureTimeout: true },
  );
  addToQueue(page, 1);
  addToQueue(page, 2);

  checkLabels(page);
  await waitFor(() => fetchStarted);
  assert.equal(page.document.getElementById("check-progress").hidden, true);
  page.runTimeout(1);
  assert.equal(page.document.getElementById("check-progress").hidden, false);
  assert.match(
    page.document.getElementById("check-progress").textContent,
    /Checking 2 labels/,
  );

  await waitFor(() => typeof resolveFetch === "function");
  resolveFetch(response(batchPayload([{ status: "PASS" }, { status: "PASS" }])));
  await waitFor(() => !page.document.getElementById("results").hidden);
  assert.equal(page.document.getElementById("check-progress").hidden, true);
  page.dom.window.close();
});

test("empty queue check makes no request", () => {
  let fetchCalls = 0;
  const page = createPage(async () => {
    fetchCalls += 1;
    return response({});
  });

  checkLabels(page);

  assert.equal(fetchCalls, 0);
  assert.match(
    page.document.getElementById("error-summary").textContent,
    /at least one label/i,
  );
  page.dom.window.close();
});

test("incomplete compose is rejected before queueing", () => {
  let fetchCalls = 0;
  const page = createPage(async () => {
    fetchCalls += 1;
    return response({});
  });

  page.document.getElementById("add-to-queue-button").click();

  assert.equal(fetchCalls, 0);
  assert.equal(page.document.querySelectorAll(".queue-item").length, 0);
  assert.equal(page.document.activeElement, page.document.getElementById("image"));
  assert.match(
    page.document.getElementById("error-summary").textContent,
    /fix \d+ items/i,
  );
  page.dom.window.close();
});

test("wrong file type is rejected before queueing and preserves entries", () => {
  const page = createPage(async () => response({}));
  fillCompose(page, 1);
  const image = page.document.getElementById("image");
  Object.defineProperty(image, "files", {
    configurable: true,
    value: [new page.window.File(["text"], "label.txt", { type: "text/plain" })],
  });

  page.document.getElementById("add-to-queue-button").click();

  assert.equal(page.document.querySelectorAll(".queue-item").length, 0);
  assert.equal(page.document.activeElement, image);
  assert.equal(page.document.getElementById("brand").value, "label 1 brand");
  assert.match(
    page.document.getElementById("image-error").textContent,
    /JPG, PNG, or WebP/,
  );
  page.dom.window.close();
});

test("large supported image is optimized before batch upload", async () => {
  let request;
  const page = createPage(async (url, options) => {
    request = { url, options };
    return response(batchPayload([{ status: "PASS" }]));
  });
  addToQueue(page, 1);
  page.window.createImageBitmap = async () => ({
    width: 2400,
    height: 1200,
    close() {},
  });
  page.window.HTMLCanvasElement.prototype.getContext = () => ({
    fillStyle: "",
    fillRect() {},
    drawImage() {},
  });
  page.window.HTMLCanvasElement.prototype.toBlob = (callback, type) => {
    callback(new page.window.Blob(["optimized-jpeg"], { type }));
  };

  checkLabels(page);
  await waitFor(() => request !== undefined);

  const uploaded = request.options.body.getAll("images")[0];
  assert.equal(uploaded.type, "image/jpeg");
  assert.equal(uploaded.size, "optimized-jpeg".length);
  page.dom.window.close();
});

test("compose warning has programmatic help and error descriptions", () => {
  const page = createPage(async () => response({}));
  const warning = page.document.getElementById("government_warning");
  const describedBy = warning.getAttribute("aria-describedby").split(" ");

  assert.equal(describedBy.length, 2);
  assert.ok(describedBy.every((id) => page.document.getElementById(id)));
  assert.match(
    page.document.getElementById(describedBy[0]).textContent,
    /Copy it exactly/,
  );
  page.dom.window.close();
});

test("automated accessibility scan passes every required UI state", async () => {
  const emptyPage = createPage(async () => response({}));
  await assertNoAxeViolations(emptyPage, "empty state");
  emptyPage.document.getElementById("add-to-queue-button").click();
  await assertNoAxeViolations(emptyPage, "compose error state");
  emptyPage.dom.window.close();

  const loadingPage = createPage(() => new Promise(() => {}));
  addToQueue(loadingPage, 1);
  checkLabels(loadingPage);
  await waitFor(() => loadingPage.document.getElementById("check-button").disabled);
  await assertNoAxeViolations(loadingPage, "loading state");
  loadingPage.dom.window.close();

  const resultPage = createPage(async () =>
    response(batchPayload([{ status: "PASS" }, { status: "NEEDS_REVIEW" }])),
  );
  addToQueue(resultPage, 1);
  await assertNoAxeViolations(resultPage, "queued state");
  addToQueue(resultPage, 2);
  checkLabels(resultPage);
  await waitFor(() => !resultPage.document.getElementById("results").hidden);
  await assertNoAxeViolations(resultPage, "results drill-down state");
  resultPage.dom.window.close();
});
