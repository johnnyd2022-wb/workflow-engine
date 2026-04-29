/**
 * Full-screen iframe overlay for step documentation during execute-step.
 * Sets window.openDocFullScreenOverlay — load before execution-render-docs.js.
 */
(function (root) {
  'use strict';

  root.openDocFullScreenOverlay = function (docUrl, docTitle) {
    if (!docUrl || docUrl === '#') return;
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
    backBtn.onclick = function () {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    };
    bar.appendChild(backBtn);
    var frameWrap = document.createElement('div');
    frameWrap.style.cssText = 'flex: 1; min-height: 0; width: 100%;';
    var iframe = document.createElement('iframe');
    iframe.src = docUrl;
    iframe.title = docTitle || 'Step instructions';
    iframe.style.cssText = 'width: 100%; height: 100%; border: none; display: block;';
    frameWrap.appendChild(iframe);
    overlay.appendChild(bar);
    overlay.appendChild(frameWrap);
    document.body.appendChild(overlay);
  };
})(typeof window !== 'undefined' ? window : this);
