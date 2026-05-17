(function () {
  'use strict';

  if (window.__core2ActiveBatchesGraphBound) {
    return;
  }
  window.__core2ActiveBatchesGraphBound = true;

  var state = {
    processes: [],
    executions: [],
    selectedProcessId: '',
    view: 'pipeline',
  };

  var latestRequest = 0;
  var loadTimer = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function toDate(raw) {
    if (!raw) return null;
    var dt = new Date(raw);
    if (Number.isNaN(dt.getTime())) return null;
    return dt;
  }

  function formatDateTime(raw) {
    var dt = toDate(raw);
    if (!dt) return 'Unknown';
    return dt.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  function formatDurationMs(ms) {
    var safe = Math.max(0, Number(ms || 0));
    var mins = Math.floor(safe / 60000);
    var hours = Math.floor(mins / 60);
    var remMins = mins % 60;
    if (hours <= 0) return remMins + 'm';
    if (remMins <= 0) return hours + 'h';
    return hours + 'h ' + remMins + 'm';
  }

  function sortSteps(steps) {
    return (steps || []).slice().sort(function (a, b) {
      return Number(a && a.step_number ? a.step_number : 0) - Number(b && b.step_number ? b.step_number : 0);
    });
  }

  function isActiveExecution(execution) {
    if (!execution) return false;
    var status = String(execution.status || '').toLowerCase();
    return status === 'in_progress' || status === 'pending';
  }

  function getCurrentStepNumber(execution) {
    var current = execution && execution.current_step ? execution.current_step : null;
    var n = current ? Number(current.step_number) : NaN;
    if (Number.isFinite(n) && n > 0) return Math.round(n);

    var sorted = sortSteps(execution && execution.execution_steps);
    var ready = sorted.find(function (step) {
      var status = String(step && step.status || '').toLowerCase();
      return status === 'ready' || status === 'in_progress';
    });
    if (ready && Number.isFinite(Number(ready.step_number))) {
      return Math.round(Number(ready.step_number));
    }
    return null;
  }

  function getLatestActivityAt(execution) {
    var points = [];
    var startedAt = toDate(execution && execution.started_at);
    if (startedAt) points.push(startedAt.getTime());

    (execution && execution.execution_steps ? execution.execution_steps : []).forEach(function (step) {
      var started = toDate(step && step.started_at);
      var completed = toDate(step && step.completed_at);
      if (started) points.push(started.getTime());
      if (completed) points.push(completed.getTime());
    });

    if (!points.length) return null;
    return new Date(Math.max.apply(Math, points));
  }

  function getCurrentStepStartAt(execution) {
    var currentStepNo = getCurrentStepNumber(execution);
    if (!currentStepNo) return null;
    var target = (execution && execution.execution_steps ? execution.execution_steps : []).find(function (step) {
      return Number(step && step.step_number) === Number(currentStepNo);
    });
    if (!target) return null;
    return toDate(target.started_at);
  }

  function classifyExecution(execution, now) {
    var latest = getLatestActivityAt(execution);
    var currentStart = getCurrentStepStartAt(execution);
    var status = String(execution && execution.status || '').toLowerCase();

    if (status === 'pending') {
      return 'queued';
    }

    // Scheduling-based risk states are disabled for now.
    if (latest && (now.getTime() - latest.getTime()) >= (24 * 3600 * 1000)) {
      return 'track';
    }

    if (currentStart && (now.getTime() - currentStart.getTime()) >= (8 * 3600 * 1000)) {
      return 'track';
    }

    return 'track';
  }

  function stepColorClass(index) {
    var idx = Math.max(0, Number(index || 0)) % 5;
    return 'core2-tl-segment--step' + String(idx);
  }

  function extractBatchLabel(execution) {
    var outputs = [];
    (execution && execution.execution_steps ? execution.execution_steps : []).forEach(function (step) {
      var stepOutputs = Array.isArray(step && step.actual_outputs) ? step.actual_outputs : [];
      stepOutputs.forEach(function (output) {
        if (output && typeof output === 'object') outputs.push(output);
      });
    });

    for (var i = 0; i < outputs.length; i += 1) {
      var out = outputs[i];
      var candidate = out.batch_id || out.batchId || out.lot_id || out.lotId || out.lot;
      if (candidate) return String(candidate);
    }

    if (execution && execution.event_summary) {
      var ev = String(execution.event_summary).trim();
      if (ev) return ev;
    }

    return null;
  }

  function getExecutionOperator(execution) {
    if (execution && execution.completed_by) {
      return String(execution.completed_by);
    }
    var steps = sortSteps(execution && execution.execution_steps);
    for (var i = steps.length - 1; i >= 0; i -= 1) {
      var data = steps[i] && steps[i].execution_data ? steps[i].execution_data : null;
      var op = data && (data.completed_by || data.completed_by_email || data.completed_by_user_id);
      if (op) return String(op);
    }
    return 'Unassigned';
  }

  function chooseDefaultProcessId(processes, executions) {
    if (!processes.length) return '';
    var activeByProcess = {};
    executions.forEach(function (execution) {
      if (!isActiveExecution(execution)) return;
      var pid = String(execution.process_id || '');
      activeByProcess[pid] = Number(activeByProcess[pid] || 0) + 1;
    });

    var winner = processes[0];
    var bestCount = -1;
    processes.forEach(function (process) {
      var pid = String(process.id || '');
      var count = Number(activeByProcess[pid] || 0);
      if (count > bestCount) {
        bestCount = count;
        winner = process;
      }
    });

    return String((winner && winner.id) || '');
  }

  function getSelectedProcess() {
    return state.processes.find(function (process) {
      return String(process.id) === String(state.selectedProcessId);
    }) || null;
  }

  function getProcessExecutions(processId) {
    return state.executions.filter(function (execution) {
      return String(execution.process_id) === String(processId);
    });
  }

  function computeStepCounts(steps, activeExecutions) {
    var out = {};
    (steps || []).forEach(function (step) {
      out[String(step.step_number)] = 0;
    });
    activeExecutions.forEach(function (execution) {
      var currentStepNo = getCurrentStepNumber(execution);
      if (!currentStepNo) return;
      var key = String(currentStepNo);
      out[key] = Number(out[key] || 0) + 1;
    });
    return out;
  }

  function renderProcessSelect() {
    var select = byId('core2-active-process-select');
    if (!select) return;

    if (!state.processes.length) {
      select.innerHTML = '<option value="">No processes</option>';
      return;
    }

    select.innerHTML = state.processes.map(function (process) {
      var pid = String(process.id || '');
      var name = process.name || 'Untitled process';
      var selected = pid === String(state.selectedProcessId) ? ' selected' : '';
      return '<option value="' + escapeHtml(pid) + '"' + selected + '>' + escapeHtml(name) + '</option>';
    }).join('');
  }

  function renderViewToggle() {
    var buttons = document.querySelectorAll('[data-core2-active-view]');
    buttons.forEach(function (btn) {
      var view = btn.getAttribute('data-core2-active-view') || 'pipeline';
      var isActive = view === state.view;
      btn.classList.toggle('core2-active-view-btn--active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    var pipeline = byId('core2-active-pipeline-view');
    var timeline = byId('core2-active-timeline-view');
    if (pipeline) pipeline.hidden = state.view !== 'pipeline';
    if (timeline) timeline.hidden = state.view !== 'timeline';
  }

  function renderStepRail(process, activeExecutions, now) {
    var host = byId('core2-active-step-rail');
    if (!host) return;

    if (!process) {
      host.innerHTML = '<p class="core2-active-batches-empty">No process selected.</p>';
      return;
    }

    var steps = sortSteps(process.steps || []);
    if (!steps.length) {
      host.innerHTML = '<p class="core2-active-batches-empty">This process has no steps defined yet.</p>';
      return;
    }

    var counts = computeStepCounts(steps, activeExecutions);
    var nodes = steps.map(function (step, idx) {
      var stepNo = Number(step.step_number || 0);
      var count = Number(counts[String(stepNo)] || 0);
      var boxClass = count > 0 ? 'core2-step-node-num is-active' : 'core2-step-node-num';
      var nodeTitle = step.name || ('Step ' + String(stepNo));
      var meta = count > 0 ? (String(count) + ' batch' + (count === 1 ? '' : 'es') + ' here') : 'No batches';
      var hasNext = idx < (steps.length - 1);
      return (
        '<div class="core2-step-node">' +
          (hasNext ? '<span class="core2-step-flow-arrow" aria-hidden="true">&#8594;</span>' : '') +
          '<span class="' + boxClass + '">' + escapeHtml(String(stepNo)) + '</span>' +
          (count > 0 ? '<span class="core2-step-node-badge">' + escapeHtml(String(count)) + '</span>' : '') +
          '<p class="core2-step-node-title">' + escapeHtml(nodeTitle) + '</p>' +
          '<p class="core2-step-node-meta">' + escapeHtml(meta) + '</p>' +
        '</div>'
      );
    }).join('');

    var processName = process.name || 'Process';
    var summary = escapeHtml(processName) + ' · ' + escapeHtml(String(steps.length)) + ' steps';

    host.innerHTML =
      '<p class="core2-active-status-note" style="margin-bottom:10px;">' + summary + '</p>' +
      '<div class="core2-step-rail-track" style="--core2-step-count:' + String(steps.length) + '">' + nodes + '</div>';
  }

  function renderStatusSummary(processExecutions, activeExecutions, now) {
    var inflightNode = document.querySelector('[data-core2-inflight-count]');
    var completed7dNode = document.querySelector('[data-core2-completed7d-count]');
    var noteNode = document.querySelector('[data-core2-active-total-note]');

    var sevenDaysAgo = new Date(now.getTime() - (7 * 24 * 3600 * 1000));
    var completed7d = processExecutions.filter(function (execution) {
      if (String(execution.status || '').toLowerCase() !== 'completed') return false;
      var completedAt = toDate(execution.completed_at);
      return completedAt && completedAt >= sevenDaysAgo;
    }).length;

    if (inflightNode) inflightNode.textContent = String(activeExecutions.length);
    if (completed7dNode) completed7dNode.textContent = String(completed7d);
    if (noteNode) noteNode.textContent = 'Showing ' + String(activeExecutions.length) + ' active · sorted by elapsed time';
  }

  function renderPipeline(process, activeExecutions, now) {
    var host = byId('core2-active-pipeline-grid');
    if (!host) return;

    var steps = sortSteps(process && process.steps);
    if (!steps.length) {
      host.style.removeProperty('--core2-step-count');
      host.innerHTML = '<p class="core2-active-batches-empty">No steps to display.</p>';
      return;
    }

    host.style.setProperty('--core2-step-count', String(steps.length));

    var byStep = {};
    steps.forEach(function (step) {
      byStep[String(step.step_number)] = [];
    });

    activeExecutions.forEach(function (execution) {
      var stepNo = getCurrentStepNumber(execution);
      if (!stepNo) return;
      var key = String(stepNo);
      if (!byStep[key]) return;

      var startedAt = toDate(execution.started_at);
      var elapsedMs = startedAt ? (now.getTime() - startedAt.getTime()) : 0;
      var status = classifyExecution(execution, now);
      var batchLabel = extractBatchLabel(execution);
      var currentStepName = execution.current_step && execution.current_step.name ? execution.current_step.name : 'Awaiting start';

      byStep[key].push({
        execution: execution,
        status: status,
        elapsedMs: elapsedMs,
        batchLabel: batchLabel,
        currentStepName: currentStepName,
      });
    });

    var columns = steps.map(function (step) {
      var key = String(step.step_number);
      var rows = byStep[key] || [];
      rows.sort(function (a, b) {
        return Number(b.elapsedMs || 0) - Number(a.elapsedMs || 0);
      });

      var cards = rows.map(function (row) {
        var startedAt = formatDateTime(row.execution.started_at);
        var operator = getExecutionOperator(row.execution);
        var primaryLabel = row.batchLabel || startedAt;
        return (
          '<article class="core2-active-card" data-core2-execution-id="' + escapeHtml(String(row.execution.id || '')) + '">' +
            '<div class="core2-active-card-top">' +
              '<p class="core2-active-card-id">' + escapeHtml(primaryLabel) + '</p>' +
              '<p class="core2-active-card-time">' + escapeHtml(formatDurationMs(row.elapsedMs)) + '</p>' +
            '</div>' +
            '<p class="core2-active-card-name">' + escapeHtml(process.name || 'Process') + '</p>' +
            '<p class="core2-active-card-sub">' + escapeHtml(row.currentStepName) + ' · ' + escapeHtml(operator) + '</p>' +
          '</article>'
        );
      }).join('');

      var empty = '<p class="core2-active-empty">No batches at this step</p>';

      return (
        '<section class="core2-active-column">' +
          '<div class="core2-active-column-head">' +
            '<div>' +
              '<p class="core2-active-column-title">' + escapeHtml(step.name || ('Step ' + String(step.step_number))) + '</p>' +
              '<p class="core2-active-column-meta">Step ' + escapeHtml(String(step.step_number)) + ' of ' + escapeHtml(String(steps.length)) + '</p>' +
            '</div>' +
            '<span class="core2-active-column-badge">' + escapeHtml(String(rows.length)) + '</span>' +
          '</div>' +
          '<div class="core2-active-column-body">' + (cards || empty) + '</div>' +
        '</section>'
      );
    }).join('');

    host.innerHTML = columns;
  }

  function renderTimeline(process, activeExecutions, now) {
    var host = byId('core2-active-timeline');
    if (!host) return;

    if (!activeExecutions.length) {
      host.innerHTML = '<p class="core2-active-batches-empty">No active batches to show in timeline.</p>';
      return;
    }

    var earliestMs = now.getTime();
    activeExecutions.forEach(function (execution) {
      var start = toDate(execution.started_at);
      if (start && start.getTime() < earliestMs) {
        earliestMs = start.getTime();
      }
      (execution.execution_steps || []).forEach(function (step) {
        var stepStart = toDate(step.started_at);
        if (stepStart && stepStart.getTime() < earliestMs) {
          earliestMs = stepStart.getTime();
        }
      });
    });

    var rangeStart = new Date(earliestMs);
    rangeStart.setHours(0, 0, 0, 0);
    var rangeMs = Math.max(1, now.getTime() - rangeStart.getTime());

    function pctFromDate(dt) {
      var ms = Math.min(now.getTime(), Math.max(rangeStart.getTime(), dt.getTime()));
      return ((ms - rangeStart.getTime()) / rangeMs) * 100;
    }

    var marks = [];
    var gridLines = [];
    var dayMs = 24 * 3600 * 1000;
    var totalDays = Math.max(1, Math.ceil(rangeMs / dayMs));
    var viewportWidth = Math.max(320, (host && host.clientWidth) ? host.clientWidth : (window.innerWidth || 1024));
    var maxTicksByViewport = viewportWidth < 640 ? 4 : (viewportWidth < 900 ? 6 : 8);
    var baseTicksByRange = totalDays <= 14 ? 7 : (totalDays <= 60 ? 8 : 9);
    var tickCount = Math.max(3, Math.min(maxTicksByViewport, baseTicksByRange));
    var labelFormat = totalDays > 90
      ? { month: 'short', year: '2-digit' }
      : { month: 'short', day: 'numeric' };

    for (var i = 0; i <= tickCount; i += 1) {
      var tickMs = rangeStart.getTime() + Math.round((rangeMs * i) / tickCount);
      var tickDate = new Date(tickMs);
      var pct = ((tickMs - rangeStart.getTime()) / rangeMs) * 100;
      var label = tickDate.toLocaleDateString('en-US', labelFormat);
      var edgeClass = i === 0 ? ' core2-tl-date-mark--start' : (i === tickCount ? ' core2-tl-date-mark--end' : '');
      marks.push('<span class="core2-tl-date-mark' + edgeClass + '" style="left:' + pct + '%">' + escapeHtml(label) + '</span>');
      gridLines.push('<span class="core2-tl-grid-line" style="left:' + pct + '%"></span>');
    }

    var gridLineHtml = gridLines.join('');

    var head =
      '<div class="core2-tl-head">' +
        '<div class="core2-tl-head-left">Batch</div>' +
        '<div class="core2-tl-head-right">' + gridLineHtml + marks.join('') +
          '<span class="core2-tl-now-label">Now ' + escapeHtml(now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })) + '</span>' +
          '<span class="core2-tl-now-line"></span>' +
        '</div>' +
      '</div>';

    var rows = activeExecutions.slice().sort(function (a, b) {
      var aStart = toDate(a.started_at);
      var bStart = toDate(b.started_at);
      var aMs = aStart ? aStart.getTime() : 0;
      var bMs = bStart ? bStart.getTime() : 0;
      return aMs - bMs;
    }).map(function (execution) {
      var batchLabel = extractBatchLabel(execution);
      var executionSteps = sortSteps(execution.execution_steps || []);
      var startedAt = formatDateTime(execution.started_at);
      var operator = getExecutionOperator(execution);
      var currentStepNo = getCurrentStepNumber(execution);
      var currentStepName = (execution.current_step && execution.current_step.name)
        ? String(execution.current_step.name)
        : 'In progress';
      var primaryLabel = batchLabel || startedAt;
      var executionStart = toDate(execution.started_at) || toDate(execution.created_at) || now;

      var cursorMs = executionStart.getTime();
      var rawSegments = [];
      var openSegmentAdded = false;

      executionSteps.forEach(function (step) {
        var stepNo = Number(step && step.step_number);
        var completedAt = toDate(step && step.completed_at);
        var stepName = step && step.step_name ? String(step.step_name) : ('Step ' + String(stepNo || '?'));

        if (completedAt) {
          var completeMs = completedAt.getTime();
          var endMs = Math.max(cursorMs, completeMs);
          if (endMs > cursorMs) {
            rawSegments.push({
              startMs: cursorMs,
              endMs: endMs,
              stepName: stepName,
              stepNo: stepNo,
            });
            cursorMs = endMs;
          }
          return;
        }

        var status = String(step && step.status || '').toLowerCase();
        if (!openSegmentAdded && (status === 'ready' || status === 'in_progress' || status === 'pending')) {
          rawSegments.push({
            startMs: cursorMs,
            endMs: now.getTime(),
            stepName: stepName,
            stepNo: stepNo,
          });
          cursorMs = now.getTime();
          openSegmentAdded = true;
        }
      });

      if (!rawSegments.length && executionStart.getTime() < now.getTime()) {
        rawSegments.push({
          startMs: executionStart.getTime(),
          endMs: now.getTime(),
          stepName: currentStepName,
          stepNo: currentStepNo,
        });
      }

      var segments = rawSegments.map(function (seg, idx) {
        var startMs = Math.max(seg.startMs, rangeStart.getTime());
        var endMs = Math.min(seg.endMs, now.getTime());
        if (endMs <= startMs) return '';

        var leftPct = ((startMs - rangeStart.getTime()) / rangeMs) * 100;
        var widthPct = ((endMs - startMs) / rangeMs) * 100;
        var width = Math.max(0.8, widthPct);
        var colorClass = stepColorClass(Number.isFinite(Number(seg.stepNo)) ? (Number(seg.stepNo) - 1) : idx);
        var label = seg.stepName + ' · ' + formatDurationMs(endMs - startMs);

        return '<div class="core2-tl-segment ' + colorClass + '" style="left:' + leftPct + '%;width:' + width + '%" title="' + escapeHtml(label) + '">' + escapeHtml(label) + '</div>';
      }).filter(Boolean).join('');

      return (
        '<div class="core2-tl-row" data-core2-execution-id="' + escapeHtml(String(execution.id || '')) + '">' +
          '<div class="core2-tl-left">' +
            '<p class="core2-tl-batch-name">' + escapeHtml(primaryLabel) + '</p>' +
            '<p class="core2-tl-batch-meta">' + escapeHtml(startedAt) + ' · ' + escapeHtml(operator) + ' · ' + escapeHtml(currentStepName) + '</p>' +
          '</div>' +
          '<div class="core2-tl-right">' + gridLineHtml + segments + '</div>' +
        '</div>'
      );
    }).join('');

    host.innerHTML = head + rows;
  }

  function renderDetailSteps(execution) {
    var host = byId('core2-active-detail-steps');
    if (!host) return;

    var steps = sortSteps(execution && execution.execution_steps);
    if (!steps.length) {
      host.innerHTML = '<p class="core2-active-batches-empty">No step metadata available.</p>';
      return;
    }

    host.innerHTML = steps.map(function (step) {
      var stepName = step.step_name || ('Step ' + String(step.step_number || '?'));
      var status = String(step.status || '').replace(/_/g, ' ');
      var operator = (step.execution_data && (step.execution_data.completed_by || step.execution_data.completed_by_email || step.execution_data.completed_by_user_id)) || 'n/a';
      var at = formatDateTime(step.completed_at || step.started_at);
      var outputs = Array.isArray(step.actual_outputs) ? step.actual_outputs : [];

      var outputsHtml = outputs.length
        ? '<ul class="core2-active-detail-output-list">' + outputs.map(function (output) {
            if (!output || typeof output !== 'object') return '<li>Output recorded</li>';
            var name = output.name || output.output_name || 'Output';
            var qty = output.quantity != null ? String(output.quantity) : null;
            var unit = output.unit || null;
            var lot = output.batch_id || output.batchId || output.lot_id || output.lotId || output.lot || null;
            var parts = [name];
            if (qty || unit) {
              parts.push((qty ? qty : '') + (unit ? (' ' + unit) : ''));
            }
            if (lot) {
              parts.push('batch/lot: ' + String(lot));
            }
            return '<li>' + escapeHtml(parts.join(' · ')) + '</li>';
          }).join('') + '</ul>'
        : '<p>No outputs recorded.</p>';

      return (
        '<article class="core2-active-detail-step">' +
          '<h4>Step ' + escapeHtml(String(step.step_number || '?')) + ' · ' + escapeHtml(stepName) + '</h4>' +
          '<p>Status: ' + escapeHtml(status) + '</p>' +
          '<p>Operator: ' + escapeHtml(String(operator)) + '</p>' +
          '<p>Timestamp: ' + escapeHtml(at) + '</p>' +
          outputsHtml +
        '</article>'
      );
    }).join('');
  }

  function openDetail(executionId) {
    var overlay = byId('core2-active-detail-overlay');
    if (!overlay) return;

    var execution = state.executions.find(function (item) {
      return String(item.id) === String(executionId);
    });
    var process = getSelectedProcess();
    if (!execution || !process) return;

    var idNode = byId('core2-active-detail-id');
    var processNode = byId('core2-active-detail-process');
    var startedNode = byId('core2-active-detail-started');
    var actionNode = byId('core2-active-detail-next-step');

    if (idNode) idNode.textContent = extractBatchLabel(execution) || formatDateTime(execution.started_at);
    if (processNode) processNode.textContent = 'Process: ' + (process.name || 'Unknown process');
    if (startedNode) startedNode.textContent = 'Started: ' + formatDateTime(execution.started_at);
    if (actionNode) {
      actionNode.href = '/core/flows/batches/start?id=' + encodeURIComponent(String(process.id)) + '&execution_id=' + encodeURIComponent(String(execution.id));
    }

    renderDetailSteps(execution);
    overlay.hidden = false;
    document.body.classList.add('core2-active-detail-open');
  }

  function closeDetail() {
    var overlay = byId('core2-active-detail-overlay');
    if (!overlay) return;
    overlay.hidden = true;
    document.body.classList.remove('core2-active-detail-open');
  }

  function resetDetailUiState() {
    var overlay = byId('core2-active-detail-overlay');
    if (overlay) {
      overlay.hidden = true;
    }
    document.body.classList.remove('core2-active-detail-open');
  }

  function setPanelVisibility(visible) {
    var panel = byId('core2-active-batches-panel');
    if (panel) {
      panel.hidden = !visible;
    }
    if (!visible) {
      closeDetail();
    }
  }

  function bindInteractions() {
    resetDetailUiState();

    var processSelect = byId('core2-active-process-select');
    if (processSelect && !processSelect.dataset.boundCore2Active) {
      processSelect.addEventListener('change', function (event) {
        state.selectedProcessId = String(event.target.value || '');
        renderAll();
      });
      processSelect.dataset.boundCore2Active = '1';
    }

    document.querySelectorAll('[data-core2-active-view]').forEach(function (btn) {
      if (btn.dataset.boundCore2Active) return;
      btn.addEventListener('click', function () {
        state.view = btn.getAttribute('data-core2-active-view') || 'pipeline';
        renderViewToggle();
      });
      btn.dataset.boundCore2Active = '1';
    });

    var pipelineHost = byId('core2-active-pipeline-grid');
    if (pipelineHost && !pipelineHost.dataset.boundCore2Active) {
      pipelineHost.addEventListener('click', function (event) {
        var card = event.target && event.target.closest ? event.target.closest('[data-core2-execution-id]') : null;
        if (!card) return;
        var executionId = card.getAttribute('data-core2-execution-id') || '';
        if (!executionId) return;
        openDetail(executionId);
      });
      pipelineHost.dataset.boundCore2Active = '1';
    }

    var timelineHost = byId('core2-active-timeline');
    if (timelineHost && !timelineHost.dataset.boundCore2Active) {
      timelineHost.addEventListener('click', function (event) {
        var row = event.target && event.target.closest ? event.target.closest('[data-core2-execution-id]') : null;
        if (!row) return;
        var executionId = row.getAttribute('data-core2-execution-id') || '';
        if (!executionId) return;
        openDetail(executionId);
      });
      timelineHost.dataset.boundCore2Active = '1';
    }

    var overlay = byId('core2-active-detail-overlay');
    if (overlay && !overlay.dataset.boundCore2Active) {
      overlay.addEventListener('click', function (event) {
        if (event.target === overlay) closeDetail();
      });

      overlay.querySelectorAll('[data-core2-detail-close]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          closeDetail();
        });
      });

      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !overlay.hidden) {
          closeDetail();
        }
      });

      overlay.dataset.boundCore2Active = '1';
    }
  }

  function renderAll() {
    var hasAnyActive = state.executions.some(isActiveExecution);
    setPanelVisibility(hasAnyActive);
    if (!hasAnyActive) {
      return;
    }

    renderProcessSelect();
    renderViewToggle();

    var process = getSelectedProcess();
    var now = new Date();
    var processExecutions = process ? getProcessExecutions(process.id) : [];
    var activeExecutions = processExecutions.filter(isActiveExecution);

    renderStepRail(process, activeExecutions, now);
    renderStatusSummary(processExecutions, activeExecutions, now);

    if (process) {
      renderPipeline(process, activeExecutions, now);
      renderTimeline(process, activeExecutions, now);
    } else {
      var pipelineHost = byId('core2-active-pipeline-grid');
      var timelineHost = byId('core2-active-timeline');
      if (pipelineHost) pipelineHost.innerHTML = '<p class="core2-active-batches-empty">No process selected.</p>';
      if (timelineHost) timelineHost.innerHTML = '<p class="core2-active-batches-empty">No process selected.</p>';
    }
  }

  async function loadData() {
    var panel = byId('core2-active-pipeline-grid');
    if (!panel) return;

    if (!window.CoreAPI || typeof window.CoreAPI.getProcesses !== 'function' || typeof window.CoreAPI.getExecutions !== 'function') {
      return;
    }

    var requestId = ++latestRequest;

    try {
      var results = await Promise.all([
        window.CoreAPI.getProcesses(true),
        window.CoreAPI.getExecutions(),
      ]);
      if (requestId !== latestRequest) return;

      state.processes = (results[0] && results[0].processes) ? results[0].processes : [];
      state.executions = (results[1] && results[1].executions) ? results[1].executions : [];

      var selectedStillExists = state.processes.some(function (process) {
        return String(process.id) === String(state.selectedProcessId);
      });
      if (!selectedStillExists) {
        state.selectedProcessId = chooseDefaultProcessId(state.processes, state.executions);
      }

      renderAll();
      bindInteractions();
    } catch (err) {
      console.error('Failed to load active batches panel', err);
      var stepRail = byId('core2-active-step-rail');
      var pipeline = byId('core2-active-pipeline-grid');
      var timeline = byId('core2-active-timeline');
      if (stepRail) stepRail.innerHTML = '<p class="core2-active-batches-empty">Could not load active batches data.</p>';
      if (pipeline) pipeline.innerHTML = '<p class="core2-active-batches-empty">Could not load active batches data.</p>';
      if (timeline) timeline.innerHTML = '<p class="core2-active-batches-empty">Could not load active batches data.</p>';
    }
  }

  function queueLoad() {
    if (loadTimer) {
      window.clearTimeout(loadTimer);
      loadTimer = null;
    }

    loadTimer = window.setTimeout(function () {
      loadData();
    }, 60);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', queueLoad);
  } else {
    queueLoad();
  }

  document.body.addEventListener('htmx:afterSettle', function () {
    if (byId('core2-active-pipeline-grid')) {
      queueLoad();
    }
  });
})();
