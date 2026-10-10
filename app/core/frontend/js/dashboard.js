(function () {
    'use strict';

    var ROOT_SELECTOR = '[data-dashboard-root]';

    function byData(root, selector) {
        return root.querySelector(selector);
    }

    function setText(root, selector, value) {
        var node = byData(root, selector);
        if (!node) return;
        node.textContent = value == null ? '' : String(value);
    }

    function formatPct(value) {
        if (value == null || Number.isNaN(Number(value))) return 'n/a';
        var n = Number(value);
        return (n > 0 ? '+' : '') + n.toFixed(1) + '%';
    }

    function formatCurrency(value) {
        var safe = Number(value || 0);
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            maximumFractionDigits: 0,
        }).format(safe);
    }

    function formatCurrencyVariance(value) {
        if (value == null || Number.isNaN(Number(value))) return 'n/a';
        var n = Number(value);
        var amount = formatCurrency(Math.abs(n));
        if (n > 0) return '+' + amount;
        if (n < 0) return '-' + amount;
        return amount;
    }

    function formatGoalPct(value) {
        if (value == null || Number.isNaN(Number(value))) return 'n/a';
        return Number(value).toFixed(1) + '%';
    }

    function severityLabel(level) {
        var normalized = String(level || '').toLowerCase();
        if (!normalized) return 'Action';
        return normalized.charAt(0).toUpperCase() + normalized.slice(1);
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatDateTime(raw) {
        if (!raw) return 'Unknown time';
        var d = new Date(raw);
        if (Number.isNaN(d.getTime())) return raw;
        var time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
        var now = new Date();
        if (d.toDateString() === now.toDateString()) return time;
        return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) + ', ' + time;
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    var SEVERITY_ORDER = { critical: 0, high: 1, warning: 2, medium: 2, low: 3, informational: 4 };

    function renderActionList(root, actionBoard) {
        var list = byData(root, '[data-action-list]');
        if (!list) return;

        var rows = (actionBoard && Array.isArray(actionBoard.items)) ? actionBoard.items.slice() : [];
        list.replaceChildren();
        if (rows.length === 0) {
            var empty = el('li', 'dash-empty');
            empty.appendChild(el('strong', '', 'Nothing needs you right now'));
            empty.appendChild(el('span', '', 'Findings, overdue work and expiring stock will show here.'));
            list.appendChild(empty);
            return;
        }

        function rank(item) {
            var value = SEVERITY_ORDER[String(item.severity || '').toLowerCase()];
            return value == null ? 3 : value;
        }
        rows.sort(function (a, b) { return rank(a) - rank(b); });

        rows.forEach(function (item) {
            var severity = String(item.severity || '').toLowerCase();
            var href = typeof item.href === 'string' && item.href.charAt(0) === '/' ? item.href : '/core/notifications';
            var li = el('li', 'dash-attention__item');
            var link = el('a', 'dash-attention__row dash-attention__row--' + (severity || 'action'));
            link.href = href;
            link.appendChild(el('span', 'dash-attention__dot'));
            var main = el('span', 'dash-attention__main');
            main.appendChild(el('span', 'dash-attention__title', item.label || 'Action item'));
            var priority = severity === 'informational' ? 'For information' : severityLabel(item.severity) + ' priority';
            main.appendChild(el('span', 'dash-attention__meta', (item.workspace || 'Workspace') + ' · ' + priority));
            link.appendChild(main);
            link.appendChild(el('span', 'dash-attention__count', String(Number(item.count || 0))));
            link.appendChild(el('span', 'dash-attention__go', '›'));
            li.appendChild(link);
            list.appendChild(li);
        });
    }

    var COMPLIANCE_STATES = {
        healthy: 'On track',
        degraded: 'Needs attention',
        critical: 'Action required',
        unknown: 'No checks run yet',
    };

    /* One compliance figure for the whole business and the parts it is the mean of. */
    function renderCompliance(root, overall) {
        var card = byData(root, '[data-dashboard-compliance]');
        if (!card) return;
        var parts = overall && Array.isArray(overall.components) ? overall.components : [];
        card.hidden = !parts.length;
        if (!parts.length) return;

        var state = COMPLIANCE_STATES[overall.state] ? overall.state : 'unknown';
        var score = Math.max(0, Math.min(100, Math.round(Number(overall.score) || 0)));
        card.dataset.complianceLevel = state;
        setText(root, '[data-compliance-score]', score);
        setText(root, '[data-compliance-state]', COMPLIANCE_STATES[state]);
        var arc = byData(root, '[data-compliance-arc]');
        // As a style, not an attribute: the stylesheet's resting value would win over an attribute.
        if (arc) arc.style.strokeDasharray = score + ' 100';
        var ring = byData(root, '[data-compliance-ring]');
        if (ring) ring.setAttribute('aria-label', 'Compliance score ' + score + ' out of 100, ' + COMPLIANCE_STATES[state].toLowerCase());

        var list = byData(root, '[data-compliance-parts]');
        if (!list) return;
        list.replaceChildren();
        parts.forEach(function (part) {
            var partState = COMPLIANCE_STATES[part.state] ? part.state : 'unknown';
            var partScore = Math.max(0, Math.min(100, Math.round(Number(part.score) || 0)));
            var li = el('li');
            var link = el('a', 'dash-part dash-part--' + partState);
            link.href = typeof part.href === 'string' && part.href.charAt(0) === '/' && part.href.charAt(1) !== '/' ? part.href : '/core';
            var head = el('span', 'dash-part__head');
            head.appendChild(el('span', 'dash-part__label', part.label || 'Compliance'));
            head.appendChild(el('strong', 'dash-part__score', String(partScore)));
            link.appendChild(head);
            var bar = el('span', 'dash-part__bar');
            var fill = el('span');
            fill.style.width = partScore + '%';
            bar.appendChild(fill);
            link.appendChild(bar);
            link.appendChild(el('span', 'dash-part__detail', part.detail || ''));
            li.appendChild(link);
            list.appendChild(li);
        });
    }

    function pluralize(count, singular, plural) {
        return String(count) + ' ' + (count === 1 ? singular : (plural || singular + 's'));
    }

    /* With one compliance module the tile opens it directly; with several, the workspace.
       The module's score and evidence count are in the Compliance card, not repeated here. */
    function linkCompliantTile(root, compliantWorkspace) {
        var card = byData(root, '[data-dashboard-compliant-card]');
        var cardLink = byData(root, '[data-dashboard-compliant-link]');
        if (!card || !cardLink) return;
        var modules = Array.isArray((compliantWorkspace || {}).modules) ? compliantWorkspace.modules : [];
        var onlyModule = modules.length === 1 ? modules[0] : null;
        card.href = onlyModule && typeof onlyModule.href === 'string' && onlyModule.href.charAt(0) === '/'
            ? onlyModule.href
            : '/compliant';
        card.setAttribute('aria-label', onlyModule ? String(onlyModule.action_label || 'Open module') : 'Open Compliance workspace');
        cardLink.textContent = onlyModule ? String(onlyModule.action_label || 'Open module') + ' →' : 'Open Compliance →';
    }

    function renderWorkspaceSummaries(root, operations, compliantWorkspace, tasks, sales) {
        var activeBatches = Number((operations || {}).active_executions || 0);
        setText(
            root,
            '[data-dashboard-core-summary]',
            activeBatches ? pluralize(activeBatches, 'active batch', 'active batches') + ' in progress.' : 'No active batches right now.'
        );

        var compliant = compliantWorkspace || {};
        setText(
            root,
            '[data-dashboard-compliant-summary]',
            compliant.label || 'Compliance is not enabled for this organisation.'
        );
        linkCompliantTile(root, compliant);

        var safeTasks = tasks || {};
        var safeSales = sales || {};
        var taskCount = Number(safeTasks.due_this_week_count || 0);
        if (safeTasks.enabled === false) {
            setText(root, '[data-dashboard-crm-summary]', 'Sales is not enabled for this organisation.');
        } else if (taskCount) {
            setText(root, '[data-dashboard-crm-summary]', pluralize(taskCount, 'customer task') + ' due this week.');
        } else if (safeSales.baseline_target_mtd != null) {
            setText(root, '[data-dashboard-crm-summary]', 'Revenue is tracking ' + formatGoalPct(safeSales.baseline_attainment_pct) + ' of the monthly baseline.');
        } else {
            setText(root, '[data-dashboard-crm-summary]', 'No customer tasks due this week.');
        }
    }

    var AUDIT_VISIBLE = 6;

    function renderAuditList(root, auditLog, selectedPeriod) {
        var list = byData(root, '[data-audit-list]');
        var meta = byData(root, '[data-audit-meta]');
        var more = byData(root, '[data-audit-more]');
        if (!list) return;

        var key = selectedPeriod === 'week' ? 'week' : 'day';
        var bucket = (auditLog && auditLog[key]) ? auditLog[key] : { total: 0, items: [] };
        var rows = Array.isArray(bucket.items) ? bucket.items : [];
        var total = Number(bucket.total || 0);
        var periodLabel = key === 'week' ? 'this week' : 'today';

        if (meta) {
            meta.textContent = total === 0
                ? 'Nothing recorded ' + periodLabel + '.'
                : String(total) + (total === 1 ? ' entry ' : ' entries ') + periodLabel +
                    (total > rows.length ? ', latest first.' : '.');
        }

        list.replaceChildren();
        rows.forEach(function (row, index) {
            var li = el('li', 'dash-activity__row');
            li.hidden = index >= AUDIT_VISIBLE;
            var body = el('div', 'dash-activity__body');
            body.appendChild(el('span', 'dash-activity__text', row.summary || row.event_type || 'Activity'));
            var details = Array.isArray(row.details) ? row.details : [];
            if (details.length) {
                var disclosure = el('details', 'dash-activity__details');
                disclosure.appendChild(el('summary', '', 'View ' + details.length + ' sale update' + (details.length === 1 ? '' : 's')));
                var inner = el('ul');
                details.forEach(function (detail) { inner.appendChild(el('li', '', detail)); });
                disclosure.appendChild(inner);
                body.appendChild(disclosure);
            }
            li.appendChild(body);
            li.appendChild(el('span', 'dash-activity__meta', (row.actor || 'System') + ' · ' + formatDateTime(row.at)));
            list.appendChild(li);
        });

        if (more) {
            var extra = rows.length - AUDIT_VISIBLE;
            more.hidden = extra <= 0;
            more.textContent = 'Show ' + extra + ' more';
            more.onclick = function () {
                Array.prototype.forEach.call(list.children, function (li) { li.hidden = false; });
                more.hidden = true;
            };
        }
    }

    function safeTrendSeries(series) {
        if (!series || !Array.isArray(series.points) || series.points.length === 0) {
            return {
                start_label: '',
                end_label: '',
                points: [{ value: 0 }],
            };
        }
        return series;
    }

    function buildLinePath(points, chartW, chartH, padX, padY) {
        var vals = points.map(function (pt) { return Number(pt.value || 0); });
        var min = Math.min.apply(Math, vals);
        var max = Math.max.apply(Math, vals);
        var range = max - min;
        var denom = range <= 0 ? 1 : range;
        var flat = range <= 0;
        var step = points.length <= 1 ? 0 : chartW / (points.length - 1);

        var coords = points.map(function (pt, idx) {
            var value = Number(pt.value || 0);
            var x = padX + (idx * step);
            var y = flat ? (padY + (chartH / 2)) : (padY + chartH - (((value - min) / denom) * chartH));
            if (!Number.isFinite(y)) y = padY + chartH;
            return { x: x, y: y };
        });

        var line = coords.map(function (pt, idx) {
            return (idx === 0 ? 'M' : 'L') + pt.x.toFixed(2) + ' ' + pt.y.toFixed(2);
        }).join(' ');

        return { path: line, coords: coords };
    }

    function renderSparkLine(root, key, series) {
        var host = byData(root, '[data-kpi-spark="' + key + '"]');
        if (!host) return;

        var safeSeries = safeTrendSeries(series);
        var points = safeSeries.points;
        // A flat line says nothing and reads as a rule under the number; draw only what moves.
        var values = points.map(function (pt) { return Number(pt.value || 0); });
        var moves = values.length > 1 && Math.max.apply(Math, values) !== Math.min.apply(Math, values);
        host.hidden = !moves;
        if (!moves) { host.replaceChildren(); return; }

        var width = 160;
        var height = 32;
        var padX = 4;
        var padY = 4;
        var chartW = width - (padX * 2);
        var chartH = height - (padY * 2);

        var built = buildLinePath(points, chartW, chartH, padX, padY);
        var circles = built.coords.map(function (pt) {
            return '<circle cx="' + pt.x.toFixed(2) + '" cy="' + pt.y.toFixed(2) + '" r="1.9"></circle>';
        }).join('');

        // nosemgrep: innerhtml-string-concat -- audited: all dynamic values here go through escapeHtml() or are numeric
        host.innerHTML =
            '<svg class="dash-kpi-trend-svg" viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="none" aria-hidden="true">' +
            '<path class="dash-kpi-trend-line" d="' + built.path + '"></path>' +
            circles +
            '</svg>' +
            '<div class="dash-kpi-trend-range">' +
            '<span>' + escapeHtml(safeSeries.start_label || '') + '</span>' +
            '<span>' + escapeHtml(safeSeries.end_label || '') + '</span>' +
            '</div>';
    }

    function wireAuditPeriodToggle(root, auditLog) {
        var buttons = root.querySelectorAll('[data-audit-period]');
        var current = root.dataset.auditPeriod === 'week' ? 'week' : 'day';
        function apply() {
            root.dataset.auditPeriod = current;
            Array.prototype.forEach.call(buttons, function (button) {
                button.setAttribute('aria-pressed', button.dataset.auditPeriod === current ? 'true' : 'false');
            });
            renderAuditList(root, auditLog, current);
        }
        Array.prototype.forEach.call(buttons, function (button) {
            // Reassigned on every summary refresh so the handler always closes over fresh data.
            button.onclick = function () {
                current = button.dataset.auditPeriod === 'week' ? 'week' : 'day';
                apply();
            };
        });
        apply();
    }

    function renderPlannedWork(root, work) {
        var list = byData(root, '[data-planned-work-list]');
        if (!list) return;
        list.replaceChildren();
        if (!work) {
            setText(root, '[data-planned-work-summary]', 'Planned production is unavailable.');
            return;
        }
        setText(root, '[data-planned-work-summary]', work.total
            ? work.total + ' batch(es) proposed for today or earlier, highest priority first. Review checks on the board before starting.'
            : 'No planned batches proposed for today or earlier.');
        (work.items || []).forEach(function (batch) {
            var item = document.createElement('li');
            item.dataset.plannedBatchId = batch.id;
            var title = document.createElement('strong');
            title.textContent = batch.reference + ' · Batch ' + batch.batch_number;
            var detail = document.createElement('p');
            detail.textContent = batch.quantity + ' ' + batch.unit + ' · ' + batch.product_name + ' · ' + batch.site_name;
            var state = document.createElement('p');
            state.textContent = 'Priority ' + batch.priority + ' · Proposed ' + batch.proposed_start_date
                + (batch.overdue ? ' · Overdue' : '') + (batch.pinned ? ' · Pinned' : '')
                + (batch.status === 'blocked' ? ' · Checks pending' : '');
            item.append(title, detail, state);
            list.append(item);
        });
        if (work.truncated) {
            var more = document.createElement('li');
            more.textContent = 'Showing the first 20 batches. Review the production board for the rest.';
            list.append(more);
        }
    }

    function renderDashboard(root, data) {
        var tasks = data.tasks || {};
        var operations = data.operations || {};
        var sales = data.sales || {};
        var compliantWorkspace = data.compliant_workspace || {};
        var actionBoard = data.action_board || {};
        var operatorActions = data.operator_actions || {};
        var auditLog = data.audit_log || {};
        var insightSeries = data.insight_series || {};

        var now = new Date();
        setText(root, '[data-dashboard-date]', now.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }));
        setText(root, '[data-dashboard-today]', now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' }));

        setText(root, '[data-kpi-operator-actions]', operatorActions.week_to_date || 0);
        setText(root, '[data-kpi-active-batches]', operations.active_executions || 0);
        setText(root, '[data-kpi-open-action-items]', actionBoard.critical_actions_total || 0);
        var openActions = byData(root, '[data-open-actions-figure]');
        if (openActions) openActions.classList.toggle('dash-figure--attention', Number(actionBoard.critical_actions_total || 0) > 0);
        setText(root, '[data-kpi-tasks-week]', tasks.due_this_week_count || 0);
        setText(root, '[data-kpi-overdue]', tasks.overdue_count || 0);
        setText(root, '[data-kpi-throughput-vs-last-week]', formatPct(operations.completed_vs_last_week_pct));
        var throughputCard = byData(root, '[data-kpi-throughput-card]');
        var throughputFallback = byData(root, '[data-kpi-throughput-fallback]');
        if (throughputCard) throughputCard.hidden = operations.completed_vs_last_week_pct == null;
        if (throughputFallback) throughputFallback.hidden = operations.completed_vs_last_week_pct != null;
        var failedFigure = byData(root, '[data-ops-failed-figure]');
        if (failedFigure) failedFigure.classList.toggle('dash-figure--alert', Number(operations.failed_or_cancelled_this_week || 0) > 0);

        renderSparkLine(root, 'operator_actions', insightSeries.operator_actions_week);
        renderSparkLine(root, 'open_action_items', insightSeries.open_action_items);
        renderSparkLine(root, 'active_batches', insightSeries.active_batches_week);
        renderSparkLine(root, 'monthly_goal', insightSeries.revenue_goal_mtd);
        renderSparkLine(root, 'tasks_week', insightSeries.tasks_due_week);
        renderSparkLine(root, 'throughput_vs_week', insightSeries.batch_completion_week);

        renderPlannedWork(root, data.planned_work);
        renderActionList(root, actionBoard);
        renderCompliance(root, data.compliance_overall);
        renderWorkspaceSummaries(root, operations, compliantWorkspace, tasks, sales);
        wireAuditPeriodToggle(root, auditLog);

        setText(root, '[data-ops-started-week]', operations.started_this_week || 0);
        setText(root, '[data-ops-completed-week]', operations.completed_this_week || 0);
        setText(root, '[data-ops-failed-week]', operations.failed_or_cancelled_this_week || 0);

        setText(root, '[data-sales-revenue-mtd]', formatCurrency(sales.current_month_revenue));
        if (sales.enabled === false) {
            setText(root, '[data-sales-caption]', 'Sales is turned off');
        } else if (sales.baseline_target_mtd == null) {
            setText(root, '[data-sales-caption]', 'Set a target to track it');
        } else {
            setText(root, '[data-sales-caption]', formatGoalPct(sales.baseline_attainment_pct) + ' of ' +
                formatCurrency(sales.baseline_target_mtd) + ' target');
        }
    }

    /* The access-denied notice and the go-live strip. Both were inline scripts in the template. */
    var GO_LIVE_HIDDEN_KEY = 'dashboard.goLiveHidden';

    function wireNotices(root) {
        var params = new URLSearchParams(window.location.search);
        if (params.get('denied') === '1') {
            var denied = byData(root, '[data-dashboard-denied]');
            if (denied) denied.hidden = false;
            params.delete('denied');
            var rest = params.toString();
            window.history.replaceState(window.history.state, '', window.location.pathname + (rest ? '?' + rest : ''));
        }

        var strip = byData(root, '[data-dashboard-go-live]');
        if (!strip) return;
        var dismissed = false;
        try { dismissed = window.localStorage.getItem(GO_LIVE_HIDDEN_KEY) === '1'; } catch (e) { /* private mode */ }
        if (dismissed) return;
        var hide = byData(root, '[data-dashboard-go-live-hide]');
        if (hide) {
            hide.addEventListener('click', function () {
                strip.hidden = true;
                try { window.localStorage.setItem(GO_LIVE_HIDDEN_KEY, '1'); } catch (e) { /* private mode */ }
            });
        }
        fetch('/api/core/go-live', { credentials: 'include', headers: { Accept: 'application/json' } })
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (state) {
                if (state && !state.go_live_date && strip.isConnected) strip.hidden = false;
            })
            .catch(function () { /* the strip is an invitation, not a requirement */ });
    }

    var pendingLoad = null;

    function abortPendingLoad() {
        if (pendingLoad) {
            pendingLoad.abort();
            pendingLoad = null;
        }
    }

    async function loadDashboard(root, options) {
        var loading = byData(root, '[data-dashboard-loading]');
        var error = byData(root, '[data-dashboard-error]');
        // A background refresh must not flash "Loading" under a page that is already drawn.
        if (loading) loading.hidden = !!(options && options.quiet);
        if (error) error.hidden = true;

        abortPendingLoad();
        var controller = new AbortController();
        pendingLoad = controller;

        try {
            if (!window.CoreAPI || typeof window.CoreAPI.getDashboardSummary !== 'function') {
                throw new Error('Dashboard API client unavailable');
            }
            var data = await window.CoreAPI.getDashboardSummary(30, { signal: controller.signal });
            if (!root.isConnected) return;
            renderDashboard(root, data || {});
            if (loading) loading.hidden = true;
        } catch (err) {
            // The request was aborted because the page navigated away (hx-boost swaps
            // the dashboard root out mid-flight). Nothing to show an error on.
            if ((err && err.name === 'AbortError') || !root.isConnected) return;
            console.error('Failed to load dashboard summary', err);
            if (loading) loading.hidden = true;
            if (error) {
                error.hidden = false;
                error.textContent = 'Could not load dashboard summary. Refresh and try again.';
            }
            // A real failure: let a later htmx:afterSettle retry (a navigation-abort
            // returned above and never gets here).
            delete root.dataset.dashboardLoaded;
        } finally {
            if (pendingLoad === controller) pendingLoad = null;
            delete root.dataset.dashboardLoading;
        }
    }

    function initDashboardPage() {
        var root = document.querySelector(ROOT_SELECTOR);
        if (!root) return;
        // DOMContentLoaded and htmx:afterSettle can both fire for one navigation; don't
        // start a second fetch over a root that is already loading or rendered.
        if (root.dataset.dashboardLoading === '1' || root.dataset.dashboardLoaded === '1') return;
        root.dataset.dashboardLoading = '1';
        root.dataset.dashboardLoaded = '1';
        wireNotices(root);
        loadDashboard(root);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDashboardPage);
    } else {
        initDashboardPage();
    }

    // This file sits inside #page-content, so it runs again on every boosted visit. The page
    // root is new each time; the document is not, so its listeners are bound once and reach
    // whichever run is current through window.
    window.__dashboardInit = initDashboardPage;
    window.__dashboardAbort = abortPendingLoad;
    if (!window.__dashboardShellBound) {
        window.__dashboardShellBound = true;
        document.body.addEventListener('htmx:afterSettle', function () {
            if (document.querySelector(ROOT_SELECTOR)) window.__dashboardInit();
        });
        // Cancel an in-flight summary fetch the moment the page starts to go away, so it
        // doesn't surface as a "Failed to fetch" error against a detached root.
        document.body.addEventListener('htmx:beforeSwap', function () { window.__dashboardAbort(); });
        window.addEventListener('pagehide', function () { window.__dashboardAbort(); });
    }

    // Live: the summary aggregates batches, tasks and events -- refresh it when a
    // colleague changes any of those, debounced so a burst is one reload. live-sync.js
    // loads *after* #page-content (this script), so defer the subscribe until it exists.
    var liveTimer = null;
    function subscribeDashboardLive() {
        window.LiveSync.subscribe({
            key: 'dashboard',
            match: function (evt) {
                var t = evt.entity_type;
                return t === 'process' || t === 'execution' || t === 'execution_step' || t === 'inventory_item' || t === 'operational_case';
            },
            onChange: function () {
                if (liveTimer) return;
                liveTimer = setTimeout(function () {
                    liveTimer = null;
                    var root = document.querySelector(ROOT_SELECTOR);
                    if (!root) return;
                    delete root.dataset.dashboardLoaded;
                    delete root.dataset.dashboardLoading;
                    loadDashboard(root);
                    if (typeof window.liveSyncFlash === 'function') window.liveSyncFlash('Updated just now');
                }, 500);
            },
        });
    }
    // A wall screen nobody touches still has to stay current, and not every change that moves
    // a figure is an event LiveSync carries (evidence falling due, a date rolling over).
    var REFRESH_MS = 60000;
    if (window.__dashboardTimer) clearInterval(window.__dashboardTimer);
    window.__dashboardTimer = setInterval(function () {
        var root = document.querySelector(ROOT_SELECTOR);
        if (!root) { clearInterval(window.__dashboardTimer); window.__dashboardTimer = null; return; }
        if (document.visibilityState === 'hidden' || root.dataset.dashboardLoading === '1') return;
        loadDashboard(root, { quiet: true });
    }, REFRESH_MS);

    if (window.LiveSync) {
        subscribeDashboardLive();
    } else {
        document.addEventListener('DOMContentLoaded', function () {
            if (window.LiveSync) subscribeDashboardLive();
        });
    }
})();
