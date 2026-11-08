/* Settings categories: one shown at a time, each with its own address so it can be linked to
   and Back returns to it. */
(function () {
  'use strict';
  window.bize.onPage('[data-settings-root]', function (root) {
    const groups = Array.from(root.querySelectorAll('[data-settings-group]'));
    const links = Array.from(root.querySelectorAll('[data-settings-link]'));
    let active = 'account';
    function select(group) {
      active = groups.some(item => item.dataset.settingsGroup === group) ? group : 'account';
      groups.forEach(item => { item.hidden = item.dataset.settingsGroup !== active; });
      links.forEach(link => {
        if (link.dataset.settingsLink === active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });
    }
    function click(event) {
      const link = event.target.closest('[data-settings-link]');
      if (!link) return;
      event.preventDefault();
      select(link.dataset.settingsLink);
      const url = new URL(window.location.href);
      url.hash = 'settings-' + active;
      window.history.pushState(window.history.state, '', url);
    }
    function fromHash() {
      const group = window.location.hash.replace('#settings-', '') || 'account';
      if (groups.some(item => item.dataset.settingsGroup === group)) select(group);
    }
    root.addEventListener('click', click);
    window.addEventListener('popstate', fromHash);
    const hashGroup = window.location.hash.replace('#settings-', '');
    if (groups.some(group => group.dataset.settingsGroup === hashGroup)) active = hashGroup;
    // Two-factor enrolment and the Google return land on the security category.
    const query = new URLSearchParams(window.location.search);
    if (query.has('enroll2fa') || query.has('google')) active = 'security';
    select(active);
    return function () {
      root.removeEventListener('click', click);
      window.removeEventListener('popstate', fromHash);
    };
  });
})();
