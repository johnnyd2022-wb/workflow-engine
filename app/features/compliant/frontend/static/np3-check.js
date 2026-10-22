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

  function card(label, heading, className) {
    var section = document.createElement('section');
    section.className = 'workspace-card np3-card' + (className ? ' ' + className : '');
    if (label) section.appendChild(text('p', label, 'np3-card__label'));
    section.appendChild(text('h2', heading));
    return section;
  }

  // MPI's cards end on "Show": what the verifier will ask to see. It leads the check.
  function verifierAsks(check) {
    var plan = check.evidence_playbook || {};
    var section = card('About this check', 'What your verifier will ask to see', 'np3-asks');
    var list = document.createElement('ul');
    list.className = 'np3-evidence-checklist';
    (plan.proof || []).forEach(function (item) { list.appendChild(text('li', item)); });
    if (!list.children.length) list.appendChild(text('li', 'The records that show this requirement is met, with who did it and when.'));
    section.appendChild(list);
    var more = document.createElement('details');
    more.className = 'np3-official-guidance';
    more.appendChild(text('summary', 'Guidance notes' + (plan.section ? ' · ' + plan.section + (plan.page ? ', page ' + plan.page : '') : '')));
    var drawer = document.createElement('div');
    drawer.className = 'np3-guidance-drawer';
    if ((plan.reference_notes || []).length) {
      var notes = document.createElement('ul');
      notes.className = 'np3-evidence-checklist';
      (plan.reference_notes || []).forEach(function (note) { notes.appendChild(text('li', note)); });
      drawer.appendChild(notes);
    }
    var link = document.createElement('a');
    link.className = 'np3-inline-link';
    link.href = check.guidance_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open “' + (check.source_reference || plan.section || NP + ' guidance') + '” in the official ' + NP + ' guidance ↗';
    drawer.appendChild(link);
    more.appendChild(drawer);
    section.appendChild(more);
    return section;
  }

  function connectedEvidence(check) {
    var evidence = check.derived_evidence || [];
    var connections = (check.evidence_playbook || {}).core_connections || [];
    if (!evidence.length && !connections.length) return null;
    var section = document.createElement('div');
    section.className = 'np3-evidence-block';
    section.appendChild(text('h3', 'From Production', 'np3-card__sub'));
    var list = document.createElement('ul');
    list.className = 'np3-connected-evidence';
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
    if (root.dataset.canManage !== '1') return null;
    var section = document.createElement('details');
    section.className = 'workspace-card np3-card np3-check-settings';
    section.appendChild(text('summary', 'Review reminder: ' + ({ 1: 'every month', 3: 'every 3 months', 6: 'every 6 months', 12: 'every year' }[Number(check.default_review_interval_months || 6)] || 'every 6 months')));
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
    if (help) label.appendChild(text('small', help, 'np3-field__help'));
    if (example) label.appendChild(text('small', 'Example: ' + example, 'np3-field__example'));
    label.appendChild(control);
    return label;
  }

  function reviewForm(check) {
    var section = card('Record evidence', 'Sign off a review', 'np3-check-review');
    section.appendChild(text(
      'p',
      'Say how this requirement is met here and point to the records. It sets the next review date.',
      'np3-card__intro'
    ));
    var form = document.createElement('form');
    form.setAttribute('hx-boost', 'false');
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
    submit.className = 'workspace-button workspace-button--primary';
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

  function fieldLabel(fields, key) {
    var definition = (fields || []).find(function (field) { return field.key === key; });
    return definition ? definition.label : key.replace(/_/g, ' ');
  }
  // A select's stored value ("action-required") read back as its label ("Yes, action required").
  function optionLabel(fields, key, value) {
    var definition = (fields || []).find(function (field) { return field.key === key; });
    var match = definition && (definition.options || []).find(function (option) { return option[0] === value; });
    return match ? match[1] : value;
  }
  function personName(staff, value) {
    var person = (staff || []).find(function (candidate) { return candidate.id === value; });
    return person ? person.name : value;
  }

  // The built-in register's form: where a check has a log, recording is adding an entry.
  function logForm(check, staff) {
    var template = check.log_template;
    if (!template) return null;
    var section = card('Record evidence', 'Add to the ' + template.title.charAt(0).toLowerCase() + template.title.slice(1), 'np3-record');
    section.appendChild(text('p', template.description, 'np3-card__intro'));
    var matrix = check.training_matrix;
    var personNames = (matrix ? matrix.people.slice() : []);
    (staff || []).forEach(function (person) {
      if (person.name && person.name.indexOf('@') === -1 && personNames.indexOf(person.name) === -1) {
        personNames.push(person.name);
      }
    });
    var form = document.createElement('form');
    form.className = 'np3-logbook__form';
    form.setAttribute('hx-boost', 'false');
    var controls = {};
    (template.fields || []).forEach(function (field) {
      var input = logInput(field, staff, personNames);
      form.appendChild(reviewField(field.label + (field.required ? '' : ' (optional)'), '', '', input));
      controls[field.key] = input;
    });
    var logFiles = fileInput();
    form.appendChild(reviewField('Attach files (optional)', 'PDF, PNG or JPEG, up to 10MB each.', '', logFiles));
    var submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'workspace-button workspace-button--primary';
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

  // Every logged entry, newest first: the evidence a log check builds up. The latest few show;
  // the rest are one click away, so recording more stays near the top.
  var SHOWN = 3;
  function logEntries(check, staff) {
    var template = check.log_template;
    var entries = check.log_entries || [];
    var wrap = document.createElement('div');
    wrap.className = 'np3-evidence-block';
    if (check.training_matrix) {
      wrap.appendChild(text('h3', 'Training register', 'np3-card__sub'));
      wrap.appendChild(trainingTable(check.training_matrix));
      return wrap;
    }
    wrap.appendChild(text('h3', entries.length ? template.title + ' · ' + plural(entries.length, 'entry', 'entries') : template.title + ' · no entries yet', 'np3-card__sub'));
    if (!entries.length) return wrap;
    var list = document.createElement('ol');
    list.className = 'np3-entries';
    entries.forEach(function (entry, index) {
      var eventDate = entry.event_date ? shortDate(entry.event_date) : (entry.created_at ? shortDate(String(entry.created_at).slice(0, 10)) : 'Date unavailable');
      var item = document.createElement('li');
      item.className = 'np3-entry' + (entry.status === 'open' ? ' np3-entry--open' : '');
      if (index >= SHOWN) item.hidden = true;
      var head = document.createElement('div');
      head.className = 'np3-entry__head';
      head.appendChild(text('strong', eventDate));
      head.appendChild(text('span', entry.status === 'open' ? 'Follow-up open' : 'Recorded' + (entry.employee_name ? ' by ' + entry.employee_name : ''), 'np3-tag np3-tag--' + (entry.status === 'open' ? 'bad' : 'good')));
      item.appendChild(head);
      var details = document.createElement('dl');
      details.className = 'np3-entry__fields';
      Object.keys(entry.fields || {}).forEach(function (key) {
        if ((template.fields || []).some(function (f) { return f.key === key && f.type === 'date'; }) && entry.fields[key] === entry.event_date) return;
        var value = key === 'employee_user_id' ? personName(staff, entry.fields[key]) : optionLabel(template.fields, key, entry.fields[key]);
        details.appendChild(text('dt', fieldLabel(template.fields, key)));
        details.appendChild(text('dd', value));
      });
      item.appendChild(details);
      var entryFiles = fileLinks(entry.files);
      if (entryFiles) item.appendChild(entryFiles);
      list.appendChild(item);
    });
    wrap.appendChild(list);
    if (entries.length > SHOWN) {
      var more = document.createElement('button');
      more.type = 'button';
      more.className = 'np3-link';
      more.textContent = 'Show all ' + entries.length + ' entries';
      more.addEventListener('click', function () {
        list.querySelectorAll('li[hidden]').forEach(function (li) { li.hidden = false; });
        more.remove();
      });
      wrap.appendChild(more);
    }
    return wrap;
  }

  function history(check, staff) {
    var section = card(null, 'History', 'np3-history');
    // Log entries are listed in the register above; the history is the sign-offs.
    var events = (check.history || []).filter(function (event) { return !(check.log_template && event.log_entry); });
    if (!events.length) {
      section.appendChild(text('p', check.log_template ? 'No reviews signed off yet: the log entries above are the record.' : 'Nothing recorded for this check yet.', 'np3-card__intro'));
      return section;
    }
    var fields = ((check.evidence_playbook || {}).fields || []).concat((check.log_template || {}).fields || []);
    var list = document.createElement('ol');
    list.className = 'np3-full-history';
    events.forEach(function (event) {
      var item = document.createElement('li');
      var when = event.created_at ? shortDate(String(event.created_at).slice(0, 10)) : 'Date unavailable';
      item.appendChild(text('strong', event.title));
      item.appendChild(text('span', when + ' · ' + (event.signed_off_by || 'Former team member') + (event.due_date ? ' · next review ' + shortDate(event.due_date) : ''), 'np3-full-history__meta'));
      if (event.how_we_meet) item.appendChild(text('p', event.how_we_meet));
      var values = event.evidence_fields || {};
      if (Object.keys(values).length) {
        var dl = document.createElement('dl');
        dl.className = 'np3-entry__fields';
        Object.keys(values).forEach(function (key) {
          dl.appendChild(text('dt', fieldLabel(fields, key)));
          dl.appendChild(text('dd', key === 'employee_user_id' ? personName(staff, values[key]) : values[key]));
        });
        item.appendChild(dl);
      }
      var eventFiles = fileLinks(event.files);
      if (eventFiles) item.appendChild(eventFiles);
      list.appendChild(item);
    });
    section.appendChild(list);
    return section;
  }

  // What there is to show today: the newest proof, the log, and what Production already records.
  function evidence(check, staff) {
    var section = card(null, 'Evidence we have', 'np3-evidence');
    var events = check.history || [];
    var latest = events[0];
    var facts = document.createElement('dl');
    facts.className = 'np3-evidence__facts';
    function fact(label, value) { facts.appendChild(text('dt', label)); facts.appendChild(text('dd', value)); }
    fact('Latest', latest ? latest.title + ' · ' + shortDate(String(latest.created_at).slice(0, 10)) + ' · ' + (latest.signed_off_by || 'Former team member') : 'Nothing recorded yet');
    fact('Records', plural(events.length, 'record'));
    fact('Next review', check.review_due_date ? shortDate(check.review_due_date) : 'Set by the next sign-off');
    section.appendChild(facts);
    var files = latest ? fileLinks(latest.files) : null;
    if (files) section.appendChild(files);
    if (check.log_template) section.appendChild(logEntries(check, staff));
    var linked = connectedEvidence(check);
    if (linked) section.appendChild(linked);
    return section;
  }

  function plural(n, word, many) { return n + ' ' + (n === 1 ? word : (many || word + 's')); }

  function render(payload) {
    var check = payload.check;
    var staff = payload.available_staff || [];
    root.querySelector('[data-np3-check-title]').textContent = check.topic;
    var leaf = document.querySelector('[data-breadcrumb-leaf]');
    if (leaf) leaf.textContent = check.topic;
    root.querySelector('[data-np3-check-summary]').textContent = check.requirement_summary;
    var stateEl = root.querySelector('[data-np3-check-state]');
    var overdue = check.review_due_date && check.review_due_date < new Date().toISOString().slice(0, 10);
    var state = check.open_remediation ? ['bad', 'Follow-up open']
      : overdue ? ['bad', 'Review overdue']
      : check.guidance_update_required ? ['warn', 'Guidance changed']
      : check.state === 'ready' ? ['good', 'Evidence current'] : ['warn', 'Needs evidence'];
    stateEl.className = 'np3-tag np3-tag--' + state[0];
    stateEl.textContent = state[1];
    var attested = (check.history || []).find(function (event) { return event.record_type === 'attestation'; });
    var lastLog = (check.log_entries || [])[0];
    root.querySelector('[data-np3-check-next-review]').textContent = check.review_due_date
      ? (overdue ? 'Review was due ' : 'Next review ') + shortDate(check.review_due_date)
      : attested ? 'Signed off ' + shortDate(String(attested.created_at).slice(0, 10))
      : lastLog ? 'Last logged ' + shortDate(lastLog.event_date || String(lastLog.created_at).slice(0, 10))
      : 'Nothing recorded yet';

    // One column, in reading order: what the check is and what the verifier will ask for, the
    // evidence there is, a place to record more (the log where the check has one, else a
    // sign-off, the other behind a disclosure), the sign-off history, then the reminder.
    var workspace = root.querySelector('[data-np3-check-workspace]');
    clear(workspace);
    var record = logForm(check, staff);
    var pieces = [verifierAsks(check), evidence(check, staff)];
    if (record) {
      var other = document.createElement('details');
      other.className = 'np3-alt';
      other.appendChild(text('summary', 'Sign off a review instead'));
      other.appendChild(reviewForm(check));
      pieces.push(record, other);
    } else {
      pieces.push(reviewForm(check));
    }
    pieces.push(history(check, staff), schedule(check));
    pieces.forEach(function (piece) { if (piece) workspace.appendChild(piece); });
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
