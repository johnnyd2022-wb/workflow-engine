/* Workflow editor page behaviour. The style preview (init's storage, query and pick handling) is CONCEPT ONLY. */
(function () {
  'use strict';
  function init(root) {
    var storageKey = 'workflow-editor-concept';
    var requested = new URLSearchParams(window.location.search).get('style');
    var remembered;
    try { remembered = sessionStorage.getItem(storageKey); } catch (error) { /* Storage is optional. */ }
    function apply(style) {
      if (!['1', '2', '3'].includes(style)) style = '1';
      root.dataset.workflowEditorStyle = style;
      root.querySelectorAll('[data-style-pick]').forEach(function (button) {
        button.setAttribute('aria-pressed', String(button.dataset.stylePick === style));
      });
      try { sessionStorage.setItem(storageKey, style); } catch (error) { /* Storage is optional. */ }
    }
    apply(requested || remembered || '1');
    function pick(event) {
      var button = event.target.closest('[data-style-pick]');
      if (button && root.contains(button)) {
        apply(button.dataset.stylePick);
        var url = new URL(window.location.href);
        url.searchParams.set('style', button.dataset.stylePick);
        window.history.replaceState(window.history.state, '', url);
      }
    }
    root.addEventListener('click', pick);
    var guide = setUpGuide(root);
    var filter = setUpMaterialFilter(root);
    return function () { root.removeEventListener('click', pick); guide(); filter(); };
  }
  // Guidance sits open beside the form when there is room for it, and closed where it would push the form down.
  function setUpGuide(root) {
    var more = root.querySelector('.process-flow-wizard__more');
    if (!more) return function () {};
    var wide = window.matchMedia('(min-width: 1101px)');
    function sync() { more.open = wide.matches && root.dataset.workflowEditorStyle === '1'; }
    sync();
    root.addEventListener('click', onPick);
    function onPick(event) { if (event.target.closest('[data-style-pick]')) sync(); }
    return function () { root.removeEventListener('click', onPick); };
  }

  // Filter the stock list on the Inputs stage by name as you type.
  function setUpMaterialFilter(root) {
    var list = root.querySelector('#guided-inventory-cards-container');
    if (!list) return function () {};
    var label = document.createElement('label');
    label.className = 'workflow-editor__filter';
    var input = document.createElement('input');
    input.type = 'search';
    input.id = 'workflow-editor-material-filter';
    input.placeholder = 'Search materials';
    input.setAttribute('aria-label', 'Search materials');
    label.appendChild(input);
    var empty = document.createElement('p');
    empty.className = 'workflow-editor__filter-empty';
    empty.hidden = true;
    empty.setAttribute('role', 'status');
    list.parentNode.insertBefore(label, list);
    list.parentNode.insertBefore(empty, list.nextSibling);
    function apply() {
      var query = input.value.trim().toLowerCase();
      var shown = 0;
      Array.prototype.forEach.call(list.children, function (card) {
        var match = !query || card.textContent.toLowerCase().indexOf(query) !== -1;
        card.hidden = !match;
        if (match) shown += 1;
      });
      // A short list is quicker to read than to search.
      label.hidden = !query && list.children.length < 6;
      empty.hidden = !query || shown > 0;
      empty.textContent = 'No materials match \u201c' + input.value.trim() + '\u201d.';
    }
    input.addEventListener('input', apply);
    apply();
    // The list is filled, and refilled when the category changes, after this runs.
    var observer = new MutationObserver(apply);
    observer.observe(list, { childList: true });
    return function () { observer.disconnect(); label.remove(); empty.remove(); };
  }

  if (window.bize && window.bize.onPage) window.bize.onPage('#workflow-editor', init, { key: 'workflow-editor-concepts' });
})();
