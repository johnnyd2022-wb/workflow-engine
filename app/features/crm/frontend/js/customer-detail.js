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
    mappings: [],
    allMappings: [],
    loading: true,
    error: null,

    // Notes
    newNoteContent: '',
    addingNote: false,
    editingNoteId: null,
    editNoteContent: '',

    // Tasks (for this contact)
    taskStatusFilter: '',

    // New mapping form
    showMappingForm: false,
    newMapping: { biz_e_product_name: '', xero_description_pattern: '', match_type: 'exact', notes: '' },
    savingMapping: false,

    async init() {
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
      } catch (e) {
        this.error = e.message || 'Failed to load customer.';
      } finally {
        this.loading = false;
      }
    },

    // ── Tabs ────────────────────────────────────────────────────
    setTab(tab) { this.activeTab = tab; },

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

    // ── Product Mappings ─────────────────────────────────────────
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
