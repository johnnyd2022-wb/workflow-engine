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
    // CONCEPT ONLY: delete style state and helpers after the founder chooses a direction.
    style: '1',
    wide: window.innerWidth >= 900,
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

    async init() {
      // CONCEPT ONLY: a URL choice wins over the local preview preference.
      const requested = new URLSearchParams(window.location.search).get('style');
      let remembered = null;
      try { remembered = sessionStorage.getItem('customers-design-style'); } catch (_) { /* Storage can be disabled. */ }
      this.style = ['1', '2', '3'].includes(requested) ? requested : ['1', '2', '3'].includes(remembered) ? remembered : '1';
      try { sessionStorage.setItem('customers-design-style', this.style); } catch (_) { /* Optional preference. */ }
      this.missingContactOnly = new URLSearchParams(window.location.search).get('missing_contact') === '1';
      await this.loadXeroStatus();
      await this.loadCustomers();
    },

    async loadXeroStatus() {
      try {
        this.xeroStatus = await CRMAPI.getXeroStatus();
      } catch (_) {
        this.xeroStatus = { connected: false };
      }
    },

    get isConnected() { return this.xeroStatus?.connected === true; },

    get syncSubtitle() {
      if (!this.xeroStatus) return 'Loading…';
      if (!this.isConnected) return 'Xero not connected';
      const s = this.xeroStatus.last_successful_sync_at;
      if (!s) return `Connected to ${this.xeroStatus.tenant_name || 'Xero'}`;
      const d = new Date(s);
      return `Synced ${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ${this.xeroStatus.tenant_name || 'Xero'}`;
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
        this.selected = this.style === '2' && this.wide ? this.customers.find(c => c.id === this.selected?.id) || this.customers[0] || null : null;
      } catch (e) {
        this.error = e.message || 'Failed to load customers.';
      } finally {
        this.loading = false;
      }
    },

    // CONCEPT ONLY: layout preference never changes the query or customer data.
    chooseStyle(style) {
      this.style = style;
      try { sessionStorage.setItem('customers-design-style', style); } catch (_) { /* Optional preference. */ }
      this.selected = style === '2' && this.wide ? this.customers[0] || null : null;
    },

    get contactGroups() {
      return [
        { name: 'Contact details needed', rows: this.customers.filter(c => !c.email_address || !c.phone_number) },
        { name: 'Ready to reach', rows: this.customers.filter(c => c.email_address && c.phone_number) },
      ];
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
      if (!(this.style === '2' && this.wide)) this.$nextTick(() => this.$root.querySelector('[data-close-preview]')?.focus());
    },

    closePreview() {
      this.selected = null;
      if (this.previewTrigger?.isConnected) this.previewTrigger.focus();
      this.previewTrigger = null;
    },

    resizePreview() {
      const wasWide = this.wide;
      this.wide = window.innerWidth >= 900;
      if (wasWide && !this.wide && this.style === '2' && this.selected) {
        this.$nextTick(() => this.$root.querySelector('[data-close-preview]')?.focus());
      }
    },

    trapPreviewFocus(event) {
      if (this.style === '2' && this.wide) return;
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
