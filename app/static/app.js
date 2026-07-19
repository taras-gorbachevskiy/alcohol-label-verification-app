(() => {
  "use strict";

  const MAX_FILE_BYTES = 20 * 1024 * 1024;
  const MAX_QUEUE = 5;
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
  const form = document.getElementById("queue-form");
  const imageInput = document.getElementById("image");
  const imageHelp = document.getElementById("image-help");
  const photoPreview = document.getElementById("photo-preview");
  const previewImage = document.getElementById("preview-image");
  const composeCard = document.getElementById("compose-card");
  const composeStepNumber = document.getElementById("compose-step-number");
  const composeHeading = document.getElementById("compose-heading");
  const addToQueueButton = document.getElementById("add-to-queue-button");
  const cancelComposeButton = document.getElementById("cancel-compose-button");
  const queueLimitNote = document.getElementById("queue-limit-note");
  const queuePanel = document.getElementById("queue-panel");
  const queueList = document.getElementById("queue-list");
  const checkButton = document.getElementById("check-button");
  const checkButtonText = document.getElementById("check-button-text");
  const checkProgress = document.getElementById("check-progress");
  const checkProgressText = document.getElementById("check-progress-text");
  const errorSummary = document.getElementById("error-summary");
  const errorSummaryTitle = document.getElementById("error-summary-title");
  const errorSummaryMessage = document.getElementById("error-summary-message");
  const results = document.getElementById("results");
  const resultTiming = document.getElementById("result-timing");
  const summary = document.getElementById("summary");
  const resultList = document.getElementById("result-list");
  const returnButton = document.getElementById("return-button");
  const newQueueButton = document.getElementById("new-queue-button");
  const loadDemoButton = document.getElementById("load-demo-button");
  const demoLoadStatus = document.getElementById("demo-load-status");

  /** @type {{ id: number, file: File, application: Record<string, string> }[]} */
  let queue = [];
  let nextQueueId = 1;
  let previewUrl = null;
  let editingId = null;
  /** @type {number | null} */
  let editingIndex = null;
  /** @type {{ id: number, file: File, application: Record<string, string> } | null} */
  let editingSnapshot = null;
  /** @type {File | null} */
  let composeFile = null;
  let demoLoading = false;
  let checking = false;

  function hide(element) {
    element.hidden = true;
  }

  function show(element) {
    element.hidden = false;
  }

  function formatDuration(ms) {
    const seconds = Math.max(0, Number(ms) || 0) / 1000;
    if (seconds < 10) {
      return `${seconds.toFixed(1)} seconds`;
    }
    return `${Math.round(seconds)} seconds`;
  }

  function showTiming(element, ms, labelCount = 1) {
    if (!element) {
      return;
    }
    const count = Math.max(1, Number(labelCount) || 1);
    element.textContent =
      count === 1
        ? `Checked in ${formatDuration(ms)}.`
        : `Checked ${count} labels in ${formatDuration(ms)}.`;
    show(element);
  }

  function makeTextElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    element.textContent = text;
    return element;
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
      bitmap = await window.createImageBitmap(file, {
        imageOrientation: "from-image",
      });
      const scale = Math.min(
        1,
        CLIENT_MAX_LONG_SIDE / Math.max(bitmap.width, bitmap.height),
      );
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

  function applicationPayload() {
    return Object.fromEntries(
      FIELDS.map((field) => [field.key, document.getElementById(field.key).value]),
    );
  }

  function setFileInput(file) {
    if (!file || typeof DataTransfer === "undefined") {
      return false;
    }
    const transfer = new DataTransfer();
    transfer.items.add(file);
    imageInput.files = transfer.files;
    return imageInput.files.length === 1;
  }

  function currentComposeFile() {
    return imageInput.files[0] || composeFile;
  }

  function composeIsDirty() {
    if (editingId !== null) {
      return true;
    }
    if (currentComposeFile()) {
      return true;
    }
    return FIELDS.some((field) =>
      document.getElementById(field.key).value.trim(),
    );
  }

  function clearFileSelection() {
    composeFile = null;
    if (typeof DataTransfer !== "undefined") {
      try {
        imageInput.files = new DataTransfer().files;
        return;
      } catch (_error) {
        // Some test doubles replace `files` with a plain value.
      }
    }
    try {
      Object.defineProperty(imageInput, "files", {
        configurable: true,
        value: [],
      });
    } catch (_error) {
      // Browser reset already ran; leave best-effort cleanup.
    }
  }

  function clearCompose() {
    clearErrors();
    form.reset();
    clearFileSelection();
    clearPreview();
    imageHelp.textContent = "No photo chosen";
    editingId = null;
    editingIndex = null;
    editingSnapshot = null;
    composeFile = null;
    composeHeading.textContent = "Add a label";
    addToQueueButton.textContent = "Add to Queue";
    updateCancelButton();
  }

  function fillCompose(item) {
    clearErrors();
    for (const field of FIELDS) {
      document.getElementById(field.key).value = item.application[field.key] || "";
    }
    clearPreview();
    composeFile = item.file || null;
    if (setFileInput(item.file)) {
      imageHelp.textContent = item.file.name;
      previewUrl = URL.createObjectURL(item.file);
      previewImage.src = previewUrl;
      show(photoPreview);
    } else if (item.file) {
      imageHelp.textContent = item.file.name;
      previewUrl = URL.createObjectURL(item.file);
      previewImage.src = previewUrl;
      show(photoPreview);
    } else {
      imageHelp.textContent = "No photo chosen";
    }
    editingId = item.id;
    editingSnapshot = item;
    composeHeading.textContent = "Edit label";
    addToQueueButton.textContent = "Update Queue";
    updateCancelButton();
  }

  function updateCancelButton() {
    const showCancel = composeIsDirty();
    cancelComposeButton.hidden = !showCancel;
    cancelComposeButton.disabled = checking || demoLoading;
  }

  function cancelCompose() {
    if (checking || demoLoading) {
      return;
    }
    if (editingSnapshot !== null) {
      const index = Math.max(
        0,
        Math.min(editingIndex ?? queue.length, queue.length),
      );
      queue.splice(index, 0, editingSnapshot);
    }
    clearCompose();
    hide(errorSummary);
    renderQueue();
    if (!composeCard.hidden) {
      imageInput.focus();
    }
  }

  function validateCompose() {
    clearErrors();
    const issues = [];
    const imageMessage = fileValidationMessage(currentComposeFile());
    if (imageMessage) {
      showFieldError("image", imageMessage);
      issues.push(imageInput);
    }
    for (const field of FIELDS) {
      const input = document.getElementById(field.key);
      if (!input.value.trim()) {
        showFieldError(field.key, field.emptyMessage);
        issues.push(input);
      }
    }
    if (issues.length) {
      showErrorSummary(
        "Check the information below",
        `Please fix ${issues.length} ${
          issues.length === 1 ? "item" : "items"
        }, then add the label to the queue.`,
      );
      issues[0].focus();
      return false;
    }
    return true;
  }

  function updateComposeVisibility() {
    const full = queue.length >= MAX_QUEUE && editingId === null;
    composeCard.hidden = full;
    queueLimitNote.hidden = !full;
    composeStepNumber.textContent = String(queue.length + 1);
    if (full) {
      checkButton.focus();
    }
  }

  function applyControlLock() {
    const locked = checking || demoLoading;
    form.setAttribute("aria-busy", String(checking));
    checkButton.disabled = locked || queue.length < 1;
    checkButton.classList.toggle("is-loading", checking);
    addToQueueButton.disabled = locked;
    updateCancelButton();
    loadDemoButton.classList.toggle("is-disabled", locked);
    loadDemoButton.setAttribute("aria-disabled", String(locked));
    if (locked) {
      loadDemoButton.setAttribute("tabindex", "-1");
    } else {
      loadDemoButton.removeAttribute("tabindex");
    }
    imageInput.disabled = locked;
    for (const field of FIELDS) {
      document.getElementById(field.key).disabled = locked;
    }
    for (const button of queueList.querySelectorAll("button")) {
      button.disabled = locked;
    }
    if (!checking) {
      const count = queue.length;
      checkButtonText.textContent =
        count === 1 ? "Check 1 Label" : `Check ${count} Labels`;
    }
  }

  function updateCheckButton() {
    applyControlLock();
  }

  function beginEdit(item, index) {
    if (composeIsDirty()) {
      showErrorSummary(
        "Finish the form first",
        "Add to Queue, Update Queue, or Cancel before editing another label.",
      );
      cancelComposeButton.focus();
      return;
    }
    editingIndex = index;
    queue = queue.filter((entry) => entry.id !== item.id);
    fillCompose(item);
    renderQueue();
    show(composeCard);
    hide(queueLimitNote);
    hide(errorSummary);
    imageInput.focus();
    composeCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderQueue() {
    queueList.replaceChildren();
    if (!queue.length) {
      hide(queuePanel);
      updateComposeVisibility();
      updateCheckButton();
      return;
    }
    show(queuePanel);
    for (const [index, item] of queue.entries()) {
      const row = document.createElement("li");
      row.className = "queue-item";
      row.dataset.queueId = String(item.id);

      const info = document.createElement("div");
      info.className = "queue-item-info";
      info.append(
        makeTextElement("strong", "queue-item-title", `Label ${index + 1}`),
      );
      info.append(
        makeTextElement("span", "queue-item-file", item.file.name || "Photo ready"),
      );
      info.append(makeTextElement("span", "queue-item-status", "Ready"));
      row.append(info);

      const actions = document.createElement("div");
      actions.className = "queue-item-actions";
      const edit = makeTextElement("button", "secondary-button queue-edit", "Edit");
      edit.type = "button";
      edit.setAttribute("aria-label", `Edit label ${index + 1}`);
      edit.addEventListener("click", () => {
        beginEdit(item, index);
      });
      const remove = makeTextElement(
        "button",
        "remove-label-button queue-remove",
        "Remove",
      );
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove label ${index + 1}`);
      remove.addEventListener("click", () => {
        queue = queue.filter((entry) => entry.id !== item.id);
        if (editingId === item.id) {
          clearCompose();
        }
        renderQueue();
        if (queue.length < MAX_QUEUE) {
          show(composeCard);
          hide(queueLimitNote);
        }
      });
      actions.append(edit, remove);
      row.append(actions);
      queueList.append(row);
    }
    updateComposeVisibility();
    updateCheckButton();
  }

  function addCurrentToQueue() {
    if (demoLoading || checking) {
      return;
    }
    if (queue.length >= MAX_QUEUE && editingId === null) {
      showErrorSummary(
        "Queue is full",
        "You already have five labels queued. Check them, or remove one to add another.",
      );
      errorSummary.focus();
      return;
    }
    if (!validateCompose()) {
      return;
    }
    const file = currentComposeFile();
    const entry = {
      id: editingId ?? nextQueueId++,
      file,
      application: applicationPayload(),
    };
    if (editingId !== null) {
      const index = Math.max(
        0,
        Math.min(editingIndex ?? queue.length, queue.length),
      );
      queue.splice(index, 0, entry);
    } else {
      queue.push(entry);
    }
    clearCompose();
    renderQueue();
    hide(errorSummary);
    if (!composeCard.hidden) {
      imageInput.focus();
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
        "Complete all seven items for every label, then check again.",
      INVALID_APPLICATION_JSON: "Check all seven items and try again.",
      INVALID_BATCH_JSON: "Check every label’s information and try again.",
      INVALID_APPLICATION: "Check all seven items and try again.",
      INVALID_BATCH_APPLICATIONS:
        "Check every label’s information and try again.",
      APPLICATION_FIELD_TOO_LONG:
        "This entry is too long. Use 2,000 characters or fewer.",
      EMPTY_BATCH: "Add at least one label to the queue before checking.",
      BATCH_SIZE_EXCEEDED: "Use no more than five labels in one check.",
      BATCH_PAIR_COUNT_MISMATCH:
        "Choose exactly one photo for each label in the queue.",
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
        "We couldn’t check these labels. Your queue is still here. Please try again.",
    };

    if (
      ["INVALID_APPLICATION", "APPLICATION_FIELD_TOO_LONG"].includes(code) &&
      typeof serverMessage === "string" &&
      serverMessage.trim()
    ) {
      return serverMessage;
    }

    return (
      messages[code] ||
      "We couldn’t check these labels. Your queue is still here. Please try again."
    );
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

  function isValidBatchResult(payload) {
    if (!payload || !payload.summary || !Array.isArray(payload.items)) {
      return false;
    }
    const batchSummary = payload.summary;
    const counts = [
      batchSummary.passed,
      batchSummary.needs_review,
      batchSummary.unable_to_verify,
      batchSummary.total,
    ];
    if (!counts.every((count) => Number.isInteger(count) && count >= 0)) {
      return false;
    }
    if (
      batchSummary.total < 1 ||
      batchSummary.total > 5 ||
      batchSummary.passed +
        batchSummary.needs_review +
        batchSummary.unable_to_verify !==
        batchSummary.total ||
      payload.items.length !== batchSummary.total ||
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
      derived.PASS === batchSummary.passed &&
      derived.NEEDS_REVIEW === batchSummary.needs_review &&
      derived.UNABLE_TO_VERIFY === batchSummary.unable_to_verify
    );
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

    const expectedMissing =
      result.expected === null || String(result.expected).trim() === "";
    const actualMissing =
      result.actual === null || String(result.actual).trim() === "";
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
        expectedMissing ? "Nothing entered" : result.expected,
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

  function summaryItem(label, value, className) {
    const wrapper = document.createElement("div");
    wrapper.className = `summary-item ${className}`;
    wrapper.append(makeTextElement("dt", "", label));
    wrapper.append(makeTextElement("dd", "", String(value)));
    return wrapper;
  }

  function batchResultItem(item) {
    const details = document.createElement("details");
    details.className = `batch-result-item ${item.status
      .toLowerCase()
      .replaceAll("_", "-")}`;
    const toggle = document.createElement("summary");
    const title = document.createElement("span");
    title.append(makeTextElement("strong", "", `Label ${item.index + 1}`));
    title.append(makeTextElement("span", "batch-filename", item.filename));
    const labels = {
      PASS: "✓ APPROVED",
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
          friendlyApiError(
            item.error.code,
            item.error.field,
            null,
            item.error.message,
          ),
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

  function renderResults(payload) {
    summary.replaceChildren(
      summaryItem("APPROVED", payload.summary.passed, "passed"),
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
    resultList.replaceChildren(...rendered);
    hide(form);
    show(results);
    results.focus();
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function setLoading(isLoading) {
    checking = isLoading;
    if (isLoading) {
      checkButtonText.textContent =
        queue.length === 1 ? "Checking 1 Label…" : `Checking ${queue.length} Labels…`;
    } else {
      hide(checkProgress);
    }
    applyControlLock();
  }

  async function buildSubmission() {
    const formData = new FormData();
    const applications = [];
    const optimized = await Promise.all(
      queue.map((item) => optimizedUpload(item.file)),
    );
    for (const [index, item] of queue.entries()) {
      formData.append("images", optimized[index]);
      applications.push(item.application);
    }
    formData.append("applications", JSON.stringify(applications));
    return formData;
  }

  function showRequestError(error) {
    let message =
      "We couldn’t check these labels. Your queue is still here. Please try again.";
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
    }
    showErrorSummary("We couldn’t check these labels", message);
    errorSummary.focus();
  }

  function resetQueue() {
    queue = [];
    nextQueueId = 1;
    editingId = null;
    editingIndex = null;
    composeFile = null;
    clearCompose();
    if (resultTiming) {
      resultTiming.textContent = "";
      hide(resultTiming);
    }
    if (demoLoadStatus) {
      demoLoadStatus.textContent = "";
      hide(demoLoadStatus);
    }
    summary.replaceChildren();
    resultList.replaceChildren();
    hide(results);
    hide(errorSummary);
    show(form);
    renderQueue();
  }

  function isDemoScenario(item) {
    return (
      item &&
      typeof item.image === "string" &&
      item.image.length > 0 &&
      item.application &&
      typeof item.application === "object" &&
      FIELDS.every(
        (field) =>
          typeof item.application[field.key] === "string" &&
          item.application[field.key].trim().length > 0,
      )
    );
  }

  async function loadDemoLabels() {
    if (demoLoading || checking) {
      return;
    }
    const hadQueueItems = queue.length > 0;
    demoLoading = true;
    applyControlLock();
    hide(errorSummary);
    if (demoLoadStatus) {
      demoLoadStatus.textContent = "Loading sample labels…";
      show(demoLoadStatus);
    }
    try {
      const manifestResponse = await fetch("/static/demo/scenarios.json");
      if (!manifestResponse.ok) {
        throw new Error("demo manifest unavailable");
      }
      const scenarios = await manifestResponse.json();
      if (!Array.isArray(scenarios) || scenarios.length < 1) {
        throw new Error("demo manifest empty");
      }
      const selected = scenarios.slice(0, MAX_QUEUE).filter(isDemoScenario);
      if (selected.length < 1) {
        throw new Error("demo scenarios invalid");
      }
      const entries = [];
      for (const scenario of selected) {
        const imageResponse = await fetch(`/static/demo/${scenario.image}`);
        if (!imageResponse.ok) {
          throw new Error(`demo image missing: ${scenario.image}`);
        }
        const blob = await imageResponse.blob();
        const type = blob.type || "image/jpeg";
        if (!SUPPORTED_IMAGE_TYPES.has(type) && type !== "application/octet-stream") {
          throw new Error(`demo image type unsupported: ${scenario.image}`);
        }
        const file = new File([blob], scenario.image, {
          type: type === "application/octet-stream" ? "image/jpeg" : type,
        });
        entries.push({
          id: nextQueueId++,
          file,
          application: Object.fromEntries(
            FIELDS.map((field) => [field.key, scenario.application[field.key]]),
          ),
        });
      }
      queue = entries;
      editingId = null;
      editingIndex = null;
      composeFile = null;
      clearCompose();
      hide(results);
      demoLoading = false;
      renderQueue();
      if (demoLoadStatus) {
        demoLoadStatus.textContent = hadQueueItems
          ? `Replaced your queue with ${entries.length} demo labels.`
          : `Loaded ${entries.length} demo labels.`;
        show(demoLoadStatus);
      }
      checkButton.focus();
    } catch (_error) {
      if (demoLoadStatus) {
        demoLoadStatus.textContent = "";
        hide(demoLoadStatus);
      }
      showErrorSummary(
        "Could not load demo labels",
        "We couldn’t load the sample labels. Please try again, or add a label by hand.",
      );
      errorSummary.focus();
    } finally {
      demoLoading = false;
      applyControlLock();
    }
  }

  imageInput.addEventListener("change", () => {
    clearFieldError("image");
    hide(errorSummary);
    clearPreview();
    const file = imageInput.files[0] || null;
    composeFile = file;
    imageHelp.textContent = file ? file.name : "No photo chosen";
    if (file && SUPPORTED_IMAGE_TYPES.has(file.type) && file.size > 0) {
      previewUrl = URL.createObjectURL(file);
      previewImage.src = previewUrl;
      show(photoPreview);
    }
    updateCancelButton();
  });

  for (const field of FIELDS) {
    const input = document.getElementById(field.key);
    input.addEventListener("input", () => {
      if (input.value.trim()) {
        clearFieldError(field.key);
      }
      hide(errorSummary);
      updateCancelButton();
    });
  }

  addToQueueButton.addEventListener("click", addCurrentToQueue);
  cancelComposeButton.addEventListener("click", cancelCompose);
  loadDemoButton.addEventListener("click", (event) => {
    event.preventDefault();
    if (loadDemoButton.getAttribute("aria-disabled") === "true") {
      return;
    }
    void loadDemoLabels();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submittedAt = window.performance?.now?.() ?? Date.now();
    hide(errorSummary);
    if (demoLoading) {
      return;
    }
    if (composeIsDirty()) {
      showErrorSummary(
        editingId !== null ? "Finish editing first" : "Finish the form first",
        editingId !== null
          ? "Update Queue or Cancel before checking."
          : "Add to Queue or Cancel before checking.",
      );
      cancelComposeButton.focus();
      return;
    }
    if (queue.length < 1) {
      showErrorSummary(
        "Nothing to check yet",
        "Add at least one label to the queue, then check.",
      );
      errorSummary.focus();
      return;
    }

    const count = queue.length;
    let payload = null;
    let requestError = null;
    let timeout = 0;
    let progressDelay = 0;
    setLoading(true);
    try {
      const formData = await buildSubmission();
      const controller = new AbortController();
      timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      progressDelay = window.setTimeout(() => {
        checkProgressText.textContent =
          count === 1 ? "Checking 1 label…" : `Checking ${count} labels…`;
        show(checkProgress);
      }, 400);
      const response = await fetch("/verify/batch", {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
      let responseBody = null;
      try {
        responseBody = await response.json();
      } catch (_error) {
        // Invalid response bodies are handled as a generic readable error.
      }
      if (isValidBatchResult(responseBody)) {
        payload = responseBody;
      } else if (!response.ok) {
        const error = new Error("Verification request failed");
        error.apiError = responseBody?.error || {};
        error.retryAfter = response.headers.get("Retry-After");
        throw error;
      } else {
        throw new Error("Invalid verification response");
      }
    } catch (error) {
      requestError = error;
    } finally {
      window.clearTimeout(timeout);
      window.clearTimeout(progressDelay);
      setLoading(false);
    }

    if (requestError) {
      showRequestError(requestError);
      return;
    }

    renderResults(payload);
    const renderedAt = window.performance?.now?.() ?? Date.now();
    const clickToResultMs = Math.max(0, Math.round(renderedAt - submittedAt));
    results.dataset.clickToResultMs = String(clickToResultMs);
    showTiming(resultTiming, clickToResultMs, payload.summary.total);
    try {
      window.performance?.measure?.("queue-click-to-result", {
        start: submittedAt,
        end: renderedAt,
      });
    } catch (_unsupportedPerformanceApi) {
      // Result already rendered; browser telemetry is optional.
    }
  });

  returnButton.addEventListener("click", () => {
    hide(results);
    show(form);
    if (queue.length) {
      queueList.querySelector("button")?.focus();
    } else {
      imageInput.focus();
    }
  });

  newQueueButton.addEventListener("click", () => {
    resetQueue();
    imageInput.focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  window.addEventListener("beforeunload", () => {
    clearPreview();
  });

  renderQueue();
})();
