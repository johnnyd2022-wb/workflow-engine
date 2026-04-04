/**
 * Process Flow SPA — full-page create/edit process step flow.
 * Reuses create-process-modal.js; this script only handles SPA-specific behavior:
 * - Back link, redirect on close/finish, and loadProcessData override.
 */
(function() {
  'use strict';

  if (!document.body || !document.body.hasAttribute('data-page') || document.body.getAttribute('data-page') !== 'process-flow-spa') {
    return;
  }

  // Banner back for /core/flows/create/step/N is synced in shared/base_spa.html (spaSyncBannerBack).

  // When modal logic calls loadProcessData (after close, save draft, or finish), redirect instead of refreshing in place.
  window.loadProcessData = function() {
    var id = new URLSearchParams(window.location.search).get('id');
    window.location.href = id ? '/core/flows?id=' + encodeURIComponent(id) : '/core';
  };
  // Step visibility and session restore: create-process-modal.js DOMContentLoaded (data-flow-step + sessionStorage).
})();
