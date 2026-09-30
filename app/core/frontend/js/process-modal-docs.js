(function() {
  'use strict';

  let pendingGuidedDocFileUpload = null;
  let pendingDeleteDoc = null;
  let deleteDocModalInitialized = false;

  function syncDocInlineDisabledState() {
    const docFileInput = document.getElementById('guided-doc-file');
    const docInlineTitle = document.getElementById('guided-doc-inline-title');
    const docInlineContent = document.getElementById('guided-doc-inline-content');
    const hasFile = docFileInput && docFileInput.files && docFileInput.files.length > 0;
    if (docInlineTitle) docInlineTitle.disabled = !!hasFile;
    if (docInlineContent) docInlineContent.disabled = !!hasFile;
  }

  function ensureDocFileListener() {
    const docFileInput = document.getElementById('guided-doc-file');
    if (!docFileInput || docFileInput.dataset.flowWizardDocListener === '1') return;
    docFileInput.dataset.flowWizardDocListener = '1';
    docFileInput.addEventListener('change', function() {
      syncDocInlineDisabledState();
      pendingGuidedDocFileUpload = null;
      const f = docFileInput.files && docFileInput.files[0];
      if (!f) {
        if (typeof window.persistSpaWizardState === 'function') window.persistSpaWizardState();
        return;
      }
      const maxB64 = 1.5 * 1024 * 1024;
      if (f.size > maxB64) {
        if (window.showNotification) {
          window.showNotification(
            'warning',
            'File too large',
            'Only files up to 1.5MB can be carried to the summary step in the browser. Use inline instructions instead, or split the document.'
          );
        }
        docFileInput.value = '';
        syncDocInlineDisabledState();
        return;
      }
      const reader = new FileReader();
      reader.onload = function() {
        const dataUrl = reader.result;
        const s = String(dataUrl);
        const comma = s.indexOf(',');
        const b64 = comma >= 0 ? s.slice(comma + 1) : '';
        pendingGuidedDocFileUpload = {
          fileName: f.name,
          mime: f.type || 'application/octet-stream',
          base64: b64
        };
        if (typeof window.persistSpaWizardState === 'function') window.persistSpaWizardState();
      };
      reader.onerror = function() {
        pendingGuidedDocFileUpload = null;
      };
      reader.readAsDataURL(f);
    });
  }

  async function loadAttachedStepDocs(stepId) {
    const container = document.getElementById('guided-step-docs-list');
    if (!container) return;
    container.innerHTML = 'Loading…';
    try {
      const res = await CoreAPI.getStepDocumentation(stepId);
      const docs = (res && res.documents) ? res.documents : [];
      container.innerHTML = '';
      if (docs.length === 0) {
        const empty = document.createElement('p');
        empty.style.cssText = 'color: var(--text-tertiary, #9ca3af); margin: 0; font-size: 13px;';
        empty.textContent = 'No documentation attached.';
        container.appendChild(empty);
      } else {
        docs.forEach(function(doc) {
          const row = document.createElement('div');
          row.style.cssText = 'display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; background: var(--bg-card, #fff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); margin-bottom: 6px;';
          const label = document.createElement('span');
          label.textContent = doc.title || (doc.content_markdown ? 'Inline doc' : 'File');
          label.style.cssText = 'flex: 1; min-width: 0; font-size: 13px; color: var(--text-primary);';
            const delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.className = 'btn btn-secondary btn-sm';
            delBtn.textContent = 'Delete';
            delBtn.onclick = function() {
              if (typeof window.showDeleteDocConfirmModal === 'function') {
                window.showDeleteDocConfirmModal(doc.id, row);
              } else {
                if (confirm('Remove this documentation from the step?')) {
                  CoreAPI.deleteProcessDoc(doc.id).then(function() {
                    row.remove();
                    if (window.showNotification) window.showNotification('success', 'Removed', 'Documentation removed.');
                  }).catch(function(e) {
                    if (window.showNotification) window.showNotification('error', 'Error', e.message || 'Could not delete.');
                  });
                }
              }
            };
          row.appendChild(label);
          row.appendChild(delBtn);
          container.appendChild(row);
        });
      }
    } catch (e) {
      container.innerHTML = '';
      const err = document.createElement('p');
      err.style.cssText = 'color: var(--error, #dc2626); margin: 0; font-size: 13px;';
      err.textContent = 'Could not load documentation.';
      container.appendChild(err);
    }
  }

  function ensureDeleteDocModalListeners() {
    if (deleteDocModalInitialized) return;
    const modalEl = document.getElementById('delete-doc-confirm-modal');
    const cancelBtn = document.getElementById('delete-doc-confirm-cancel');
    const removeBtn = document.getElementById('delete-doc-confirm-remove');
    if (!modalEl || !cancelBtn || !removeBtn) return;
    deleteDocModalInitialized = true;
    cancelBtn.addEventListener('click', function() {
      modalEl.style.display = 'none';
      pendingDeleteDoc = null;
    });
    removeBtn.addEventListener('click', async function() {
      if (!pendingDeleteDoc) return;
      const { docId, row } = pendingDeleteDoc;
      pendingDeleteDoc = null;
      modalEl.style.display = 'none';
      try {
        await CoreAPI.deleteProcessDoc(docId);
        if (row && row.parentNode) row.remove();
        if (window.showNotification) window.showNotification('success', 'Removed', 'Documentation removed.');
      } catch (e) {
        if (window.showNotification) window.showNotification('error', 'Error', e.message || 'Could not delete.');
      }
    });
  }

  window.showDeleteDocConfirmModal = function(docId, row) {
    const modalEl = document.getElementById('delete-doc-confirm-modal');
    if (!modalEl) return;
    ensureDeleteDocModalListeners();
    pendingDeleteDoc = { docId, row };
    modalEl.style.display = 'flex';
  };

  window.ensureGuidedDocFileListener = ensureDocFileListener;
  window.ProcessModalDocs = Object.freeze({
    syncDocInlineDisabledState,
    ensureDocFileListener,
    loadAttachedStepDocs,
    getPendingGuidedDocFileUpload: function() { return pendingGuidedDocFileUpload; },
    setPendingGuidedDocFileUpload: function(fileUpload) { pendingGuidedDocFileUpload = fileUpload; }
  });
})();
