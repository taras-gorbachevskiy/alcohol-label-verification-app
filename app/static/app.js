(() => {
  "use strict";

  const MAX_FILE_BYTES = 20 * 1024 * 1024;
  const REQUEST_TIMEOUT_MS = 6_000;
  const CLIENT_MAX_LONG_SIDE = 1280;
  const CLIENT_JPEG_QUALITY = 0.82;
  const CLIENT_TARGET_BYTES = 1024 * 1024;
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

  async function optimizedUpload(file) {
    if (!file || typeof window.createImageBitmap !== "function") {
      return file;
    }
    let bitmap;
    try {
      const started = window.performance?.now?.() ?? 0;
      bitmap = await window.createImageBitmap(file, { imageOrientation: "from-image" });
      const scale = Math.min(1, CLIENT_MAX_LONG_SIDE / Math.max(bitmap.width, bitmap.height));
      if (scale === 1 && file.size <= CLIENT_TARGET_BYTES) {
        return file;
      }
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext("2d", { alpha: false });
      if (!context || typeof canvas.toBlob !== "function") {
        return file;
      }
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) =>
        canvas.toBlob(resolve, "image/jpeg", CLIENT_JPEG_QUALITY),
      );
      if (!blob) {
        return file;
      }
      const ended = window.performance?.now?.() ?? started;
      try {
        window.performance?.measure?.("label-image-preprocess", {
          start: started,
          end: ended,
        });
      } catch (_unsupportedPerformanceApi) {
        // Image optimization is more important than optional browser telemetry.
      }
      return new File([blob], file.name, {
        type: "image/jpeg",
        lastModified: file.lastModified,
      });
    } catch (_error) {
      return file;
    } finally {
      bitmap?.close?.();
    }
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
    singleModeButton.disabled = isLoading;
    batchModeButton.disabled = isLoading;

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

  function friendlyApiError(code, fieldName, retryAfter, serverMessage = null) {
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
      MISSING_BATCH_SUBMISSION:
        "Choose a photo and complete all seven items for every label.",
      EMPTY_APPLICATION: "Complete all seven items, then check the label again.",
      EMPTY_BATCH_APPLICATIONS:
        "Complete all seven items for every label, then check the batch again.",
      INVALID_APPLICATION_JSON: "Check all seven items and try again.",
      INVALID_BATCH_JSON: "Check every label’s information and try again.",
      INVALID_APPLICATION: "Check all seven items and try again.",
      INVALID_BATCH_APPLICATIONS:
        "Check every label’s information and try again.",
      APPLICATION_FIELD_TOO_LONG:
        "This entry is too long. Use 2,000 characters or fewer.",
      EMPTY_BATCH: "Add at least one label before checking the batch.",
      BATCH_SIZE_EXCEEDED: "Use no more than five labels in one batch.",
      BATCH_PAIR_COUNT_MISMATCH:
        "Choose exactly one photo for each label in the batch.",
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

    if (
      ["INVALID_APPLICATION", "APPLICATION_FIELD_TOO_LONG"].includes(code) &&
      typeof serverMessage === "string" &&
      serverMessage.trim()
    ) {
      return serverMessage;
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
        error.apiError.message,
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
    for (const [index, result] of payload.fields.entries()) {
      if (!result || typeof result !== "object") {
        return false;
      }
      if (
        !fieldByKey.has(result.field) ||
        seen.has(result.field) ||
        result.field !== FIELDS[index].key
      ) {
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
          (typeof result.score === "number" &&
            Number.isFinite(result.score) &&
            result.score >= 0 &&
            result.score <= 100)
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
    const submittedAt = window.performance?.now?.() ?? Date.now();
    hideStaleResults();

    if (!validateForm()) {
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(
      () => controller.abort(),
      REQUEST_TIMEOUT_MS,
    );
    let payload = null;
    let requestError = null;
    setLoading(true);

    try {
      const formData = new FormData();
      formData.append("image", await optimizedUpload(imageInput.files[0]));
      formData.append("application", JSON.stringify(applicationPayload()));
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
    const renderedAt = window.performance?.now?.() ?? Date.now();
    results.dataset.clickToResultMs = String(
      Math.max(0, Math.round(renderedAt - submittedAt)),
    );
    try {
      window.performance?.measure?.("single-label-click-to-result", {
        start: submittedAt,
        end: renderedAt,
      });
    } catch (_unsupportedPerformanceApi) {
      // The result is already rendered; browser telemetry is optional.
    }
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

  const singleModeButton = document.getElementById("single-mode-button");
  const batchModeButton = document.getElementById("batch-mode-button");
  const batchForm = document.getElementById("batch-form");
  const batchCards = document.getElementById("batch-cards");
  const addLabelButton = document.getElementById("add-label-button");
  const batchSubmitButton = document.getElementById("batch-submit-button");
  const batchSubmitText = document.getElementById("batch-submit-text");
  const batchProgress = document.getElementById("batch-progress");
  const batchProgressText = document.getElementById("batch-progress-text");
  const batchErrorSummary = document.getElementById("batch-error-summary");
  const batchErrorTitle = document.getElementById("batch-error-title");
  const batchErrorMessage = document.getElementById("batch-error-message");
  const batchResults = document.getElementById("batch-results");
  const batchSummary = document.getElementById("batch-summary");
  const batchResultList = document.getElementById("batch-result-list");
  const editBatchButton = document.getElementById("edit-batch-button");
  const newBatchButton = document.getElementById("new-batch-button");

  let nextBatchCardId = 1;
  const batchPreviewUrls = new Map();

  function batchInputId(cardId, key) {
    return `batch-${cardId}-${key}`;
  }

  function batchField(cardId, field) {
    const wrapper = document.createElement("div");
    wrapper.className = "field";
    const id = batchInputId(cardId, field.key);
    const label = makeTextElement("label", "", field.label);
    label.htmlFor = id;
    wrapper.append(label);

    if (field.key === "government_warning") {
      const help = makeTextElement(
          "p",
          "field-help important-help",
          "Copy this exactly, including capital letters, spaces, and punctuation.",
      );
      help.id = `${id}-help`;
      wrapper.append(help);
    }

    const input = document.createElement(
      field.key === "government_warning" ? "textarea" : "input",
    );
    input.id = id;
    input.name = field.key;
    input.required = true;
    input.maxLength = 2000;
    if (input.tagName === "INPUT") {
      input.type = "text";
    } else {
      input.rows = 5;
    }
    input.setAttribute(
      "aria-describedby",
      field.key === "government_warning" ? `${id}-help ${id}-error` : `${id}-error`,
    );
    input.addEventListener("input", () => {
      if (input.value.trim()) {
        input.removeAttribute("aria-invalid");
        hide(document.getElementById(`${id}-error`));
      }
      hide(batchErrorSummary);
    });
    wrapper.append(input);
    const error = makeTextElement("p", "field-error", "");
    error.id = `${id}-error`;
    error.hidden = true;
    wrapper.append(error);
    return wrapper;
  }

  function updateBatchCards() {
    const cards = [...batchCards.querySelectorAll(".batch-card")];
    cards.forEach((card, index) => {
      card.querySelector(".batch-card-number").textContent = String(index + 1);
      card.querySelector(".batch-card-title").textContent = `Label ${index + 1}`;
      const remove = card.querySelector(".remove-label-button");
      remove.hidden = cards.length <= 2;
      remove.setAttribute("aria-label", `Remove label ${index + 1}`);
    });
    addLabelButton.hidden = cards.length >= 5;
  }

  function addBatchCard() {
    if (batchCards.children.length >= 5) {
      return;
    }
    const cardId = nextBatchCardId;
    nextBatchCardId += 1;
    const card = document.createElement("section");
    card.className = "card batch-card";
    card.dataset.cardId = String(cardId);

    const heading = document.createElement("div");
    heading.className = "batch-card-heading";
    const titleGroup = document.createElement("div");
    titleGroup.className = "section-heading";
    const number = makeTextElement("span", "step-number batch-card-number", "");
    number.setAttribute("aria-hidden", "true");
    titleGroup.append(number);
    const title = makeTextElement("h2", "batch-card-title", "");
    title.id = `batch-${cardId}-heading`;
    card.setAttribute("aria-labelledby", title.id);
    titleGroup.append(title);
    heading.append(titleGroup);
    const remove = makeTextElement("button", "remove-label-button", "Remove");
    remove.type = "button";
    remove.addEventListener("click", () => {
      const url = batchPreviewUrls.get(cardId);
      if (url) {
        URL.revokeObjectURL(url);
        batchPreviewUrls.delete(cardId);
      }
      card.remove();
      updateBatchCards();
    });
    heading.append(remove);
    card.append(heading);

    const imageId = batchInputId(cardId, "image");
    const picker = document.createElement("div");
    picker.className = "file-picker";
    const input = document.createElement("input");
    input.className = "file-input";
    input.id = imageId;
    input.name = "image";
    input.type = "file";
    input.accept = "image/jpeg,image/png,image/webp";
    input.required = true;
    input.setAttribute("aria-describedby", `${imageId}-help ${imageId}-error`);
    const label = makeTextElement("label", "file-button", "Choose Label Photo");
    label.htmlFor = imageId;
    const help = makeTextElement("p", "file-name", "No photo chosen");
    help.id = `${imageId}-help`;
    help.setAttribute("aria-live", "polite");
    picker.append(input, label, help);
    card.append(picker);
    const imageError = makeTextElement("p", "field-error", "");
    imageError.id = `${imageId}-error`;
    imageError.hidden = true;
    card.append(imageError);
    const preview = document.createElement("img");
    preview.className = "batch-photo-preview";
    preview.alt = "Selected label photo";
    preview.hidden = true;
    card.append(preview);
    input.addEventListener("change", () => {
      const oldUrl = batchPreviewUrls.get(cardId);
      if (oldUrl) {
        URL.revokeObjectURL(oldUrl);
        batchPreviewUrls.delete(cardId);
      }
      input.removeAttribute("aria-invalid");
      hide(imageError);
      const file = input.files[0];
      help.textContent = file ? file.name : "No photo chosen";
      preview.hidden = true;
      preview.removeAttribute("src");
      if (file && SUPPORTED_IMAGE_TYPES.has(file.type) && file.size > 0) {
        const url = URL.createObjectURL(file);
        batchPreviewUrls.set(cardId, url);
        preview.src = url;
        preview.hidden = false;
      }
      hide(batchErrorSummary);
    });

    for (const field of FIELDS) {
      card.append(batchField(cardId, field));
    }
    batchCards.append(card);
    updateBatchCards();
  }

  function clearBatchPreviews() {
    for (const url of batchPreviewUrls.values()) {
      URL.revokeObjectURL(url);
    }
    batchPreviewUrls.clear();
  }

  function resetBatch() {
    clearBatchPreviews();
    batchCards.replaceChildren();
    batchSummary.replaceChildren();
    batchResultList.replaceChildren();
    hide(batchErrorSummary);
    hide(batchResults);
    nextBatchCardId = 1;
    addBatchCard();
    addBatchCard();
  }

  function setMode(mode) {
    const isBatch = mode === "batch";
    singleModeButton.classList.toggle("selected", !isBatch);
    batchModeButton.classList.toggle("selected", isBatch);
    singleModeButton.setAttribute("aria-pressed", String(!isBatch));
    batchModeButton.setAttribute("aria-pressed", String(isBatch));
    hide(results);
    hide(batchResults);
    form.hidden = isBatch;
    batchForm.hidden = !isBatch;
    if (isBatch && batchCards.children.length === 0) {
      resetBatch();
    }
  }

  function showBatchFieldError(input, error, message) {
    input.setAttribute("aria-invalid", "true");
    error.textContent = `Error: ${message}`;
    show(error);
  }

  function validateBatch() {
    hide(batchErrorSummary);
    const issues = [];
    for (const card of batchCards.querySelectorAll(".batch-card")) {
      const cardId = card.dataset.cardId;
      const image = document.getElementById(batchInputId(cardId, "image"));
      const imageError = document.getElementById(`${image.id}-error`);
      image.removeAttribute("aria-invalid");
      hide(imageError);
      const imageMessage = fileValidationMessage(image.files[0]);
      if (imageMessage) {
        showBatchFieldError(image, imageError, imageMessage);
        issues.push(image);
      }
      for (const field of FIELDS) {
        const input = document.getElementById(batchInputId(cardId, field.key));
        const error = document.getElementById(`${input.id}-error`);
        input.removeAttribute("aria-invalid");
        hide(error);
        if (!input.value.trim()) {
          showBatchFieldError(input, error, field.emptyMessage);
          issues.push(input);
        }
      }
    }
    if (issues.length) {
      batchErrorTitle.textContent = "Check the labels below";
      batchErrorMessage.textContent = `Please fix ${issues.length} ${issues.length === 1 ? "item" : "items"}, then check the batch again.`;
      show(batchErrorSummary);
      issues[0].focus();
      return false;
    }
    return true;
  }

  async function batchSubmission() {
    const formData = new FormData();
    const applications = [];
    const cards = [...batchCards.querySelectorAll(".batch-card")];
    const optimized = await Promise.all(
      cards.map((card) => {
        const cardId = card.dataset.cardId;
        const image = document.getElementById(batchInputId(cardId, "image"));
        return optimizedUpload(image.files[0]);
      }),
    );
    for (const [index, card] of cards.entries()) {
      const cardId = card.dataset.cardId;
      formData.append("images", optimized[index]);
      applications.push(
        Object.fromEntries(
          FIELDS.map((field) => [
            field.key,
            document.getElementById(batchInputId(cardId, field.key)).value,
          ]),
        ),
      );
    }
    formData.append("applications", JSON.stringify(applications));
    return formData;
  }

  function setBatchLoading(isLoading) {
    batchForm.setAttribute("aria-busy", String(isLoading));
    batchSubmitButton.disabled = isLoading;
    batchSubmitButton.classList.toggle("is-loading", isLoading);
    batchSubmitText.textContent = isLoading ? "Checking Batch…" : "Check Batch";
    addLabelButton.disabled = isLoading;
    singleModeButton.disabled = isLoading;
    batchModeButton.disabled = isLoading;
    for (const control of batchCards.querySelectorAll("input, textarea, button")) {
      control.disabled = isLoading;
    }
    if (!isLoading) {
      hide(batchProgress);
    }
  }

  function isValidBatchResult(payload) {
    if (!payload || !payload.summary || !Array.isArray(payload.items)) {
      return false;
    }
    const summary = payload.summary;
    const counts = [
      summary.passed,
      summary.needs_review,
      summary.unable_to_verify,
      summary.total,
    ];
    if (!counts.every((count) => Number.isInteger(count) && count >= 0)) {
      return false;
    }
    if (
      summary.total < 1 ||
      summary.total > 5 ||
      summary.passed + summary.needs_review + summary.unable_to_verify !==
        summary.total ||
      payload.items.length !== summary.total ||
      typeof payload.latency_ms !== "number" ||
      !Number.isFinite(payload.latency_ms) ||
      payload.latency_ms < 0
    ) {
      return false;
    }
    const derived = { PASS: 0, NEEDS_REVIEW: 0, UNABLE_TO_VERIFY: 0 };
    for (const [index, item] of payload.items.entries()) {
      if (
        !item ||
        item.index !== index ||
        typeof item.filename !== "string" ||
        item.filename.length < 1 ||
        item.filename.length > 255 ||
        !Object.hasOwn(derived, item.status)
      ) {
        return false;
      }
      derived[item.status] += 1;
      if (item.status === "UNABLE_TO_VERIFY") {
        if (
          item.result !== null ||
          !item.error ||
          typeof item.error.code !== "string" ||
          typeof item.error.message !== "string" ||
          !(item.error.field === null || typeof item.error.field === "string")
        ) {
          return false;
        }
      } else if (
        item.error !== null ||
        !isValidResult(item.result) ||
        item.result.verdict !== item.status
      ) {
        return false;
      }
    }
    return (
      derived.PASS === summary.passed &&
      derived.NEEDS_REVIEW === summary.needs_review &&
      derived.UNABLE_TO_VERIFY === summary.unable_to_verify
    );
  }

  function summaryItem(label, value, className) {
    const wrapper = document.createElement("div");
    wrapper.className = `summary-item ${className}`;
    wrapper.append(makeTextElement("dt", "", label));
    wrapper.append(makeTextElement("dd", "", String(value)));
    return wrapper;
  }

  function batchResultItem(item) {
    const details = document.createElement("details");
    details.className = `batch-result-item ${item.status.toLowerCase().replaceAll("_", "-")}`;
    const toggle = document.createElement("summary");
    const title = document.createElement("span");
    title.append(makeTextElement("strong", "", `Label ${item.index + 1}`));
    title.append(makeTextElement("span", "batch-filename", item.filename));
    const labels = {
      PASS: "✓ Passed",
      NEEDS_REVIEW: "! Needs review",
      UNABLE_TO_VERIFY: "✕ Unable to verify",
    };
    toggle.append(title, makeTextElement("span", "status", labels[item.status]));
    details.append(toggle);
    const content = document.createElement("div");
    content.className = "batch-result-content";
    if (item.status === "UNABLE_TO_VERIFY") {
      content.append(
        makeTextElement(
          "p",
          "failure-reason",
          friendlyApiError(item.error.code, item.error.field, null, item.error.message),
        ),
      );
    } else {
      const ordered = FIELDS.map((field) => ({
        field,
        result: item.result.fields.find((result) => result.field === field.key),
      }));
      const failed = ordered.filter(({ result }) => result.status === "FAIL");
      const passed = ordered.filter(({ result }) => result.status === "PASS");
      const list = document.createElement("ul");
      list.className = "result-list";
      list.append(
        ...[...failed, ...passed].map(({ field, result }) =>
          resultItem(field, result),
        ),
      );
      content.append(list);
    }
    details.append(content);
    return details;
  }

  function renderBatchResults(payload) {
    batchSummary.replaceChildren(
      summaryItem("Passed", payload.summary.passed, "passed"),
      summaryItem("Needs review", payload.summary.needs_review, "review"),
      ...(payload.summary.unable_to_verify
        ? [
            summaryItem(
              "Unable to verify",
              payload.summary.unable_to_verify,
              "unavailable",
            ),
          ]
        : []),
      summaryItem("Total", payload.summary.total, "total"),
    );
    const priority = { UNABLE_TO_VERIFY: 0, NEEDS_REVIEW: 1, PASS: 2 };
    const sorted = [...payload.items].sort(
      (left, right) => priority[left.status] - priority[right.status],
    );
    const rendered = sorted.map(batchResultItem);
    const firstActionable = rendered.find(
      (_element, index) => sorted[index].status !== "PASS",
    );
    if (firstActionable) {
      firstActionable.open = true;
    }
    batchResultList.replaceChildren(...rendered);
    hide(batchForm);
    show(batchResults);
    batchResults.focus();
    batchResults.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function showBatchRequestError(error) {
    let message = "We couldn’t check this batch. Your information is still here. Please try again.";
    if (error.name === "AbortError") {
      message = "This batch is taking longer than expected. Please try again.";
    } else if (error instanceof TypeError) {
      message = "We couldn’t connect. Check your internet connection and try again.";
    } else if (error.apiError) {
      message = friendlyApiError(
        error.apiError.code,
        error.apiError.field,
        error.retryAfter,
        error.apiError.message,
      );
    }
    batchErrorTitle.textContent = "We couldn’t check this batch";
    batchErrorMessage.textContent = message;
    show(batchErrorSummary);
    const input = error.apiError ? batchApiInput(error.apiError.field) : null;
    if (input) {
      const fieldError = document.getElementById(`${input.id}-error`);
      showBatchFieldError(input, fieldError, message);
      input.focus();
    } else {
      batchErrorSummary.focus();
    }
  }

  function batchApiInput(fieldName) {
    const match = /^(applications|images)\[(\d+)](?:\.([a-z_]+))?$/.exec(fieldName || "");
    if (!match) {
      return null;
    }
    const card = batchCards.querySelectorAll(".batch-card")[Number(match[2])];
    if (!card) {
      return null;
    }
    const key = match[1] === "images" ? "image" : match[3];
    return key ? document.getElementById(batchInputId(card.dataset.cardId, key)) : null;
  }

  addLabelButton.addEventListener("click", addBatchCard);
  singleModeButton.addEventListener("click", () => setMode("single"));
  batchModeButton.addEventListener("click", () => setMode("batch"));

  batchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!validateBatch()) {
      return;
    }
    const count = batchCards.children.length;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    const progressDelay = window.setTimeout(() => {
      batchProgressText.textContent = `Checking ${count} labels…`;
      show(batchProgress);
    }, 400);
    let payload = null;
    let requestError = null;
    setBatchLoading(true);
    try {
      const response = await fetch("/verify/batch", {
        method: "POST",
        body: await batchSubmission(),
        signal: controller.signal,
      });
      let body = null;
      try {
        body = await response.json();
      } catch (_error) {
        // Invalid response bodies are handled as a generic readable error.
      }
      if (isValidBatchResult(body)) {
        payload = body;
      } else if (!response.ok) {
        const error = new Error("Batch verification request failed");
        error.apiError = body?.error || {};
        error.retryAfter = response.headers.get("Retry-After");
        throw error;
      } else {
        throw new Error("Invalid batch verification response");
      }
    } catch (error) {
      requestError = error;
    } finally {
      window.clearTimeout(timeout);
      window.clearTimeout(progressDelay);
      setBatchLoading(false);
    }
    if (requestError) {
      showBatchRequestError(requestError);
      return;
    }
    hide(batchErrorSummary);
    renderBatchResults(payload);
  });

  editBatchButton.addEventListener("click", () => {
    hide(batchResults);
    show(batchForm);
    batchForm.querySelector("input").focus();
  });
  newBatchButton.addEventListener("click", () => {
    resetBatch();
    show(batchForm);
    batchForm.querySelector("input").focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  window.addEventListener("beforeunload", () => {
    clearPreview();
    clearBatchPreviews();
  });
})();
