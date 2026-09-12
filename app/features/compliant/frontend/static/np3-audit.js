(function () {
  'use strict';

  var root = document.querySelector('[data-np3-audit-root]');
  if (!root) return;

  var error = root.querySelector('[data-np3-error]');
  var date = root.querySelector('[data-np3-date]');
  var disclaimer = root.querySelector('[data-np3-disclaimer]');
  var tabs = root.querySelector('[data-np3-category-tabs]');
  var categoryRoot = root.querySelector('[data-np3-categories]');
  var activeCategoryHeading = root.querySelector('[data-np3-active-category]');
  var healthCards = root.querySelector('[data-np3-health-cards]');
  var queue = root.querySelector('[data-np3-work-queue]');
  var queueItems = root.querySelector('[data-np3-work-queue-items]');
  var prep = root.querySelector('[data-np3-preparation]');
  var coreStats = root.querySelector('[data-np3-core-stats]');
  var audit;
  var activeCategory;
  var activeFilter = 'all';

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function text(tag, value, className) {
    var node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  }
  function showError(message) { error.textContent = message || ''; error.hidden = !message; }
  function stateLabel(row) {
    if (row.state === 'ready') return 'Evidence ready';
    if (row.state === 'attention') return 'Needs attention';
    return 'Needs evidence';
  }
  function stateClass(row) {
    if (row.state === 'ready') return 'ready';
    if (row.state === 'attention') return 'attention';
    return 'setup';
  }
  function isOverdue(row) {
    return Boolean(row.review_due_date) && new Date(row.review_due_date + 'T00:00:00') < new Date(new Date().toDateString());
  }
  function isDueSoon(row) {
    if (!row.review_due_date || isOverdue(row)) return false;
    var due = new Date(row.review_due_date + 'T00:00:00');
    var limit = new Date();
    limit.setDate(limit.getDate() + 30);
    return due <= limit;
  }
  function matchesFilter(row) {
    if (activeFilter === 'all') return true;
    if (activeFilter === 'ok') return row.state === 'ready';
    if (activeFilter === 'attention') return row.state === 'attention' || row.state === 'missing';
    if (activeFilter === 'overdue') return isOverdue(row);
    if (activeFilter === 'due-soon') return isDueSoon(row);
    if (activeFilter === 'staff') return Boolean((row.staff_actions || []).length);
    if (activeFilter === 'remediation') return Boolean(row.open_remediation);
    return true;
  }
  function checkUrl(row) { return '/compliant/nz-alcohol/np3-audit/check/' + encodeURIComponent(row.control_id); }
  function guidance(row) {
    var plan = row.evidence_playbook || {};
    var details = document.createElement('details');
    details.className = 'np3-evidence-options';
    details.appendChild(text('summary', 'Show guidance and evidence options'));
    var body = document.createElement('div');
    body.className = 'np3-evidence-options__body';
    body.appendChild(text('p', 'The official guidance is mapped to “' + (plan.section || row.source_reference || 'NP3 guidance') + '”.'));
    var link = document.createElement('a');
    link.className = 'np3-inline-link';
    link.href = row.guidance_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open the official NP3 section ↗';
    body.appendChild(link);
    if ((plan.proof || []).length) {
      var list = document.createElement('ul');
      (plan.proof || []).forEach(function (proof) { list.appendChild(text('li', proof)); });
      body.appendChild(list);
    }
    if ((plan.reference_notes || []).length) {
      body.appendChild(text('p', 'Important guidance notes:'));
      var notes = document.createElement('ul');
      (plan.reference_notes || []).forEach(function (note) { notes.appendChild(text('li', note)); });
      body.appendChild(notes);
    }
    details.appendChild(body);
    return details;
  }
  function topic(row) {
    var details = document.createElement('details');
    details.className = 'np3-topic np3-topic--' + stateClass(row);
    var heading = document.createElement('summary');
    var copy = document.createElement('span');
    copy.appendChild(text('strong', row.topic || row.control_title || 'NP3 check'));
    copy.appendChild(text('span', row.requirement_summary || row.summary || '', 'np3-topic-action'));
    heading.appendChild(copy);
    heading.appendChild(text('span', stateLabel(row), 'np3-state'));
    details.appendChild(heading);
    var detail = document.createElement('div');
    detail.className = 'np3-topic__detail';
    detail.appendChild(text('p', row.requirement_summary || 'Review this NP3 requirement and its evidence.'));
    detail.appendChild(text('p', 'MPI section: ' + (row.source_reference || (row.evidence_playbook || {}).section || 'National Programme 3 guidance'), 'np3-guidance-reference'));
    if (row.guidance_update) detail.appendChild(text('p', row.guidance_update, 'np3-guidance-alert'));
    if ((row.staff_actions || []).length) {
      detail.appendChild(text('p', row.staff_actions.length + ' active team member' + (row.staff_actions.length === 1 ? '' : 's') + ' needs a training/competency entry.', 'np3-guidance-alert'));
    }
    detail.appendChild(guidance(row));
    var open = document.createElement('a');
    open.className = 'np3-download np3-open-check';
    open.href = checkUrl(row);
    open.setAttribute('hx-boost', 'false');
    open.textContent = 'Open full check, register and history';
    detail.appendChild(open);
    details.appendChild(detail);
    return details;
  }
  function renderTabs(rowsByCategory) {
    clear(tabs);
    (audit.categories || []).forEach(function (category, index) {
      var rows = rowsByCategory[category.key] || [];
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'np3-category-tab' + (category.key === activeCategory ? ' is-active' : '');
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-selected', category.key === activeCategory ? 'true' : 'false');
      button.setAttribute('aria-controls', 'np3-category-panel');
      button.id = 'np3-category-tab-' + index;
      button.appendChild(text('strong', category.title));
      var outstanding = rows.filter(function (row) { return row.state !== 'ready'; }).length;
      button.appendChild(text('span', outstanding ? outstanding + ' require evidence' : 'All evidence ready'));
      button.addEventListener('click', function () { activeCategory = category.key; render(); });
      tabs.appendChild(button);
    });
  }
  function renderCategory(rowsByCategory) {
    clear(categoryRoot);
    var category = (audit.categories || []).filter(function (item) { return item.key === activeCategory; })[0];
    if (!category) return;
    var allRows = rowsByCategory[category.key] || [];
    var visibleRows = allRows.filter(matchesFilter);
    activeCategoryHeading.textContent = category.title;
    var section = document.createElement('section');
    section.className = 'np3-category';
    section.id = 'np3-category-panel';
    section.setAttribute('role', 'tabpanel');
    section.setAttribute('aria-labelledby', 'np3-category-tab-' + (audit.categories || []).indexOf(category));
    section.appendChild(text('p', visibleRows.length + ' of ' + allRows.length + ' verification check' + (allRows.length === 1 ? '' : 's') + (activeFilter === 'all' ? '' : ' matching this health view'), 'np3-category-count'));
    var list = document.createElement('div');
    list.className = 'np3-topic-list';
    if (visibleRows.length) visibleRows.forEach(function (row) { list.appendChild(topic(row)); });
    else list.appendChild(text('p', 'No checks in this section match the selected health view. Choose another status above to see the full register.'));
    section.appendChild(list);
    categoryRoot.appendChild(section);
  }
  function healthCard(key, number, label, detail) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'np3-health-card' + (activeFilter === key ? ' is-active' : '');
    button.appendChild(text('strong', String(number)));
    button.appendChild(text('span', label));
    button.appendChild(text('small', detail));
    button.addEventListener('click', function () { activeFilter = activeFilter === key ? 'all' : key; render(); });
    return button;
  }
  function renderHealth() {
    clear(healthCards);
    var health = audit.health || {};
    healthCards.appendChild(healthCard('ok', health.ok || 0, 'Evidence ready', 'Current and signed off'));
    healthCards.appendChild(healthCard('attention', health.needs_attention || 0, 'Needs attention', 'Evidence or response required'));
    healthCards.appendChild(healthCard('overdue', health.overdue || 0, 'Overdue review', 'Past its review date'));
    healthCards.appendChild(healthCard('due-soon', health.due_soon || 0, 'Due soon', 'Review within 30 days'));
    healthCards.appendChild(healthCard('staff', health.staff_actions || 0, 'People actions', 'Staff records to add or refresh'));
    healthCards.appendChild(healthCard('remediation', health.open_remediation || 0, 'Open remediation', 'A logged deviation remains open'));
  }
  function renderQueue() {
    clear(queueItems);
    var items = audit.work_queue || [];
    queue.hidden = !items.length;
    items.forEach(function (item) {
      var link = document.createElement('a');
      link.className = 'np3-work-queue__item np3-work-queue__item--' + (item.severity || 'attention');
      link.href = '/compliant/nz-alcohol/np3-audit/check/' + encodeURIComponent(item.control_id);
      link.setAttribute('hx-boost', 'false');
      link.appendChild(text('strong', item.title));
      link.appendChild(text('span', item.description));
      link.appendChild(text('small', 'Open check →'));
      queueItems.appendChild(link);
    });
  }
  function renderCoreStats() {
    clear(coreStats);
    var stats = audit.core_evidence || {};
    var live = stats.live_np3_evidence || {};
    var data = [
      [live.dag_traced_final_products || 0, 'traceable product batches'],
      [stats.completed_core_steps_with_captured_data || 0, 'completed execution records'],
      [stats.active_core_evidence_files || 0, 'active evidence files'],
      [live.supplier_identified_materials || 0, 'material records with supplier']
    ];
    data.forEach(function (item) {
      var stat = document.createElement('div');
      stat.appendChild(text('strong', String(item[0])));
      stat.appendChild(text('span', item[1]));
      coreStats.appendChild(stat);
    });
  }
  function renderPrep() {
    clear(prep);
    (audit.preparation_items || []).forEach(function (item) { prep.appendChild(text('li', item)); });
  }
  function render() {
    if (!audit) return;
    // Kept as a named mapping because category selection must never require the user to
    // scroll through every NP3 topic to find their next action.
    var rowsByCategory = {};
    (audit.categories || []).forEach(function (category) { rowsByCategory[category.key] = []; });
    (audit.rows || []).forEach(function (row) {
      if (!rowsByCategory[row.category_key]) rowsByCategory[row.category_key] = [];
      rowsByCategory[row.category_key].push(row);
    });
    if (!activeCategory || !rowsByCategory[activeCategory]) activeCategory = (audit.categories || [])[0] && audit.categories[0].key;
    renderHealth();
    renderTabs(rowsByCategory);
    renderQueue();
    renderCategory(rowsByCategory);
    renderCoreStats();
    renderPrep();
    date.textContent = audit.verification && audit.verification.date
      ? 'Verification date: ' + audit.verification.date
      : 'Set the verification date in Configuration.';
    disclaimer.textContent = audit.disclaimer || '';
    root.setAttribute('aria-busy', 'false');
  }
  fetch('/api/compliant/np3-audit').then(function (response) {
    if (!response.ok) throw new Error('Could not load the NP3 audit register');
    return response.json();
  }).then(function (data) { audit = data; render(); }).catch(function (err) {
    root.setAttribute('aria-busy', 'false');
    showError(err.message || 'Could not load the NP3 audit register');
  });
}());
