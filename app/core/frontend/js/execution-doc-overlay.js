/**
 * Full-screen iframe overlay for step documentation during execute-step.
 * Depends on execution-security-utils.js — load before execution-render-docs.js.
 */
(function (root) {
  'use strict';

  function removeDocFullscreenOverlay() {
    var existing = document.getElementById('doc-fullscreen-overlay');
    if (existing && existing.parentNode) {
      existing.parentNode.removeChild(existing);
    }
  }

  root.openDocFullScreenOverlay = function (docUrl, docTitle) {
    if (!docUrl || docUrl === '#') return;
    var sec = root.ExecutionSecurityUtils;
    if (!sec || typeof sec.isSameOriginEmbedUrl !== 'function') {
      if (!root.__executionSecurityUtilsMissingLogged) {
        root.__executionSecurityUtilsMissingLogged = true;
        if (typeof console !== 'undefined' && console.warn) {
          console.warn(
            'openDocFullScreenOverlay: ExecutionSecurityUtils missing — load execution-security-utils.js before execution-doc-overlay.js. Full-screen doc embed disabled (fail closed).'
          );
        }
      }
      return;
    }
    if (!sec.isSameOriginEmbedUrl(docUrl)) {
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('openDocFullScreenOverlay: blocked URL', docUrl);
      }
      return;
    }
    removeDocFullscreenOverlay();
    var overlay = document.createElement('div');
    overlay.id = 'doc-fullscreen-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', docTitle || 'Step instructions');
    overlay.style.cssText =
      'position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 1100; display: flex; flex-direction: column; background: var(--bg-primary, #fff);';
    var bar = document.createElement('div');
    bar.style.cssText =
      'flex-shrink: 0; display: flex; align-items: center; min-height: 48px; padding: 0 16px; border-bottom: 1px solid var(--border-default, #e5e7eb); background: var(--bg-card, #fff);';
    var backBtn = document.createElement('button');
    backBtn.type = 'button';
    backBtn.className = 'btn btn-secondary';
    backBtn.innerHTML = '&#8592; Back to step';
    var frameWrap = document.createElement('div');
    frameWrap.style.cssText = 'flex: 1; min-height: 0; width: 100%;';
    var iframe = document.createElement('iframe');
    iframe.src = docUrl;
    iframe.title = docTitle || 'Step instructions';
    iframe.setAttribute(
      'sandbox',
      'allow-same-origin allow-scripts allow-popups allow-downloads'
    );
    iframe.referrerPolicy = 'strict-origin-when-cross-origin';
    iframe.style.cssText = 'width: 100%; height: 100%; border: none; display: block;';
    frameWrap.appendChild(iframe);

    function teardown() {
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('popstate', onPopState);
      removeDocFullscreenOverlay();
    }

    function onKeyDown(ev) {
      if (ev.key === 'Escape') {
        teardown();
      }
    }

    function onPopState() {
      teardown();
    }

    backBtn.onclick = teardown;
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('popstate', onPopState);

    bar.appendChild(backBtn);
    overlay.appendChild(bar);
    overlay.appendChild(frameWrap);
    document.body.appendChild(overlay);
  };
})(typeof window !== 'undefined' ? window : this);
