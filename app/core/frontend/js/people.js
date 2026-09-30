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

  var STATUS_LABELS = { active: 'Active', invited: 'Invited', deactivated: 'Deactivated', expired: 'Access ended' };

  function init(root) {
    if (!root || root.dataset.peopleBound === '1') return;
    root.dataset.peopleBound = '1';

    var state = { people: [], roles: [], me: null };
    var rows = $(root, '[data-people-rows]');
    var message = $(root, '[data-people-message]');
    var dialog = document.querySelector('[data-people-dialog]');
    var form = $(dialog, '[data-people-form]');
    var formError = $(dialog, '[data-people-form-error]');
    var roleSelect = $(dialog, '[data-people-role-select]');
    var roleHint = $(dialog, '[data-people-role-hint]');
    var expiryField = $(dialog, '[data-people-expiry-field]');
    var inviteResult = $(dialog, '[data-people-invite-result]');

    function say(text, ok) {
      message.textContent = text;
      message.className = 'people-message ' + (ok ? 'people-message--ok' : 'people-message--error');
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

    function renderRoleGuide() {
      var dl = $(root, '[data-people-role-guide]');
      dl.replaceChildren();
      state.roles.forEach(function (r) {
        var dt = document.createElement('dt'); dt.textContent = r.label;
        var dd = document.createElement('dd'); dd.textContent = r.description;
        dl.append(dt, dd);
      });
      roleSelect.replaceChildren();
      state.roles.forEach(function (r) {
        var opt = document.createElement('option');
        opt.value = r.value; opt.textContent = r.label; opt.disabled = r.assignable === false;
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

    function statusCell(p) {
      var td = document.createElement('td');
      var pill = document.createElement('span');
      pill.className = 'people-status people-status--' + p.status;
      pill.textContent = STATUS_LABELS[p.status] || p.status;
      td.append(pill);
      var meta = '';
      if (p.status === 'invited' && p.invite_expires_at) meta = 'Link expires ' + formatDate(p.invite_expires_at);
      else if (p.access_expires_at) meta = (p.status === 'expired' ? 'Ended ' : 'Until ') + formatDate(p.access_expires_at);
      if (meta) { var m = document.createElement('div'); m.className = 'people-meta'; m.textContent = meta; td.append(m); }
      return td;
    }

    function actionButton(text, handler, danger) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'people-link-btn' + (danger ? ' people-link-btn--danger' : '');
      b.textContent = text;
      b.addEventListener('click', handler);
      return b;
    }

    function render() {
      rows.replaceChildren();
      if (!state.people.length) {
        var tr0 = document.createElement('tr'); var td0 = document.createElement('td');
        td0.colSpan = 5; td0.textContent = 'No one here yet.'; tr0.append(td0); rows.append(tr0);
        return;
      }
      state.people.forEach(function (p) {
        var isMe = state.me && p.id === state.me.id;
        var tr = document.createElement('tr');

        var who = document.createElement('td');
        var name = document.createElement('div'); name.className = 'people-name'; name.textContent = p.display_name;
        if (isMe) { var you = document.createElement('span'); you.className = 'people-you'; you.textContent = '(you)'; name.append(you); }
        var email = document.createElement('div'); email.className = 'people-email'; email.textContent = p.email;
        who.append(name); if (p.display_name !== p.email) who.append(email);

        var roleTd = document.createElement('td');
        var sel = document.createElement('select');
        sel.className = 'people-role-select';
        sel.setAttribute('aria-label', 'Role for ' + p.display_name);
        state.roles.forEach(function (r) {
          var o = document.createElement('option'); o.value = r.value; o.textContent = r.label; o.disabled = r.assignable === false;
          if (r.value === p.role) o.selected = true;
          sel.append(o);
        });
        sel.disabled = isMe || p.status === 'deactivated';
        if (isMe) sel.title = "You can't change your own role. Ask another admin.";
        sel.addEventListener('change', function () { changeRole(p, sel); });
        roleTd.append(sel);

        var tfa = document.createElement('td');
        tfa.textContent = p.status === 'invited' ? '—' : (p.two_factor_enabled ? 'On' : 'Off');

        var actions = document.createElement('td');
        var wrap = document.createElement('div'); wrap.className = 'people-actions';
        if (p.status === 'invited') wrap.append(actionButton('New invite link', function () { reissue(p); }));
        if (!isMe && (p.status === 'active' || p.status === 'expired' || p.status === 'invited')) {
          wrap.append(actionButton(p.status === 'invited' ? 'Cancel invite' : 'Deactivate', function () { deactivate(p); }, true));
        }
        if (p.status === 'deactivated') wrap.append(actionButton('Reactivate', function () { reactivate(p); }));
        actions.append(wrap);

        tr.append(who, roleTd, statusCell(p), tfa, actions);
        rows.append(tr);
      });
    }

    async function load() {
      try {
        var me = await api('GET', '/auth/me');
        state.me = me.user;
        var data = await api('GET', '/org/users');
        state.people = data.users || [];
        state.roles = data.roles || [];
        renderRoleGuide();
        render();
        loadCustomRoles();
      } catch (err) {
        rows.replaceChildren();
        say(err.message, false);
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
        state.people.sort(function (a, b) { return a.display_name.toLowerCase().localeCompare(b.display_name.toLowerCase()); });
        render();
        showInvite(data.user.email, data.invite_url);
        say('Invite created for ' + data.user.email + '.', true);
      } catch (err) {
        formError.textContent = err.message;
        formError.hidden = false;
      }
    });

    // --- custom roles (plan 0.4c) ------------------------------------------------------
    var rolesRoot = $(root, '[data-custom-roles]');
    var rolesState = null;

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

    async function loadCustomRoles() {
      if (!rolesRoot || !state.me || (state.me.permissions || []).indexOf('users.manage') === -1) return;
      try { renderCustomRoles(await api('GET', '/org/roles')); } catch (err) { say(err.message, false); }
    }

    async function refreshAfterRoleChange(data) {
      renderCustomRoles(data);
      var users = await api('GET', '/org/users');
      state.people = users.users || [];
      state.roles = users.roles || [];
      renderRoleGuide();
      render();
    }

    function permissionBoxes(selected) {
      var box = el('div', { className: 'people-perms' });
      rolesState.permissions.forEach(function (p) {
        var input = el('input', { type: 'checkbox', value: p.key });
        input.checked = selected.indexOf(p.key) !== -1;
        if (!p.grantable) { input.disabled = true; input.checked = false; }
        box.append(el('label', { className: 'people-perm' + (p.grantable ? '' : ' people-perm--admin') }, [
          input, el('span', {}, [el('strong', { text: p.key }), document.createTextNode(' ' + p.description + (p.grantable ? '' : ' (admins only)'))])
        ]));
      });
      return box;
    }

    function ticked(box) {
      return Array.prototype.filter.call(box.querySelectorAll('input[type="checkbox"]'), function (i) { return i.checked; })
        .map(function (i) { return i.value; });
    }

    function siteScopeFields(role) {
      var root = el('fieldset');
      root.append(el('legend', { text: 'Site access' }));
      var mode = el('select', { 'aria-label': 'Site access' });
      mode.append(el('option', { value: 'all', text: 'All sites' }), el('option', { value: 'selected', text: 'Selected sites' }));
      mode.value = role.site_access_mode || 'all';
      var choices = el('div');
      (rolesState.sites || []).forEach(function (site) {
        var input = el('input', { type: 'checkbox', value: site.id });
        input.checked = (role.site_ids || []).indexOf(site.id) !== -1;
        input.disabled = !site.is_active && !input.checked;
        choices.append(el('label', {}, [input, document.createTextNode(' ' + site.name + (site.is_active ? '' : ' (inactive)'))]));
      });
      function sync() { choices.hidden = mode.value !== 'selected'; }
      mode.onchange = sync; sync();
      root.append(mode, choices, el('p', { className: 'people-hint', text: 'Selected-site roles can be prepared now. They cannot be assigned to people yet. No selected sites means no access.' }));
      root.scopeValue = function () { return { site_access_mode: mode.value, site_ids: mode.value === 'selected' ? ticked(choices) : [] }; };
      return root;
    }

    function renderCustomRoles(data) {
      rolesState = data;
      rolesRoot.hidden = false;
      var list = $(rolesRoot, '[data-custom-role-list]');
      list.replaceChildren();
      if (!data.custom_roles.length) list.append(el('p', { className: 'people-hint', text: 'No custom roles yet.' }));
      data.custom_roles.forEach(function (r) {
        var base = data.built_in.find(function (b) { return b.value === r.base_role; });
        var details = el('details', { className: 'people-custom-role' });
        details.append(el('summary', {}, [el('strong', { text: r.name }),
          document.createTextNode(' · from ' + (base ? base.label : r.base_role) + ' · ' + r.permissions.length + ' permissions · ' + r.holders + (r.holders === 1 ? ' person' : ' people'))]));
        var name = el('input', { value: r.name, maxlength: '100', 'aria-label': 'Role name' });
        var boxes = permissionBoxes(r.permissions);
        var sites = siteScopeFields(r);
        var save = el('button', { type: 'button', className: 'btn btn-primary', text: 'Save' });
        save.addEventListener('click', async function () {
          try { await refreshAfterRoleChange(await api('PATCH', '/org/roles/' + r.id, Object.assign({ name: name.value, permissions: ticked(boxes) }, sites.scopeValue()))); say(name.value + ' saved. Everyone with it has the new permissions.', true); }
          catch (err) { say(err.message, false); }
        });
        var del = el('button', { type: 'button', className: 'btn btn-secondary', text: 'Delete' });
        del.disabled = r.holders > 0;
        if (r.holders > 0) del.title = 'Give its people another role first';
        del.addEventListener('click', async function () {
          if (!window.confirm('Delete the role ' + r.name + '?')) return;
          try { await refreshAfterRoleChange(await api('DELETE', '/org/roles/' + r.id)); say(r.name + ' deleted.', true); }
          catch (err) { say(err.message, false); }
        });
        details.append(el('label', { className: 'people-field' }, [document.createTextNode('Name'), name]), boxes, sites,
          el('div', { className: 'people-dialog-actions' }, [del, save]));
        list.append(details);
      });

      var base = $(rolesRoot, '[data-custom-role-base]');
      if (!base.options.length) {
        data.built_in.filter(function (b) { return b.can_clone; }).forEach(function (b) {
          base.append(el('option', { value: b.value, text: b.label }));
        });
        base.value = 'production';
      }
      var slot = $(rolesRoot, '[data-custom-role-perms]');
      function reseed() {
        var b = data.built_in.find(function (x) { return x.value === base.value; });
        slot.replaceChildren(permissionBoxes(b ? b.clone_permissions : []));
      }
      base.onchange = reseed;
      reseed();
      $(rolesRoot, '[data-custom-role-sites]').replaceChildren(siteScopeFields({}));
    }

    if (rolesRoot) {
      $(rolesRoot, '[data-custom-role-form]').addEventListener('submit', async function (e) {
        e.preventDefault();
        var f = e.target;
        var boxes = $(rolesRoot, '[data-custom-role-perms] .people-perms');
        try {
          await refreshAfterRoleChange(await api('POST', '/org/roles', {
            name: f.name.value, base_role: f.base_role.value, description: f.description.value, permissions: ticked(boxes),
            site_access_mode: $(rolesRoot, '[data-custom-role-sites] fieldset').scopeValue().site_access_mode,
            site_ids: $(rolesRoot, '[data-custom-role-sites] fieldset').scopeValue().site_ids
          }));
          say(f.name.value + ' created.', true);
          f.reset();
          f.closest('details').open = false;
        } catch (err) { say(err.message, false); }
      });
    }

    load();
  }

  function boot() { init(document.querySelector('[data-people-root]')); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  document.addEventListener('htmx:afterSwap', boot);
})();
