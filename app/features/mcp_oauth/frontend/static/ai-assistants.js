/* Settings -> AI assistants (public MCP 8.2e). Binds to its page root on every arrival.
   Every string that came from somebody else (a client's chosen name, a person's name, a role name)
   is written with textContent: a client picks its own name when it registers. */
(function () {
  'use strict';
  var SETTINGS = '/api/core/mcp/settings';
  var GRANTS = '/api/core/mcp/grants';

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function call(method, url, body) {
    var token = document.querySelector('meta[name="csrf-token"]');
    var headers = { Accept: 'application/json' };
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRFToken'] = token ? token.content : '';
    }
    return fetch(url, { method: method, credentials: 'same-origin', headers: headers, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (!r.ok) { var e = new Error(d.error || 'Something went wrong'); e.status = r.status; throw e; }
          return d;
        });
      });
  }

  function day(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function bind() {
    var root = document.querySelector('[data-ai-root]');
    if (!root || root.getAttribute('data-bound') === '1') return;
    root.setAttribute('data-bound', '1');
    var canManage = root.getAttribute('data-can-manage') === 'true';
    var myId = root.getAttribute('data-user-id');
    var q = function (sel) { return root.querySelector(sel); };
    var els = {
      sw: q('[data-ai-switch]'), unverified: q('[data-ai-unverified]'), unverifiedBox: q('[data-ai-unverified-box]'),
      unverifiedDialog: q('[data-ai-unverified-dialog]'), unverifiedForm: q('[data-ai-unverified-form]'),
      unverifiedCancel: q('[data-ai-unverified-cancel]'),
      rolesBox: q('[data-ai-roles]'), rolesList: q('[data-ai-roles-list]'),
      rolesHint: q('[data-ai-roles-hint]'), save: q('[data-ai-save]'), status: q('[data-ai-status]'),
      settingsError: q('[data-ai-settings-error]'),
      url: q('[data-ai-url]'), copy: q('[data-ai-copy]'),
      loading: q('[data-ai-loading]'), grantsError: q('[data-ai-grants-error]'), grantsErrorText: q('[data-ai-grants-error-text]'),
      retry: q('[data-ai-retry]'), list: q('[data-ai-grants]'), empty: q('[data-ai-empty]'), title: q('[data-ai-grants-title]'),
      dialog: q('[data-ai-dialog]'), dialogForm: q('[data-ai-dialog-form]'), dialogName: q('[data-ai-dialog-name]'),
      dialogPerson: q('[data-ai-dialog-person]'), dialogError: q('[data-ai-dialog-error]'),
      cancel: q('[data-ai-dialog-cancel]'), confirm: q('[data-ai-dialog-confirm]')
    };
    var saved = { enabled: false, roles: [], unverified: false };
    var roleChoices = [];
    var grants = [];
    var revoking = null;
    var opener = null;
    var busy = false;

    function done() { root.setAttribute('aria-busy', 'false'); }

    /* ---- the switch and the roles (users.manage only; the markup is not there for anyone else) ---- */
    function ticked() {
      return Array.prototype.filter.call(els.rolesList.querySelectorAll('input[type=checkbox]'), function (c) { return c.checked; })
        .map(function (c) { return c.value; }).sort();
    }

    function sameRoles(a, b) { return a.length === b.length && a.every(function (k, i) { return k === b[i]; }); }

    function syncSettings() {
      var on = els.sw.checked;
      Array.prototype.forEach.call(els.rolesList.querySelectorAll('input[type=checkbox]'), function (c) { c.disabled = !on || busy; });
      els.rolesBox.classList.toggle('is-off', !on);
      els.rolesHint.hidden = !(on && ticked().length === 0);
      els.unverified.disabled = !on || busy;
      els.unverifiedBox.classList.toggle('is-off', !on);
      var dirty = els.sw.checked !== saved.enabled || !sameRoles(ticked(), saved.roles) ||
        els.unverified.checked !== saved.unverified;
      els.save.disabled = !dirty || busy;
    }

    function roleRow(role) {
      var label = el('label', 'ai-role');
      var box = el('input');
      box.type = 'checkbox';
      box.value = role.key;
      box.checked = saved.roles.indexOf(role.key) !== -1;
      label.appendChild(box);
      label.appendChild(el('span', 'ai-role__name', role.label));
      return label;
    }

    function renderRoles() {
      els.rolesList.replaceChildren();
      var builtin = roleChoices.filter(function (r) { return !r.custom; });
      var custom = roleChoices.filter(function (r) { return r.custom; });
      builtin.forEach(function (r) { els.rolesList.appendChild(roleRow(r)); });
      if (custom.length) {
        els.rolesList.appendChild(el('p', 'ai-roles__group', 'Custom roles'));
        custom.forEach(function (r) { els.rolesList.appendChild(roleRow(r)); });
      }
    }

    function applySettings(data) {
      saved = {
        enabled: !!data.enabled, roles: (data.allowed_roles || []).slice().sort(),
        unverified: !!data.allow_unverified_clients
      };
      roleChoices = data.roles || [];
      els.sw.checked = saved.enabled;
      els.unverified.checked = saved.unverified;
      els.sw.disabled = false;
      renderRoles();
      syncSettings();
    }

    function loadSettings() {
      return call('GET', SETTINGS).then(applySettings).catch(function (err) {
        els.settingsError.textContent = "Couldn't load the settings. " + err.message;
        els.settingsError.hidden = false;
      });
    }

    function saveSettings() {
      busy = true;
      els.settingsError.hidden = true;
      els.status.textContent = '';
      syncSettings();
      els.save.textContent = 'Saving…';
      call('PUT', SETTINGS, {
        enabled: els.sw.checked, allowed_roles: ticked(), allow_unverified_clients: els.unverified.checked
      })
        .then(function (data) {
          busy = false;
          applySettings(data);
          els.status.textContent = 'Saved';
        })
        .catch(function (err) {
          busy = false;
          els.settingsError.textContent = err.message;
          els.settingsError.hidden = false;
          syncSettings();
        })
        .then(function () { els.save.textContent = 'Save changes'; });
    }

    /* ---- connected apps ---- */
    function personLine(grant) {
      var u = grant.user || {};
      if (u.id === myId) return 'You';
      return u.name ? u.name + ' · ' + u.email : (u.email || '');
    }

    function grantRow(grant) {
      var li = el('li', 'ai-grant');
      li.setAttribute('data-grant-id', grant.id);
      var main = el('div', 'ai-grant__main');
      var head = el('div', 'ai-grant__head');
      head.appendChild(el('span', 'ai-grant__name', grant.client_name));
      if (!grant.verified) head.appendChild(el('span', 'ai-badge', 'Unverified app'));
      main.appendChild(head);
      var meta = el('div', 'ai-grant__meta');
      if (canManage) meta.appendChild(el('span', 'ai-grant__person', personLine(grant)));
      meta.appendChild(el('span', '', 'Connected ' + day(grant.created_at)));
      meta.appendChild(el('span', '', grant.last_used_at ? 'Last used ' + day(grant.last_used_at) : 'Never used'));
      main.appendChild(meta);
      li.appendChild(main);
      var button = el('button', 'workspace-button ai-revoke', 'Revoke');
      button.type = 'button';
      button.setAttribute('aria-label', 'Revoke ' + grant.client_name);
      button.addEventListener('click', function () { openRevoke(grant, button); });
      li.appendChild(button);
      return li;
    }

    function renderGrants() {
      els.list.replaceChildren();
      grants.forEach(function (g) { els.list.appendChild(grantRow(g)); });
      els.empty.hidden = grants.length !== 0;
    }

    function loadGrants() {
      els.loading.hidden = false;
      els.grantsError.hidden = true;
      els.empty.hidden = true;
      return call('GET', GRANTS).then(function (data) {
        grants = data.grants || [];
        els.loading.hidden = true;
        renderGrants();
      }).catch(function (err) {
        els.loading.hidden = true;
        els.grantsErrorText.textContent = "Couldn't load connected apps. " + err.message;
        els.grantsError.hidden = false;
      });
    }

    /* ---- revoke, asked in a bottom sheet ---- */
    function openRevoke(grant, trigger) {
      revoking = grant;
      opener = trigger;
      els.dialogName.textContent = grant.client_name;
      var who = canManage && (grant.user || {}).id !== myId ? 'Connected by ' + personLine(grant) + '.' : '';
      els.dialogPerson.textContent = who;
      els.dialogPerson.hidden = !who;
      els.dialogError.hidden = true;
      els.confirm.disabled = false;
      els.confirm.textContent = 'Revoke access';
      els.dialog.showModal();
      els.cancel.focus();
    }

    function closeSheet() {
      if (els.dialog.open) els.dialog.close();
    }

    function confirmRevoke(event) {
      event.preventDefault();
      if (!revoking) return;
      var grant = revoking;
      els.confirm.disabled = true;
      els.confirm.textContent = 'Revoking…';
      els.dialogError.hidden = true;
      call('POST', GRANTS + '/' + encodeURIComponent(grant.id) + '/revoke', {})
        .then(gone, function (err) {
          // 404 is "already gone" (someone revoked it, or it was never yours): the list is the truth.
          if (err.status === 404) return gone();
          els.dialogError.textContent = err.message;
          els.dialogError.hidden = false;
          els.confirm.disabled = false;
          els.confirm.textContent = 'Revoke access';
        });
      function gone() {
        grants = grants.filter(function (g) { return g.id !== grant.id; });
        revoking = null;
        opener = null;
        closeSheet();
        renderGrants();
        els.title.focus();
      }
    }

    els.dialog.addEventListener('close', function () {
      revoking = null;
      if (opener && opener.isConnected) opener.focus();
      opener = null;
    });
    // A tap on the dimmed area outside the sheet cancels it.
    els.dialog.addEventListener('click', function (event) {
      var r = els.dialog.getBoundingClientRect();
      var outside = event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom;
      if (outside) closeSheet();
    });
    els.cancel.addEventListener('click', closeSheet);
    els.dialogForm.addEventListener('submit', confirmRevoke);
    els.retry.addEventListener('click', loadGrants);

    /* ---- how to connect ---- */
    function flashCopied() {
      els.copy.textContent = 'Copied';
      window.setTimeout(function () { els.copy.textContent = 'Copy'; }, 2000);
    }
    els.copy.addEventListener('click', function () {
      var text = els.url.value;
      els.url.select();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(flashCopied, function () {
          if (document.execCommand && document.execCommand('copy')) flashCopied();
        });
      } else if (document.execCommand && document.execCommand('copy')) {
        flashCopied();
      }
    });
    els.url.addEventListener('focus', function () { els.url.select(); });

    if (canManage) {
      els.sw.addEventListener('change', function () { els.status.textContent = ''; syncSettings(); });
      els.rolesList.addEventListener('change', function () { els.status.textContent = ''; syncSettings(); });
      els.save.addEventListener('click', saveSettings);

      /* Turning unverified apps on is asked in a bottom sheet; turning it off is not. */
      var unverifiedConfirmed = false;
      els.unverified.addEventListener('change', function () {
        els.status.textContent = '';
        if (els.unverified.checked) {
          unverifiedConfirmed = false;
          els.unverifiedDialog.showModal();
          els.unverifiedCancel.focus();
        }
        syncSettings();
      });
      els.unverifiedForm.addEventListener('submit', function (event) {
        event.preventDefault();
        unverifiedConfirmed = true;
        els.unverifiedDialog.close();
      });
      els.unverifiedCancel.addEventListener('click', function () { els.unverifiedDialog.close(); });
      els.unverifiedDialog.addEventListener('click', function (event) {
        // Only a click on the backdrop itself (a keyboard "click" on a button reports 0,0).
        if (event.target !== els.unverifiedDialog) return;
        var r = els.unverifiedDialog.getBoundingClientRect();
        var outside = event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom;
        if (outside) els.unverifiedDialog.close();
      });
      // Cancel, Escape or a tap outside all leave it off.
      els.unverifiedDialog.addEventListener('close', function () {
        if (!unverifiedConfirmed) els.unverified.checked = false;
        syncSettings();
        els.unverified.focus();
      });
    }

    var work = [loadGrants()];
    if (canManage) work.push(loadSettings());
    Promise.all(work).then(done, done);
  }

  bind();
  if (!window.__aiAssistantsListener) {
    window.__aiAssistantsListener = true;
    document.addEventListener('htmx:afterSettle', bind);
  }
})();
