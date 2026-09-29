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

    // Audited: every interpolated value (name, description, traceability_shape,
    // advisory, and each input/output/prompt list item built above) is passed
    // through escapeHtml() before concatenation.
    modalBodyEl.innerHTML = // nosemgrep: innerhtml-string-concat
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
    // Audited: csrfHeaders() reads meta[name="csrf-token"] and sets X-CSRFToken
    // explicitly, the rule's own suggested mitigation for a non-CoreAPI-client fetch.
    fetch("/api/core/process-templates/" + encodeURIComponent(templateId) + "/copy", { // nosemgrep: raw-fetch-post
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

  // --- starter packs (plan 2.4c) ---------------------------------------------------
  var packsEl = root.querySelector("[data-pt-packs]");
  var packGridEl = root.querySelector("[data-pt-pack-grid]");

  function node(tag, className, text, attrs) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text != null) n.textContent = text;
    Object.keys(attrs || {}).forEach(function (key) { n.setAttribute(key, attrs[key]); });
    return n;
  }

  function list(items) {
    var ul = node("ul", "pt-preview-list");
    items.forEach(function (item) { ul.appendChild(item); });
    return ul;
  }

  function renderPacks(packs) {
    packsEl.hidden = !packs.length;
    packGridEl.replaceChildren();
    packs.forEach(function (p) {
      var card = node("article", "pt-card pt-pack-card");
      card.appendChild(node("span", "pt-card-family", p.product_type));
      card.appendChild(node("span", "pt-card-name", p.name));
      card.appendChild(node("span", "pt-card-shape", p.steps.join(" → ")));
      card.appendChild(node("span", "pt-card-meta", "ABV is required on “" + p.final_output + "”. Checks that matter:"));
      card.appendChild(list(p.key_checks.map(function (c) { return node("li", null, c.why); })));
      var btn = node("button", "btn btn-primary", "Use this pack", { type: "button" });
      btn.addEventListener("click", function () { usePack(p.id, btn); });
      card.appendChild(btn);
      packGridEl.appendChild(card);
    });
  }

  function showPackResult(data) {
    modalBodyEl.replaceChildren();
    modalBodyEl.appendChild(node("h2", null, data.name + (data.created ? " is ready" : " is already in your workflows")));
    if (data.compliance_skipped) {
      modalBodyEl.appendChild(node("p", "pt-advisory", "Ask someone who manages compliance to switch on this pack's fields (ABV on the final product)."));
    } else if (data.compliance_changes.length) {
      modalBodyEl.appendChild(list(data.compliance_changes.map(function (c) { return node("li", null, c); })));
    } else {
      modalBodyEl.appendChild(node("p", null, "Its compliance fields were already set up."));
    }
    modalBodyEl.appendChild(node("p", null, "Worth checking for this product:"));
    modalBodyEl.appendChild(list(data.key_checks.map(function (c) {
      var li = node("li");
      li.appendChild(node("a", null, c.title, { href: "/compliant/nz-alcohol/np3-audit/check/" + encodeURIComponent(c.control_id) }));
      li.appendChild(document.createTextNode(": " + c.why));
      return li;
    })));
    modalBodyEl.appendChild(node("p", "pt-advisory", data.advisory));
    modalBodyEl.appendChild(node("a", "btn btn-primary", "Review the workflow", { href: "/core/flows/create/summary?id=" + encodeURIComponent(data.process_id) }));
    modalEl.hidden = false;
  }

  function usePack(packId, btn) {
    btn.disabled = true;
    // Audited: csrfHeaders() sets X-CSRFToken explicitly, as in useTemplate above.
    fetch("/api/core/process-templates/starter-packs/" + encodeURIComponent(packId) + "/apply", { // nosemgrep: raw-fetch-post
      method: "POST",
      headers: csrfHeaders(),
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          if (!resp.ok) throw new Error(data.error || "Could not apply the starter pack");
          return data;
        });
      })
      .then(showPackResult)
      .catch(function (err) {
        showError(err.message || "Could not apply the starter pack. Please try again.");
      })
      .finally(function () { btn.disabled = false; });
  }

  fetch("/api/core/process-templates/starter-packs")
    .then(function (resp) { return resp.ok ? resp.json() : { packs: [] }; })
    .then(function (data) { renderPacks(data.packs || []); })
    .catch(function () { packsEl.hidden = true; });

  loadCatalog();
})();
