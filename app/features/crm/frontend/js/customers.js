/* Customers list Alpine.js component */
function crmCustomers() {
  return {
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
    xeroStatus: null,
    syncing: false,

    async init() {
      CRMAPI.ensureBackButton('/crm');
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
        const data = await CRMAPI.getCustomers(params);
        this.customers  = data.customers  || [];
        this.total      = data.total      || 0;
        this.totalPages = data.total_pages || 1;
        this.page       = data.page       || 1;
      } catch (e) {
        this.error = e.message || 'Failed to load customers.';
      } finally {
        this.loading = false;
      }
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

    openCustomer(id) { CRMAPI.navigate(`/crm/customers/${id}`); },

    async doSync() {
      if (this.syncing) return;
      this.syncing = true;
      try {
        await CRMAPI.triggerSync();
        await this.loadXeroStatus();
        this.page = 1;
        await this.loadCustomers();
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
