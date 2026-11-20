/**
 * Step documentation (SOP) rendering for execute-step UI — no modal/page coupling.
 * Depends on: CoreAPI; execution-security-utils.js (embed URL policy).
 * Load execution-doc-overlay.js first for openDocFullScreenOverlay (optional).
 *
 * Load before execution-modal.js — exposes window.ExecutionRenderDocs.
 */
(function (root) {
  'use strict';

  /** Escape plain-text markdown body for safe innerHTML (line breaks preserved). */
  function escapeInlineMarkdownContent(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>');
  }

  /**
   * @param {HTMLElement | null} docsSection #execute-docs-section
   * @param {HTMLElement | null} docsContainer #execute-docs-container
   * @param {Array<{ title?: string, content_markdown?: string, id?: string, storage_path?: string, mime_type?: string }>} documents
   */
  function renderStepDocumentation(docsSection, docsContainer, documents) {
    if (!docsSection || !docsContainer) return;
    docsContainer.innerHTML = '';
    var docs = Array.isArray(documents) ? documents : [];
    if (docs.length === 0) {
      docsSection.style.display = 'none';
      return;
    }

    docsSection.style.display = 'block';

    docs.forEach(function (doc) {
      var block = document.createElement('div');
      block.style.cssText =
        'margin-bottom: 16px; padding: 12px 16px; border: 1px solid var(--border-light); border-radius: var(--radius-md); background: var(--bg-secondary, #f9fafb);';
      var titleEl = document.createElement('div');
      titleEl.style.cssText =
        'font-weight: 600; font-size: 14px; color: var(--text-primary); margin-bottom: 8px;';
      titleEl.textContent = doc.title || 'Documentation';
      block.appendChild(titleEl);

      if (doc.content_markdown) {
        var details = document.createElement('details');
        details.className = 'flow-wizard-example-disclosure';
        details.open = true;
        details.style.cssText = 'margin-top: 12px; border-top: none;';

        var summary = document.createElement('summary');
        summary.className = 'flow-wizard-example-disclosure__summary';
        summary.appendChild(document.createTextNode('View inline'));
        var sumHint = document.createElement('span');
        sumHint.className = 'flow-wizard-example-disclosure__hint';
        sumHint.setAttribute('aria-hidden', 'true');
        sumHint.textContent = '(click to collapse)';
        summary.appendChild(sumHint);
        details.appendChild(summary);

        var body = document.createElement('div');
        body.className = 'flow-wizard-example-disclosure__body';

        var content = document.createElement('div');
        content.style.cssText = 'font-size: 13px; color: var(--text-primary); white-space: pre-wrap; line-height: 1.5;';
        content.innerHTML = escapeInlineMarkdownContent(doc.content_markdown || '');
        body.appendChild(content);
        details.appendChild(body);
        block.appendChild(details);
      } else if (doc.storage_path && doc.id) {
        var coreApi =
          root.CoreAPI ||
          (typeof window !== 'undefined' ? window.CoreAPI : undefined);
        var viewUrl =
          coreApi && typeof coreApi.getProcessDocViewUrl === 'function'
            ? coreApi.getProcessDocViewUrl(doc.id)
            : '#';
        var downloadUrl =
          coreApi && typeof coreApi.getProcessDocDownloadUrl === 'function'
            ? coreApi.getProcessDocDownloadUrl(doc.id)
            : viewUrl;
        var mime = (doc.mime_type || '').toLowerCase();
        var isPdf = mime.indexOf('pdf') !== -1;
        var isNarrowOrTouch = typeof root.innerWidth === 'number' && root.innerWidth <= 768;

        var sec = root.ExecutionSecurityUtils;
        if (!sec || typeof sec.isSameOriginEmbedUrl !== 'function') {
          if (!root.__executionSecurityUtilsMissingLogged) {
            root.__executionSecurityUtilsMissingLogged = true;
            if (typeof console !== 'undefined' && console.warn) {
              console.warn(
                'ExecutionRenderDocs: ExecutionSecurityUtils missing — load execution-security-utils.js before execution-render-docs.js. Inline doc embeds disabled (fail closed).'
              );
            }
          }
        }
        var viewUrlEmbedOk =
          sec && typeof sec.isSameOriginEmbedUrl === 'function' && sec.isSameOriginEmbedUrl(viewUrl);

        var preview = document.createElement('details');
        preview.className = 'flow-wizard-example-disclosure';
        preview.setAttribute('aria-label', (doc.title || 'Documentation') + ' preview');
        preview.style.cssText = 'margin-top: 12px; border-top: none;';
        var sum = document.createElement('summary');
        sum.className = 'flow-wizard-example-disclosure__summary';
        sum.appendChild(document.createTextNode('View inline'));
        var expHint = document.createElement('span');
        expHint.className = 'flow-wizard-example-disclosure__hint';
        expHint.setAttribute('aria-hidden', 'true');
        expHint.textContent = '(click to expand)';
        sum.appendChild(expHint);
        preview.appendChild(sum);
        var body = document.createElement('div');
        body.className = 'flow-wizard-example-disclosure__body';
        body.style.cssText = 'padding-bottom: 0;';

        var frameWrap = document.createElement('div');
        frameWrap.style.cssText =
          'width: 100%; border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md, 10px); overflow: hidden; background: var(--bg-card, #fff);';

        if (mime.indexOf('image/') === 0) {
          if (viewUrlEmbedOk) {
            var img = document.createElement('img');
            img.src = viewUrl;
            img.alt = doc.title || 'Documentation image';
            img.style.cssText = 'display: block; width: 100%; height: auto;';
            frameWrap.appendChild(img);
          } else {
            var imgWarn = document.createElement('p');
            imgWarn.style.cssText =
              'margin: 0; padding: 12px; font-size: 13px; color: var(--text-secondary);';
            imgWarn.textContent =
              'Inline image preview is only shown for same-origin documents. Use Open or Download below.';
            frameWrap.appendChild(imgWarn);
          }
        } else {
          if (viewUrlEmbedOk) {
            var iframe = document.createElement('iframe');
            iframe.src = viewUrl;
            iframe.title = doc.title || 'Documentation';
            iframe.setAttribute(
              'sandbox',
              'allow-same-origin allow-scripts allow-popups allow-downloads'
            );
            iframe.referrerPolicy = 'strict-origin-when-cross-origin';
            iframe.style.cssText =
              'display: block; width: 100%; height: min(70vh, 820px); min-height: 420px; border: none;';
            frameWrap.appendChild(iframe);
          } else {
            var frameWarn = document.createElement('p');
            frameWarn.style.cssText =
              'margin: 0; padding: 12px; font-size: 13px; color: var(--text-secondary);';
            frameWarn.textContent =
              'Inline preview is only shown for same-origin documents. Use Open or Download below.';
            frameWrap.appendChild(frameWarn);
          }
        }

        body.appendChild(frameWrap);
        preview.appendChild(body);
        block.appendChild(preview);

        var actionsDiv = document.createElement('div');
        actionsDiv.style.cssText = 'margin-top: 10px; display: flex; flex-wrap: wrap; align-items: center; gap: 12px;';

        var openLink = document.createElement('a');
        openLink.href = viewUrl;
        openLink.rel = 'noopener';
        openLink.target = '_blank';
        openLink.textContent = isPdf ? 'Open full screen' : 'Open in new tab';
        openLink.style.cssText =
          'display: inline-flex; align-items: center; min-height: 44px; padding: 0 8px; color: var(--text-secondary); font-size: 14px; text-decoration: none;';
        if (
          isNarrowOrTouch &&
          isPdf &&
          typeof root.openDocFullScreenOverlay === 'function'
        ) {
          openLink.target = '_self';
          openLink.addEventListener('click', function (e) {
            e.preventDefault();
            root.openDocFullScreenOverlay(viewUrl, doc.title || 'Step instructions');
          });
        }

        var downloadLink = document.createElement('a');
        downloadLink.href = downloadUrl;
        downloadLink.target = '_blank';
        downloadLink.rel = 'noopener';
        downloadLink.download = true;
        downloadLink.textContent = 'Download';
        downloadLink.style.cssText =
          'display: inline-flex; align-items: center; min-height: 44px; padding: 0 8px; color: var(--text-secondary); font-size: 14px; text-decoration: none;';

        actionsDiv.appendChild(openLink);
        actionsDiv.appendChild(downloadLink);
        block.appendChild(actionsDiv);
      }

      docsContainer.appendChild(block);
    });
  }

  var api = {
    renderStepDocumentation: renderStepDocumentation,
    escapeInlineMarkdownContent: escapeInlineMarkdownContent,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.ExecutionRenderDocs = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
