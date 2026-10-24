// People page (plan 0.4): list people, add by invite link, change roles, deactivate.
// The server enforces every rule (last admin, own role, auditor end dates); this page
// only presents them and shows the server's message when it refuses.
(function () {
  'use strict';

  function $(root, sel) { return root.querySelector(sel); }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  async function api(method, url, body) {
    var headers = { 'Accept': 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET') headers['X-CSRFToken'] = csrfToken();
    var resp = await fetch(url, {
      method: method, credentials: 'include', headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    var data = {};
    try { data = await resp.json(); } catch (_) { /* empty body */ }
    if (!resp.ok) throw new Error(data.error || ('Request failed (' + resp.status + ')'));
    return data;
  }

  function formatDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'className') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.append(c); });
    return n;
  }

  function initials(name) {
    var parts = String(name || '?').replace(/@.*/, '').split(/[\s._-]+/).filter(Boolean);
    return ((parts[0] || '?')[0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
  }

  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  var STATUS_LABELS = { active: 'Active', invited: 'Invited', deactivated: 'Deactivated', expired: 'Access ended' };
  var STATUS_ORDER = { active: 0, invited: 1, expired: 2, deactivated: 3 };
  var AREAS = { production: 'Production', inventory: 'Inventory', sales: 'Sales', compliance: 'Compliance', users: 'People', settings: 'Settings' };

  function init(root) {
    if (!root || root.dataset.peopleBound === '1') return;
    root.dataset.peopleBound = '1';

    var state = { people: [], roles: [], me: null, selected: null };
    var rolesState = null;
    var rows = $(root, '[data-people-rows]');
    var roleList = $(root, '[data-people-role-guide]');
    var message = $(root, '[data-people-message]');
    var panel = $(root, '[data-people-panel]');
    var dialog = document.querySelector('[data-people-dialog]');
    var form = $(dialog, '[data-people-form]');
    var formError = $(dialog, '[data-people-form-error]');
    var roleSelect = $(dialog, '[data-people-role-select]');
    var roleHint = $(dialog, '[data-people-role-hint]');
    var expiryField = $(dialog, '[data-people-expiry-field]');
    var inviteResult = $(dialog, '[data-people-invite-result]');
    var roleDialog = document.querySelector('[data-role-dialog]');
    var roleForm = $(roleDialog, '[data-custom-role-form]');
    var roleError = $(roleDialog, '[data-role-error]');

    function say(text, ok) {
      message.textContent = text;
      message.className = 'pp-message ' + (ok ? 'pp-message--ok' : 'pp-message--error');
      message.hidden = !text;
    }

    function needsExpiry(value) {
      var r = state.roles.find(function (x) { return x.value === value; });
      return !!(r && r.needs_expiry);
    }

    function roleLabel(value) {
      var r = state.roles.find(function (x) { return x.value === value; });
      return r ? r.label : value;
    }

    function fillInviteRoles() {
      roleSelect.replaceChildren();
      state.roles.forEach(function (r) {
        var opt = el('option', { value: r.value, text: r.label });
        opt.disabled = r.assignable === false;
        if (r.value === 'member') { opt.selected = true; opt.setAttribute('selected', ''); }
        roleSelect.append(opt);
      });
      syncRoleHint();
    }

    function syncRoleHint() {
      var r = state.roles.find(function (x) { return x.value === roleSelect.value; });
      roleHint.textContent = r ? r.description : '';
      expiryField.hidden = !needsExpiry(roleSelect.value);
    }

    // --- one person ------------------------------------------------------------------------
    function statusWords(p) {
      var words = STATUS_LABELS[p.status] || p.status;
      if (p.status === 'invited' && p.invite_expires_at) words += ' · link expires ' + formatDate(p.invite_expires_at);
      else if (p.access_expires_at) words += (p.status === 'expired' ? ' · ended ' : ' · until ') + formatDate(p.access_expires_at);
      return words;
    }

    function roleControl(p, isMe) {
      var sel = el('select', { className: 'pp-role-select', 'aria-label': 'Role for ' + p.display_name });
      state.roles.forEach(function (r) {
        var o = el('option', { value: r.value, text: r.label });
        o.disabled = r.assignable === false;
        if (r.value === p.role) o.selected = true;
        sel.append(o);
      });
      sel.disabled = isMe || p.status === 'deactivated';
      if (isMe) sel.title = "You can't change your own role. Ask another admin.";
      sel.addEventListener('change', function () { changeRole(p, sel); });
      return sel;
    }

    function actionButtons(p, isMe) {
      var wrap = el('div', { className: 'pp-actions' });
      function add(text, handler, danger) {
        var b = el('button', { type: 'button', className: 'pp-link' + (danger ? ' pp-link--danger' : ''), text: text });
        b.addEventListener('click', function (event) { event.stopPropagation(); handler(); });
        wrap.append(b);
      }
      if (p.status === 'invited') add('New invite link', function () { reissue(p); });
      if (!isMe && (p.status === 'active' || p.status === 'expired' || p.status === 'invited')) {
        add(p.status === 'invited' ? 'Cancel invite' : 'Deactivate', function () { deactivate(p); }, true);
      }
      if (p.status === 'deactivated') add('Reactivate', function () { reactivate(p); });
      return wrap;
    }

    function personRow(p) {
      var isMe = state.me && p.id === state.me.id;
      var li = el('li', { className: 'pp-person pp-person--' + p.status, 'data-person-id': p.id });
      if (state.selected === p.id) li.classList.add('is-selected');
      var who = el('div', { className: 'pp-who' });
      var name = el('button', { type: 'button', className: 'pp-name', text: p.display_name, 'aria-label': 'Open ' + p.display_name });
      name.addEventListener('click', function () { select(p.id); });
      who.append(name);
      if (isMe) who.append(el('span', { className: 'pp-you', text: 'You' }));
      if (p.display_name !== p.email) who.append(el('span', { className: 'pp-email', text: p.email }));
      var twoFactor = p.status === 'invited' ? '' : (p.two_factor_enabled ? '2FA on' : '2FA off');
      li.append(
        el('span', { className: 'pp-avatar', 'aria-hidden': 'true', text: initials(p.display_name) }),
        who,
        el('span', { className: 'pp-role-text', text: roleLabel(p.role) }),
        el('div', { className: 'pp-role' }, [roleControl(p, isMe)]),
        el('span', { className: 'pp-status pp-status--' + p.status, text: statusWords(p) }),
        el('span', { className: 'pp-2fa' + (p.two_factor_enabled ? '' : ' pp-2fa--off'), text: twoFactor }),
        actionButtons(p, isMe)
      );
      return li;
    }

    function render() {
      rows.replaceChildren();
      if (!state.people.length) {
        rows.append(el('li', { className: 'pp-empty', text: 'No one here yet.' }));
      }
      var sorted = state.people.slice().sort(function (a, b) {
        return (STATUS_ORDER[a.status] || 0) - (STATUS_ORDER[b.status] || 0) || a.display_name.toLowerCase().localeCompare(b.display_name.toLowerCase());
      });
      sorted.forEach(function (p) { rows.append(personRow(p)); });
      var count = function (status) { return state.people.filter(function (p) { return p.status === status; }).length; };
      var parts = [plural(count('active'), 'person can sign in', 'people can sign in')];
      if (count('invited')) parts.push(plural(count('invited'), 'invite waiting', 'invites waiting'));
      if (count('expired')) parts.push(plural(count('expired'), 'auditor finished', 'auditors finished'));
      if (count('deactivated')) parts.push(count('deactivated') + ' deactivated');
      $(root, '[data-people-summary]').textContent = parts.join(' · ');
      renderPanel();
      renderRoles();
    }

    // CONCEPT ONLY: Style 3's panel. The other layouts edit in the row.
    function select(id) {
      state.selected = id;
      rows.querySelectorAll('.pp-person').forEach(function (row) { row.classList.toggle('is-selected', row.dataset.personId === id); });
      renderPanel();
    }

    function renderPanel() {
      var p = state.people.find(function (x) { return x.id === state.selected; });
      panel.hidden = !p;
      if (!p) return;
      var isMe = state.me && p.id === state.me.id;
      $(panel, '[data-panel-name]').textContent = p.display_name + (isMe ? ' (you)' : '');
      $(panel, '[data-panel-email]').textContent = p.email;
      var body = $(panel, '[data-panel-body]');
      var guide = state.roles.find(function (r) { return r.value === p.role; });
      var list = el('dl', { className: 'pp-facts' });
      function fact(term, value) { list.append(el('div', {}, [el('dt', { text: term }), el('dd', {}, [value])])); }
      var roleField = el('div', { className: 'pp-panel-role' }, [roleControl(p, isMe)]);
      if (guide) roleField.append(el('p', { className: 'pp-hint', text: guide.description }));
      fact('Role', roleField);
      fact('Status', el('span', { className: 'pp-status pp-status--' + p.status, text: statusWords(p) }));
      if (p.status !== 'invited') fact('Two-factor sign-in', document.createTextNode(p.two_factor_enabled ? 'On' : 'Off'));
      body.replaceChildren(list, actionButtons(p, isMe));
    }

    // --- roles ---------------------------------------------------------------------------------
    function holders(value) { return state.people.filter(function (p) { return p.role === value && p.status !== 'deactivated'; }).length; }

    function renderRoles() {
      roleList.replaceChildren();
      var customs = (rolesState && rolesState.custom_roles) || [];
      state.roles.forEach(function (r) {
        var custom = customs.find(function (c) { return c.value === r.value; });
        var li = el('li', { className: 'pp-role-row' + (r.custom ? ' pp-role-row--custom' : '') });
        var text = el('div', { className: 'pp-role-what' }, [el('strong', { text: r.label }), el('span', { text: r.description })]);
        if (r.custom && custom) {
          var base = (rolesState.built_in || []).find(function (b) { return b.value === custom.base_role; });
          var bits = ['From ' + (base ? base.label : custom.base_role), plural(custom.permissions.length, 'permission', 'permissions')];
          if (custom.site_access_mode === 'selected') bits.push('selected sites only');
          text.append(el('small', { text: bits.join(' · ') }));
        }
        li.append(text, el('span', { className: 'pp-holders', text: plural(holders(r.value), 'person', 'people') }));
        if (custom) {
          var edit = el('button', { type: 'button', className: 'pp-link', text: 'Edit', 'aria-label': 'Edit ' + r.label });
          edit.addEventListener('click', function () { openRole(custom); });
          li.append(edit);
        } else {
          li.append(el('span', { className: 'pp-builtin', text: 'Built in' }));
        }
        roleList.append(li);
      });
    }

    var loadError = $(root, '[data-people-load-error]');
    function showLoaded(ok, text) {
      root.querySelectorAll('[data-people-loaded]').forEach(function (n) { n.hidden = !ok; });
      loadError.hidden = ok;
      $(root, '[data-people-load-text]').textContent = text || '';
    }

    async function load() {
      root.setAttribute('aria-busy', 'true');
      try {
        var me = await api('GET', '/auth/me');
        state.me = me.user;
        var data = await api('GET', '/org/users');
        state.people = data.users || [];
        state.roles = data.roles || [];
        fillInviteRoles();
        if (state.me && (state.me.permissions || []).indexOf('users.manage') !== -1) {
          try { rolesState = await api('GET', '/org/roles'); } catch (err) { say(err.message, false); }
        }
        render();
        showLoaded(true);
      } catch (err) {
        // Nothing half-loaded stays on screen to act on.
        showLoaded(false, err.message);
      } finally {
        root.setAttribute('aria-busy', 'false');
      }
    }

    function replacePerson(updated) {
      state.people = state.people.map(function (x) { return x.id === updated.id ? updated : x; });
      render();
    }

    // Switching someone to Auditor needs an end date; ask for it in a small dialog
    // (window.prompt doesn't work everywhere and can't show a date picker).
    function askExpiry(p) {
      return new Promise(function (resolve) {
        var dlg = document.querySelector('[data-people-expiry-dialog]');
        var input = dlg.querySelector('input[type="date"]');
        dlg.querySelector('[data-people-expiry-name]').textContent = p.display_name;
        input.value = '';
        var finish = function (value) { dlg.close(); resolve(value); };
        dlg.querySelector('[data-people-expiry-ok]').onclick = function () { finish(input.value || null); };
        dlg.querySelector('[data-people-expiry-cancel]').onclick = function () { finish(null); };
        dlg.showModal();
        setTimeout(function () { input.focus(); }, 0);
      });
    }

    async function changeRole(p, sel) {
      var body = { role: sel.value };
      if (needsExpiry(sel.value)) {
        var until = await askExpiry(p);
        if (!until) { sel.value = p.role; return; }
        body.access_expires_at = until;
      }
      try {
        var data = await api('PATCH', '/org/users/' + p.id, body);
        replacePerson(data.user);
        say(p.display_name + ' is now ' + roleLabel(data.user.role) + '.', true);
      } catch (err) {
        sel.value = p.role;
        say(err.message, false);
      }
    }

    async function deactivate(p) {
      try {
        await api('DELETE', '/org/users/' + p.id);
        await load();
        say(p.status === 'invited' ? 'Invite cancelled for ' + p.email + '.' : p.display_name + " can't sign in any more.", true);
      } catch (err) { say(err.message, false); }
    }

    async function reactivate(p) {
      try {
        var data = await api('PATCH', '/org/users/' + p.id, { is_active: true });
        replacePerson(data.user);
        say(p.display_name + ' can sign in again.', true);
      } catch (err) { say(err.message, false); }
    }

    function showInvite(email, url) {
      form.hidden = true;
      inviteResult.hidden = false;
      $(dialog, '[data-people-invite-email]').textContent = email;
      $(dialog, '[data-people-invite-url]').value = url;
      if (!dialog.open) dialog.showModal();
    }

    async function reissue(p) {
      try {
        var data = await api('POST', '/org/users/' + p.id + '/invite');
        replacePerson(data.user);
        showInvite(p.email, data.invite_url);
      } catch (err) { say(err.message, false); }
    }

    function openAdd() {
      form.reset();
      form.hidden = false;
      inviteResult.hidden = true;
      formError.hidden = true;
      syncRoleHint();
      dialog.showModal();
      setTimeout(function () { $(dialog, '#people-email').focus(); }, 0);
    }

    roleSelect.addEventListener('change', syncRoleHint);
    $(root, '[data-people-add]').addEventListener('click', openAdd);
    $(root, '[data-people-retry]').addEventListener('click', load);
    $(dialog, '[data-people-cancel]').addEventListener('click', function () { dialog.close(); });
    $(dialog, '[data-people-done]').addEventListener('click', function () { dialog.close(); });
    $(dialog, '[data-people-copy]').addEventListener('click', function () {
      var input = $(dialog, '[data-people-invite-url]');
      input.select();
      var btn = this;
      var done = function () { btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = 'Copy'; }, 1500); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value).then(done, function () { document.execCommand && document.execCommand('copy'); done(); });
      } else { document.execCommand && document.execCommand('copy'); done(); }
    });

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      formError.hidden = true;
      var fd = new FormData(form);
      var body = {
        email: (fd.get('email') || '').trim(),
        first_name: (fd.get('first_name') || '').trim(),
        last_name: (fd.get('last_name') || '').trim(),
        role: fd.get('role')
      };
      if (needsExpiry(body.role)) body.access_expires_at = fd.get('access_expires_at') || '';
      if (!body.email) { formError.textContent = 'Enter their email address.'; formError.hidden = false; return; }
      try {
        var data = await api('POST', '/org/users', body);
        state.people.push(data.user);
        render();
        showInvite(data.user.email, data.invite_url);
        say('Invite created for ' + data.user.email + '.', true);
      } catch (err) {
        formError.textContent = err.message;
        formError.hidden = false;
      }
    });

    // --- custom roles (plan 0.4c), in one dialog for new and existing ----------------------------
    var editing = null;

    async function refreshAfterRoleChange(data) {
      rolesState = data;
      var users = await api('GET', '/org/users');
      state.people = users.users || [];
      state.roles = users.roles || [];
      fillInviteRoles();
      render();
    }

    // Grouped by area in plain words; admin-only permissions are shown, greyed, so it is clear
    // why a custom role can't have them.
    function permissionBoxes(selected) {
      var box = el('fieldset', { className: 'pp-perms' }, [el('legend', { text: 'What it can do' })]);
      var groups = {};
      rolesState.permissions.forEach(function (p) {
        var area = p.key.split('.')[0];
        (groups[area] = groups[area] || []).push(p);
      });
      Object.keys(groups).forEach(function (area) {
        var group = el('div', { className: 'pp-perm-group' }, [el('p', { className: 'pp-perm-area', text: AREAS[area] || area })]);
        groups[area].forEach(function (p) {
          var input = el('input', { type: 'checkbox', value: p.key });
          input.checked = selected.indexOf(p.key) !== -1;
          if (!p.grantable) { input.disabled = true; input.checked = false; }
          group.append(el('label', { className: 'pp-perm' + (p.grantable ? '' : ' pp-perm--admin') }, [
            input, el('span', { text: p.description + (p.grantable ? '' : ' (admins only)') })
          ]));
        });
        box.append(group);
      });
      return box;
    }

    function ticked(box) {
      return Array.prototype.filter.call(box.querySelectorAll('input[type="checkbox"]'), function (i) { return i.checked; })
        .map(function (i) { return i.value; });
    }

    function siteScopeFields(role) {
      var fs = el('fieldset', { className: 'pp-sites' });
      fs.append(el('legend', { text: 'Site access' }));
      var mode = el('select', { 'aria-label': 'Site access', id: 'pp-role-sites' });
      mode.append(el('option', { value: 'all', text: 'All sites' }), el('option', { value: 'selected', text: 'Selected sites' }));
      mode.value = role.site_access_mode || 'all';
      var choices = el('div', { className: 'pp-site-choices' });
      (rolesState.sites || []).forEach(function (site) {
        var input = el('input', { type: 'checkbox', value: site.id });
        input.checked = (role.site_ids || []).indexOf(site.id) !== -1;
        input.disabled = !site.is_active && !input.checked;
        choices.append(el('label', { className: 'pp-perm' }, [input, el('span', { text: site.name + (site.is_active ? '' : ' (inactive)') })]));
      });
      function sync() { choices.hidden = mode.value !== 'selected'; }
      mode.onchange = sync; sync();
      fs.append(mode, choices, el('p', { className: 'pp-hint', text: 'A selected-sites role can be prepared now but not given to anyone yet. No sites ticked means no access.' }));
      fs.scopeValue = function () { return { site_access_mode: mode.value, site_ids: mode.value === 'selected' ? ticked(choices) : [] }; };
      return fs;
    }

    function openRole(custom) {
      if (!rolesState) return;
      editing = custom || null;
      roleForm.reset();
      roleError.hidden = true;
      $(roleDialog, '[data-role-title]').textContent = custom ? 'Edit ' + custom.name : 'New role';
      $(roleDialog, '[data-role-submit]').textContent = custom ? 'Save role' : 'Create role';
      $(roleDialog, '[data-role-base-field]').hidden = Boolean(custom);
      var del = $(roleDialog, '[data-role-delete]');
      del.hidden = !custom;
      del.dataset.armed = '';
      del.textContent = 'Delete role';
      del.disabled = Boolean(custom && custom.holders > 0);
      del.title = custom && custom.holders > 0 ? 'Give its people another role first' : '';
      var base = $(roleDialog, '[data-custom-role-base]');
      if (!base.options.length) {
        rolesState.built_in.filter(function (b) { return b.can_clone; }).forEach(function (b) { base.append(el('option', { value: b.value, text: b.label })); });
      }
      base.value = custom ? custom.base_role : 'production';
      roleForm.name.value = custom ? custom.name : '';
      roleForm.description.value = custom ? (custom.description || '') : '';
      var slot = $(roleDialog, '[data-custom-role-perms]');
      function reseed() {
        var b = rolesState.built_in.find(function (x) { return x.value === base.value; });
        slot.replaceChildren(permissionBoxes(b ? b.clone_permissions : []));
      }
      base.onchange = reseed;
      if (custom) slot.replaceChildren(permissionBoxes(custom.permissions)); else reseed();
      $(roleDialog, '[data-custom-role-sites]').replaceChildren(siteScopeFields(custom || {}));
      roleDialog.showModal();
      setTimeout(function () { roleForm.name.focus(); }, 0);
    }

    $(root, '[data-role-new]').addEventListener('click', function () { openRole(null); });
    $(roleDialog, '[data-role-cancel]').addEventListener('click', function () { roleDialog.close(); });
    // Deleting asks twice in place, rather than through window.confirm.
    $(roleDialog, '[data-role-delete]').addEventListener('click', async function () {
      var btn = this;
      if (!editing) return;
      if (btn.dataset.armed !== '1') { btn.dataset.armed = '1'; btn.textContent = 'Delete ' + editing.name + '?'; return; }
      try {
        await refreshAfterRoleChange(await api('DELETE', '/org/roles/' + editing.id));
        say(editing.name + ' deleted.', true);
        roleDialog.close();
      } catch (err) { roleError.textContent = err.message; roleError.hidden = false; }
    });
    roleForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      roleError.hidden = true;
      var scope = $(roleDialog, '[data-custom-role-sites] fieldset').scopeValue();
      var body = Object.assign({
        name: roleForm.name.value,
        description: roleForm.description.value,
        permissions: ticked($(roleDialog, '[data-custom-role-perms] .pp-perms'))
      }, scope);
      try {
        if (editing) {
          await refreshAfterRoleChange(await api('PATCH', '/org/roles/' + editing.id, body));
          say(body.name + ' saved. Everyone with it has the new permissions.', true);
        } else {
          body.base_role = roleForm.base_role.value;
          await refreshAfterRoleChange(await api('POST', '/org/roles', body));
          say(body.name + ' created.', true);
        }
        roleDialog.close();
      } catch (err) { roleError.textContent = err.message; roleError.hidden = false; }
    });

    // --- layout switch (CONCEPT ONLY: deleted with the two layouts not picked) ----------------
    function setStyle(style) {
      root.dataset.ppStyle = style;
      root.querySelectorAll('[data-pp-style-pick]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.ppStylePick === style)); });
      try { window.localStorage.setItem('people-style', style); } catch (_) { /* a convenience only */ }
    }
    function setView(view) {
      root.dataset.ppView = view;
      root.querySelectorAll('[data-pp-view]').forEach(function (a) {
        if (a.dataset.ppView === view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
      });
    }
    root.querySelectorAll('[data-pp-style-pick]').forEach(function (b) { b.addEventListener('click', function () { setStyle(b.dataset.ppStylePick); }); });
    root.querySelectorAll('[data-pp-view]').forEach(function (a) {
      a.addEventListener('click', function (event) { event.preventDefault(); setView(a.dataset.ppView); history.replaceState(null, '', '#' + a.dataset.ppView); });
    });
    $(panel, '[data-panel-close]').addEventListener('click', function () { select(null); });
    (function () {
      var wanted = new URLSearchParams(window.location.search).get('style');
      var kept = null;
      try { kept = window.localStorage.getItem('people-style'); } catch (_) { /* storage blocked */ }
      setStyle(['1', '2', '3'].includes(wanted) ? wanted : (['1', '2', '3'].includes(kept) ? kept : '1'));
      setView(window.location.hash === '#roles' ? 'roles' : 'people');
    })();

    load();
  }

  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-people-root]', init);
})();
