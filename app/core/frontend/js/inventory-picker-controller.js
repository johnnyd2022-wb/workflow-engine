/**
 * Owns execution inventory picker tab + search query state; rendering stays in the caller (onFilterChange).
 * Load after inventory-type-utils.js; before execution-render-inputs.js.
 */
(function (root) {
  'use strict';

  root.InventoryPickerController = {
    /**
     * @param {object} opts
     * @param {HTMLElement} [opts.inputSection]
     * @param {Array<HTMLElement>|NodeList} opts.pickerTabs
     * @param {HTMLInputElement} [opts.pickerSearch]
     * @param {string} opts.defaultActiveType
     * @param {function(string, string): void} opts.onFilterChange
     * @param {number} [opts.searchDebounceMs]
     */
    create: function (opts) {
      var inputSection = opts.inputSection;
      var pickerTabs = opts.pickerTabs || [];
      var pickerSearch = opts.pickerSearch;
      var onFilterChange = opts.onFilterChange;
      var debounceMs = opts.searchDebounceMs != null ? opts.searchDebounceMs : 300;

      var state = {
        activeType: opts.defaultActiveType || 'raw_material',
        q: ''
      };

      function emit() {
        if (typeof onFilterChange === 'function') onFilterChange(state.activeType, state.q);
      }

      function syncTabState(next) {
        state.activeType = next;
        try {
          if (inputSection) inputSection.dataset.activePickerType = String(next || '');
        } catch (e) {}
        for (var i = 0; i < pickerTabs.length; i++) {
          var t = pickerTabs[i];
          var isOn = t.getAttribute('data-exec-type') === next;
          t.setAttribute('aria-pressed', isOn ? 'true' : 'false');
          t.classList.toggle('flow-mode-segment--active', isOn);
        }
        emit();
      }

      function resetSearchUiAndQuery() {
        state.q = '';
        if (pickerSearch) pickerSearch.value = '';
      }

      var searchDebounceTimer = null;

      return {
        state: state,
        syncTabState: syncTabState,
        resetSearchUiAndQuery: resetSearchUiAndQuery,
        bind: function () {
          for (var b = 0; b < pickerTabs.length; b++) {
            (function (btn) {
              btn.addEventListener('click', function () {
                syncTabState(btn.getAttribute('data-exec-type') || 'all');
              });
            })(pickerTabs[b]);
          }
          if (pickerSearch) {
            pickerSearch.addEventListener('input', function () {
              var v = pickerSearch.value || '';
              if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
              searchDebounceTimer = setTimeout(function () {
                searchDebounceTimer = null;
                state.q = v;
                emit();
              }, debounceMs);
            });
          }
        }
      };
    }
  };
})(typeof window !== 'undefined' ? window : this);
