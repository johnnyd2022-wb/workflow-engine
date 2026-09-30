(function () {
  'use strict';

  var root = document.querySelector('[data-np3-check-root]');
  if (!root) return;
  // NP1, NP2 and NP3 share this workspace (plan 2.4b).
  var NP = root.dataset.programmeShort || 'NP3';

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


  var MAX_FILE_BYTES = 10 * 1024 * 1024;
  function fileInput() {
    var input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = 'application/pdf,image/png,image/jpeg';
    input.setAttribute('data-np3-attachments', '');
    return input;
  }
  // Files go up one at a time after the record exists; a failed file is reported but the
  // record stays, because it is already part of the audit trail.
  async function uploadFiles(input, recordId) {
    var failures = [];
    var files = Array.prototype.slice.call(input.files || []);
    for (var i = 0; i < files.length; i += 1) {
      var file = files[i];
      try {
        if (file.size > MAX_FILE_BYTES) throw new Error('is larger than 10MB');
        var body = new FormData();
        body.append('file', file);
        var token = document.querySelector('meta[name="csrf-token"]');
        await api('/api/compliant/np3-audit/records/' + encodeURIComponent(recordId) + '/files', {
          method: 'POST',
          headers: { 'X-CSRFToken': token ? token.content : '' },
          body: body,
        });
      } catch (err) {
        failures.push(file.name + ': ' + (err.message === 'Request failed' ? 'upload failed' : err.message));
      }
    }
    return failures;
  }
  function fileLinks(files) {
    if (!files || !files.length) return null;
    var list = document.createElement('ul');
    list.className = 'np3-attachments';
    files.forEach(function (file) {
      var item = document.createElement('li');
      var link = text('a', file.file_name);
      link.href = file.url;
      link.setAttribute('download', file.file_name);
      item.appendChild(link);
      item.appendChild(text('small', ' ' + Math.max(1, Math.round(file.file_size / 1024)) + ' KB'));
      list.appendChild(item);
    });
    return list;
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
    link.textContent = 'Open “' + (check.source_reference || plan.section || NP + ' guidance') + '” in the official ' + NP + ' guidance ↗';
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
    if ((plan.reference_notes || []).length) {
      drawer.appendChild(text('p', 'Important guidance notes:'));
      var notes = document.createElement('ul');
      notes.className = 'np3-evidence-checklist';
      (plan.reference_notes || []).forEach(function (note) { notes.appendChild(text('li', note)); });
      drawer.appendChild(notes);
    }
    show.appendChild(drawer);
    section.appendChild(show);
    return section;
  }

  function connectedEvidence(check) {
    var section = card('CONNECTED EVIDENCE', 'What Production can already show');
    var evidence = check.derived_evidence || [];
    var titles = check.evidence_titles || [];
    var connections = (check.evidence_playbook || {}).core_connections || [];
    if (!evidence.length && !titles.length && !connections.length) {
      section.appendChild(text(
        'p',
        'There is no linked Production evidence for this check yet. That is normal for policy and people controls; record the tailored evidence in the review below.'
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
        link.textContent = item.workspace_label || 'Open Production';
        line.appendChild(link);
      }
      list.appendChild(line);
    });
    connections.forEach(function (item) {
      var line = document.createElement('li');
      line.appendChild(text('strong', item.title));
      line.appendChild(document.createElement('br'));
      line.appendChild(document.createTextNode(item.detail + ' '));
      if (item.workspace_url) {
        var link = document.createElement('a');
        link.href = item.workspace_url;
        link.setAttribute('hx-boost', 'false');
        link.textContent = item.workspace_label || 'Open Production';
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
      'Add one extra file, log, SOP, certificate or Production record that supports this sign-off.',
      'SOP-FS-04, revision 7 / Quality drive',
      evidence
    ));

    var attachments = fileInput();
    form.appendChild(reviewField(
      'Attach files (optional)',
      'PDF, PNG or JPEG, up to 10MB each. They are kept with this sign-off and included in the evidence PDF.',
      'Signed SOP, photo of the completed log',
      attachments
    ));

    var confirmation = document.createElement('label');
    confirmation.className = 'np3-confirmation';
    var checkBox = document.createElement('input');
    checkBox.type = 'checkbox';
    checkBox.required = true;
    confirmation.appendChild(checkBox);
    confirmation.appendChild(document.createTextNode(
      ' I reviewed the relevant evidence and confirm it is fit for purpose against the current ' + NP + ' guidance.'
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
        var saved = await api('/api/compliant/np3-audit/attestations', {
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
        var failed = await uploadFiles(attachments, saved.record.id);
        await load();
        if (failed.length) showError('Review saved, but these files were not attached: ' + failed.join('; '));
      } catch (err) {
        showError(err.message);
        submit.disabled = false;
        submit.textContent = 'Sign off this review';
      }
    });
    section.appendChild(form);
    return section;
  }

  function logInput(field, staff, names) {
    var control;
    if (field.type === 'textarea') {
      control = document.createElement('textarea');
      control.rows = 3;
    } else if (field.type === 'select' || field.type === 'user') {
      control = document.createElement('select');
      var blank = document.createElement('option');
      blank.value = '';
      blank.textContent = 'Choose an option';
      control.appendChild(blank);
      var options = field.type === 'user'
        ? (staff || []).map(function (person) { return [person.id, person.name]; })
        : (field.options || []);
      options.forEach(function (option) {
        var item = document.createElement('option');
        item.value = option[0];
        item.textContent = option[1];
        control.appendChild(item);
      });
    } else {
      control = document.createElement('input');
      control.type = field.type === 'date' ? 'date' : 'text';
      if (field.type === 'person') {
        var listId = 'np3-people-' + field.key;
        var suggestions = document.createElement('datalist');
        suggestions.id = listId;
        (names || []).forEach(function (name) {
          var item = document.createElement('option');
          item.value = name;
          suggestions.appendChild(item);
        });
        var stale = document.getElementById(listId);
        if (stale) stale.remove();
        root.appendChild(suggestions);
        control.setAttribute('list', listId);
        control.autocomplete = 'off';
      }
    }
    control.name = field.key;
    control.maxLength = 4000;
    if (field.required) control.required = true;
    return control;
  }

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function shortDate(iso) {
    var parts = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    if (!parts) return '—';
    return Number(parts[3]) + ' ' + MONTHS[Number(parts[2]) - 1] + ' ' + parts[1];
  }

  function trainingTable(matrix) {
    var wrap = document.createElement('div');
    wrap.className = 'np3-training-table';
    if (!matrix.people.length) {
      wrap.appendChild(text('p', 'No training recorded yet. Add the first record below.'));
      return wrap;
    }
    var table = document.createElement('table');
    var head = document.createElement('tr');
    head.appendChild(text('th', 'Training category'));
    matrix.people.forEach(function (name) { head.appendChild(text('th', name)); });
    var thead = document.createElement('thead');
    thead.appendChild(head);
    table.appendChild(thead);
    var body = document.createElement('tbody');
    matrix.rows.forEach(function (row) {
      var tr = document.createElement('tr');
      tr.appendChild(text('th', row.label));
      row.dates.forEach(function (dates) {
        tr.appendChild(text('td', dates.length ? dates.map(shortDate).join(', ') : '—'));
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    wrap.appendChild(text('p', 'Dates each person completed the training, newest first.', 'np3-field__help'));
    wrap.appendChild(table);
    return wrap;
  }

  function logBook(check, staff) {
    var template = check.log_template;
    if (!template) return null;
    var section = card('BUILT-IN REGISTER', template.title, 'np3-logbook');
    section.appendChild(text('p', template.description));

    var entries = check.log_entries || [];
    var matrix = check.training_matrix;
    var register = document.createElement('details');
    register.className = 'np3-logbook__entries';
    register.open = !!entries.length;
    register.appendChild(text('summary', 'Saved entries (' + entries.length + ')'));
    var registerBody = document.createElement('div');
    registerBody.className = 'np3-logbook__entries-body';
    if (!entries.length) {
      registerBody.appendChild(text('p', 'No entries yet. Add the first record below; it becomes part of this check’s audit trail.'));
    } else {
      var list = document.createElement('ol');
      entries.slice(0, 12).forEach(function (entry) {
        var eventDate = entry.event_date || (entry.created_at ? new Date(entry.created_at).toLocaleDateString() : 'Date unavailable');
        var item = text('li', eventDate + (entry.status === 'open' ? ' · follow-up open' : ' · recorded'));
        Object.keys(entry.fields || {}).forEach(function (key) {
          var definition = (template.fields || []).find(function (field) { return field.key === key; });
          var value = entry.fields[key];
          if (key === 'employee_user_id') {
            var person = (staff || []).find(function (candidate) { return candidate.id === value; });
            value = person ? person.name : value;
          }
          item.appendChild(text('small', (definition ? definition.label : key.replace(/_/g, ' ')) + ': ' + value));
        });
        var entryFiles = fileLinks(entry.files);
        if (entryFiles) item.appendChild(entryFiles);
        list.appendChild(item);
      });
      registerBody.appendChild(list);
    }
    register.appendChild(registerBody);
    if (matrix) section.appendChild(trainingTable(matrix));
    else section.appendChild(register);

    // Suggest people already on the register, plus team members with a real name.
    var personNames = (matrix ? matrix.people.slice() : []);
    (staff || []).forEach(function (person) {
      if (person.name && person.name.indexOf('@') === -1 && personNames.indexOf(person.name) === -1) {
        personNames.push(person.name);
      }
    });

    var form = document.createElement('form');
    form.className = 'np3-logbook__form';
    var controls = {};
    (template.fields || []).forEach(function (field) {
      var input = logInput(field, staff, personNames);
      var help = field.required ? 'Required for this record.' : 'Optional supporting detail.';
      form.appendChild(reviewField(field.label, help, '', input));
      controls[field.key] = input;
    });
    var logFiles = fileInput();
    form.appendChild(reviewField(
      'Attach files (optional)',
      'PDF, PNG or JPEG, up to 10MB each. They are kept with this entry and included in the evidence PDF.',
      '',
      logFiles
    ));
    var submit = document.createElement('button');
    submit.type = 'submit';
    submit.textContent = 'Add log entry';
    form.appendChild(submit);
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      var fields = {};
      Object.keys(controls).forEach(function (key) { fields[key] = controls[key].value || ''; });
      submit.disabled = true;
      submit.textContent = 'Saving entry…';
      try {
        showError('');
        var savedEntry = await api('/api/compliant/np3-audit/checks/' + encodeURIComponent(check.control_id) + '/logs', {
          method: 'POST',
          headers: csrfHeaders(),
          body: JSON.stringify({ fields: fields }),
        });
        var failedFiles = await uploadFiles(logFiles, savedEntry.record.id);
        await load();
        if (failedFiles.length) showError('Entry saved, but these files were not attached: ' + failedFiles.join('; '));
      } catch (err) {
        showError(err.message);
        submit.disabled = false;
        submit.textContent = 'Add log entry';
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
      var eventFiles = fileLinks(event.files);
      if (eventFiles) item.appendChild(eventFiles);
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

    // Top to bottom: guidance and the review reminder side by side (read this before you act),
    // then one full-width place to act (sign off, plus the built-in register when this check has
    // one), then the supporting Core evidence, then the full audit trail.
    var workspace = root.querySelector('[data-np3-check-workspace]');
    clear(workspace);
    var topRow = document.createElement('div');
    topRow.className = 'np3-check-top-row';
    topRow.appendChild(guidance(check));
    topRow.appendChild(schedule(check));

    var primary = document.createElement('div');
    primary.className = 'np3-check-workspace__primary';
    primary.appendChild(reviewForm(check));
    var log = logBook(check, payload.available_staff || []);
    if (log) primary.appendChild(log);

    workspace.append(topRow, primary, connectedEvidence(check), history(check));
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
