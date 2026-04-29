/**
 * Pure-ish helpers shared by execution UI (modal / page).
 * Load before execution-modal.js — exposes window.ExecutionSharedUtils.
 */
(function (root) {
  'use strict';

  function getGlobalStore() {
    return typeof globalThis !== 'undefined'
      ? globalThis
      : typeof window !== 'undefined'
        ? window
        : typeof root !== 'undefined'
          ? root
          : {};
  }

  async function loadOrgUsersMap(opts) {
    opts = opts || {};
    var signal = opts.signal;
    var g = getGlobalStore();
    if (g.__OrgUsersMap) return g.__OrgUsersMap;
    try {
      async function tryFetchUsers(url) {
        var fetchOpts = { credentials: 'same-origin', cache: 'no-store' };
        if (signal) fetchOpts.signal = signal;
        var resp = await fetch(url, fetchOpts);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return await resp.json();
      }
      var data = await tryFetchUsers('/org/users');
      var m = new Map();
      (data.users || []).forEach(function (u) {
        if (!u || !u.id) return;
        var label =
          u.display_name ||
          [u.first_name, u.last_name].filter(Boolean).join(' ').trim() ||
          u.email ||
          u.name ||
          u.username ||
          u.id;
        m.set(String(u.id), String(label));
      });
      g.__OrgUsersMap = m;
      return m;
    } catch (e) {
      if (e && e.name === 'AbortError') {
        throw e;
      }
      if (typeof console !== 'undefined' && typeof console.warn === 'function') {
        console.warn('loadOrgUsersMap: failed to fetch /org/users', e);
      }
      g.__OrgUsersMap = new Map();
      return g.__OrgUsersMap;
    }
  }

  function prettyLabel(s) {
    if (!s) return '';
    return String(s)
      .replace(/_/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
  }

  function convertUnit(quantity, fromUnit, toUnit) {
    if (!fromUnit || !toUnit || String(fromUnit).toLowerCase() === String(toUnit).toLowerCase()) {
      return quantity;
    }

    var from = String(fromUnit).toLowerCase();
    var to = String(toUnit).toLowerCase();

    var massFactors = {
      kg: 1.0,
      g: 0.001,
      mg: 0.000001,
      lb: 0.453592,
      oz: 0.0283495,
      ton: 1000.0,
      tonne: 1000.0,
    };

    var volumeFactors = {
      l: 1.0,
      ml: 0.001,
      gal: 3.78541,
      m3: 1000.0,
      ft3: 28.3168,
    };

    var lengthFactors = {
      m: 1.0,
      cm: 0.01,
      mm: 0.001,
      ft: 0.3048,
      in: 0.0254,
    };

    var fromMass = from in massFactors;
    var toMass = to in massFactors;
    var fromVolume = from in volumeFactors;
    var toVolume = to in volumeFactors;
    var fromLength = from in lengthFactors;
    var toLength = to in lengthFactors;

    if (fromMass && toMass) {
      return (quantity * massFactors[from]) / massFactors[to];
    }
    if (fromVolume && toVolume) {
      return (quantity * volumeFactors[from]) / volumeFactors[to];
    }
    if (fromLength && toLength) {
      return (quantity * lengthFactors[from]) / lengthFactors[to];
    }
    return quantity;
  }

  var api = {
    convertUnit: convertUnit,
    prettyLabel: prettyLabel,
    loadOrgUsersMap: loadOrgUsersMap,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (typeof root !== 'undefined' && root) {
    root.ExecutionSharedUtils = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
