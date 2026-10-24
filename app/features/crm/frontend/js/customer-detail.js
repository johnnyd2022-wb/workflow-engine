/* Customer detail Alpine.js component */
// The address parts the edit form holds; lines 3 and 4 and "attention to" stay as Xero has them.
var ADDRESS_EDIT_PARTS = ['line1', 'line2', 'city', 'region', 'postal_code', 'country'];
function joinAddress(parts) { return ADDRESS_EDIT_PARTS.map((part) => (parts[part] || '').trim()).filter(Boolean).join(', '); }
// The edit form is in the page (hidden) from the start, so it needs every field it binds to before it opens.
function blankEditForm() {
  const blankAddress = () => Object.fromEntries(ADDRESS_EDIT_PARTS.map((part) => [part, '']));
  return { name: '', first_name: '', last_name: '', email_address: '', phone_number: '', addresses: { POBOX: blankAddress(), STREET: blankAddress() } };
}

function crmCustomerDetail(contactId) {
  return {
    contactId,
    activeTab: 'overview',
    cdStyle: '1',
    feedFilter: 'all',
    feedFilters: [
      { key: 'all', label: 'Everything' },
      { key: 'invoice', label: 'Invoices' },
      { key: 'note', label: 'Notes' },
      { key: 'task', label: 'Tasks' },
    ],
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
    authorisingInvoiceId: null,
    invoiceForm: {
      invoice_date: '',
      due_date: '',
      invoice_status: 'DRAFT',
      line_items: [],
    },
    loading: true,
    error: null,

    // Details and their sync to Xero
    xeroSync: {},
    xeroConnection: {},
    editing: false,
    confirming: false,
    editSaving: false,
    editError: '',
    editForm: blankEditForm(),
    pendingChanges: [],
    syncSaving: false,
    syncMessage: '',

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
      // CONCEPT ONLY: ?style=1|2|3, then the last one picked, then Style 1.
      const asked = new URLSearchParams(window.location.search || '').get('style');
      let kept = null;
      try { kept = window.localStorage.getItem('customer-detail-style'); } catch (_) { /* private mode */ }
      this.cdStyle = ['1', '2', '3'].includes(asked) ? asked : (['1', '2', '3'].includes(kept) ? kept : '1');
      this.loading = true;
      this.error = null;
      try {
        const data = await CRMAPI.getCustomer(this.contactId);
        this.customer = data.customer;
        this.xeroSync = data.xero_sync || {};
        this.xeroConnection = data.xero_connection || {};
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

    // CONCEPT ONLY
    setCdStyle(style) {
      this.cdStyle = style;
      try { window.localStorage.setItem('customer-detail-style', style); } catch (_) { /* private mode */ }
      this.$nextTick(() => this.drawCustomerAnalyticsCharts());
    },

    // ── What the header and facts say ───────────────────────────
    get contactPerson() {
      const name = `${this.customer?.first_name || ''} ${this.customer?.last_name || ''}`.trim();
      return name && name !== this.customer?.name ? name : '';
    },

    get lastOrder() {
      return this.invoices.find((inv) => inv.date && inv.status !== 'VOIDED' && inv.status !== 'DELETED') || null;
    },

    get openTasks() {
      return this.tasks.filter((t) => t.status === 'pending' || t.status === 'in_progress');
    },

    get overdueTasks() {
      return this.openTasks.filter((t) => t.due_date && this.daysUntil(t.due_date) < 0).length;
    },

    get nextTaskWords() {
      if (!this.openTasks.length) return 'Nothing to follow up';
      if (this.overdueTasks) return `${this.overdueTasks} overdue`;
      const next = this.openTasks.filter((t) => t.due_date).sort((a, b) => (a.due_date < b.due_date ? -1 : 1))[0];
      return next ? `Next: ${next.title} · ${this.dueWords(next).toLowerCase()}` : 'None has a due date';
    },

    get rangeWords() {
      if (!this.analyticsDateFrom || !this.analyticsDateTo) return 'Choose dates';
      return `${this.formatDate(this.analyticsDateFrom)} to ${this.formatDate(this.analyticsDateTo)}`;
    },

    daysUntil(iso) {
      const today = new Date(); today.setHours(0, 0, 0, 0);
      return Math.round((new Date(`${String(iso).slice(0, 10)}T00:00:00`) - today) / 86400000);
    },

    agoWords(iso) {
      const n = -this.daysUntil(iso);
      if (n <= 0) return 'Today';
      if (n === 1) return 'Yesterday';
      if (n < 60) return `${n} days ago`;
      return `${Math.round(n / 30)} months ago`;
    },

    dueWords(task) {
      if (!task.due_date) return 'No date';
      if (task.status === 'completed') return 'Done';
      if (task.status === 'cancelled') return 'Cancelled';
      const n = this.daysUntil(task.due_date);
      if (n < 0) return n === -1 ? '1 day overdue' : `${-n} days overdue`;
      if (n === 0) return 'Today';
      if (n === 1) return 'Tomorrow';
      return this.formatDate(task.due_date);
    },

    // Style 3: invoices, notes and tasks in one list, newest first.
    get activity() {
      const items = [];
      const statusWords = { AUTHORISED: 'Awaiting payment', PAID: 'Paid', DRAFT: 'Draft', SUBMITTED: 'Awaiting approval', VOIDED: 'Voided' };
      this.invoices.forEach((inv) => {
        const owed = inv.status === 'AUTHORISED' && inv.due_date && this.daysUntil(inv.due_date) < 0 ? ' · overdue' : '';
        items.push({
          key: `i-${inv.id}`, kind: 'invoice', icon: '$', when: inv.date || '',
          title: `Invoice ${inv.invoice_number || ''}`.trim(),
          meta: `${this.formatDate(inv.date)} · ${statusWords[inv.status] || inv.status}${owed}`,
          side: this.formatCurrency(inv.total, inv.currency_code),
          open: () => this.viewInvoice(inv),
        });
      });
      this.notes.forEach((note) => {
        items.push({
          key: `n-${note.id}`, kind: 'note', icon: '✎', when: note.created_at || '', text: note.content,
          meta: this.formatNoteDate(note.created_at), side: '',
        });
      });
      this.tasks.forEach((task) => {
        const done = task.status === 'completed' || task.status === 'cancelled';
        if (!done) return; // open tasks are under "Coming up"
        items.push({
          key: `t-${task.id}`, kind: 'task', icon: done ? '✓' : '○',
          when: (done ? task.completed_at || task.updated_at : task.due_date) || task.created_at || '',
          title: task.title,
          meta: [done ? (task.status === 'completed' ? 'Done' : 'Cancelled') : this.dueWords(task), task.assigned_to_user_id ? this.assigneeName(task.assigned_to_user_id) : ''].filter(Boolean).join(' · '),
          side: '',
          open: () => this.openTaskEdit(task),
        });
      });
      return items
        .filter((item) => this.feedFilter === 'all' || item.kind === this.feedFilter)
        .sort((a, b) => (String(a.when) < String(b.when) ? 1 : -1));
    },

    get upcoming() {
      if (this.feedFilter !== 'all' && this.feedFilter !== 'task') return [];
      return this.openTasks.slice()
        .sort((a, b) => String(a.due_date || '9999').localeCompare(String(b.due_date || '9999')))
        .map((task) => ({
          key: `u-${task.id}`, title: task.title,
          late: !!task.due_date && this.daysUntil(task.due_date) < 0,
          meta: [this.dueWords(task), task.status === 'in_progress' ? 'In progress' : '', task.assigned_to_user_id ? this.assigneeName(task.assigned_to_user_id) : ''].filter(Boolean).join(' · '),
          open: () => this.openTaskEdit(task),
        }));
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

    async viewInvoice(inv) {
      if (!inv?.id) return;
      try {
        const data = await CRMAPI.getInvoiceViewUrl(inv.id);
        const url = data?.view_url;
        if (!url) throw new Error('Xero did not return an online invoice URL.');
        window.open(url, '_blank', 'noopener,noreferrer');
      } catch (e) {
        alert(e.message || 'Failed to open invoice in Xero.');
      }
    },

    async downloadInvoice(inv) {
      if (!inv?.id) return;
      try {
        const blob = await this.fetchInvoicePdfBlob(inv.id, false);
        const objectUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = objectUrl;
        a.download = `${inv.invoice_number || 'invoice'}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
      } catch (e) {
        alert(e.message || 'Failed to download invoice PDF.');
      }
    },

    async fetchInvoicePdfBlob(invoiceId, inline = false) {
      const res = await fetch(CRMAPI.invoicePdfUrl(invoiceId, inline), { credentials: 'same-origin' });
      if (!res.ok) {
        let msg = `Failed to load invoice PDF (HTTP ${res.status}).`;
        try {
          const data = await res.json();
          msg = data?.message || data?.error || msg;
        } catch (_) {}
        throw new Error(msg);
      }
      const contentType = String(res.headers.get('content-type') || '').toLowerCase();
      const blob = await res.blob();
      if (contentType.includes('application/pdf')) return blob;
      let msg = 'Xero did not return a PDF for this invoice.';
      try {
        const text = await blob.text();
        const data = JSON.parse(text);
        msg = data?.message || data?.error || msg;
      } catch (_) {}
      throw new Error(msg);
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
    // Open work first, soonest due first; finished work after it.
    get filteredTasks() {
      const shown = this.taskStatusFilter ? this.tasks.filter(t => t.status === this.taskStatusFilter) : this.tasks;
      const open = (t) => (t.status === 'pending' || t.status === 'in_progress' ? 0 : 1);
      return shown.slice().sort((a, b) => open(a) - open(b) || String(a.due_date || '9999').localeCompare(String(b.due_date || '9999')));
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
        invoice_status: 'DRAFT',
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

    canAuthoriseInvoice(inv) {
      const status = String(inv?.status || '').toUpperCase();
      return status === 'DRAFT';
    },

    async authoriseInvoice(inv) {
      if (!inv?.id) return;
      if (!this.canAuthoriseInvoice(inv)) return;
      this.authorisingInvoiceId = inv.id;
      try {
        const { invoice } = await CRMAPI.authoriseInvoice(inv.id);
        const idx = this.invoices.findIndex((x) => x.id === inv.id);
        if (idx !== -1 && invoice) {
          this.invoices[idx] = invoice;
        } else {
          await this.loadInvoices(this.invoicePage || 1);
        }
      } catch (e) {
        alert(e.message || 'Failed to authorise invoice.');
      } finally {
        this.authorisingInvoiceId = null;
      }
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
          invoice_status: this.invoiceForm.invoice_status || 'DRAFT',
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

    get syncChoice() {
      if (this.xeroSync.sync_to_xero === true) return 'on';
      if (this.xeroSync.sync_to_xero === false) return 'off';
      return 'default';
    },

    startEdit() {
      const c = this.customer;
      this.editForm = { name: c.name || '', first_name: c.first_name || '', last_name: c.last_name || '', email_address: c.email_address || '', phone_number: c.phone_number || '' };
      this.editForm.addresses = { POBOX: this.addressParts('POBOX'), STREET: this.addressParts('STREET') };
      this.editError = '';
      this.confirming = false;
      this.editing = true;
      this.$nextTick(() => document.getElementById('edit-name')?.focus());
    },

    cancelEdit() { this.editing = false; this.confirming = false; this.editError = ''; },

    editedFields() {
      const labels = { name: 'Name', first_name: 'First name', last_name: 'Last name', email_address: 'Email', phone_number: 'Phone' };
      const changes = Object.keys(labels)
        .map((field) => ({ field, label: labels[field], before: this.customer[field] || '', after: (this.editForm[field] || '').trim() }))
        .filter((change) => change.before !== change.after);
      ['POBOX', 'STREET'].forEach((kind) => {
        const before = this.addressParts(kind);
        const after = {};
        ADDRESS_EDIT_PARTS.forEach((part) => { after[part] = (this.editForm.addresses[kind][part] || '').trim(); });
        if (ADDRESS_EDIT_PARTS.some((part) => before[part] !== after[part])) {
          changes.push({ field: 'address:' + kind, kind, parts: after, label: this.addressLabel(kind), before: joinAddress(before), after: joinAddress(after) });
        }
      });
      return changes;
    },

    addressLabel(kind) { return kind === 'POBOX' ? 'Postal address' : 'Street address'; },

    addressParts(kind) {
      const stored = (this.customer?.addresses || []).find((a) => (a.type || '').toUpperCase() === kind) || {};
      const parts = {};
      ADDRESS_EDIT_PARTS.forEach((part) => { parts[part] = stored[part] || ''; });
      return parts;
    },

    addressLine(kind) { return joinAddress(this.addressParts(kind)); },

    copyPostalToStreet() { this.editForm.addresses.STREET = { ...this.editForm.addresses.POBOX }; },

    // Edits to a customer that is in Xero (or about to be) wait for an explicit confirmation.
    reviewEdit() {
      this.editError = '';
      if (!(this.editForm.name || '').trim()) { this.editError = 'A customer needs a name.'; return; }
      this.pendingChanges = this.editedFields();
      if (!this.pendingChanges.length) { this.cancelEdit(); return; }
      if (this.xeroSync.syncs) { this.confirming = true; return; }
      this.saveEdit();
    },

    async saveEdit() {
      this.editSaving = true;
      this.editError = '';
      const body = {};
      this.pendingChanges.forEach((change) => {
        if (change.kind) (body.addresses = body.addresses || []).push({ type: change.kind, ...change.parts });
        else body[change.field] = change.after;
      });
      try {
        const saved = await CRMAPI.updateCustomer(this.contactId, body);
        Object.assign(this.customer, saved.customer);
        this.xeroSync = { ...this.xeroSync, ...saved.xero_sync };
        this.editing = false;
        this.confirming = false;
        const status = saved.xero_sync.push_status;
        if (!this.xeroSync.syncs) this.syncMessage = 'Saved.';
        else if (status === 'synced') this.syncMessage = 'Saved and sent to Xero.';
        else this.syncMessage = 'Saved in Biz-E. Xero has not got these changes yet.';
      } catch (e) {
        this.confirming = false;
        this.editError = e.message || 'Could not save the details.';
      } finally {
        this.editSaving = false;
      }
    },

    async setXeroSync(value) {
      const choice = value === 'on' ? true : value === 'off' ? false : null;
      this.syncSaving = true;
      this.syncMessage = '';
      try {
        const saved = await CRMAPI.setCustomerXeroSync(this.contactId, choice);
        Object.assign(this.customer, saved.customer);
        this.xeroSync = { ...this.xeroSync, ...saved.xero_sync };
        if (this.xeroSync.syncs && this.xeroSync.push_status === 'synced') this.syncMessage = 'Sent to Xero. Later edits follow when you save them.';
        else if (!this.xeroSync.syncs && this.xeroSync.in_xero) this.syncMessage = 'Edits now stay in Biz-E. The customer is not removed from Xero.';
      } catch (e) {
        this.error = e.message || 'Could not change the Xero setting.';
      } finally {
        this.syncSaving = false;
      }
    },

    async retryXero() {
      this.syncSaving = true;
      try {
        const saved = await CRMAPI.retryCustomerXeroSync(this.contactId);
        Object.assign(this.customer, saved.customer);
        this.xeroSync = { ...this.xeroSync, ...saved.xero_sync };
        this.syncMessage = this.xeroSync.push_status === 'synced' ? 'Sent to Xero.' : '';
      } catch (e) {
        this.error = e.message || 'Could not send to Xero.';
      } finally {
        this.syncSaving = false;
      }
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
      // Colours from the page's tokens, so the labels stay readable in the dark theme.
      const css = getComputedStyle(canvas);
      const theme = {
        accent: css.getPropertyValue('--ui-accent').trim() || '#0d9488',
        text: css.getPropertyValue('--ui-text').trim() || '#0f172a',
        muted: css.getPropertyValue('--ui-text-muted').trim() || '#6b7280',
      };
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
      ctx.fillStyle = theme.muted;
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
        ctx.fillStyle = theme.accent;
        ctx.fillRect(x, y, barW, barH);
        ctx.fillStyle = theme.text;
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
          ctx.fillStyle = theme.text;
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
