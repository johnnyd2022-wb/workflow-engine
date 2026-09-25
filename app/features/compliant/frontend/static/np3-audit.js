(function () {
  'use strict';

  var root = document.querySelector('[data-np3-audit-root]');
  if (!root) return;

  var error = root.querySelector('[data-np3-error]');
  var date = root.querySelector('[data-np3-date]');
  var tabs = root.querySelector('[data-np3-category-tabs]');
  var categoryRoot = root.querySelector('[data-np3-categories]');
  var activeCategoryHeading = root.querySelector('[data-np3-active-category]');
  var healthCards = root.querySelector('[data-np3-health-cards]');
  var healthProgress = root.querySelector('[data-np3-health-progress]');
  var queue = root.querySelector('[data-np3-work-queue]');
  var queueItems = root.querySelector('[data-np3-work-queue-items]');
  var checkSearch = root.querySelector('[data-np3-check-search]');
  var prep = root.querySelector('[data-np3-preparation]');
  var coreStats = root.querySelector('[data-np3-core-stats]');
  var audit;
  var activeCategory;
  var activeFilter = 'all';
  var searchQuery = '';
  var initialFilter = new URLSearchParams(window.location.search).get('filter');
  if (['ok', 'attention', 'overdue', 'due-soon', 'remediation'].includes(initialFilter)) activeFilter = initialFilter;

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
    if (activeFilter === 'remediation') return Boolean(row.open_remediation);
    return true;
  }
  function matchesSearch(row) {
    if (!searchQuery) return true;
    return [row.topic, row.control_title, row.control_id].some(function (value) {
      return String(value || '').toLowerCase().includes(searchQuery);
    });
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
      button.appendChild(text(
        'span',
        outstanding ? outstanding + ' require evidence' : 'All evidence ready',
        outstanding ? 'np3-category-tab__evidence-needed' : 'np3-category-tab__evidence-ready'
      ));
      button.addEventListener('click', function () {
        activeCategory = category.key;
        searchQuery = '';
        if (checkSearch) checkSearch.value = '';
        render();
      });
      tabs.appendChild(button);
    });
  }
  function renderCategory(rowsByCategory) {
    clear(categoryRoot);
    var category = (audit.categories || []).filter(function (item) { return item.key === activeCategory; })[0];
    if (!category) return;
    var searching = Boolean(searchQuery);
    var allRows = searching || activeFilter !== 'all' ? (audit.rows || []) : (rowsByCategory[category.key] || []);
    var matchingRows = allRows.filter(matchesSearch);
    var visibleRows = matchingRows.filter(matchesFilter);
    activeCategoryHeading.textContent = searching ? 'Search results' : activeFilter !== 'all' ? 'Checks matching this health view' : category.title;
    var section = document.createElement('section');
    section.className = 'np3-category';
    section.id = 'np3-category-panel';
    section.setAttribute('role', 'tabpanel');
    section.setAttribute('aria-labelledby', 'np3-category-tab-' + (audit.categories || []).indexOf(category));
    var countText = searching
      ? visibleRows.length + ' of ' + matchingRows.length + ' matching check' + (matchingRows.length === 1 ? '' : 's')
      : visibleRows.length + ' of ' + allRows.length + ' verification check' + (allRows.length === 1 ? '' : 's') + (activeFilter === 'all' ? '' : ' matching this health view');
    section.appendChild(text('p', countText, 'np3-category-count'));
    var list = document.createElement('div');
    list.className = 'np3-topic-list';
    if (visibleRows.length) visibleRows.forEach(function (row) { list.appendChild(topic(row)); });
    else list.appendChild(text('p', searching ? 'No NP3 checks match this search.' : 'No checks in this section match the selected health view. Choose another status above to see the full register.'));
    section.appendChild(list);
    categoryRoot.appendChild(section);
  }
  function healthCard(key, number, label) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'np3-health-card np3-health-card--' + key + (activeFilter === key ? ' is-active' : '');
    button.appendChild(text('strong', String(number)));
    button.appendChild(text('span', label));
    button.addEventListener('click', function () { activeFilter = activeFilter === key ? 'all' : key; render(); });
    return button;
  }
  function renderHealth() {
    clear(healthCards);
    var health = audit.health || {};
    var ready = Number(health.ok || 0);
    var needsAttention = Number(health.needs_attention || 0);
    var total = ready + needsAttention;
    var percent = total ? Math.round((ready / total) * 100) : 0;
    if (healthProgress) {
      clear(healthProgress);
      var score = text('strong', percent + '%', 'np3-health-progress__score');
      var track = document.createElement('div');
      track.className = 'np3-health-progress__track';
      track.setAttribute('role', 'progressbar');
      track.setAttribute('aria-label', 'NP3 evidence readiness');
      track.setAttribute('aria-valuemin', '0');
      track.setAttribute('aria-valuemax', '100');
      track.setAttribute('aria-valuenow', String(percent));
      var fill = document.createElement('span');
      fill.style.width = percent + '%';
      track.appendChild(fill);
      var counts = document.createElement('div');
      counts.className = 'np3-health-progress__counts';
      counts.appendChild(text('span', ready + ' ready'));
      counts.appendChild(text('span', total + ' total'));
      healthProgress.appendChild(score);
      healthProgress.appendChild(track);
      healthProgress.appendChild(counts);
    }
    healthCards.appendChild(healthCard('ok', ready, 'Evidence ready'));
    healthCards.appendChild(healthCard('attention', needsAttention, 'Needs attention'));
    healthCards.appendChild(healthCard('overdue', health.overdue || 0, 'Overdue review'));
    healthCards.appendChild(healthCard('due-soon', health.due_soon || 0, 'Due soon'));
    healthCards.appendChild(healthCard('remediation', health.open_remediation || 0, 'Open remediation'));
  }
  // Shows the few steps worth doing first, prepared server-side as `guided_steps`. The
  // full list lives in the category tabs and health filters, so it is not repeated here.
  function openRegisterView(step) {
    activeFilter = step.filter || 'all';
    if (step.category_key) activeCategory = step.category_key;
    searchQuery = '';
    if (checkSearch) checkSearch.value = '';
    render();
    categoryRoot.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function renderQueue() {
    clear(queueItems);
    var steps = audit.guided_steps || [];
    queue.hidden = !steps.length;
    steps.forEach(function (step) {
      var opensCheck = step.opens === 'check';
      var item;
      if (opensCheck) {
        item = document.createElement('a');
        item.href = '/compliant/nz-alcohol/np3-audit/check/' + encodeURIComponent(step.control_id);
        item.setAttribute('hx-boost', 'false');
      } else {
        item = document.createElement('button');
        item.type = 'button';
        item.addEventListener('click', function () { openRegisterView(step); });
      }
      item.className = 'np3-work-queue__item np3-work-queue__item--' + (step.severity || 'attention');
      item.appendChild(text('strong', step.title));
      item.appendChild(text('span', step.description));
      item.appendChild(text('small', opensCheck ? 'Open check →' : 'Show in register →'));
      queueItems.appendChild(item);
    });
  }
  function renderCoreStats() {
    clear(coreStats);
    var stats = audit.core_evidence || {};
    var live = stats.live_np3_evidence || {};
    var data = [
      [live.dag_traced_final_products || 0, 'traceable product batches', '/core/inventory/live'],
      [stats.completed_core_steps_with_captured_data || 0, 'completed execution records', '/core/executions/live'],
      [stats.active_core_evidence_files || 0, 'active files attached to executions', '/core/executions/live'],
      [live.supplier_identified_materials || 0, 'material records with supplier', '/core/inventory/live']
    ];
    data.forEach(function (item) {
      var stat = document.createElement('a');
      stat.href = item[2];
      stat.setAttribute('hx-boost', 'false');
      stat.appendChild(text('strong', String(item[0])));
      stat.appendChild(text('span', item[1]));
      coreStats.appendChild(stat);
    });
  }
  function renderPrep() {
    clear(prep);
    (audit.preparation_items || []).forEach(function (item) { prep.appendChild(text('li', item)); });
  }
  if (checkSearch) checkSearch.addEventListener('input', function (event) {
    searchQuery = String(event.currentTarget.value || '').trim().toLowerCase();
    render();
  });
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
