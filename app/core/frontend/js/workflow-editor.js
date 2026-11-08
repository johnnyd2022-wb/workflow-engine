/* Workflow editor page behaviour: guidance beside the form, and a search on the Inputs stage. */
(function () {
  'use strict';
  function init(root) {
    var guide = setUpGuide(root);
    var filter = setUpMaterialFilter(root);
    return function () { guide(); filter(); };
  }
  // Guidance sits open beside the form when there is room for it, and closed where it would push the form down.
  function setUpGuide(root) {
    var more = root.querySelector('.process-flow-wizard__more');
    if (!more) return function () {};
    var wide = window.matchMedia('(min-width: 1101px)');
    function sync() { more.open = wide.matches; }
    sync();
    wide.addEventListener('change', sync);
    return function () { wide.removeEventListener('change', sync); };
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
