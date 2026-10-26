// Record a production step (/core/record): every batch in flight and every workflow, each one
// tap from its recording screen. The server shapes the lists (/api/core/record-options).
(function () {
  'use strict';

  var SEARCH_FROM = 7; // a search box only once the list is long enough to need one

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] == null) return;
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'className') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.append(c); });
    return node;
  }

  function span(seconds) {
    var minutes = Math.floor(seconds / 60);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return minutes + ' min';
    var hours = Math.floor(minutes / 60);
    if (hours < 48) return hours + (hours === 1 ? ' hour' : ' hours');
    var days = Math.floor(hours / 24);
    return days + (days === 1 ? ' day' : ' days');
  }

  function started(iso) {
    if (!iso) return 'Batch';
    var d = new Date(iso);
    return isNaN(d) ? 'Batch' : 'Started ' + d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' });
  }

  function chevron() {
    return el('span', { className: 'rs-chevron', 'aria-hidden': 'true', text: '›' });
  }

  function batchRow(b, highlight) {
    var fresh = b.step_number > 1 ? 'Just now' : 'Just started';
    var wait = b.waited_seconds < 60 ? fresh : (b.waiting ? 'Waiting ' : '') + span(b.waited_seconds);
    var link = el('a', { className: 'rs-batch' + (b.waiting ? ' is-waiting' : '') + (highlight ? ' is-recorded' : ''), href: b.href }, [
      el('span', { className: 'rs-batch__main' }, [
        el('span', { className: 'rs-batch__workflow', text: b.workflow }),
        el('span', { className: 'rs-batch__label', text: b.label || started(b.started_at) })
      ]),
      el('span', { className: 'rs-batch__step' }, [
        el('span', { className: 'rs-batch__next', text: 'Next' }),
        el('span', { className: 'rs-batch__stepname', text: b.step_name }),
        el('span', { className: 'rs-batch__of', text: 'Step ' + b.step_number + ' of ' + b.step_total })
      ]),
      el('span', { className: 'rs-wait' + (b.waiting ? ' rs-wait--late' : ''), text: wait }),
      chevron()
    ]);
    return el('li', null, [link]);
  }

  function workflowTile(w) {
    var meta = w.step_count + (w.step_count === 1 ? ' step' : ' steps') + ' · starts with ' + w.first_step;
    return el('li', null, [
      el('a', { className: 'rs-workflow', href: w.href }, [
        el('span', { className: 'rs-workflow__plus', 'aria-hidden': 'true', text: '+' }),
        el('span', { className: 'rs-workflow__main' }, [
          el('span', { className: 'rs-workflow__name', text: w.name }),
          el('span', { className: 'rs-workflow__meta', text: meta }),
          w.in_flight ? el('span', { className: 'rs-workflow__inflight', text: w.in_flight + ' in progress' }) : null
        ]),
        chevron()
      ])
    ]);
  }

  function init(root) {
    var $ = function (sel) { return root.querySelector(sel); };
    var data = null;
    var recordedId = new URLSearchParams(window.location.search).get('recorded');

    function renderBatches() {
      var list = $('[data-rs-batches]');
      var query = ($('[data-rs-search]').value || '').trim().toLowerCase();
      // The batch just recorded leads, so its next step is one tap away at the top.
      var ordered = data.batches.slice().sort(function (x, y) { return (y.execution_id === recordedId) - (x.execution_id === recordedId); });
      var shown = ordered.filter(function (b) {
        return !query || [b.workflow, b.label, b.step_name].join(' ').toLowerCase().indexOf(query) !== -1;
      });
      list.replaceChildren.apply(list, shown.map(function (b) { return batchRow(b, b.execution_id === recordedId); }));
      var empty = $('[data-rs-batches-empty]');
      empty.hidden = shown.length > 0;
      empty.textContent = 'No batch matches “' + query + '”.';
    }

    function renderRecorded() {
      var box = $('[data-rs-recorded]');
      if (!recordedId) return;
      var b = data.batches.find(function (x) { return x.execution_id === recordedId; });
      box.replaceChildren();
      if (b) {
        box.append(
          el('p', { className: 'rs-recorded__text' }, [
            el('strong', { text: 'Recorded.' }),
            document.createTextNode(' ' + (b.label || b.workflow) + ' is now at step ' + b.step_number + ' of ' + b.step_total + ': ' + b.step_name + '.')
          ]),
          el('a', { className: 'workspace-button workspace-button--primary rs-primary', href: b.href, text: 'Record ' + b.step_name })
        );
      } else {
        box.append(el('p', { className: 'rs-recorded__text' }, [el('strong', { text: 'Recorded.' }), document.createTextNode(' That was the last step, so the batch is finished.')]));
      }
      box.hidden = false;
    }

    function render() {
      $('[data-rs-loading]').hidden = true;
      // No batches in progress: the section has nothing to offer, so it isn't shown.
      $('[data-rs-batches-section]').hidden = !data.batches.length;
      $('[data-rs-workflows-section]').hidden = false;
      $('[data-rs-batch-count]').textContent = data.batches.length ? String(data.batches.length) : '';
      $('[data-rs-search-wrap]').hidden = data.batches.length < SEARCH_FROM;
      renderRecorded();
      renderBatches();
      var tiles = $('[data-rs-workflows]');
      tiles.replaceChildren.apply(tiles, data.workflows.map(workflowTile));
      var noWorkflows = $('[data-rs-workflows-empty]');
      noWorkflows.hidden = data.workflows.length > 0;
      if (root.getAttribute('data-can-design') !== '1') {
        var link = $('[data-rs-create-workflow]');
        if (link) link.replaceWith(document.createTextNode('Ask someone who designs workflows to set one up'));
      }
    }

    $('[data-rs-search]').addEventListener('input', function () { if (data) renderBatches(); });

    fetch('/api/core/record-options', { credentials: 'include', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('Could not load batches (' + r.status + '). Refresh to try again.'); return r.json(); })
      .then(function (body) { if (!root.isConnected) return; data = body; render(); })
      .catch(function (err) {
        $('[data-rs-loading]').hidden = true;
        var m = $('[data-rs-message]');
        m.textContent = err.message;
        m.className = 'rs-message rs-message--error';
        m.hidden = false;
      });
  }

  // Runs at first load and after every boosted swap that brings the page in (page-init.js).
  bize.onPage('[data-record-step-root]', init);
})();
