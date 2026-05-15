/* Customer detail Alpine.js component */
function crmCustomerDetail(contactId) {
  return {
    contactId,
    activeTab: 'overview',
    customer: null,
    invoices: [],
    invoicePage: 1,
    invoiceTotal: 0,
    openInvoiceId: null,
    notes: [],
    tasks: [],
    operators: [],
    mappings: [],
    allMappings: [],
    lineItemOptions: [],
    repeatLineItemOptions: [],
    allLineItemOptions: [],
    loadingLineItemOptions: false,
    showInvoiceModal: false,
    showInvoicePreview: false,
    creatingInvoice: false,
    invoiceForm: {
      invoice_date: '',
      due_date: '',
      line_items: [],
    },
    loading: true,
    error: null,

    // Notes
    newNoteContent: '',
    addingNote: false,
    editingNoteId: null,
    editNoteContent: '',

    // Tasks (for this contact)
    taskStatusFilter: '',
    showCustomerTaskModal: false,
    creatingCustomerTask: false,
    showTaskEditModal: false,
    savingTaskEdit: false,
    editingTask: null,
    taskEditForm: {
      title: '',
      description: '',
      due_date: '',
      priority: 'medium',
      status: 'pending',
      assigned_to_user_id: '',
    },
    customerTaskForm: {
      title: '',
      description: '',
      due_date: '',
      priority: 'medium',
      assigned_to_user_id: '',
    },

    customerAnalytics: {
      monthly_sales: [],
      top_products: [],
      total_revenue: 0,
      total_invoices: 0,
    },
    analyticsDateFrom: '',
    analyticsDateTo: '',
    analyticsDraftFrom: '',
    analyticsDraftTo: '',
    showAnalyticsDateModal: false,

    // New mapping form
    showMappingForm: false,
    newMapping: { biz_e_product_name: '', xero_description_pattern: '', match_type: 'exact', notes: '' },
    savingMapping: false,

    async init() {
      CRMAPI.ensureBackButton('/crm');
      this.loading = true;
      this.error = null;
      try {
        const data = await CRMAPI.getCustomer(this.contactId);
        this.customer = data.customer;
        this.invoices = data.recent_invoices || [];
        this.notes    = data.notes || [];
        this.tasks    = data.tasks || [];
        this.allMappings = data.product_mappings || [];
        this.mappings = this.allMappings;
        await this.loadOperators();
        this.resetInvoiceForm();
        this.setDefaultAnalyticsRange();
        await this.loadCustomerAnalytics();
      } catch (e) {
        this.error = e.message || 'Failed to load customer.';
      } finally {
        this.loading = false;
        await this.$nextTick();
        this.drawCustomerAnalyticsCharts();
      }
    },

    get hasSalesTerms() {
      return !!this.customer?.payment_terms?.sales;
    },

    // ── Tabs ────────────────────────────────────────────────────
    setTab(tab) {
      this.activeTab = tab;
      if (tab === 'overview') {
        this.$nextTick(() => this.drawCustomerAnalyticsCharts());
      }
    },

    // ── Invoices ────────────────────────────────────────────────
    async loadInvoices(page = 1) {
      try {
        const data = await CRMAPI.getCustomerInvoices(this.contactId, { page, page_size: 25 });
        this.invoices = data.invoices || [];
        this.invoicePage = data.page || 1;
        this.invoiceTotal = data.total || 0;
      } catch (e) {
        this.error = e.message;
      }
    },

    toggleInvoice(id) { this.openInvoiceId = this.openInvoiceId === id ? null : id; },

    invoiceBadgeClass(status) {
      const s = (status || '').toLowerCase();
      return {
        'paid': 'crm-badge--paid',
        'authorised': 'crm-badge--authorised',
        'draft': 'crm-badge--draft',
        'voided': 'crm-badge--voided',
        'deleted': 'crm-badge--deleted',
      }[s] || 'crm-badge--draft';
    },

    formatCurrency(v, code = 'NZD') {
      if (v == null) return '—';
      return new Intl.NumberFormat('en-NZ', { style: 'currency', currency: code || 'NZD', minimumFractionDigits: 2 }).format(v);
    },

    formatDate(d) {
      if (!d) return '—';
      const dt = new Date(d + (d.includes('T') ? '' : 'T00:00:00'));
      return isNaN(dt) ? '—' : dt.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
    },

    // ── Notes ────────────────────────────────────────────────────
    async submitNote() {
      const content = this.newNoteContent.trim();
      if (!content) return;
      this.addingNote = true;
      try {
        const { note } = await CRMAPI.createNote(this.contactId, content);
        this.notes.unshift(note);
        this.newNoteContent = '';
      } catch (e) {
        alert(e.message || 'Failed to add note.');
      } finally {
        this.addingNote = false;
      }
    },

    startEditNote(note) { this.editingNoteId = note.id; this.editNoteContent = note.content; },
    cancelEditNote()    { this.editingNoteId = null; this.editNoteContent = ''; },

    async saveEditNote(note) {
      const content = this.editNoteContent.trim();
      if (!content) return;
      try {
        const { note: updated } = await CRMAPI.updateNote(note.id, content);
        const idx = this.notes.findIndex(n => n.id === note.id);
        if (idx !== -1) this.notes[idx] = updated;
        this.cancelEditNote();
      } catch (e) {
        alert(e.message || 'Failed to update note.');
      }
    },

    async deleteNote(noteId) {
      if (!confirm('Delete this note?')) return;
      try {
        await CRMAPI.deleteNote(noteId);
        this.notes = this.notes.filter(n => n.id !== noteId);
      } catch (e) {
        alert(e.message || 'Failed to delete note.');
      }
    },

    formatNoteDate(d) {
      if (!d) return '';
      const dt = new Date(d);
      return isNaN(dt) ? '' : dt.toLocaleString('en-NZ', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    },

    // ── Tasks ────────────────────────────────────────────────────
    get filteredTasks() {
      if (!this.taskStatusFilter) return this.tasks;
      return this.tasks.filter(t => t.status === this.taskStatusFilter);
    },

    taskStatusClass(status) {
      return { pending: 'crm-badge--pending', in_progress: 'crm-badge--in_progress', completed: 'crm-badge--completed', cancelled: 'crm-badge--cancelled' }[status] || 'crm-badge--draft';
    },

    priorityClass(p) {
      return { high: 'crm-badge--high', medium: 'crm-badge--medium', low: 'crm-badge--low' }[p] || '';
    },

    async updateTaskStatus(task, newStatus) {
      try {
        const { task: updated } = await CRMAPI.updateTask(task.id, { status: newStatus });
        const idx = this.tasks.findIndex(t => t.id === task.id);
        if (idx !== -1) this.tasks[idx] = updated;
      } catch (e) {
        alert(e.message || 'Failed to update task.');
      }
    },

    async loadOperators() {
      try {
        const data = await CRMAPI.getOrgUsers();
        this.operators = data?.users || [];
      } catch (_) {
        this.operators = [];
      }
    },

    openCustomerTaskModal() {
      this.customerTaskForm = {
        title: '',
        description: '',
        due_date: '',
        priority: 'medium',
        assigned_to_user_id: '',
      };
      this.showCustomerTaskModal = true;
    },

    closeCustomerTaskModal() {
      this.showCustomerTaskModal = false;
    },

    async submitCustomerTask() {
      if (!this.customerTaskForm.title.trim()) return;
      this.creatingCustomerTask = true;
      try {
        const payload = {
          title: this.customerTaskForm.title.trim(),
          description: (this.customerTaskForm.description || '').trim() || null,
          due_date: this.customerTaskForm.due_date || null,
          priority: this.customerTaskForm.priority || 'medium',
          contact_id: this.contactId,
          assigned_to_user_id: this.customerTaskForm.assigned_to_user_id || null,
        };
        if (!payload.due_date) delete payload.due_date;
        if (!payload.assigned_to_user_id) delete payload.assigned_to_user_id;
        const { task } = await CRMAPI.createTask(payload);
        this.tasks.unshift(task);
        this.closeCustomerTaskModal();
        this.activeTab = 'tasks';
      } catch (e) {
        alert(e.message || 'Failed to create task.');
      } finally {
        this.creatingCustomerTask = false;
      }
    },

    assigneeName(userId) {
      const user = this.operators.find((x) => x.id === userId);
      return user ? (user.display_name || user.email || 'Assigned') : 'Assigned';
    },

    openTaskEdit(task) {
      this.editingTask = task;
      this.taskEditForm = {
        title: task.title || '',
        description: task.description || '',
        due_date: task.due_date || '',
        priority: task.priority || 'medium',
        status: task.status || 'pending',
        assigned_to_user_id: task.assigned_to_user_id || '',
      };
      this.showTaskEditModal = true;
    },

    closeTaskEditModal() {
      this.showTaskEditModal = false;
      this.editingTask = null;
    },

    async saveTaskEdit() {
      if (!this.editingTask || !this.taskEditForm.title.trim()) return;
      this.savingTaskEdit = true;
      try {
        const assignedRaw = String(this.taskEditForm.assigned_to_user_id || '').trim().toLowerCase();
        const payload = {
          title: this.taskEditForm.title.trim(),
          description: (this.taskEditForm.description || '').trim() || null,
          due_date: this.taskEditForm.due_date || null,
          priority: this.taskEditForm.priority || 'medium',
          status: this.taskEditForm.status || 'pending',
          assigned_to_user_id: assignedRaw ? this.taskEditForm.assigned_to_user_id : null,
        };
        if (!payload.due_date) delete payload.due_date;
        const { task } = await CRMAPI.updateTask(this.editingTask.id, payload);
        const idx = this.tasks.findIndex((t) => t.id === task.id);
        if (idx !== -1) this.tasks[idx] = task;
        this.closeTaskEditModal();
      } catch (e) {
        alert(e.message || 'Failed to save task.');
      } finally {
        this.savingTaskEdit = false;
      }
    },

    async deleteTask(task) {
      if (!task) return;
      if (!confirm(`Delete task "${task.title}"?`)) return;
      try {
        await CRMAPI.deleteTask(task.id);
        this.tasks = this.tasks.filter((t) => t.id !== task.id);
        if (this.editingTask?.id === task.id) this.closeTaskEditModal();
      } catch (e) {
        alert(e.message || 'Failed to delete task.');
      }
    },

    // ── Product Mappings ─────────────────────────────────────────
    async loadLineItemOptions() {
      this.loadingLineItemOptions = true;
      try {
        const [repeatData, orgData] = await Promise.all([
          CRMAPI.getCustomerLineItemOptions(this.contactId),
          CRMAPI.getOrgLineItemOptions(),
        ]);
        this.repeatLineItemOptions = repeatData?.line_item_options || [];
        const orgOptions = orgData?.line_item_options || [];
        const seen = new Set(this.repeatLineItemOptions.map((opt) => `${opt.description || ''}||${opt.item_code || ''}`.toLowerCase()));
        const extras = orgOptions.filter((opt) => !seen.has(`${opt.description || ''}||${opt.item_code || ''}`.toLowerCase()));
        this.allLineItemOptions = [...this.repeatLineItemOptions, ...extras];
        this.lineItemOptions = this.allLineItemOptions;
      } catch (e) {
        this.error = e.message || 'Failed to load Xero line item descriptions.';
      } finally {
        this.loadingLineItemOptions = false;
      }
    },

    resetInvoiceForm() {
      const today = new Date();
      const iso = today.toISOString().slice(0, 10);
      this.invoiceForm = {
        invoice_date: iso,
        due_date: '',
        line_items: [
          {
            option_key: '',
            description: '',
            item_code: '',
            quantity: null,
            unit_amount: null,
            tax_type: '',
            account_code: '',
            source_invoice_date: '',
          },
        ],
      };
      this.applyInvoiceDueDateDefault(false);
      this.showInvoicePreview = false;
    },

    async openInvoiceModal() {
      this.resetInvoiceForm();
      if (!this.lineItemOptions.length) await this.loadLineItemOptions();
      this.showInvoiceModal = true;
    },

    closeInvoiceModal() {
      this.showInvoiceModal = false;
      this.showInvoicePreview = false;
    },

    async applyInvoiceDueDateDefault(force = false) {
      if (!this.invoiceForm.invoice_date) return;
      let suggested = '';
      try {
        const data = await CRMAPI.getCustomerInvoiceDefaults(this.contactId, { invoice_date: this.invoiceForm.invoice_date });
        suggested = data?.due_date || '';
      } catch (_) {}
      if (!suggested) suggested = this.suggestDueDateFromPaymentTerms(this.invoiceForm.invoice_date);
      const fallback = this.suggestFallbackDueDate(this.invoiceForm.invoice_date);
      const nextDue = suggested || fallback;
      if (!nextDue) return;
      if (force || !this.invoiceForm.due_date) this.invoiceForm.due_date = nextDue;
    },

    suggestFallbackDueDate(invoiceDateIso) {
      if (!invoiceDateIso) return '';
      const base = new Date(invoiceDateIso + 'T00:00:00');
      if (Number.isNaN(base.getTime())) return '';
      base.setDate(base.getDate() + 30);
      return base.toISOString().slice(0, 10);
    },

    suggestDueDateFromPaymentTerms(invoiceDateIso) {
      if (!invoiceDateIso) return '';
      const base = new Date(invoiceDateIso + 'T00:00:00');
      if (Number.isNaN(base.getTime())) return '';
      const terms = this.customer?.payment_terms?.sales;
      if (!terms) return '';

      const day = Number(terms.day || 0) || 0;
      const monthOffsetHint = Number(terms.month || 0) || 0;
      const typeRaw = String(terms.type || '').toUpperCase();
      const result = new Date(base);

      // e.g. DAYSAFTERBILLDATE
      if (typeRaw.includes('DAYSAFTER')) {
        const addDays = Math.max(0, day);
        result.setDate(result.getDate() + addDays);
        return result.toISOString().slice(0, 10);
      }

      // Month-anchored terms such as OFCURRENTMONTH / OFFOLLOWINGMONTH / MONTHSAFTER...
      let monthOffset = 0;
      if (typeRaw.includes('FOLLOWINGMONTH')) monthOffset = 1;
      if (typeRaw.includes('MONTHSAFTER')) monthOffset = monthOffsetHint > 0 ? monthOffsetHint : 1;

      if (typeRaw.includes('MONTH') || monthOffset > 0) {
        const target = new Date(base);
        target.setDate(1);
        target.setMonth(target.getMonth() + monthOffset);
        const dueDay = day > 0 ? day : base.getDate();
        const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
        target.setDate(Math.min(dueDay, last));
        return target.toISOString().slice(0, 10);
      }

      // Fallback: if we only have day, use that day in current month; if already passed, next month.
      if (day > 0) {
        const target = new Date(base);
        const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
        target.setDate(Math.min(day, last));
        if (target < base) {
          target.setMonth(target.getMonth() + 1);
          const nextLast = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
          target.setDate(Math.min(day, nextLast));
        }
        return target.toISOString().slice(0, 10);
      }
      return '';
    },

    addInvoiceLine() {
      this.invoiceForm.line_items.push({
        option_key: '',
        description: '',
        item_code: '',
        quantity: null,
        unit_amount: null,
        tax_type: '',
        account_code: '',
        source_invoice_date: '',
      });
    },

    removeInvoiceLine(idx) {
      this.invoiceForm.line_items.splice(idx, 1);
      if (!this.invoiceForm.line_items.length) this.addInvoiceLine();
    },

    async applyLineItemOption(idx) {
      const row = this.invoiceForm.line_items[idx];
      if (!row) return;
      const [description, itemCode] = String(row.option_key || '').split('||');
      row.description = description || '';
      row.item_code = itemCode || '';
      try {
        const data = await CRMAPI.getCustomerLineItemPricing(this.contactId, {
          description: row.description || '',
          item_code: row.item_code || '',
        });
        const pricing = data?.line_item_pricing;
        if (pricing) {
          if (pricing.unit_amount != null) row.unit_amount = Number(pricing.unit_amount);
          row.tax_type = pricing.tax_type || row.tax_type;
          row.account_code = pricing.account_code || row.account_code;
          row.source_invoice_date = pricing.source_invoice_date || '';
        }
      } catch (_) {}
    },

    async applyLineItemText(idx) {
      const row = this.invoiceForm.line_items[idx];
      if (!row) return;
      const desc = String(row.description || '').trim();
      if (!desc) {
        row.option_key = '';
        row.item_code = '';
        row.source_invoice_date = '';
        return;
      }
      const match = this.lineItemOptions.find((opt) => String(opt.description || '').trim().toLowerCase() === desc.toLowerCase());
      if (match) {
        const itemCode = String(match.item_code || '');
        row.option_key = `${match.description || ''}||${itemCode}`;
        row.item_code = itemCode;
      }
      try {
        const data = await CRMAPI.getCustomerLineItemPricing(this.contactId, {
          description: row.description || '',
          item_code: row.item_code || '',
        });
        const pricing = data?.line_item_pricing;
        if (pricing) {
          if (pricing.unit_amount != null) row.unit_amount = Number(pricing.unit_amount);
          row.tax_type = pricing.tax_type || row.tax_type;
          row.account_code = pricing.account_code || row.account_code;
          row.source_invoice_date = pricing.source_invoice_date || '';
        }
      } catch (_) {}
    },

    get previewInvoiceRows() {
      return (this.invoiceForm?.line_items || [])
        .filter((row) => (row.description || '').trim())
        .map((row) => {
          const qty = Number(row.quantity || 0);
          const unit = Number(row.unit_amount || 0);
          const lineTotal = (qty > 0 ? qty : 0) * (unit || 0);
          const taxType = String(row.tax_type || '').toUpperCase();
          const taxable = !!taxType && !taxType.includes('NONE') && !taxType.includes('EXEMPT') && !taxType.includes('ZERO') && !taxType.includes('NO');
          const gst = taxable ? (lineTotal * 0.15) : 0;
          return {
            description: row.description || '',
            quantity: qty || null,
            unit_amount: unit || 0,
            tax_type: row.tax_type || '',
            line_total: lineTotal,
            gst_total: gst,
          };
        });
    },

    get previewInvoiceTotal() {
      return this.previewInvoiceRows.reduce((sum, row) => sum + Number(row.line_total || 0), 0);
    },

    get previewInvoiceGstTotal() {
      return this.previewInvoiceRows.reduce((sum, row) => sum + Number(row.gst_total || 0), 0);
    },

    get previewInvoiceGrandTotal() {
      return this.previewInvoiceTotal + this.previewInvoiceGstTotal;
    },

    async submitInvoice() {
      if (!this.invoiceForm.invoice_date) {
        alert('Invoice date is required.');
        return;
      }
      const line_items = this.invoiceForm.line_items
        .filter((row) => (row.description || '').trim())
        .map((row) => ({
          description: (row.description || '').trim(),
          item_code: (row.item_code || '').trim() || null,
          quantity: row.quantity,
          unit_amount: row.unit_amount,
          tax_type: (row.tax_type || '').trim() || null,
          account_code: (row.account_code || '').trim() || null,
        }));
      if (!line_items.length) {
        alert('At least one line item is required.');
        return;
      }
      if (line_items.some((row) => !row.quantity || Number(row.quantity) <= 0)) {
        alert('Each line item needs a quantity greater than 0.');
        return;
      }
      if (line_items.some((row) => row.unit_amount == null)) {
        alert('Each line item needs a unit price.');
        return;
      }

      this.creatingInvoice = true;
      try {
        await CRMAPI.createCustomerInvoice(this.contactId, {
          invoice_date: this.invoiceForm.invoice_date,
          due_date: this.invoiceForm.due_date || null,
          line_items,
        });
        await this.loadInvoices(1);
        this.closeInvoiceModal();
      } catch (e) {
        alert(e.message || 'Failed to create invoice.');
      } finally {
        this.creatingInvoice = false;
      }
    },

    setDefaultAnalyticsRange() {
      const end = new Date();
      const start = new Date(end);
      start.setMonth(start.getMonth() - 5);
      start.setDate(1);
      this.analyticsDateFrom = start.toISOString().slice(0, 10);
      this.analyticsDateTo = end.toISOString().slice(0, 10);
      this.analyticsDraftFrom = this.analyticsDateFrom;
      this.analyticsDraftTo = this.analyticsDateTo;
    },

    openAnalyticsDateModal() {
      this.analyticsDraftFrom = this.analyticsDateFrom;
      this.analyticsDraftTo = this.analyticsDateTo;
      this.showAnalyticsDateModal = true;
    },

    closeAnalyticsDateModal() {
      this.showAnalyticsDateModal = false;
    },

    async applyAnalyticsDateRange() {
      this.analyticsDateFrom = this.analyticsDraftFrom || this.analyticsDateFrom;
      this.analyticsDateTo = this.analyticsDraftTo || this.analyticsDateTo;
      this.showAnalyticsDateModal = false;
      await this.loadCustomerAnalytics();
    },

    async loadCustomerAnalytics() {
      try {
        this.customerAnalytics = await CRMAPI.getCustomerAnalytics(this.contactId, {
          start_date: this.analyticsDateFrom,
          end_date: this.analyticsDateTo,
        });
        await this.$nextTick();
        this.drawCustomerAnalyticsCharts();
      } catch (_) {}
    },

    drawCustomerAnalyticsCharts() {
      this.drawSimpleBars(
        document.getElementById('crmCustomerRevenueChart'),
        (this.customerAnalytics?.monthly_sales || []).map((row) => ({
          label: this.monthLabel(row.month),
          value: Number(row.total || 0),
        })),
        { showValueLabels: true, maxLabelLines: 2 },
      );
      this.drawSimpleBars(
        document.getElementById('crmCustomerProductChart'),
        (this.customerAnalytics?.top_products || []).slice(0, 6).map((row) => ({
          label: String(row.description || row.item_code || 'Item'),
          value: Number(row.total_revenue || 0),
        })),
        { showValueLabels: false, maxLabelLines: 3 },
      );
    },

    drawSimpleBars(canvas, rows, opts = {}) {
      if (!canvas || !rows.length) return;
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.parentElement.getBoundingClientRect();
      const W = rect.width || 480;
      const H = Number(canvas.style.height?.replace('px', '') || (opts.maxLabelLines && opts.maxLabelLines > 2 ? 240 : 220));
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
      const ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const pad = { top: 18, right: 16, bottom: 48, left: 56 };
      const chartW = W - pad.left - pad.right;
      const chartH = H - pad.top - pad.bottom;
      const maxVal = Math.max(...rows.map((x) => x.value), 1) * 1.15;
      const gap = rows.length > 6 ? 6 : 10;
      const barW = Math.max(10, (chartW - gap * (rows.length - 1)) / Math.max(rows.length, 1));
      ctx.font = '11px -apple-system, system-ui, sans-serif';
      ctx.fillStyle = '#6b7280';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const y = pad.top + chartH - (i / 4) * chartH;
        const v = (i / 4) * maxVal;
        ctx.strokeStyle = 'rgba(107,114,128,0.18)';
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(pad.left + chartW, y);
        ctx.stroke();
        ctx.fillText(this.shortCurrency(v), pad.left - 6, y + 4);
      }
      rows.forEach((row, idx) => {
        const x = pad.left + idx * (barW + gap);
        const barH = (row.value / maxVal) * chartH;
        const y = pad.top + chartH - barH;
        ctx.fillStyle = '#2DD4BF';
        ctx.fillRect(x, y, barW, barH);
        ctx.fillStyle = '#0f172a';
        ctx.textAlign = 'center';
        ctx.font = '10px -apple-system, system-ui, sans-serif';
        this.drawWrappedXAxisLabel(
          ctx,
          String(row.label || ''),
          x + (barW / 2),
          pad.top + chartH + 14,
          Math.max(56, barW + gap - 2),
          10,
          Math.max(2, Number(opts.maxLabelLines || 2)),
        );
        if (opts.showValueLabels) {
          ctx.fillStyle = '#0f172a';
          ctx.font = '10px -apple-system, system-ui, sans-serif';
          ctx.fillText(this.formatCurrency(row.value || 0, 'NZD'), x + (barW / 2), Math.max(pad.top + 10, y - 6));
        }
      });
    },

    monthLabel(month) {
      if (!month) return '';
      const [y, m] = String(month).split('-');
      const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return `${names[Number(m) - 1] || m} ${String(y).slice(2)}`;
    },

    shortCurrency(value) {
      if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
      if (value >= 1000) return `$${(value / 1000).toFixed(0)}k`;
      return `$${Number(value || 0).toFixed(0)}`;
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
      lines.forEach((ln, i) => ctx.fillText(ln, centerX, topY + (i * lineHeight)));
    },

    async submitMapping() {
      if (!this.newMapping.biz_e_product_name || !this.newMapping.xero_description_pattern) return;
      this.savingMapping = true;
      try {
        const { product_mapping } = await CRMAPI.createProductMapping(this.newMapping);
        this.mappings.push(product_mapping);
        this.newMapping = { biz_e_product_name: '', xero_description_pattern: '', match_type: 'exact', notes: '' };
        this.showMappingForm = false;
      } catch (e) {
        alert(e.message || 'Failed to create mapping.');
      } finally {
        this.savingMapping = false;
      }
    },

    async deleteMapping(id) {
      if (!confirm('Delete this product mapping?')) return;
      try {
        await CRMAPI.deleteProductMapping(id);
        this.mappings = this.mappings.filter(m => m.id !== id);
      } catch (e) {
        alert(e.message || 'Failed to delete mapping.');
      }
    },

    // ── Address ──────────────────────────────────────────────────
    get primaryAddress() {
      const addrs = this.customer?.addresses;
      if (!addrs || !addrs.length) return null;
      const street = addrs.find(a => a.type === 'STREET') || addrs[0];
      return [street.line1, street.line2, street.city, street.region, street.postal_code, street.country].filter(Boolean).join(', ');
    },

    get initials() {
      return (this.customer?.name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();
    },
  };
}
