(function () {
  'use strict';
  var root = document.querySelector('[data-np3-audit-root]');
  if (!root) return;
  var error = root.querySelector('[data-np3-error]');
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function text(tag, value, className) { var node = document.createElement(tag); node.textContent = value; if (className) node.className = className; return node; }
  function showError(message) { error.textContent = message || ''; error.hidden = !message; }
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
    (audit.categories || []).forEach(function (category) {
      var rows = (audit.rows || []).filter(function (row) { return row.category === category; });
      var section = document.createElement('section'); section.className = 'np3-category';
      var heading = text('h2', category); heading.appendChild(text('span', rows.filter(function (row) { return row.state === 'ready'; }).length + ' / ' + rows.length + ' recorded', 'np3-category-count')); section.appendChild(heading);
      var list = document.createElement('div'); list.className = 'np3-topic-list';
      rows.forEach(function (row) {
        var item = document.createElement('article'); item.className = 'np3-topic np3-topic--' + row.state;
        var body = document.createElement('div'); body.appendChild(text('h3', row.topic));
        body.appendChild(text('p', row.evidence_titles && row.evidence_titles.length ? row.evidence_titles.join(' · ') : 'No current evidence record linked yet.'));
        if (row.evidence_references && row.evidence_references.length) body.appendChild(text('p', row.evidence_references.join(' · '), 'np3-evidence-ref'));
        (row.derived_evidence || []).forEach(function (evidence) { body.appendChild(text('p', 'Live from Core (' + evidence.source_kind + '): ' + evidence.detail + ' Source IDs: ' + (evidence.source_refs || []).join(', '), 'np3-core-derived')); });
        item.appendChild(body); item.appendChild(text('span', stateLabel(row), 'np3-state'));
        if (row.state !== 'ready') { var add = document.createElement('a'); add.href = '/compliant/nz-alcohol#evidence'; add.textContent = 'Add evidence'; add.className = 'np3-add-evidence'; item.appendChild(add); }
        list.appendChild(item);
      });
      section.appendChild(list); categories.appendChild(section);
    });
  }
  fetch('/api/compliant/np3-audit').then(function (response) { return response.json().then(function (body) { if (!response.ok) throw new Error(body.error || 'Could not load the NP3 audit plan'); return body; }); }).then(render).catch(function (err) { showError(err.message); root.querySelector('[data-np3-summary]').textContent = 'Audit plan unavailable'; });
})();
