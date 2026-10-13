/* CONCEPT ONLY: style preview; remove when a design is selected. */
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
    return function () { root.removeEventListener('click', pick); };
  }
  if (window.bize && window.bize.onPage) window.bize.onPage('#workflow-editor', init, { key: 'workflow-editor-concepts' });
})();
