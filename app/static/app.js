(() => {
  "use strict";

  const MAX_FILE_BYTES = 20 * 1024 * 1024;
  const REQUEST_TIMEOUT_MS = 15_000;
  const SUPPORTED_IMAGE_TYPES = new Set([
    "image/jpeg",
    "image/png",
    "image/webp",
  ]);

  const FIELDS = [
    {
      key: "brand",
      label: "Brand name",
      emptyMessage: "Enter the brand name.",
      missingReason: "We could not find the brand name on the photo.",
      mismatchReason: "The brand name does not match.",
    },
    {
      key: "class_type",
      label: "Type of alcohol",
      emptyMessage: "Enter the type of alcohol.",
      missingReason: "We could not find the type of alcohol on the photo.",
      mismatchReason: "The type of alcohol does not match.",
    },
    {
      key: "producer",
      label: "Company shown on label",
      emptyMessage: "Enter the company shown on the label.",
      missingReason: "We could not find the company name on the photo.",
      mismatchReason: "The company name does not match.",
    },
    {
      key: "country",
      label: "Country of origin",
      emptyMessage: "Enter the country of origin.",
      missingReason: "We could not find the country of origin on the photo.",
      mismatchReason: "The country of origin does not match.",
    },
    {
      key: "abv",
      label: "Alcohol percentage (ABV)",
      emptyMessage: "Enter the alcohol percentage.",
      missingReason: "We could not find the alcohol percentage on the photo.",
      mismatchReason: "The alcohol percentage is different.",
    },
    {
      key: "net_contents",
      label: "Bottle size",
      emptyMessage: "Enter the bottle size.",
      missingReason: "We could not find the bottle size on the photo.",
      mismatchReason: "The bottle size is different.",
    },
    {
      key: "government_warning",
      label: "Government warning text",
      emptyMessage: "Enter the government warning text.",
      missingReason: "We could not read the full government warning on the photo.",
      mismatchReason:
        "The government warning does not match exactly. Check every word, capital letter, space, and punctuation mark.",
    },
  ];

  const fieldByKey = new Map(FIELDS.map((field) => [field.key, field]));
  const form = document.getElementById("verification-form");
  const imageInput = document.getElementById("image");
  const imageHelp = document.getElementById("image-help");
  const photoPreview = document.getElementById("photo-preview");
  const previewImage = document.getElementById("preview-image");
  const submitButton = document.getElementById("submit-button");
  const submitButtonText = document.getElementById("submit-button-text");
  const loadingStatus = document.getElementById("loading-status");
  const errorSummary = document.getElementById("error-summary");
  const errorSummaryTitle = document.getElementById("error-summary-title");
  const errorSummaryMessage = document.getElementById("error-summary-message");
  const results = document.getElementById("results");
  const verdict = document.getElementById("verdict");
  const resultsTitle = document.getElementById("results-title");
  const verdictSummary = document.getElementById("verdict-summary");
  const resultList = document.getElementById("result-list");
  const startOverButton = document.getElementById("start-over-button");

  let previewUrl = null;

  function hide(element) {
    element.hidden = true;
  }

  function show(element) {
    element.hidden = false;
  }

  function clearPreview() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = null;
    }
    previewImage.removeAttribute("src");
    hide(photoPreview);
  }

  function clearFieldError(key) {
    const input = document.getElementById(key);
    const error = document.getElementById(`${key}-error`);
    input.removeAttribute("aria-invalid");
    error.textContent = "";
    hide(error);
  }

  function showFieldError(key, message) {
    const input = document.getElementById(key);
    const error = document.getElementById(`${key}-error`);
    input.setAttribute("aria-invalid", "true");
    error.textContent = `Error: ${message}`;
    show(error);
  }

  function clearErrors() {
    clearFieldError("image");
    for (const field of FIELDS) {
      clearFieldError(field.key);
    }
    hide(errorSummary);
    errorSummaryMessage.textContent = "";
  }

  function showErrorSummary(title, message) {
    errorSummaryTitle.textContent = title;
    errorSummaryMessage.textContent = message;
    show(errorSummary);
  }

  function fileValidationMessage(file) {
    if (!file) {
      return "Choose a label photo.";
    }
    if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
      return "Choose a JPG, PNG, or WebP photo. Most phone photos will work.";
    }
    if (file.size > MAX_FILE_BYTES) {
      return "This photo is too large. Choose one smaller than 20 MB.";
    }
    if (file.size === 0) {
      return "This photo is empty. Choose a different photo.";
    }
    return null;
  }

  function validateForm() {
    clearErrors();
    const issues = [];
    const file = imageInput.files[0];
    const imageMessage = fileValidationMessage(file);

    if (imageMessage) {
      showFieldError("image", imageMessage);
      issues.push({ input: imageInput, message: imageMessage });
    }

    for (const field of FIELDS) {
      const input = document.getElementById(field.key);
      if (!input.value.trim()) {
        showFieldError(field.key, field.emptyMessage);
        issues.push({ input, message: field.emptyMessage });
      }
    }

    if (issues.length > 0) {
      const itemWord = issues.length === 1 ? "item" : "items";
      showErrorSummary(
        "Check the information below",
        `Please fix ${issues.length} ${itemWord}, then check the label again.`,
      );
      issues[0].input.focus();
      return false;
    }

    return true;
  }

  function applicationPayload() {
    return Object.fromEntries(
      FIELDS.map((field) => [field.key, document.getElementById(field.key).value]),
    );
  }

  function setLoading(isLoading) {
    form.setAttribute("aria-busy", String(isLoading));
    submitButton.disabled = isLoading;
    submitButton.classList.toggle("is-loading", isLoading);
    submitButtonText.textContent = isLoading ? "Checking Label…" : "Check Label";
    loadingStatus.hidden = !isLoading;

    imageInput.disabled = isLoading;
    for (const field of FIELDS) {
      document.getElementById(field.key).disabled = isLoading;
    }
  }

  function retryWaitDescription(rawValue) {
    const seconds = Number.parseInt(rawValue, 10);
    if (!Number.isFinite(seconds) || seconds <= 0) {
      return null;
    }
    if (seconds < 60) {
      return `${seconds} ${seconds === 1 ? "second" : "seconds"}`;
    }
    const minutes = Math.ceil(seconds / 60);
    return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  }

  function friendlyApiError(code, fieldName, retryAfter) {
    const wait = retryWaitDescription(retryAfter);
    if (code === "RATE_LIMITED") {
      return wait
        ? `Too many labels have been checked. Please wait about ${wait} and try again.`
        : "Too many labels have been checked. Please wait and try again.";
    }
    if (code === "VERIFICATION_BUSY") {
      return wait
        ? `The checker is busy. Please wait about ${wait} and try again.`
        : "The checker is busy. Please wait a few seconds and try again.";
    }

    const messages = {
      MISSING_SUBMISSION: "Choose a label photo and complete all seven items.",
      EMPTY_APPLICATION: "Complete all seven items, then check the label again.",
      INVALID_APPLICATION_JSON: "Check all seven items and try again.",
      INVALID_APPLICATION: "Check all seven items and try again.",
      APPLICATION_FIELD_TOO_LONG:
        "This entry is too long. Use 2,000 characters or fewer.",
      INVALID_MULTIPART: "We could not read this submission. Please try again.",
      REQUEST_TOO_LARGE:
        "This upload is too large. Choose a photo smaller than 20 MB.",
      UNSUPPORTED_IMAGE_TYPE:
        "Choose a JPG, PNG, or WebP photo. Most phone photos will work.",
      IMAGE_TOO_LARGE: "This photo is too large. Choose one smaller than 20 MB.",
      EMPTY_IMAGE: "This photo is empty. Choose a different photo.",
      INVALID_IMAGE: "We can’t open this photo. Try a different photo.",
      IMAGE_TYPE_MISMATCH: "We can’t open this photo. Try a different photo.",
      VERIFICATION_UNAVAILABLE:
        "We couldn’t check this label. Your information is still here. Please try again.",
    };

    if (code === "APPLICATION_FIELD_TOO_LONG") {
      return messages[code];
    }

    if (fieldName?.startsWith("application.")) {
      const key = fieldName.slice("application.".length);
      const field = fieldByKey.get(key);
      if (field) {
        return field.emptyMessage;
      }
    }

    return (
      messages[code] ||
      "We couldn’t check this label. Your information is still here. Please try again."
    );
  }

  function apiFieldKey(fieldName) {
    if (fieldName === "image") {
      return "image";
    }
    if (fieldName?.startsWith("application.")) {
      const key = fieldName.slice("application.".length);
      return fieldByKey.has(key) ? key : null;
    }
    return null;
  }

  function showRequestError(error) {
    let message;
    let key = null;

    if (error.name === "AbortError") {
      message = "This is taking longer than expected. Please try again.";
    } else if (error instanceof TypeError) {
      message =
        "We couldn’t connect. Check your internet connection and try again.";
    } else if (error.apiError) {
      message = friendlyApiError(
        error.apiError.code,
        error.apiError.field,
        error.retryAfter,
      );
      key = apiFieldKey(error.apiError.field);
    } else {
      message =
        "We couldn’t check this label. Your information is still here. Please try again.";
    }

    clearErrors();
    showErrorSummary("We couldn’t check this label", message);
    if (key) {
      showFieldError(key, message);
      document.getElementById(key).focus();
    } else {
      errorSummary.focus();
    }
  }

  function isValidResult(payload) {
    if (!payload || !["PASS", "NEEDS_REVIEW"].includes(payload.verdict)) {
      return false;
    }
    if (
      typeof payload.latency_ms !== "number" ||
      !Number.isFinite(payload.latency_ms) ||
      payload.latency_ms < 0
    ) {
      return false;
    }
    if (!Array.isArray(payload.fields) || payload.fields.length !== FIELDS.length) {
      return false;
    }

    const seen = new Set();
    for (const result of payload.fields) {
      if (!result || typeof result !== "object") {
        return false;
      }
      if (!fieldByKey.has(result.field) || seen.has(result.field)) {
        return false;
      }
      if (!["PASS", "FAIL"].includes(result.status)) {
        return false;
      }
      if (
        ![result.expected, result.actual].every(
          (value) => value === null || typeof value === "string",
        )
      ) {
        return false;
      }
      if (
        !(
          result.score === null ||
          (typeof result.score === "number" && Number.isFinite(result.score))
        ) ||
        !(result.detail === null || typeof result.detail === "string")
      ) {
        return false;
      }
      seen.add(result.field);
    }

    const hasFailure = payload.fields.some((result) => result.status === "FAIL");
    return payload.verdict === (hasFailure ? "NEEDS_REVIEW" : "PASS");
  }

  function makeTextElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    element.textContent = text;
    return element;
  }

  function resultItem(field, result) {
    const item = document.createElement("li");
    const failed = result.status === "FAIL";
    item.className = `result-item ${failed ? "fail" : "pass"}`;

    const header = document.createElement("div");
    header.className = "result-header";
    header.append(makeTextElement("h3", "", field.label));
    header.append(
      makeTextElement(
        "span",
        `status ${failed ? "fail" : "pass"}`,
        failed ? "✕ FAIL — Does not match" : "✓ PASS — Matches",
      ),
    );
    item.append(header);

    if (!failed) {
      return item;
    }

    const actualMissing = result.actual === null || result.actual === "";
    item.append(
      makeTextElement(
        "p",
        "failure-reason",
        actualMissing ? field.missingReason : field.mismatchReason,
      ),
    );

    const comparison = document.createElement("dl");
    comparison.className = "comparison";
    comparison.append(makeTextElement("dt", "", "Should say"));
    comparison.append(
      makeTextElement(
        "dd",
        "comparison-value",
        result.expected || "Not provided",
      ),
    );
    comparison.append(makeTextElement("dt", "", "Label says"));
    comparison.append(
      makeTextElement(
        "dd",
        "comparison-value",
        actualMissing ? "Not found on the photo" : result.actual,
      ),
    );
    item.append(comparison);
    return item;
  }

  function renderResults(payload) {
    const ordered = FIELDS.map((field) => ({
      field,
      result: payload.fields.find((result) => result.field === field.key),
    }));
    const failed = ordered.filter(({ result }) => result.status === "FAIL");
    const passed = ordered.filter(({ result }) => result.status === "PASS");
    const isApproved = payload.verdict === "PASS";

    verdict.className = `verdict ${isApproved ? "approved" : "needs-review"}`;
    resultsTitle.textContent = isApproved ? "✓ APPROVED" : "! NEEDS REVIEW";

    if (isApproved) {
      verdictSummary.textContent = "All 7 items match.";
    } else {
      const labels = failed.map(({ field }) => field.label).join(", ");
      const itemWord = failed.length === 1 ? "item does" : "items do";
      verdictSummary.textContent = `${failed.length} ${itemWord} not match: ${labels}.`;
    }

    resultList.replaceChildren(
      ...[...failed, ...passed].map(({ field, result }) =>
        resultItem(field, result),
      ),
    );
    hide(form);
    show(results);
    results.focus();
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function hideStaleResults() {
    if (!results.hidden) {
      hide(results);
      resultList.replaceChildren();
    }
  }

  imageInput.addEventListener("change", () => {
    clearFieldError("image");
    hide(errorSummary);
    hideStaleResults();
    clearPreview();

    const file = imageInput.files[0];
    imageHelp.textContent = file ? file.name : "No photo chosen";
    if (file && SUPPORTED_IMAGE_TYPES.has(file.type) && file.size > 0) {
      previewUrl = URL.createObjectURL(file);
      previewImage.src = previewUrl;
      show(photoPreview);
    }
  });

  for (const field of FIELDS) {
    const input = document.getElementById(field.key);
    input.addEventListener("input", () => {
      if (input.value.trim()) {
        clearFieldError(field.key);
      }
      hide(errorSummary);
      hideStaleResults();
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideStaleResults();

    if (!validateForm()) {
      return;
    }

    const formData = new FormData();
    formData.append("image", imageInput.files[0]);
    formData.append("application", JSON.stringify(applicationPayload()));

    const controller = new AbortController();
    const timeout = window.setTimeout(
      () => controller.abort(),
      REQUEST_TIMEOUT_MS,
    );
    let payload = null;
    let requestError = null;
    setLoading(true);

    try {
      const response = await fetch("/verify", {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
      let body = null;
      try {
        body = await response.json();
      } catch (_error) {
        // A malformed response is handled as a readable generic error below.
      }

      if (!response.ok) {
        const error = new Error("Verification request failed");
        error.apiError = body?.error || {};
        error.retryAfter = response.headers.get("Retry-After");
        throw error;
      }
      if (!isValidResult(body)) {
        throw new Error("Invalid verification response");
      }
      payload = body;
    } catch (error) {
      requestError = error;
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
    }

    if (requestError) {
      showRequestError(requestError);
      return;
    }

    clearErrors();
    renderResults(payload);
  });

  startOverButton.addEventListener("click", () => {
    form.reset();
    clearPreview();
    clearErrors();
    hide(results);
    show(form);
    resultList.replaceChildren();
    imageHelp.textContent = "No photo chosen";
    imageInput.focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  window.addEventListener("beforeunload", clearPreview);
})();
