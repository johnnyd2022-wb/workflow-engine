(function () {
  "use strict";

  function csrfHeaders() {
    var token = document.querySelector('meta[name="csrf-token"]');
    return { "Content-Type": "application/json", "X-CSRFToken": token ? token.content : "" };
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  var root = document.querySelector("[data-pt-root]");
  if (!root) return;

  var errorEl = root.querySelector("[data-pt-error]");
  var emptyEl = root.querySelector("[data-pt-empty]");
  var gridEl = root.querySelector("[data-pt-card-grid]");
  var filtersEl = root.querySelector("[data-pt-family-filters]");
  var modalEl = root.querySelector("[data-pt-preview-modal]");
  var modalBodyEl = root.querySelector("[data-pt-preview-body]");
  var modalCloseEl = root.querySelector("[data-pt-preview-close]");

  var state = { families: [], templates: [], activeFamily: "" };

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function closeModal() {
    modalEl.hidden = true;
    modalBodyEl.innerHTML = "";
  }

  modalCloseEl.addEventListener("click", closeModal);
  modalEl.addEventListener("click", function (evt) {
    if (evt.target === modalEl) closeModal();
  });

  function renderFilters() {
    var chips = ['<button type="button" class="pt-family-chip' + (state.activeFamily === "" ? " is-active" : "") + '" data-family="">All available templates</button>'];
    state.families.forEach(function (f) {
      var active = state.activeFamily === f.key ? " is-active" : "";
      chips.push('<button type="button" class="pt-family-chip' + active + '" data-family="' + escapeHtml(f.key) + '">' + escapeHtml(f.name) + "</button>");
    });
    filtersEl.innerHTML = chips.join("");
    filtersEl.querySelectorAll("[data-family]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.activeFamily = btn.getAttribute("data-family") || "";
        loadCatalog();
      });
    });
  }

  function renderCards() {
    var visible = state.templates.filter(function (t) {
      return !state.activeFamily || t.family === state.activeFamily;
    });
    emptyEl.hidden = state.templates.length !== 0;
    gridEl.innerHTML = visible
      .map(function (t) {
        return (
          '<button type="button" class="pt-card" data-template-id="' +
          escapeHtml(t.id) +
          '">' +
          '<span class="pt-card-family">' + escapeHtml(t.family.replace("_", " / ")) + "</span>" +
          '<span class="pt-card-name">' + escapeHtml(t.name) + "</span>" +
          '<span class="pt-card-shape">' + escapeHtml(t.traceability_shape) + "</span>" +
          '<span class="pt-card-meta">' + t.step_count + " step &middot; " + escapeHtml(t.default_units.join(", ")) + "</span>" +
          "</button>"
        );
      })
      .join("");
    gridEl.querySelectorAll("[data-template-id]").forEach(function (card) {
      card.addEventListener("click", function () {
        openPreview(card.getAttribute("data-template-id"));
      });
    });
  }

  function loadCatalog() {
    var url = "/api/core/process-templates" + (state.activeFamily ? "?family=" + encodeURIComponent(state.activeFamily) : "");
    fetch(url, { headers: { "X-CSRFToken": (document.querySelector('meta[name="csrf-token"]') || {}).content || "" } })
      .then(function (resp) {
        if (!resp.ok) throw new Error("Failed to load templates");
        return resp.json();
      })
      .then(function (data) {
        state.families = data.families || [];
        state.templates = data.templates || [];
        renderFilters();
        renderCards();
      })
      .catch(function () {
        showError("Could not load the template catalogue. Please try again.");
      });
  }

  function openPreview(templateId) {
    modalEl.hidden = false;
    modalBodyEl.innerHTML = "Loading…";
    fetch("/api/core/process-templates/" + encodeURIComponent(templateId))
      .then(function (resp) {
        if (!resp.ok) throw new Error("Not found");
        return resp.json();
      })
      .then(function (detail) {
        renderPreview(detail);
      })
      .catch(function () {
        modalBodyEl.innerHTML = "<p>This template is not available.</p>";
      });
  }

  function renderPreview(detail) {
    var inputs = (detail.step.inputs || []).map(function (i) {
      return "<li>" + escapeHtml(i.name) + " (" + escapeHtml(i.unit) + ")</li>";
    }).join("");
    var outputs = (detail.step.outputs || []).map(function (o) {
      return "<li>" + escapeHtml(o.name) + " (" + escapeHtml(o.unit) + ")</li>";
    }).join("");
    var prompts = (detail.step.execution_prompts || []).map(function (p) {
      return "<li>" + escapeHtml(p.label) + (p.required ? " (required)" : " (optional)") + "</li>";
    }).join("");

    modalBodyEl.innerHTML =
      "<h2>" + escapeHtml(detail.name) + "</h2>" +
      "<p>" + escapeHtml(detail.description) + "</p>" +
      "<p class=\"pt-card-shape\">" + escapeHtml(detail.traceability_shape) + "</p>" +
      "<div class=\"pt-advisory\">" + escapeHtml(detail.advisory) + "</div>" +
      (inputs ? "<strong>Inputs</strong><ul class=\"pt-preview-list\">" + inputs + "</ul>" : "") +
      "<strong>Outputs</strong><ul class=\"pt-preview-list\">" + outputs + "</ul>" +
      (prompts ? "<strong>Execution prompts</strong><ul class=\"pt-preview-list\">" + prompts + "</ul>" : "") +
      "<button type=\"button\" class=\"btn btn-primary pt-use-template-btn\" data-pt-use>Use this template</button>";

    modalBodyEl.querySelector("[data-pt-use]").addEventListener("click", function () {
      useTemplate(detail.id);
    });
  }

  function useTemplate(templateId) {
    fetch("/api/core/process-templates/" + encodeURIComponent(templateId) + "/copy", {
      method: "POST",
      headers: csrfHeaders(),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error("Copy failed");
        return resp.json();
      })
      .then(function (data) {
        window.location.href = "/core/flows/create/summary?id=" + encodeURIComponent(data.process_id);
      })
      .catch(function () {
        showError("Could not create a process from this template. Please try again.");
        closeModal();
      });
  }

  loadCatalog();
})();
