/* Settings › Integrations: the Xero connection (Alpine component). */

// What the Xero OAuth routes send back in ?error=, in words.
var XERO_CONNECT_ERRORS = {
  xero_not_configured: "Xero isn't set up on this server yet. Ask whoever runs Biz-E to add the Xero app details.",
  xero_state_mismatch: "The Xero sign-in didn't match this session. Try connecting again.",
  xero_access_denied: "Xero wasn't given access. Try again and choose Allow access in Xero.",
  xero_no_code: "Xero didn't send an answer back. Try connecting again.",
  xero_no_tenant: 'No Xero organisation was chosen. Try again and pick one.',
  xero_exchange_failed: "Xero couldn't finish connecting. Try again in a minute.",
  xero_session_expired: 'Connecting took too long. Start again.',
};

function xeroIntegration() {
  return {
    loading: true,
    connected: false,
    reconnect: false,
    tenantName: '',
    lastSync: '',
    contacts: 0,
    invoices: 0,
    syncing: false,
    disconnecting: false,
    error: null,
    notice: '',

    // CONCEPT ONLY: the layout switch. Deleted with the two layouts not picked.
    igStyle: '1',
    setIgStyle(style) {
      this.igStyle = style;
      try { window.localStorage.setItem('integrations-style', style); } catch (_) { /* a convenience only */ }
    },

    async init() {
      const params = new URLSearchParams(window.location.search);
      const wanted = params.get('style');
      let kept = null;
      try { kept = window.localStorage.getItem('integrations-style'); } catch (_) { /* storage blocked */ }
      this.igStyle = ['1', '2', '3'].includes(wanted) ? wanted : (['1', '2', '3'].includes(kept) ? kept : '1');
      // A failed connection used to land on Sales settings, which never read ?error=.
      const code = params.get('error');
      if (code) this.error = XERO_CONNECT_ERRORS[code] || `Xero couldn't connect (${code.replace(/^xero_/, '').replace(/_/g, ' ')}).`;
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        const data = await CRMAPI.getXeroStatus();
        this.connected = data.connected || false;
        this.reconnect = !this.connected && data.reconnect_required === true;
        this.tenantName = data.tenant_name || '';
        this.contacts = Number(data.contacts_count || 0);
        this.invoices = Number(data.invoices_count || 0);
        const d = data.last_successful_sync_at ? new Date(data.last_successful_sync_at) : null;
        this.lastSync = d && !Number.isNaN(d.getTime())
          ? d.toLocaleString('en-NZ', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
          : '';
      } catch (e) {
        this.error = e.message || 'The Xero connection could not be checked.';
      } finally {
        this.loading = false;
      }
    },

    get countsWords() {
      const plural = (n, one, many) => `${n.toLocaleString('en-NZ')} ${n === 1 ? one : many}`;
      return `${plural(this.contacts, 'contact', 'contacts')} · ${plural(this.invoices, 'invoice', 'invoices')}`;
    },

    async doSync() {
      if (this.syncing) return;
      this.syncing = true;
      this.error = null;
      this.notice = '';
      try {
        const result = await CRMAPI.triggerSync();
        await this.load();
        if (result?.ok === false) this.error = result.error || 'The Xero sync did not finish.';
        else this.notice = 'Synced.';
      } catch (e) {
        this.error = e.message || 'Sync failed.';
      } finally {
        this.syncing = false;
      }
    },

    // A confirm dialog in the page, rather than window.confirm.
    askDisconnect() {
      this.$refs.disconnect.showModal();
    },

    async doDisconnect() {
      this.disconnecting = true;
      this.error = null;
      try {
        await CRMAPI.disconnectXero();
        this.$refs.disconnect.close();
        this.notice = 'Xero disconnected.';
        await this.load();
      } catch (e) {
        this.error = e.message || 'Disconnect failed.';
      } finally {
        this.disconnecting = false;
      }
    },
  };
}
