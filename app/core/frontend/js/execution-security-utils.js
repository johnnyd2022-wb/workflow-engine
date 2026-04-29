/**
 * Shared embed/sink URL policy for execution UI (iframe, img).
 * Load before execution-doc-overlay.js and execution-render-docs.js.
 *
 * Exposes window.ExecutionSecurityUtils.isSameOriginEmbedUrl — fail-closed if page origin
 * cannot be derived from location.href (never compares resolved.origin to itself).
 *
 * This is a client-side guard only. Process-doc and download URLs should still be
 * validated and restricted on the server (signed URLs, org scoping, MIME allowlists).
 */
(function (root) {
  'use strict';

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
    try {
      var loc = root && root.location;
      if (!loc) return false;
      var pageOrigin;
      var baseForResolve;
      if (
        (loc.protocol === 'http:' || loc.protocol === 'https:') &&
        typeof loc.origin === 'string' &&
        loc.origin &&
        loc.origin !== 'null'
      ) {
        pageOrigin = loc.origin;
        baseForResolve = typeof loc.href === 'string' && loc.href ? loc.href : loc.origin + '/';
      } else if (typeof loc.href === 'string' && loc.href) {
        var pageBase = new URL(loc.href);
        pageOrigin = pageBase.origin;
        if (!pageOrigin || pageOrigin === 'null') return false;
        baseForResolve = loc.href;
      } else {
        return false;
      }
      var resolved = new URL(s, baseForResolve);
      return resolved.origin === pageOrigin;
    } catch (e) {
      return false;
    }
  }

  root.ExecutionSecurityUtils = {
    isSameOriginEmbedUrl: isSameOriginEmbedUrl,
  };
})(typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : this);
