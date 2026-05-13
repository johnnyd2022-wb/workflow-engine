/**
 * Inline quantity adjustment widget for inventory items.
 *
 * Usage: render a button with class "inv-adj-btn" and data attributes:
 *   data-item-id   — inventory item UUID
 *   data-unit      — unit string (e.g. "kg")
 *   data-current   — current quantity string
 *
 * After a successful save the widget calls window.invAdjustOnSave(itemId, newQty, unit)
 * if that function exists — callers set it to trigger a page refresh.
 */
(function () {
  if (window._invAdjLoaded) return;
  window._invAdjLoaded = true;

  function getCsrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  function closeForm(btn) {
    var f = btn.closest('.inv-adj-wrap');
    if (f) f.querySelector('.inv-adj-form') && f.querySelector('.inv-adj-form').remove();
  }

  function showForm(btn) {
    var wrap = btn.closest('.inv-adj-wrap');
    if (!wrap) return;

    // Toggle off if already open
    var existing = wrap.querySelector('.inv-adj-form');
    if (existing) { existing.remove(); return; }

    var itemId  = btn.dataset.itemId;
    var unit    = btn.dataset.unit || '';
    var current = btn.dataset.current || '';

    var form = document.createElement('div');
    form.className = 'inv-adj-form';
    form.innerHTML =
      '<label class="inv-adj-label">New quantity (' + escInvAdj(unit) + ')</label>' +
      '<div class="inv-adj-row">' +
        '<input type="number" class="inv-adj-input" step="any" min="0" value="' + escInvAdj(current) + '" placeholder="0">' +
        '<button type="button" class="inv-adj-save">Save</button>' +
        '<button type="button" class="inv-adj-cancel">Cancel</button>' +
      '</div>' +
      '<span class="inv-adj-msg"></span>';

    wrap.appendChild(form);
    var input = form.querySelector('.inv-adj-input');
    input.focus();
    input.select();

    form.querySelector('.inv-adj-cancel').addEventListener('click', function () {
      form.remove();
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') form.querySelector('.inv-adj-save').click();
      if (e.key === 'Escape') form.remove();
    });

    form.querySelector('.inv-adj-save').addEventListener('click', function () {
      var val = input.value.trim();
      if (val === '' || isNaN(parseFloat(val))) {
        form.querySelector('.inv-adj-msg').textContent = 'Enter a valid number.';
        return;
      }
      var saveBtn = form.querySelector('.inv-adj-save');
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';

      fetch('/api/core/inventory/' + encodeURIComponent(itemId) + '/adjust', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrf(),
          'X-CSRF-Token': getCsrf(),
        },
        body: JSON.stringify({ new_quantity: val }),
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (res) {
          if (!res.ok) {
            form.querySelector('.inv-adj-msg').textContent = res.data.error || 'Save failed.';
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
            return;
          }
          var newQty = res.data.quantity;
          // Update the btn data-current so toggling again shows the new value
          btn.dataset.current = newQty;
          form.remove();
          if (typeof window.invAdjustOnSave === 'function') {
            window.invAdjustOnSave(itemId, newQty, unit);
          }
        })
        .catch(function () {
          form.querySelector('.inv-adj-msg').textContent = 'Network error — try again.';
          saveBtn.disabled = false;
          saveBtn.textContent = 'Save';
        });
    });
  }

  function escInvAdj(s) {
    if (!s) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Event delegation — works on dynamically rendered cards
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.inv-adj-btn');
    if (btn) showForm(btn);
  });
})();
