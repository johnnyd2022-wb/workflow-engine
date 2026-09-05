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
        return d.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
        });
    }

    function renderActionList(root, actionBoard) {
        var list = byData(root, '[data-action-list]');
        if (!list) return;

        var rows = (actionBoard && Array.isArray(actionBoard.items)) ? actionBoard.items : [];
        if (rows.length === 0) {
            list.innerHTML = '<li class="dash-empty">No critical actions right now.</li>';
            return;
        }

        list.innerHTML = rows.map(function (item) {
            var href = item.href || '/core/notifications';
            var label = item.label || 'Action item';
            var count = Number(item.count || 0);
            var sev = severityLabel(item.severity);
            var sevLower = String(item.severity || '').toLowerCase();
            var priorityText = sevLower === 'informational' ? (sev + ' only') : (sev + ' priority');
            var workspace = item.workspace || 'Workspace';
            return (
                '<li class="dash-list-item">' +
                '<div class="dash-action-row">' +
                '<div class="dash-action-main">' +
                '<p class="dash-action-title"><span class="dash-action-workspace">' + escapeHtml(workspace) + '</span>' + escapeHtml(label) + '</p>' +
                '<p class="dash-action-meta">' + escapeHtml(priorityText) + ' · <a class="dash-action-link" href="' + escapeHtml(href) + '">Open</a></p>' +
                '</div>' +
                '<div class="dash-action-count">' + escapeHtml(String(count)) + '</div>' +
                '</div>' +
                '</li>'
            );
        }).join('');
    }

    function pluralize(count, singular, plural) {
        return String(count) + ' ' + (count === 1 ? singular : (plural || singular + 's'));
    }

    function renderWorkspaceSummaries(root, operations, compliantWorkspace, tasks, sales) {
        var activeBatches = Number((operations || {}).active_executions || 0);
        setText(
            root,
            '[data-dashboard-core-summary]',
            activeBatches ? pluralize(activeBatches, 'active batch') + ' in progress.' : 'No active batches right now.'
        );

        var compliant = compliantWorkspace || {};
        setText(
            root,
            '[data-dashboard-compliant-summary]',
            compliant.label || 'Compliant is not enabled for this organisation.'
        );

        var safeTasks = tasks || {};
        var safeSales = sales || {};
        var taskCount = Number(safeTasks.due_this_week_count || 0);
        if (safeTasks.enabled === false) {
            setText(root, '[data-dashboard-crm-summary]', 'CRM is not enabled for this organisation.');
        } else if (taskCount) {
            setText(root, '[data-dashboard-crm-summary]', pluralize(taskCount, 'customer task') + ' due this week.');
        } else if (safeSales.baseline_target_mtd != null) {
            setText(root, '[data-dashboard-crm-summary]', 'Revenue is tracking ' + formatGoalPct(safeSales.baseline_attainment_pct) + ' of the monthly baseline.');
        } else {
            setText(root, '[data-dashboard-crm-summary]', 'No customer tasks due this week.');
        }
    }

    function renderAuditList(root, auditLog, selectedPeriod) {
        var list = byData(root, '[data-audit-list]');
        var meta = byData(root, '[data-audit-meta]');
        var summary = byData(root, '.dash-audit-summary');
        if (!list) return;

        var key = selectedPeriod === 'week' ? 'week' : 'day';
        var bucket = (auditLog && auditLog[key]) ? auditLog[key] : { total: 0, items: [] };
        var rows = Array.isArray(bucket.items) ? bucket.items : [];
        var limit = Number((auditLog && auditLog.limit) || 10);
        var total = Number(bucket.total || 0);
        var periodLabel = key === 'week' ? 'this week' : 'today';

        if (meta) {
            if (total <= limit) {
                meta.textContent = 'Showing all ' + String(total) + ' events ' + periodLabel + '.';
            } else {
                meta.textContent = 'Showing top ' + String(limit) + ' of ' + String(total) + ' events ' + periodLabel + '.';
            }
        }
        if (summary) {
            summary.textContent = key === 'week' ? 'Events for this week' : 'Events for today';
        }

        if (rows.length === 0) {
            list.innerHTML = '<li class="dash-empty">No changes recorded for this window.</li>';
            return;
        }

        list.innerHTML = rows.map(function (row) {
            var summaryText = row.summary || row.event_type || 'Activity';
            var actor = row.actor || 'System';
            var at = formatDateTime(row.at);
            return (
                '<li class="dash-list-item">' +
                '<p class="dash-audit-title">' + escapeHtml(summaryText) + '</p>' +
                '<p class="dash-audit-meta-line">' + escapeHtml(actor) + ' · ' + escapeHtml(at) + '</p>' +
                '</li>'
            );
        }).join('');
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

        var width = 250;
        var height = 44;
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
        var toggle = byData(root, '[data-audit-week-toggle]');
        var track = byData(root, '[data-audit-week-toggle-track]');
        var period = 'day';
        if (!toggle) {
            renderAuditList(root, auditLog, period);
            return;
        }

        function applyState() {
            var isWeek = period === 'week';
            toggle.setAttribute('aria-checked', isWeek ? 'true' : 'false');
            if (track) {
                track.classList.toggle('spa-advanced-toggle__track--on', isWeek);
            }
            renderAuditList(root, auditLog, period);
        }

        if (!toggle.dataset.boundDashboardAudit) {
            toggle.addEventListener('click', function () {
                period = period === 'week' ? 'day' : 'week';
                applyState();
            });
            toggle.dataset.boundDashboardAudit = '1';
        }
        applyState();
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

        setText(root, '[data-dashboard-date]', new Date().toLocaleString('en-US', {
            month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
        }));

        setText(root, '[data-kpi-operator-actions]', operatorActions.week_to_date || 0);
        setText(root, '[data-kpi-open-action-items]', actionBoard.critical_actions_total || 0);
        setText(root, '[data-kpi-active-batches]', operations.active_executions || 0);
        setText(root, '[data-kpi-revenue-goal]', formatGoalPct(sales.baseline_attainment_pct));
        setText(root, '[data-kpi-tasks-week]', tasks.due_this_week_count || 0);
        setText(root, '[data-kpi-overdue]', tasks.overdue_count || 0);
        setText(root, '[data-kpi-throughput-vs-last-week]', formatPct(operations.completed_vs_last_week_pct));

        renderSparkLine(root, 'operator_actions', insightSeries.operator_actions_week);
        renderSparkLine(root, 'open_action_items', insightSeries.open_action_items);
        renderSparkLine(root, 'active_batches', insightSeries.active_batches_week);
        renderSparkLine(root, 'monthly_goal', insightSeries.revenue_goal_mtd);
        renderSparkLine(root, 'tasks_week', insightSeries.tasks_due_week);
        renderSparkLine(root, 'throughput_vs_week', insightSeries.batch_completion_week);

        renderActionList(root, actionBoard);
        renderWorkspaceSummaries(root, operations, compliantWorkspace, tasks, sales);
        wireAuditPeriodToggle(root, auditLog);

        setText(root, '[data-ops-active]', operations.active_executions || 0);
        setText(root, '[data-ops-started-week]', operations.started_this_week || 0);
        setText(root, '[data-ops-completed-week]', operations.completed_this_week || 0);
        setText(root, '[data-ops-failed-week]', operations.failed_or_cancelled_this_week || 0);

        setText(root, '[data-sales-revenue-mtd]', formatCurrency(sales.current_month_revenue));
        setText(root, '[data-sales-baseline-target]', sales.baseline_target_mtd == null ? 'Not set' : formatCurrency(sales.baseline_target_mtd));
        setText(root, '[data-sales-baseline-variance]', formatCurrencyVariance(sales.baseline_variance_mtd));
        setText(root, '[data-sales-mom]', formatPct(sales.revenue_vs_last_month_pct));

        if (sales.enabled === false) {
            setText(root, '[data-sales-caption]', 'CRM is disabled for this tenant.');
        } else if (sales.baseline_target_mtd == null) {
            setText(root, '[data-sales-caption]', 'Define a baseline in CRM Configuration to track attainment.');
        } else {
            var attainment = sales.baseline_attainment_pct == null ? 'n/a' : String(sales.baseline_attainment_pct) + '%';
            setText(root, '[data-sales-caption]', 'Baseline attainment: ' + attainment + '.');
        }
    }

    var pendingLoad = null;

    function abortPendingLoad() {
        if (pendingLoad) {
            pendingLoad.abort();
            pendingLoad = null;
        }
    }

    async function loadDashboard(root) {
        var loading = byData(root, '[data-dashboard-loading]');
        var error = byData(root, '[data-dashboard-error]');
        if (loading) loading.hidden = false;
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
        loadDashboard(root);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDashboardPage);
    } else {
        initDashboardPage();
    }

    document.body.addEventListener('htmx:afterSettle', function () {
        if (document.querySelector(ROOT_SELECTOR)) initDashboardPage();
    });

    // Cancel an in-flight summary fetch the moment the page starts to go away, so it
    // doesn't surface as a "Failed to fetch" error against a detached root.
    document.body.addEventListener('htmx:beforeSwap', abortPendingLoad);
    window.addEventListener('pagehide', abortPendingLoad);

    // Live: the summary aggregates batches, tasks and events -- refresh it when a
    // colleague changes any of those, debounced so a burst is one reload. live-sync.js
    // loads *after* #page-content (this script), so defer the subscribe until it exists.
    var liveTimer = null;
    function subscribeDashboardLive() {
        window.LiveSync.subscribe({
            key: 'dashboard',
            match: function (evt) {
                var t = evt.entity_type;
                return t === 'process' || t === 'execution' || t === 'execution_step' || t === 'inventory_item';
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
    if (window.LiveSync) {
        subscribeDashboardLive();
    } else {
        document.addEventListener('DOMContentLoaded', function () {
            if (window.LiveSync) subscribeDashboardLive();
        });
    }
})();
