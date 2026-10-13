/* Page-local navigation and CONCEPT ONLY preview selection. */
(function () {
  'use strict';
  window.bize.onPage('[data-settings-style]', function (root) {
    const groups = Array.from(root.querySelectorAll('[data-settings-group]'));
    const links = Array.from(root.querySelectorAll('[data-settings-link]'));
    let active = 'account';
    let style = '1';
    function select(group, scroll) {
      active = groups.some(item => item.dataset.settingsGroup === group) ? group : 'account';
      groups.forEach(item => {
        item.hidden = style === '2' && item.dataset.settingsGroup !== active;
        if (style !== '3' || item.dataset.settingsGroup === active) item.open = true;
      });
      links.forEach(link => {
        if (link.dataset.settingsLink === active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });
      if (scroll && style !== '2') {
        root.querySelector('[data-settings-group="' + active + '"]').scrollIntoView({block: 'start'});
      }
    }
    // CONCEPT ONLY — fold the winning layout into the base rules after selection.
    function setStyle(value) {
      style = ['1', '2', '3'].includes(value) ? value : '1';
      root.dataset.settingsStyle = style;
      try { sessionStorage.setItem('settings-design-style', style); } catch (_) {}
      root.querySelectorAll('[data-style-pick]').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.stylePick === style));
      });
      groups.forEach(item => {
        item.open = style !== '3' || item.dataset.settingsGroup === active;

      });
      select(active, false);
    }
    function click(event) {
      const pick = event.target.closest('[data-style-pick]');
      if (pick) { setStyle(pick.dataset.stylePick); return; }
      const link = event.target.closest('[data-settings-link]');
      if (link) {
        event.preventDefault();
        select(link.dataset.settingsLink, true);
        // Each category has its own address, so it can be linked to and Back returns to it.
        const url = new URL(window.location.href);
        url.hash = 'settings-' + active;
        window.history.pushState(window.history.state, '', url);
      }
    }
    function fromHash() {
      const group = window.location.hash.replace('#settings-', '') || 'account';
      if (groups.some(item => item.dataset.settingsGroup === group)) select(group, false);
    }
    function toggle(event) {
      if (style !== '3' && !event.target.open) event.target.open = true;
    }
    root.addEventListener('click', click);
    window.addEventListener('popstate', fromHash);
    groups.forEach(group => group.addEventListener('toggle', toggle));
    let remembered;
    try { remembered = sessionStorage.getItem('settings-design-style'); } catch (_) {}
    const query = new URLSearchParams(window.location.search);
    const hashGroup = window.location.hash.replace('#settings-', '');
    if (groups.some(group => group.dataset.settingsGroup === hashGroup)) active = hashGroup;
    if (query.has('enroll2fa') || query.has('google')) active = 'security';
    setStyle(query.get('style') || remembered || '1');
    return function () {
      root.removeEventListener('click', click);
      window.removeEventListener('popstate', fromHash);
      groups.forEach(group => group.removeEventListener('toggle', toggle));
    };
  });
})();
