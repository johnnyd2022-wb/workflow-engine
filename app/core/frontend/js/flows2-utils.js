    // RULE: Never use innerHTML with API data. Use textContent or DOM APIs.
    // State reset on every navigation — window properties survive HTMX swaps across pages
    window.currentProcess = null;
    window.currentUser = window.currentUser || null;

    /** Caps for API-fed lists (performance / accidental huge payloads). */
    var FLOWS2_MAX_AUDIT_HISTORY = 80;
    var FLOWS2_MAX_RECONCILIATION_BLOCKS = 50;
    var FLOWS2_MAX_SYSTEM_FINDING_MESSAGES = 30;
    var FLOWS2_MAX_UPSTREAM_STEPS = 40;
    var FLOWS2_MAX_PROMPT_ENTRIES = 40;
    var FLOWS2_MAX_COMPLETED_EXECUTION_STEPS = 100;
    var FLOWS2_MAX_EVIDENCE_ITEMS = 50;
    var FLOWS2_MAX_IO_ROWS_PER_STEP = 200;
    var FLOWS2_MAX_EXECUTION_METADATA_KEYS = 50;
    /** Bound serialized JSON / strings from API objects shown in the UI (DoS / huge stringify). */
    var FLOWS2_MAX_JSON_DISPLAY_CHARS = 65536;

    /** In-flight inventory fetch + generation counter (avoid stale overwrites). */
    var Flows2InvLoad = {
      controller: null,
      generation: 0,
      begin() {
        if (this.controller) this.controller.abort();
        this.controller = new AbortController();
        this.generation += 1;
        return { signal: this.controller.signal, gen: this.generation };
      },
    };

    /** Own enumerable keys only; drop prototype-pollution-prone names. */
    function flows2SafeKeys(obj) {
      if (!obj || typeof obj !== 'object') return [];
      return Object.keys(obj).filter(
        (k) =>
          k !== '__proto__' &&
          k !== 'constructor' &&
          k !== 'prototype' &&
          Object.prototype.hasOwnProperty.call(obj, k)
      );
    }

    /** Double-quoted HTML attributes; safe if attrs stay quoted (single-quote contexts include &#39;). */
    function flows2EscapeAttr(val) {
      return String(val)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    }

    /** Strip non-alphanumeric characters from an API-supplied ID before using it as a DOM id or dataset value. */
    function flows2NormalizeId(v) {
      return String(v).replace(/[^a-zA-Z0-9_-]/g, '');
    }

    /** Resolve element by id when id may contain CSS-special characters (matches dataset inventory IDs). */
    function flows2QueryById(id) {
      const s = String(id);
      if (typeof CSS !== 'undefined' && CSS.escape) {
        return document.querySelector('#' + CSS.escape(s));
      }
      return document.getElementById(s);
    }

    /**
     * Module-scoped inventory UI state (avoid window.*).
     * itemsByType: map inventory_type -> items; allItems: full list from last load.
     */
    var flows2Inventory = {
      filter: 'raw_material',
      allItems: [],
      itemsByType: {},
      loadedProcessId: null,
    };

    function flows2SetInventoryFromApi(items, forProcessId) {
      const list = Array.isArray(items) ? items : [];
      flows2Inventory.allItems = list;
      if (forProcessId !== undefined) flows2Inventory.loadedProcessId = forProcessId;
      const by = {};
      list.forEach((i) => {
        const t = i.inventory_type || 'raw_material';
        if (!by[t]) by[t] = [];
        by[t].push(i);
      });
      flows2Inventory.itemsByType = by;
    }

    function flows2GetFilteredInventoryItems() {
      const f = flows2Inventory.filter || 'raw_material';
      return flows2Inventory.itemsByType[f] || [];
    }

    /**
     * Encoding contract for flows2 UI code:
     * - User/API text in the DOM: prefer element.textContent = …
     * - Legacy HTML strings: escapeHtml() once at interpolation time
     * - Double-quoted attributes only: flows2EscapeAttr()
     * - Arbitrary values as plain text: flows2ValueForHtml() then escapeHtml if building a string; prefer textContent
     * - escapeHtml: pure string replacement (no innerHTML / DOM); safe for text and double-quoted attribute contexts
     */
    function escapeHtml(text) {
      if (text === null || text === undefined) return '';
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }
    function flows2SvgStepDragGrip18() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '18');
      svg.setAttribute('height', '18');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      svg.setAttribute('aria-hidden', 'true');
      [
        [8, 6, 8, 6],
        [8, 12, 8, 12],
        [8, 18, 8, 18],
        [16, 6, 16, 6],
        [16, 12, 16, 12],
        [16, 18, 16, 18],
      ].forEach(([x1, y1, x2, y2]) => {
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', String(x1));
        line.setAttribute('y1', String(y1));
        line.setAttribute('x2', String(x2));
        line.setAttribute('y2', String(y2));
        svg.appendChild(line);
      });
      return svg;
    }

    function flows2SvgChevronDown18() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '18');
      svg.setAttribute('height', '18');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      svg.setAttribute('aria-hidden', 'true');
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      poly.setAttribute('points', '6 9 12 15 18 9');
      svg.appendChild(poly);
      return svg;
    }

    function flows2SvgHelpCircle14() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '14');
      svg.setAttribute('height', '14');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('cx', '12');
      c.setAttribute('cy', '12');
      c.setAttribute('r', '10');
      const l1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l1.setAttribute('x1', '12');
      l1.setAttribute('y1', '16');
      l1.setAttribute('x2', '12');
      l1.setAttribute('y2', '12');
      const l2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l2.setAttribute('x1', '12');
      l2.setAttribute('y1', '8');
      l2.setAttribute('x2', '12.01');
      l2.setAttribute('y2', '8');
      svg.appendChild(c);
      svg.appendChild(l1);
      svg.appendChild(l2);
      return svg;
    }

    function flows2SvgCloseX14() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '14');
      svg.setAttribute('height', '14');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      const l1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l1.setAttribute('x1', '18');
      l1.setAttribute('y1', '6');
      l1.setAttribute('x2', '6');
      l1.setAttribute('y2', '18');
      const l2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      l2.setAttribute('x1', '6');
      l2.setAttribute('y1', '6');
      l2.setAttribute('x2', '18');
      l2.setAttribute('y2', '18');
      svg.appendChild(l1);
      svg.appendChild(l2);
      return svg;
    }
    function flows2SvgChevron14() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '14');
      svg.setAttribute('height', '14');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      poly.setAttribute('points', '6 9 12 15 18 9');
      svg.appendChild(poly);
      return svg;
    }

    function flows2SvgChevron16() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '16');
      svg.setAttribute('height', '16');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      poly.setAttribute('points', '6 9 12 15 18 9');
      svg.appendChild(poly);
      return svg;
    }

    function flows2SvgPlayTriangle16() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '16');
      svg.setAttribute('height', '16');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
      poly.setAttribute('points', '5 3 19 12 5 21 5 3');
      svg.appendChild(poly);
      return svg;
    }

    function flows2SvgPlayTriangle14() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '14');
      svg.setAttribute('height', '14');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
      poly.setAttribute('points', '5 3 19 12 5 21 5 3');
      svg.appendChild(poly);
      return svg;
    }
    function flows2ClampObjectForDisplay(val, maxDepth, depth) {
      if (depth >= maxDepth) return '[Max nesting depth for display]';
      if (val === null || typeof val !== 'object') return val;
      if (Array.isArray(val)) {
        const cap = Math.min(val.length, FLOWS2_JSON_DISPLAY_MAX_ARRAY_ITEMS);
        const out = [];
        for (let i = 0; i < cap; i++) {
          const x = val[i];
          out.push(
            x !== null && typeof x === 'object'
              ? flows2ClampObjectForDisplay(x, maxDepth, depth + 1)
              : x
          );
        }
        if (val.length > cap) out.push('… [array truncated for display]');
        return out;
      }
      const out = {};
      flows2SafeKeys(val).forEach((k) => {
        const v = val[k];
        out[k] =
          v !== null && typeof v === 'object'
            ? flows2ClampObjectForDisplay(v, maxDepth, depth + 1)
            : v;
      });
      return out;
    }

    function flows2SerializeForDisplay(val) {
      if (val === null || val === undefined) return '';
      if (typeof val === 'object') {
        try {
          const clamped = flows2ClampObjectForDisplay(val, FLOWS2_JSON_DISPLAY_MAX_DEPTH, 0);
          let s = JSON.stringify(clamped, null, 2);
          if (s.length > FLOWS2_MAX_JSON_DISPLAY_CHARS) {
            return s.slice(0, FLOWS2_MAX_JSON_DISPLAY_CHARS) + '\n… [truncated for display]';
          }
          return s;
        } catch {
          const fallback = String(val);
          return fallback.length > FLOWS2_MAX_JSON_DISPLAY_CHARS
            ? fallback.slice(0, FLOWS2_MAX_JSON_DISPLAY_CHARS) + '…'
            : fallback;
        }
      }
      const str = String(val);
      return str.length > FLOWS2_MAX_JSON_DISPLAY_CHARS ? str.slice(0, FLOWS2_MAX_JSON_DISPLAY_CHARS) + '…' : str;
    }

    /** Normalize any API value to a display string before escapeHtml (objects → bounded JSON text). */
    function flows2ValueForHtml(val) {
      if (val === null || val === undefined) return '';
      if (typeof val === 'object') return flows2SerializeForDisplay(val);
      return String(val);
    }

    function flows2CreateChevronSvgEl16() {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '16');
      svg.setAttribute('height', '16');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      poly.setAttribute('points', '6 9 12 15 18 9');
      svg.appendChild(poly);
      return svg;
    }
