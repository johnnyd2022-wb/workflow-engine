/**
 * Shared embed/sink URL policy for execution UI (iframe, img).
 * Load before execution-doc-overlay.js and execution-render-docs.js.
 *
 * Exposes window.ExecutionSecurityUtils.isSameOriginEmbedUrl — fail-closed if page origin
 * cannot be derived from location.href (never compares resolved.origin to itself).
 */
(function (root) {
  'use strict';

  function getPageOrigin() {
    try {
      var loc = root && root.location;
      if (!loc || typeof loc.href !== 'string' || !loc.href) {
        return null;
      }
      return new URL(loc.href).origin;
    } catch (e) {
      return null;
    }
  }

  /**
   * @param {string} url
   * @returns {boolean}
   */
  function isSameOriginEmbedUrl(url) {
    if (!url || url === '#') return false;
    var s = String(url).trim();
    var lower = s.toLowerCase();
    if (
      lower.indexOf('javascript:') === 0 ||
      lower.indexOf('data:') === 0 ||
      lower.indexOf('vbscript:') === 0
    ) {
      return false;
    }
    var pageOrigin = getPageOrigin();
    if (!pageOrigin) return false;
    try {
      var loc = root && root.location;
      if (!loc || typeof loc.href !== 'string' || !loc.href) return false;
      var resolved = new URL(s, loc.href);
      return resolved.origin === pageOrigin;
    } catch (e) {
      return false;
    }
  }

  root.ExecutionSecurityUtils = {
    isSameOriginEmbedUrl: isSameOriginEmbedUrl,
  };
})(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this);
