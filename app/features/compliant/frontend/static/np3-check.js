(function () {
  'use strict';

  var root = document.querySelector('[data-np3-check-root]');
  if (!root) return;

  var controlId = root.dataset.controlId;
  var error = root.querySelector('[data-np3-check-error]');

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function text(tag, value, className) {
    var node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  }
  function showError(message) { error.textContent = message || ''; error.hidden = !message; }
  function csrfHeaders() {
    var token = document.querySelector('meta[name="csrf-token"]');
    return { 'Content-Type': 'application/json', 'X-CSRFToken': token ? token.content : '' };
  }
  async function api(url, options) {
    var response = await fetch(url, options || {});
    var body = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(body.error || 'Request failed');
    return body;
  }

  function card(eyebrow, heading, className) {
    var section = document.createElement('section');
    section.className = 'np3-detail-card' + (className ? ' ' + className : '');
    section.appendChild(text('p', eyebrow, 'compliant-eyebrow'));
    section.appendChild(text('h2', heading));
    return section;
  }

  function guidance(check) {
    var plan = check.evidence_playbook || {};
    var section = card('OFFICIAL GUIDANCE', plan.section || 'National Programme 3 Guidance');
    section.appendChild(text(
      'p',
      'This check is mapped to the named MPI card' + (plan.page ? ', page ' + plan.page : '') +
        '. The evidence plan below turns that card into a short, reviewable checklist.'
    ));

    var link = document.createElement('a');
    link.className = 'np3-inline-link';
    link.href = check.guidance_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open “' + (check.source_reference || plan.section || 'NP3 guidance') + '” in the official NP3 guidance ↗';
    section.appendChild(link);

    var show = document.createElement('details');
    show.className = 'np3-official-guidance';
    show.appendChild(text('summary', 'What to collect for this check'));
    var drawer = document.createElement('div');
    drawer.className = 'np3-guidance-drawer';
    drawer.appendChild(text('p', 'At verification, be ready to show:'));
    var list = document.createElement('ul');
    list.className = 'np3-evidence-checklist';
    (plan.proof || []).forEach(function (item) { list.appendChild(text('li', item)); });
    drawer.appendChild(list);
    show.appendChild(drawer);
    section.appendChild(show);
    return section;
  }

  function connectedEvidence(check) {
    var section = card('CONNECTED EVIDENCE', 'What Core can already show');
    var evidence = check.derived_evidence || [];
    var titles = check.evidence_titles || [];
    if (!evidence.length && !titles.length) {
      section.appendChild(text(
        'p',
        'There is no linked Core evidence for this check yet. That is normal for policy and people controls; record the tailored evidence in the review below.'
      ));
      return section;
    }
    var list = document.createElement('ul');
    list.className = 'np3-connected-evidence';
    titles.forEach(function (item) { list.appendChild(text('li', item)); });
    evidence.forEach(function (item) {
      var line = text('li', item.detail + ' ');
      if (item.workspace_url) {
        var link = document.createElement('a');
        link.href = item.workspace_url;
        link.setAttribute('hx-boost', 'false');
        link.textContent = item.workspace_label || 'Open Core';
        line.appendChild(link);
      }
      list.appendChild(line);
    });
    section.appendChild(list);
    return section;
  }

  function schedule(check) {
    var section = card('CHECK SETTINGS', 'Review reminder', 'np3-check-settings');
    section.appendChild(text(
      'p',
      'This setting applies to future sign-offs for this one check and overrides the default cadence in NZ Alcohol configuration.'
    ));
    var label = document.createElement('label');
    label.className = 'np3-field';
    label.appendChild(text('span', 'Review this check', 'np3-field__label'));
    label.appendChild(text('small', 'Choose how often this process needs a fresh, signed review.', 'np3-field__help'));
    var select = document.createElement('select');
    [[1, 'Every month'], [3, 'Every 3 months'], [6, 'Every 6 months'], [12, 'Every year']].forEach(function (option) {
      var item = document.createElement('option');
      item.value = String(option[0]);
      item.textContent = option[1];
      if (option[0] === Number(check.default_review_interval_months || 6)) item.selected = true;
      select.appendChild(item);
    });
    label.appendChild(select);
    section.appendChild(label);
    var save = document.createElement('button');
    save.type = 'button';
    save.textContent = 'Save reminder setting';
    save.addEventListener('click', async function () {
      save.disabled = true;
      try {
        showError('');
        await api('/api/compliant/np3-audit/checks/' + encodeURIComponent(check.control_id) + '/settings', {
          method: 'PUT',
          headers: csrfHeaders(),
          body: JSON.stringify({ review_interval_months: Number(select.value) }),
        });
        await load();
      } catch (err) {
        showError(err.message);
        save.disabled = false;
      }
    });
    section.appendChild(save);
    return section;
  }

  function reviewField(labelText, help, example, control) {
    var label = document.createElement('label');
    label.className = 'np3-field';
    label.appendChild(text('span', labelText, 'np3-field__label'));
    label.appendChild(text('small', help, 'np3-field__help'));
    if (example) label.appendChild(text('small', 'Example: ' + example, 'np3-field__example'));
    label.appendChild(control);
    return label;
  }

  function reviewForm(check) {
    var section = card('SIGN OFF THIS CHECK', 'Record the evidence you reviewed', 'np3-check-review');
    section.appendChild(text(
      'p',
      'Use the fields below to leave an auditor a concise, specific trail. The guidance and examples stay visible while you write.'
    ));
    var form = document.createElement('form');
    var how = document.createElement('textarea');
    how.required = true;
    how.rows = 5;
    how.maxLength = 4000;
    how.placeholder = 'Describe the process';
    form.appendChild(reviewField(
      'How this requirement is met',
      'Describe what happens at this site and point to the records or routine a verifier can see.',
      'Supervisor reviews the live training matrix monthly and observes each new operator in their first shift.',
      how
    ));

    var fields = {};
    ((check.evidence_playbook || {}).fields || []).forEach(function (field) {
      var input = document.createElement('input');
      input.name = field.key;
      input.maxLength = 1024;
      input.placeholder = 'Enter a specific record or result';
      form.appendChild(reviewField(
        field.label,
        field.help || 'Record the specific evidence reviewed for this check.',
        field.example || '',
        input
      ));
      fields[field.key] = input;
    });

    var evidence = document.createElement('input');
    evidence.maxLength = 1024;
    evidence.placeholder = 'Enter a supporting record reference';
    form.appendChild(reviewField(
      'Supporting record reference (optional)',
      'Add one extra file, log, SOP, certificate or Core record that supports this sign-off.',
      'SOP-FS-04, revision 7 / Quality drive',
      evidence
    ));

    var confirmation = document.createElement('label');
    confirmation.className = 'np3-confirmation';
    var checkBox = document.createElement('input');
    checkBox.type = 'checkbox';
    checkBox.required = true;
    confirmation.appendChild(checkBox);
    confirmation.appendChild(document.createTextNode(
      ' I reviewed the relevant evidence and confirm it is fit for purpose against the current NP3 guidance.'
    ));
    form.appendChild(confirmation);

    var submit = document.createElement('button');
    submit.type = 'submit';
    submit.textContent = 'Sign off this review';
    form.appendChild(submit);
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      var values = {};
      Object.keys(fields).forEach(function (key) {
        if (fields[key].value.trim()) values[key] = fields[key].value.trim();
      });
      submit.disabled = true;
      submit.textContent = 'Saving review…';
      try {
        showError('');
        await api('/api/compliant/np3-audit/attestations', {
          method: 'POST',
          headers: csrfHeaders(),
          body: JSON.stringify({
            control_id: check.control_id,
            how_we_meet: how.value,
            evidence_reference: evidence.value || null,
            evidence_fields: values,
            review_interval_months: Number(check.default_review_interval_months || 6),
            confirmed: checkBox.checked,
          }),
        });
        await load();
      } catch (err) {
        showError(err.message);
        submit.disabled = false;
        submit.textContent = 'Sign off this review';
      }
    });
    section.appendChild(form);
    return section;
  }

  function history(check) {
    var section = card('AUDIT TRAIL', 'Records and review history');
    var events = check.history || [];
    if (!events.length) {
      section.appendChild(text('p', 'No evidence has been signed off for this check yet.'));
      return section;
    }
    var list = document.createElement('ol');
    list.className = 'np3-full-history';
    events.forEach(function (event) {
      var date = event.created_at ? new Date(event.created_at).toLocaleDateString() : 'Date unavailable';
      var item = text('li', date + ' · ' + (event.signed_off_by || 'Former team member') + ' · ' + event.title);
      if (event.how_we_meet) item.appendChild(text('p', event.how_we_meet));
      Object.keys(event.evidence_fields || {}).forEach(function (key) {
        item.appendChild(text('small', key.replace(/_/g, ' ') + ': ' + event.evidence_fields[key]));
      });
      if (event.due_date) item.appendChild(text('small', 'Next review: ' + event.due_date));
      list.appendChild(item);
    });
    section.appendChild(list);
    return section;
  }

  function render(payload) {
    var check = payload.check;
    root.querySelector('[data-np3-check-title]').textContent = check.topic;
    root.querySelector('[data-np3-check-breadcrumb]').textContent = check.topic;
    root.querySelector('[data-np3-check-summary]').textContent = check.requirement_summary;
    root.querySelector('[data-np3-check-state]').textContent = check.guidance_update_required
      ? 'Guidance update required'
      : check.state === 'ready' ? 'Evidence current' : 'Evidence needed';
    var latest = (check.history || [])[0];
    root.querySelector('[data-np3-check-next-review]').textContent = latest && latest.due_date
      ? 'Next review: ' + latest.due_date : 'No signed review yet';

    var workspace = root.querySelector('[data-np3-check-workspace]');
    clear(workspace);
    var primary = document.createElement('div');
    primary.className = 'np3-check-workspace__primary';
    primary.appendChild(reviewForm(check));
    primary.appendChild(history(check));
    var context = document.createElement('aside');
    context.className = 'np3-check-workspace__context';
    context.setAttribute('aria-label', 'Check guidance and settings');
    context.appendChild(guidance(check));
    context.appendChild(connectedEvidence(check));
    context.appendChild(schedule(check));
    workspace.appendChild(primary);
    workspace.appendChild(context);
  }

  async function load() {
    root.setAttribute('aria-busy', 'true');
    try {
      showError('');
      render(await api('/api/compliant/np3-audit/checks/' + encodeURIComponent(controlId)));
    } catch (err) {
      showError(err.message);
    } finally {
      root.setAttribute('aria-busy', 'false');
    }
  }

  load();
})();
