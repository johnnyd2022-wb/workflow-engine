/* CRM Overview Alpine.js component */
function crmOverview() {
  const WIDGET_STORAGE_KEY = 'crm_overview_widgets_v3';
  const SYSTEM_WIDGET_PREFS_KEY = 'crm_overview_system_widget_prefs_v1';

  return {
    loading: true,
    error: null,
    overview: {},
    operators: [],
    boardOperatorFilter: '',
    allMonthlySales: [],
    dateFrom: '',
    dateTo: '',
    dateDraftFrom: '',
    dateDraftTo: '',
    showDateRangeModal: false,
    showMoMModal: false,
    momPeriodMonths: 1,
    momDraftMonths: 1,
    showInvoiceModal: false,
    invoiceModalKind: 'this_month',
    invoiceModalTitle: '',
    invoiceModalLoading: false,
    invoiceModalInvoices: [],
    openModalInvoiceId: null,
    chartData: [],
    chartMode: 'bar',
    taskColumns: [
      { status: 'pending', title: 'To Do' },
      { status: 'in_progress', title: 'In Progress' },
    ],
    draggedTaskId: null,
    dragSuppressUntil: 0,
    expandedTaskId: null,

    widgetLayout: [],
    draggingWidgetId: null,
    resizingWidgetId: null,
    resizeStartX: 0,
    resizeStartSize: 'half',
    showGridGuide: false,
    showWidgetModal: false,
    widgetDraft: {
      title: '',
      entity: 'customers',
      metric: 'revenue',
      direction: 'top',
      limit: 8,
      periodN: 6,
      periodUnit: 'months',
      viewMode: 'table',
    },
    widgetDraftPreview: [],
    widgetDraftLoading: false,
    widgetDraftError: null,
    showTopNModal: false,
    topNModalType: '',
    topNDraftValue: 10,
    systemWidgetLimits: {
      top_products: 10,
      top_customers: 10,
    },

    async init() {
      CRMAPI.ensureBackButton('/crm', true);
      try {
        const [overview, monthly, users] = await Promise.all([
          CRMAPI.getOverview(),
          CRMAPI.getMonthlySales(24),
          CRMAPI.getOrgUsers(),
        ]);
        this.overview = overview || {};
        this.operators = users?.users || [];
        this.allMonthlySales = (monthly?.monthly_sales || []).slice().sort((a, b) => String(a.month || '').localeCompare(String(b.month || '')));
        this.setDefaultDateRange();
        this.refreshChart();
        this.loadSystemWidgetPrefs();
        this.loadWidgetLayout();
        await this.refreshCustomWidgets();
      } catch (e) {
        this.error = e.message || 'Failed to load CRM overview.';
      } finally {
        this.loading = false;
        await this.$nextTick();
        this.drawSalesChart();
        this.drawAllCustomCharts();
      }
    },

    setDefaultDateRange() {
      if (!this.allMonthlySales.length) return;
      const endMonth = this.allMonthlySales[this.allMonthlySales.length - 1]?.month || '';
      const startIndex = Math.max(0, this.allMonthlySales.length - 6);
      const startMonth = this.allMonthlySales[startIndex]?.month || endMonth;
      this.dateFrom = `${startMonth}-01`;
      this.dateTo = this.endOfMonthIso(endMonth);
      this.dateDraftFrom = this.dateFrom;
      this.dateDraftTo = this.dateTo;
    },

    endOfMonthIso(month) {
      if (!month) return '';
      const [y, m] = month.split('-').map((x) => Number(x));
      if (!y || !m) return '';
      const d = new Date(y, m, 0);
      return d.toISOString().slice(0, 10);
    },

    openDateRangeModal() {
      this.dateDraftFrom = this.dateFrom;
      this.dateDraftTo = this.dateTo;
      this.showDateRangeModal = true;
    },

    closeDateRangeModal() {
      this.showDateRangeModal = false;
    },

    openMoMModal() {
      this.momDraftMonths = this.momPeriodMonths;
      this.showMoMModal = true;
    },

    closeMoMModal() {
      this.showMoMModal = false;
    },

    applyMoMPeriod() {
      const months = Math.max(1, Math.min(24, Number(this.momDraftMonths || 1)));
      this.momPeriodMonths = months;
      this.showMoMModal = false;
    },

    async openInvoiceModal(kind) {
      this.invoiceModalKind = kind || 'this_month';
      this.invoiceModalTitle = this.invoiceModalKind === 'outstanding' ? 'Outstanding Invoices' : 'This Month Invoices';
      this.showInvoiceModal = true;
      this.invoiceModalLoading = true;
      this.openModalInvoiceId = null;
      try {
        const data = await CRMAPI.getOrgInvoices({ kind: this.invoiceModalKind, page: 1, page_size: 50 });
        this.invoiceModalInvoices = data?.invoices || [];
      } catch (e) {
        this.error = e.message || 'Failed to load invoices.';
      } finally {
        this.invoiceModalLoading = false;
      }
    },

    closeInvoiceModal() {
      this.showInvoiceModal = false;
      this.invoiceModalInvoices = [];
      this.openModalInvoiceId = null;
    },

    toggleModalInvoice(id) {
      this.openModalInvoiceId = this.openModalInvoiceId === id ? null : id;
    },

    applyDateRange() {
      this.dateFrom = this.dateDraftFrom || this.dateFrom;
      this.dateTo = this.dateDraftTo || this.dateTo;
      this.showDateRangeModal = false;
      this.refreshChart();
    },

    get dateRangeLabel() {
      if (!this.dateFrom || !this.dateTo) return 'All';
      return `${this.prettyDate(this.dateFrom)} - ${this.prettyDate(this.dateTo)}`;
    },

    prettyDate(iso) {
      const d = new Date(`${iso}T00:00:00`);
      if (Number.isNaN(d.getTime())) return iso;
      return d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: '2-digit' });
    },

    refreshChart() {
      const from = this.dateFrom ? new Date(`${this.dateFrom}T00:00:00`) : null;
      const to = this.dateTo ? new Date(`${this.dateTo}T23:59:59`) : null;
      this.chartData = this.allMonthlySales.filter((row) => {
        const month = String(row.month || '');
        if (!month) return false;
        const rowDate = new Date(`${month}-01T00:00:00`);
        if (from && rowDate < from) return false;
        if (to && rowDate > to) return false;
        return true;
      });
      this.chartMode = this.chartData.length > 6 ? 'line' : 'bar';
      this.$nextTick(() => this.drawSalesChart());
    },

    get monthOnMonthChangePct() {
      const months = Math.max(1, Number(this.momPeriodMonths || 1));
      const rows = this.allMonthlySales || [];
      if (rows.length < months * 2) return null;
      const current = rows.slice(-months).reduce((sum, row) => sum + Number(row.total || 0), 0);
      const previous = rows.slice(-(months * 2), -months).reduce((sum, row) => sum + Number(row.total || 0), 0);
      if (!previous) return null;
      return Math.round(((current - previous) / previous) * 1000) / 10;
    },

    tasksFor(status) {
      return (this.overview.overview_tasks || []).filter((task) => {
        if (task.status !== status) return false;
        if (this.boardOperatorFilter && task.assigned_to_user_id !== this.boardOperatorFilter) return false;
        return true;
      });
    },

    toggleTask(task) {
      if (Date.now() < this.dragSuppressUntil) return;
      this.expandedTaskId = this.expandedTaskId === task.id ? null : task.id;
    },

    openTaskInTasksPage(task) {
      if (!task?.id) return;
      CRMAPI.navigate(`/crm/tasks?task_id=${encodeURIComponent(task.id)}`);
    },

    onTaskDragStart(task) {
      this.draggedTaskId = task?.id || null;
      this.dragSuppressUntil = Date.now() + 200;
    },

    onTaskDragEnd() {
      this.draggedTaskId = null;
      this.dragSuppressUntil = Date.now() + 200;
    },

    async onColumnDrop(status) {
      if (!this.draggedTaskId) return;
      const tasks = this.overview.overview_tasks || [];
      const task = tasks.find((t) => t.id === this.draggedTaskId);
      this.draggedTaskId = null;
      if (!task || task.status === status) return;
      const prevStatus = task.status;
      task.status = status;
      try {
        const { task: updated } = await CRMAPI.updateTask(task.id, { status });
        const idx = tasks.findIndex((t) => t.id === task.id);
        if (idx !== -1) tasks[idx] = updated;
      } catch (e) {
        task.status = prevStatus;
        this.error = e.message || 'Failed to move task.';
      }
    },

    defaultWidgets() {
      return [
        { id: 'sales-trend', kind: 'system', type: 'sales_trend', title: 'Sales Trend', size: 'full', locked: true },
        { id: 'task-board', kind: 'system', type: 'task_board', title: 'Task Board', size: 'full', locked: true },
        { id: 'top-products', kind: 'system', type: 'top_products', title: 'Top Products', size: 'half', locked: true },
        { id: 'top-customers', kind: 'system', type: 'top_customers', title: 'Top Customers', size: 'half', locked: true },
      ];
    },

    loadWidgetLayout() {
      const defaults = this.defaultWidgets();
      try {
        const raw = localStorage.getItem(WIDGET_STORAGE_KEY);
        if (!raw) {
          this.widgetLayout = defaults;
          return;
        }
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) {
          this.widgetLayout = defaults;
          return;
        }
        const systemById = {};
        defaults.forEach((w) => { systemById[w.id] = w; });
        const next = [];
        parsed.forEach((w) => {
          if (!w || typeof w !== 'object' || !w.id || !w.kind) return;
          if (w.kind === 'system' && systemById[w.id]) {
            next.push({
              ...systemById[w.id],
              size: w.size === 'full' ? 'full' : 'half',
              locked: w.locked !== false,
            });
          } else if (w.kind === 'custom') {
            next.push({
              id: String(w.id),
              kind: 'custom',
              type: 'custom',
              title: String(w.title || 'Custom Widget'),
              size: w.size === 'half' ? 'half' : 'full',
              locked: w.locked === true,
              viewMode: w.viewMode === 'graph' ? 'graph' : 'table',
              config: w.config || {},
              rows: Array.isArray(w.rows) ? w.rows : [],
            });
          }
        });
        defaults.forEach((d) => {
          if (!next.some((x) => x.id === d.id)) next.push(d);
        });
        this.widgetLayout = next;
      } catch (_) {
        this.widgetLayout = defaults;
      }
    },

    persistWidgetLayout() {
      try { localStorage.setItem(WIDGET_STORAGE_KEY, JSON.stringify(this.widgetLayout)); } catch (_) {}
    },

    toggleWidgetLock(widget) {
      widget.locked = !widget.locked;
      this.persistWidgetLayout();
    },

    widgetSubtitle(widget) {
      if (widget.type === 'sales_trend') return this.chartMode === 'line' ? 'Line chart for larger ranges' : 'Bar chart for shorter ranges';
      if (widget.type === 'task_board') return 'To Do and In Progress tasks';
      if (widget.type === 'top_products') return 'By invoice line revenue';
      if (widget.type === 'top_customers') return 'By total invoiced revenue';
      if (widget.kind === 'custom') return this.customWidgetSubtitle(widget);
      return '';
    },

    customWidgetSubtitle(widget) {
      const c = widget.config || {};
      const label = c.entity === 'products' ? 'Products' : (c.entity === 'customers_by_product' ? 'Customers by product' : 'Customers');
      const dir = c.entity === 'customers_by_product' ? 'Top' : ((c.direction || 'top') === 'bottom' ? 'Bottom' : 'Top');
      return `${dir} ${c.limit || 8} ${label} • Last ${c.periodN || 6} ${c.periodUnit || 'months'}`;
    },

    assigneeName(userId) {
      const user = this.operators.find((x) => x.id === userId);
      return user ? (user.display_name || user.email || 'Assigned') : 'Assigned';
    },

    loadSystemWidgetPrefs() {
      try {
        const raw = localStorage.getItem(SYSTEM_WIDGET_PREFS_KEY);
        if (!raw) return;
        const prefs = JSON.parse(raw) || {};
        const products = Number(prefs.top_products || 10);
        const customers = Number(prefs.top_customers || 10);
        this.systemWidgetLimits.top_products = Math.max(1, products);
        this.systemWidgetLimits.top_customers = Math.max(1, customers);
      } catch (_) {}
    },

    persistSystemWidgetPrefs() {
      try {
        localStorage.setItem(SYSTEM_WIDGET_PREFS_KEY, JSON.stringify(this.systemWidgetLimits));
      } catch (_) {}
    },

    maxSystemRows(type) {
      if (type === 'top_products') return (this.overview.top_products || []).length;
      if (type === 'top_customers') return (this.overview.top_customers || []).length;
      return 0;
    },

    isSystemExpanded(type) {
      const max = this.maxSystemRows(type);
      const limit = Number(this.systemWidgetLimits[type] || 10);
      return max > 10 && limit > 10;
    },

    systemLimitLabel(type) {
      const max = this.maxSystemRows(type);
      const limit = Number(this.systemWidgetLimits[type] || 10);
      if (max > 0 && limit >= max) return 'All';
      return String(limit);
    },

    systemRows(type) {
      const all = type === 'top_products' ? (this.overview.top_products || []) : (this.overview.top_customers || []);
      const max = all.length;
      if (!max) return [];
      const limit = Math.max(1, Number(this.systemWidgetLimits[type] || 10));
      if (limit >= max) return all;
      return all.slice(0, limit);
    },

    openTopNModal(type) {
      this.topNModalType = type;
      this.topNDraftValue = Number(this.systemWidgetLimits[type] || 10);
      this.showTopNModal = true;
    },

    closeTopNModal() {
      this.showTopNModal = false;
      this.topNModalType = '';
    },

    showAllTopN() {
      if (!this.topNModalType) return;
      this.topNDraftValue = this.maxSystemRows(this.topNModalType) || 10;
    },

    applyTopNModal() {
      if (!this.topNModalType) return;
      const max = this.maxSystemRows(this.topNModalType) || 10;
      const val = Math.max(1, Math.min(max, Number(this.topNDraftValue || 10)));
      this.systemWidgetLimits[this.topNModalType] = val;
      this.persistSystemWidgetPrefs();
      this.closeTopNModal();
    },

    collapseSystemRows(type) {
      this.systemWidgetLimits[type] = 10;
      this.persistSystemWidgetPrefs();
    },

    startWidgetDrag(widgetId) {
      const widget = this.widgetLayout.find((w) => w.id === widgetId);
      if (!widget || widget.locked) return;
      this.draggingWidgetId = widgetId;
      this.showGridGuide = true;
    },

    endWidgetDrag() {
      this.draggingWidgetId = null;
      this.showGridGuide = false;
    },

    dropWidget(targetId) {
      const srcId = this.draggingWidgetId;
      this.draggingWidgetId = null;
      this.showGridGuide = false;
      if (!srcId || srcId === targetId) return;
      const srcIndex = this.widgetLayout.findIndex((w) => w.id === srcId);
      const targetIndex = this.widgetLayout.findIndex((w) => w.id === targetId);
      if (srcIndex < 0 || targetIndex < 0) return;
      const [moved] = this.widgetLayout.splice(srcIndex, 1);
      this.widgetLayout.splice(targetIndex, 0, moved);
      this.persistWidgetLayout();
      this.$nextTick(() => this.drawAllCustomCharts());
    },

    beginWidgetResize(widgetId, evt) {
      const widget = this.widgetLayout.find((w) => w.id === widgetId);
      if (!widget || widget.locked) return;
      this.resizingWidgetId = widgetId;
      this.resizeStartX = this.pointerClientX(evt);
      this.resizeStartSize = widget.size === 'full' ? 'full' : 'half';
      this.showGridGuide = true;
      this._onResizeMove = this.onWidgetResizeMove.bind(this);
      this._onResizeEnd = this.endWidgetResize.bind(this);
      window.addEventListener('mousemove', this._onResizeMove);
      window.addEventListener('touchmove', this._onResizeMove, { passive: false });
      window.addEventListener('mouseup', this._onResizeEnd);
      window.addEventListener('touchend', this._onResizeEnd);
    },

    pointerClientX(evt) {
      if (evt && evt.touches && evt.touches.length) return evt.touches[0].clientX;
      if (evt && evt.changedTouches && evt.changedTouches.length) return evt.changedTouches[0].clientX;
      return evt?.clientX || 0;
    },

    onWidgetResizeMove(evt) {
      if (!this.resizingWidgetId) return;
      if (evt?.cancelable) evt.preventDefault();
      const widget = this.widgetLayout.find((w) => w.id === this.resizingWidgetId);
      if (!widget) return;
      const delta = this.pointerClientX(evt) - this.resizeStartX;
      if (delta > 32) widget.size = 'full';
      if (delta < -32) widget.size = 'half';
    },

    endWidgetResize() {
      if (!this.resizingWidgetId) return;
      this.resizingWidgetId = null;
      this.showGridGuide = false;
      window.removeEventListener('mousemove', this._onResizeMove);
      window.removeEventListener('touchmove', this._onResizeMove);
      window.removeEventListener('mouseup', this._onResizeEnd);
      window.removeEventListener('touchend', this._onResizeEnd);
      this.persistWidgetLayout();
      this.$nextTick(() => this.drawAllCustomCharts());
    },

    removeWidget(widgetId) {
      this.widgetLayout = this.widgetLayout.filter((w) => w.id !== widgetId);
      this.persistWidgetLayout();
    },

    openWidgetModal() {
      this.widgetDraft = {
        title: '',
        entity: 'customers',
        metric: 'revenue',
        direction: 'top',
        limit: 8,
        periodN: 6,
        periodUnit: 'months',
        viewMode: 'table',
      };
      this.widgetDraftPreview = [];
      this.widgetDraftError = null;
      this.showWidgetModal = true;
    },

    closeWidgetModal() {
      this.showWidgetModal = false;
      this.widgetDraftLoading = false;
      this.widgetDraftError = null;
    },

    draftParams() {
      return {
        entity: this.widgetDraft.entity,
        direction: this.widgetDraft.entity === 'customers_by_product' ? 'top' : this.widgetDraft.direction,
        limit: this.widgetDraft.limit || 8,
        period_n: this.widgetDraft.periodN || 6,
        period_unit: this.widgetDraft.periodUnit || 'months',
      };
    },

    async previewWidget() {
      this.widgetDraftLoading = true;
      this.widgetDraftError = null;
      try {
        const data = await CRMAPI.getRankings(this.draftParams());
        this.widgetDraftPreview = this.transformRows(this.widgetDraft, data?.rankings || []);
      } catch (e) {
        this.widgetDraftError = e.message || 'Failed to load preview.';
      } finally {
        this.widgetDraftLoading = false;
      }
    },

    transformRows(draft, rows) {
      if (draft.metric !== 'monthly_rate' || draft.entity !== 'customers') return rows;
      const months = draft.periodUnit === 'months' ? Math.max(1, Number(draft.periodN || 1))
        : draft.periodUnit === 'years' ? Math.max(1, Number(draft.periodN || 1) * 12)
          : draft.periodUnit === 'weeks' ? Math.max(1, Number(draft.periodN || 1) / 4.345)
            : Math.max(1, Number(draft.periodN || 1) / 30.4375);
      return rows.map((row) => ({ ...row, monthly_rate: Number(row.total || 0) / months }));
    },

    async createWidgetFromDraft() {
      if (!this.widgetDraft.title.trim()) return;
      if (!this.widgetDraftPreview.length) await this.previewWidget();
      const id = `custom-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const widget = {
        id,
        kind: 'custom',
        type: 'custom',
        title: this.widgetDraft.title.trim(),
        size: 'full',
        locked: false,
        viewMode: this.widgetDraft.viewMode === 'graph' ? 'graph' : 'table',
        config: { ...this.widgetDraft },
        rows: this.widgetDraftPreview.slice(),
      };
      this.widgetLayout.push(widget);
      this.persistWidgetLayout();
      this.closeWidgetModal();
      await this.$nextTick();
      this.drawCustomChart(widget);
    },

    async refreshCustomWidgets() {
      const customs = this.widgetLayout.filter((w) => w.kind === 'custom');
      await Promise.all(customs.map(async (w) => {
        try {
          const data = await CRMAPI.getRankings({
            entity: w.config?.entity || 'customers',
            direction: (w.config?.entity === 'customers_by_product') ? 'top' : (w.config?.direction || 'top'),
            limit: w.config?.limit || 8,
            period_n: w.config?.periodN || 6,
            period_unit: w.config?.periodUnit || 'months',
          });
          w.rows = this.transformRows(w.config || {}, data?.rankings || []);
        } catch (_) {
          w.rows = [];
        }
      }));
      this.persistWidgetLayout();
      this.$nextTick(() => this.drawAllCustomCharts());
    },

    drawSalesChart() {
      const canvas = document.getElementById('crmOverviewSalesChart');
      if (!canvas || !this.chartData.length) return;
      const mode = this.chartMode === 'line' ? 'line' : 'bar';
      this.drawSeriesChart(
        canvas,
        this.chartData.map((row) => ({ xLabel: this.monthLabel(row.month), yValue: Number(row.total || 0) })),
        { mode, showValueLabels: mode === 'bar', maxLabels: 12 },
      );
    },

    drawAllCustomCharts() {
      this.widgetLayout.filter((w) => w.kind === 'custom').forEach((w) => this.drawCustomChart(w));
    },

    drawCustomChart(widget) {
      if (!widget || widget.viewMode !== 'graph' || !widget.rows?.length) return;
      const canvas = document.getElementById(`customWidgetChart-${widget.id}`);
      if (!canvas) return;
      this.drawSeriesChart(
        canvas,
        widget.rows.map((row) => ({ xLabel: this.customRowLabel(widget, row), yValue: Number(this.customRowValue(widget, row) || 0) })),
        { mode: 'bar', showValueLabels: false, maxLabels: 8 },
      );
    },

    customCol1Label(widget) {
      if (widget.config?.entity === 'products') return 'Product';
      if (widget.config?.entity === 'customers_by_product') return 'Customer · Product';
      return 'Customer';
    },

    customRowLabel(widget, row) {
      const entity = widget.config?.entity;
      if (entity === 'products') return row.description || row.item_code || 'Unknown product';
      if (entity === 'customers_by_product') {
        const product = row.description || row.item_code || 'Unknown product';
        const customer = row.contact_name || 'Unknown customer';
        return `${product} · ${customer}`;
      }
      return row.contact_name || 'Unknown customer';
    },

    customRowCount(widget, row) {
      const entity = widget.config?.entity;
      if (entity === 'products' || entity === 'customers_by_product') return this.formatNumber(row.total_qty || 0);
      return row.invoice_count || 0;
    },

    customRowValue(widget, row) {
      const entity = widget.config?.entity;
      if (widget.config?.metric === 'monthly_rate') return row.monthly_rate || 0;
      if (entity === 'products') return row.total_revenue || 0;
      if (entity === 'customers_by_product') return row.total_revenue || 0;
      return row.total || 0;
    },

    previewRowLabel(row) {
      if (row.contact_name && (row.description || row.item_code)) {
        const product = row.description || row.item_code || 'Product';
        return `${product} · ${row.contact_name}`;
      }
      return row.contact_name || row.description || row.item_code || '—';
    },

    previewRowCount(row) {
      if (row.total_qty != null) return this.formatNumber(row.total_qty);
      return row.invoice_count || 0;
    },

    previewRowValue(row) {
      return row.monthly_rate || row.total_revenue || row.top_customer_revenue || row.total || 0;
    },

    drawSeriesChart(canvas, rows, opts = {}) {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.parentElement.getBoundingClientRect();
      const W = rect.width || 600;
      const H = Number(canvas.style.height?.replace('px', '') || 220);
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;

      const ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);

      const textColor = '#6b7280';
      const gridColor = 'rgba(107,114,128,0.18)';
      const accent = '#2DD4BF';
      const accentLine = '#14B8A6';
      const pad = { top: 16, right: 16, bottom: 38, left: 58 };
      const chartW = W - pad.left - pad.right;
      const chartH = H - pad.top - pad.bottom;
      const values = rows.map((r) => r.yValue || 0);
      const maxVal = Math.max(...values, 1) * 1.15;

      ctx.font = '11px -apple-system, system-ui, sans-serif';
      ctx.fillStyle = textColor;
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + chartH - (i / 4) * chartH;
        const val = (i / 4) * maxVal;
        ctx.strokeStyle = gridColor;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(pad.left + chartW, y);
        ctx.stroke();
        ctx.fillText(this.shortCurrency(val), pad.left - 6, y + 4);
      }

      if (opts.mode === 'line') {
        const stepX = rows.length <= 1 ? chartW : (chartW / (rows.length - 1));
        const points = rows.map((row, idx) => ({ x: pad.left + idx * stepX, y: pad.top + chartH - ((row.yValue || 0) / maxVal) * chartH, row }));
        ctx.strokeStyle = accentLine;
        ctx.lineWidth = 2;
        ctx.beginPath();
        points.forEach((pt, idx) => { if (idx === 0) ctx.moveTo(pt.x, pt.y); else ctx.lineTo(pt.x, pt.y); });
        ctx.stroke();
        points.forEach((pt, idx) => {
          ctx.fillStyle = '#ffffff';
          ctx.strokeStyle = accentLine;
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, 3.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
          if (idx % Math.ceil(rows.length / (opts.maxLabels || 12)) === 0 || idx === rows.length - 1) {
            ctx.fillStyle = textColor;
            ctx.textAlign = 'center';
            ctx.font = '10px -apple-system, system-ui, sans-serif';
            this.drawWrappedXAxisLabel(ctx, String(pt.row.xLabel || ''), pt.x, pad.top + chartH + 14, Math.max(52, stepX - 4), 10, 2);
          }
        });
        return;
      }

      const gap = rows.length > 8 ? 6 : 10;
      const barW = Math.max(8, (chartW - gap * (rows.length - 1)) / Math.max(rows.length, 1));
      rows.forEach((row, idx) => {
        const barH = ((row.yValue || 0) / maxVal) * chartH;
        const x = pad.left + idx * (barW + gap);
        const y = pad.top + chartH - barH;
        ctx.fillStyle = accent;
        ctx.fillRect(x, y, barW, barH);
        ctx.fillStyle = textColor;
        ctx.textAlign = 'center';
        ctx.font = '10px -apple-system, system-ui, sans-serif';
        this.drawWrappedXAxisLabel(ctx, String(row.xLabel || ''), x + barW / 2, pad.top + chartH + 14, Math.max(56, barW + gap - 2), 10, 3);
        if (opts.showValueLabels) {
          ctx.fillStyle = '#0f172a';
          ctx.font = '10px -apple-system, system-ui, sans-serif';
          ctx.fillText(this.formatCurrency2(row.yValue || 0), x + barW / 2, Math.max(pad.top + 10, y - 6));
        }
      });
    },

    monthLabel(month) {
      if (!month) return '';
      const [year, monthNumber] = month.split('-');
      const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return `${names[Number(monthNumber) - 1] || monthNumber} ${year.slice(2)}`;
    },

    shortCurrency(value) {
      if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
      if (value >= 1000) return `$${(value / 1000).toFixed(0)}k`;
      return `$${Number(value || 0).toFixed(0)}`;
    },

    formatCurrency2(value) {
      if (value == null) return '—';
      return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
    },

    formatPercent(value) {
      if (value == null) return '—';
      return `${value > 0 ? '+' : ''}${value}%`;
    },

    formatNumber(value) {
      if (value == null) return '—';
      return new Intl.NumberFormat('en-NZ', { maximumFractionDigits: 2 }).format(value);
    },

    formatInvoiceCurrency(value, code = 'NZD') {
      if (value == null) return '—';
      return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: code || 'NZD', minimumFractionDigits: 2 }).format(value);
    },

    formatInvoiceDate(value) {
      if (!value) return '—';
      const dt = new Date(value + (String(value).includes('T') ? '' : 'T00:00:00'));
      if (Number.isNaN(dt.getTime())) return '—';
      return dt.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
    },

    invoiceBadgeClass(status) {
      const s = String(status || '').toLowerCase();
      return {
        paid: 'crm-badge--paid',
        authorised: 'crm-badge--authorised',
        draft: 'crm-badge--draft',
        voided: 'crm-badge--voided',
        deleted: 'crm-badge--deleted',
      }[s] || 'crm-badge--draft';
    },

    downloadInvoice(inv) {
      if (!inv) return;
      const payload = {
        invoice_number: inv.invoice_number,
        date: inv.date,
        due_date: inv.due_date,
        status: inv.status,
        currency_code: inv.currency_code,
        sub_total: inv.sub_total,
        total_tax: inv.total_tax,
        total: inv.total,
        line_items: inv.line_items || [],
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${inv.invoice_number || inv.id || 'invoice'}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);
    },

    drawWrappedXAxisLabel(ctx, text, centerX, topY, maxWidth, lineHeight, maxLines) {
      const words = String(text || '').split(/\s+/).filter(Boolean);
      if (!words.length) return;
      const lines = [];
      let line = '';
      for (const word of words) {
        const next = line ? `${line} ${word}` : word;
        if (ctx.measureText(next).width <= maxWidth || !line) {
          line = next;
        } else {
          lines.push(line);
          line = word;
        }
        if (lines.length === maxLines) break;
      }
      if (lines.length < maxLines && line) lines.push(line);
      if (lines.length > maxLines) lines.length = maxLines;
      if (lines.length && words.length > 1 && lines.length === maxLines) {
        const idx = lines.length - 1;
        if (ctx.measureText(lines[idx]).width > maxWidth) {
          while (lines[idx].length > 1 && ctx.measureText(`${lines[idx]}…`).width > maxWidth) {
            lines[idx] = lines[idx].slice(0, -1);
          }
          lines[idx] = `${lines[idx]}…`;
        }
      }
      lines.forEach((ln, i) => {
        ctx.fillText(ln, centerX, topY + (i * lineHeight));
      });
    },

    priorityClass(priority) {
      return { high: 'crm-badge--high', medium: 'crm-badge--medium', low: 'crm-badge--low' }[priority] || '';
    },
  };
}
