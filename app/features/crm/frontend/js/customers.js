/* Customers list Alpine.js component */

// The new-customer sheet is in the page from the start (hidden), so Alpine evaluates its
// bindings on load: the form must already have every field, address included.
function blankCustomerForm(sync = false) {
  return {
    name: '', first_name: '', last_name: '', email_address: '', phone_number: '', sync,
    address: { line1: '', line2: '', city: '', region: '', postal_code: '', country: '' },
  };
}

function crmCustomers() {
  return {
    filtersOpen: false,
    selected: null,
    previewTrigger: null,
    customers: [],
    total: 0,
    page: 1,
    pageSize: 50,
    totalPages: 1,
    loading: true,
    error: null,
    search: '',
    searchTimer: null,
    sortBy: 'name',
    sortDir: 'asc',
    statusFilter: '',
    missingContactOnly: false,
    xeroStatus: null,
    syncing: false,
    newCustomer: { open: false, saving: false, error: '', hint: '', form: blankCustomerForm() },
    importer: { open: false, format: 'csv', text: '', fileName: '', busy: false, error: '', result: null, saved: false },

    async init() {
      const params = new URLSearchParams(window.location.search);
      this.missingContactOnly = params.get('missing_contact') === '1';
      await this.loadXeroStatus();
      await this.loadCustomers();
      if (params.get('new') === '1' && this.$el.querySelector('[data-new-customer]')) {
        await this.openNewCustomer();
      }
    },

    async loadXeroStatus() {
      try {
        this.xeroStatus = await CRMAPI.getXeroStatus();
      } catch (_) {
        this.xeroStatus = { connected: false };
      }
    },

    get isConnected() { return this.xeroStatus?.connected === true; },
    get importReady() { return this.importer.result ? this.importer.result.ready : 0; },
    get importCreated() { return this.importer.result ? this.importer.result.created : 0; },
    get importRejected() { return this.importer.result ? this.importer.result.rejected : 0; },
    get importProblems() { return this.importer.result ? this.importer.result.problems : []; },
    get importPreview() { return this.importer.result ? this.importer.result.preview.slice(0, 20) : []; },
    get importMore() { return Math.max(0, this.importReady - 20); },
    get hasImportResult() { return Boolean(this.importer.result); },
    get canCommitImport() { return this.hasImportResult && !this.importer.saved && !this.importer.busy && this.importReady > 0; },

    get syncSubtitle() {
      if (!this.xeroStatus) return 'Loading…';
      if (!this.isConnected) return 'Xero not connected';
      const s = this.xeroStatus.last_successful_sync_at;
      if (!s) return `Connected to ${this.xeroStatus.tenant_name || 'Xero'}`;
      const d = new Date(s);
      return `Synced ${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ${this.xeroStatus.tenant_name || 'Xero'}`;
    },

    filtersChanged() {
      this.page = 1;
      return this.loadCustomers();
    },

    toggleMissingContact() {
      this.missingContactOnly = !this.missingContactOnly;
      return this.filtersChanged();
    },

    async loadCustomers() {
      this.loading = true;
      this.error = null;
      try {
        const params = { page: this.page, page_size: this.pageSize, sort_by: this.sortBy, sort_dir: this.sortDir };
        if (this.search)      params.q      = this.search;
        if (this.statusFilter) params.status = this.statusFilter;
        if (this.missingContactOnly) params.missing_contact = '1';
        const data = await CRMAPI.getCustomers(params);
        this.customers  = data.customers  || [];
        this.total      = data.total      || 0;
        this.totalPages = data.total_pages || 1;
        this.page       = data.page       || 1;
        this.selected = null;
      } catch (e) {
        this.error = e.message || 'Failed to load customers.';
      } finally {
        this.loading = false;
      }
    },

    get resultLabel() {
      if (this.error) return 'Customer directory unavailable';
      return `${this.total} ${this.total === 1 ? 'customer' : 'customers'}${this.search || this.statusFilter || this.missingContactOnly ? ' match' : ' in your directory'}`;
    },

    changeOrder(value) {
      [this.sortBy, this.sortDir] = value.split(':');
      this.page = 1;
      this.loadCustomers();
    },

    clearFilters() {
      clearTimeout(this.searchTimer);
      this.search = '';
      this.statusFilter = '';
      this.missingContactOnly = false;
      this.page = 1;
      this.loadCustomers();
    },

    customerUrl(id) { return `/crm/customers/${encodeURIComponent(id)}`; },

    previewCustomer(customer, trigger) {
      this.selected = customer;
      this.previewTrigger = trigger;
      this.$nextTick(() => this.$root.querySelector('[data-close-preview]')?.focus());
    },

    closePreview() {
      this.selected = null;
      if (this.previewTrigger?.isConnected) this.previewTrigger.focus();
      this.previewTrigger = null;
    },

    trapPreviewFocus(event) {
      const links = [...event.currentTarget.querySelectorAll('button, a[href]')].filter(el => el.getClientRects().length);
      const first = links[0], last = links[links.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    },

    onSearchInput() {
      clearTimeout(this.searchTimer);
      this.searchTimer = setTimeout(() => { this.page = 1; this.loadCustomers(); }, 300);
    },

    setSort(col) {
      if (this.sortBy === col) {
        this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        this.sortBy = col;
        this.sortDir = 'asc';
      }
      this.page = 1;
      this.loadCustomers();
    },

    prevPage() { if (this.page > 1) { this.page--; this.loadCustomers(); } },
    nextPage() { if (this.page < this.totalPages) { this.page++; this.loadCustomers(); } },

    openCustomer(id) { CRMAPI.navigate(this.customerUrl(id)); },

    openImport() {
      this.importer = { open: true, format: 'csv', text: '', fileName: '', busy: false, error: '', result: null, saved: false };
      this.$nextTick(() => document.getElementById('crm-import-file')?.focus());
    },

    async importFile(event) {
      const file = event.target.files?.[0];
      this.importer.result = null;
      this.importer.error = '';
      this.importer.saved = false;
      this.importer.text = '';
      if (!file) return;
      if (file.size > 1000000) { this.importer.error = 'Choose a CSV file smaller than 1 MB.'; return; }
      this.importer.text = await file.text();
      this.importer.fileName = file.name;
      this.importer.format = 'csv';
    },

    async runImport(commit = false) {
      if (this.importer.busy) return;
      if (!this.importer.text.trim()) { this.importer.error = 'Choose a CSV file or paste spreadsheet rows.'; return; }
      this.importer.busy = true;
      this.importer.error = '';
      try {
        const result = await CRMAPI.importCustomers(this.importer.text, this.importer.format, commit);
        this.importer.result = result;
        this.importer.saved = commit;
        if (commit) await this.loadCustomers();
      } catch (e) {
        this.importer.error = e.message || 'Could not read the import.';
        this.importer.result = null;
      } finally {
        this.importer.busy = false;
      }
    },

    downloadImportProblems() {
      const problems = this.importer.result?.problems || [];
      if (!problems.length) return;
      const cell = (value) => {
        let text = String(value ?? '');
        if (/^[\s]*[=+\-@]/.test(text)) text = "'" + text;
        return '"' + text.replaceAll('"', '""') + '"';
      };
      const headers = this.importer.result.headers || [];
      const rows = [[...headers, 'import_error'], ...problems.map((item) => [...headers.map((header) => item.data?.[header] || ''), item.error])];
      const blob = new Blob([rows.map((row) => row.map(cell).join(',')).join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'crm-import-problems.csv';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },

    async openNewCustomer() {
      let settings = { sync_contacts_to_xero: false, xero: { connected: false, can_write_contacts: false } };
      try { settings = await CRMAPI.getContactSyncSettings(); } catch (_) { /* The form still works without it. */ }
      const xero = settings.xero || {};
      this.newCustomer = {
        open: true,
        saving: false,
        error: '',
        // A blank choice follows the Sales default; ticking or unticking makes it this customer's own.
        defaultSync: settings.sync_contacts_to_xero === true,
        hint: !xero.connected
          ? 'Xero is not connected, so it stays in Biz-E until Xero is connected and you try again.'
          : !xero.can_write_contacts
            ? 'The Xero connection only allows reading contacts. Reconnect Xero to send customers.'
            : `Later edits are sent to ${xero.tenant_name || 'Xero'} when you save them.`,
        form: blankCustomerForm(settings.sync_contacts_to_xero === true),
      };
      this.$nextTick(() => document.getElementById('new-customer-name')?.focus());
    },

    closeNewCustomer() { this.newCustomer.open = false; },

    async saveNewCustomer() {
      const form = this.newCustomer.form;
      if (!form.name.trim()) { this.newCustomer.error = 'A customer needs a name.'; return; }
      this.newCustomer.saving = true;
      this.newCustomer.error = '';
      const body = { name: form.name, first_name: form.first_name, last_name: form.last_name, email_address: form.email_address, phone_number: form.phone_number };
      if (Object.values(form.address).some((part) => part.trim())) body.addresses = [{ type: 'POBOX', ...form.address }];
      // Only an explicit difference from the Sales default is stored on the customer.
      body.sync_to_xero = form.sync === this.newCustomer.defaultSync ? null : form.sync;
      try {
        const saved = await CRMAPI.createCustomer(body);
        this.newCustomer.open = false;
        this.openCustomer(saved.customer.id);
      } catch (e) {
        this.newCustomer.error = e.message || 'Could not save the customer.';
      } finally {
        this.newCustomer.saving = false;
      }
    },

    beginXeroConnect() {
      window.location.assign('/crm/xero/auth');
    },

    async doSync() {
      if (this.syncing) return;
      this.syncing = true;
      try {
        const result = await CRMAPI.triggerSync();
        await this.loadXeroStatus();
        this.page = 1;
        await this.loadCustomers();
        if (result?.ok === false) this.error = result.error || 'The Xero sync did not finish.';
      } catch (e) {
        this.error = e.message || 'Sync failed.';
      } finally {
        this.syncing = false;
      }
    },

    statusBadgeClass(status) {
      const s = (status || '').toLowerCase();
      if (s === 'active')   return 'crm-badge--active';
      if (s === 'archived') return 'crm-badge--archived';
      return 'crm-badge--draft';
    },

    initials(name) {
      return (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();
    },

    formatDate(d) {
      if (!d) return '—';
      const dt = new Date(d);
      return isNaN(dt) ? '—' : dt.toLocaleDateString();
    },

    get paginationStart() { return this.total === 0 ? 0 : (this.page - 1) * this.pageSize + 1; },
    get paginationEnd()   { return Math.min(this.page * this.pageSize, this.total); },
  };
}
