/* Xero integration card Alpine.js component (Integrations page) */
function xeroIntegration() {
  return {
    loading: true,
    connected: false,
    tenantName: '',
    lastSync: '',
    syncing: false,
    disconnecting: false,
    error: null,

    async init() {
      try {
        const data = await CRMAPI.getXeroStatus();
        this.connected = data.connected || false;
        this.tenantName = data.tenant_name || '';
        if (data.last_successful_sync_at) {
          const d = new Date(data.last_successful_sync_at);
          this.lastSync = Number.isNaN(d.getTime())
            ? ''
            : d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
        } else {
          this.lastSync = '';
        }
      } catch (e) {
        this.error = e.message || 'Failed to load Xero status.';
      } finally {
        this.loading = false;
      }
    },

    async doSync() {
      if (this.syncing) return;
      this.syncing = true;
      this.error = null;
      try {
        await CRMAPI.triggerSync();
        await this.init();
      } catch (e) {
        this.error = e.message || 'Sync failed.';
      } finally {
        this.syncing = false;
      }
    },

    async doDisconnect() {
      if (!confirm('Disconnect Xero? This will remove your synced contacts and invoices.')) return;
      this.disconnecting = true;
      this.error = null;
      try {
        await CRMAPI.disconnectXero();
        this.connected = false;
        this.tenantName = '';
        this.lastSync = '';
      } catch (e) {
        this.error = e.message || 'Disconnect failed.';
      } finally {
        this.disconnecting = false;
      }
    },
  };
}
