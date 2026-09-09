(function () {
  'use strict';
  var root = document.querySelector('[data-np3-audit-root]');
  if (!root) return;
  var error = root.querySelector('[data-np3-error]');
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function text(tag, value, className) { var node = document.createElement(tag); node.textContent = value; if (className) node.className = className; return node; }
  function showError(message) { error.textContent = message || ''; error.hidden = !message; }
  async function api(url) {
    var response = await fetch(url);
    var body = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(body.error || 'Could not load the NP3 audit plan');
    return body;
  }
  function evidenceUrl(row) {
    return '/compliant/nz-alcohol?framework=np3-food-control&control=' + encodeURIComponent(row.control_id) + '#evidence';
  }
  function openControlDetail(row) {
    var dialog = root.querySelector('[data-np3-control-detail]'); clear(dialog);
    dialog.appendChild(text('h2', row.topic)); dialog.lastChild.id = 'np3-control-detail-title';
    dialog.appendChild(text('p', 'Framework mapping: ' + (row.source_reference || 'National Programme 3 guidance')));
    dialog.appendChild(text('p', row.state === 'ready' ? 'This check has current evidence. Review it before a verification.' : 'This check still needs a current, reviewable evidence record.'));
    var proof = document.createElement('div'); proof.className = 'np3-detail-proof';
    proof.appendChild(text('h3', 'Evidence currently connected'));
    if (row.evidence_titles && row.evidence_titles.length) proof.appendChild(text('p', row.evidence_titles.join(' · ')));
    (row.derived_evidence || []).forEach(function (evidence) {
      var item = document.createElement('p'); item.textContent = evidence.title + ' — ' + evidence.detail + ' ';
      if (evidence.workspace_url) { var link = document.createElement('a'); link.href = evidence.workspace_url; link.setAttribute('hx-boost', 'false'); link.textContent = evidence.workspace_label || 'Open Core'; item.appendChild(link); }
      proof.appendChild(item);
    });
    if (!proof.querySelector('p')) proof.appendChild(text('p', 'No manual record or live Core observation is connected yet.'));
    dialog.appendChild(proof);
    var actions = document.createElement('div'); actions.className = 'np3-detail-actions'; var add = document.createElement('a'); add.href = evidenceUrl(row); add.setAttribute('hx-boost', 'false'); add.className = 'np3-download'; add.textContent = row.state === 'ready' ? 'Review this evidence' : 'Add evidence for this check'; actions.appendChild(add);
    var close = document.createElement('button'); close.type = 'button'; close.textContent = 'Close'; close.addEventListener('click', function () { dialog.close(); }); actions.appendChild(close); dialog.appendChild(actions);
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', 'open');
  }
  function stateLabel(row) { if (row.state === 'attention') return 'Needs attention'; if (row.state !== 'ready') return 'Evidence needed'; return row.derived_evidence_count ? 'Live Core proof' : 'Proof recorded'; }
  function render(audit) {
    var counts = audit.counts || {};
    root.querySelector('[data-np3-summary]').textContent = (counts.ready || 0) + ' topics have proof · ' + (counts.missing || 0) + ' need evidence';
    var verification = audit.verification || {};
    root.querySelector('[data-np3-date]').textContent = verification.date ? 'Verification: ' + verification.date + (verification.verifier ? ' · ' + verification.verifier : '') : 'Set the verification date in Configuration.';
    root.querySelector('[data-np3-disclaimer]').textContent = audit.disclaimer || '';
    var coreEvidence = audit.core_evidence || {}; var corePanel = root.querySelector('[data-np3-core-evidence]');
    corePanel.hidden = !Object.keys(coreEvidence).length;
    if (!corePanel.hidden) { var stats = root.querySelector('[data-np3-core-stats]'); var live = coreEvidence.live_np3_evidence || {}; clear(stats); [['DAG-traced final-product batches', live.dag_traced_final_products], ['DAG lineage edges', live.dag_lineage_edges], ['Completed Core steps with captured data', live.completed_steps_with_operational_data], ['Active Core evidence files', live.active_evidence_files]].forEach(function (item) { var stat = document.createElement('div'); stat.appendChild(text('strong', String(item[1] || 0))); stat.appendChild(text('span', item[0])); stats.appendChild(stat); }); }
    var preparation = root.querySelector('[data-np3-preparation]'); clear(preparation);
    (audit.preparation_items || []).forEach(function (item) { preparation.appendChild(text('li', item)); });
    var categories = root.querySelector('[data-np3-categories]'); clear(categories);
    var rowsByCategory = (audit.rows || []).reduce(function (grouped, row) {
      (grouped[row.category] || (grouped[row.category] = [])).push(row);
      return grouped;
    }, {});
    (audit.categories || []).forEach(function (category) {
      var rows = rowsByCategory[category] || [];
      var allReady = rows.length && rows.every(function (row) { return row.state === 'ready'; });
      var section = document.createElement('details'); section.className = 'np3-category' + (allReady ? ' np3-category--ready' : ''); section.open = !allReady;
      var heading = text('summary', category); heading.appendChild(text('span', rows.filter(function (row) { return row.state === 'ready'; }).length + ' / ' + rows.length + ' recorded', 'np3-category-count')); section.appendChild(heading);
      var list = document.createElement('div'); list.className = 'np3-topic-list';
      rows.forEach(function (row) {
        var item = document.createElement('article'); item.className = 'np3-topic np3-topic--' + row.state;
        var body = document.createElement('div'); body.appendChild(text('h3', row.topic));
        body.appendChild(text('p', 'NP3 guidance: ' + (row.source_reference || 'See latest guidance'), 'np3-guidance-reference'));
        body.appendChild(text('p', row.evidence_titles && row.evidence_titles.length ? row.evidence_titles.join(' · ') : 'No current evidence record linked yet.'));
        if (row.evidence_references && row.evidence_references.length) body.appendChild(text('p', row.evidence_references.join(' · '), 'np3-evidence-ref'));
        (row.derived_evidence || []).forEach(function (evidence) { var derived = text('p', 'Live from Core: ' + evidence.detail + ' ', 'np3-core-derived'); if (evidence.workspace_url) { var link = document.createElement('a'); link.href = evidence.workspace_url; link.setAttribute('hx-boost', 'false'); link.textContent = evidence.workspace_label || 'Open Core'; derived.appendChild(link); } body.appendChild(derived); });
        item.appendChild(body); item.appendChild(text('span', stateLabel(row), 'np3-state'));
        var inspect = document.createElement('button'); inspect.type = 'button'; inspect.textContent = row.state === 'ready' ? 'Review check' : 'Add evidence'; inspect.className = 'np3-add-evidence'; inspect.addEventListener('click', function () { openControlDetail(row); }); item.appendChild(inspect);
        list.appendChild(item);
      });
      section.appendChild(list); categories.appendChild(section);
    });
  }
  api('/api/compliant/np3-audit').then(render).catch(function (err) { showError(err.message); root.querySelector('[data-np3-summary]').textContent = 'Audit plan unavailable'; }).finally(function () { root.setAttribute('aria-busy', 'false'); });
})();
