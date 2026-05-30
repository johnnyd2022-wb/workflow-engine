/* CRM Configuration page */
function crmConfiguration() {
  return {
    loading: true,
    error: null,
    xero: { connected: false },
    syncing: false,
    disconnecting: false,
    showDisconnectModal: false,
    mappings: [],
    finalProducts: [],
    lineItemOptions: [],
    traceConfig: {
      mode: 'fifo',
      key: 'batch_id',
      review_days: 7,
      strict: true,
      task_done_archive_days: 7,
      revenue_baseline_target_mtd: '',
    },
    savingMapping: false,
    mappingDraft: {
      product_key: '',
      xero_description_pattern: '',
      notes: '',
    },

    async init() {
      CRMAPI.ensureBackButton('/crm');
      this.loading = true;
      this.error = null;
      try {
        const [xero, mappings, finalProducts, lineItems, traceCfg] = await Promise.all([
          CRMAPI.getXeroStatus(),
          CRMAPI.getProductMappings(),
          CRMAPI.getFinalProducts(),
          CRMAPI.getOrgLineItemOptions(),
          CRMAPI.getTraceabilityConfig(),
        ]);
        this.xero = xero || { connected: false };
        this.mappings = mappings?.product_mappings || [];
        this.finalProducts = finalProducts?.final_products || [];
        this.lineItemOptions = lineItems?.line_item_options || [];
        this.traceConfig = {
          mode: traceCfg?.matching_strategy || 'fifo',
          key: traceCfg?.matching_key || 'batch_id',
          review_days: Number(traceCfg?.manual_review_days || 7),
          strict: traceCfg?.strict_mapping !== false,
          task_done_archive_days: Number(traceCfg?.task_done_archive_days || 7),
          revenue_baseline_target_mtd:
            traceCfg?.revenue_baseline_target_mtd == null ? '' : Number(traceCfg.revenue_baseline_target_mtd),
        };
      } catch (e) {
        this.error = e.message || 'Failed to load configuration.';
      } finally {
        this.loading = false;
      }
    },

    get tenantName() {
      return this.xero?.tenant_name || '';
    },

    get lastSyncLabel() {
      const raw = this.xero?.last_successful_sync_at;
      if (!raw) return '';
      const dt = new Date(raw);
      if (Number.isNaN(dt.getTime())) return '';
      return dt.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
    },

    async doSync() {
      if (this.syncing) return;
      this.syncing = true;
      try {
        await CRMAPI.triggerSync();
        this.xero = await CRMAPI.getXeroStatus();
      } catch (e) {
        this.error = e.message || 'Sync failed.';
      } finally {
        this.syncing = false;
      }
    },

    async doDisconnect() {
      this.disconnecting = true;
      try {
        await CRMAPI.disconnectXero();
        this.xero = { connected: false };
        this.closeDisconnectModal();
      } catch (e) {
        this.error = e.message || 'Disconnect failed.';
      } finally {
        this.disconnecting = false;
      }
    },

    openDisconnectModal() {
      this.showDisconnectModal = true;
    },

    closeDisconnectModal() {
      this.showDisconnectModal = false;
    },

    beginXeroConnect() {
      const fallbackLocal = () => {
        const popup = window.open('/crm/xero/auth', '_blank');
        if (popup && !popup.closed) return;
        window.location.assign('/crm/xero/auth');
        window.setTimeout(() => {
          if (window.location.pathname.startsWith('/crm/configuration')) {
            window.location.replace('/crm/xero/auth');
          }
        }, 120);
      };

      CRMAPI.getXeroAuthUrl()
        .then((data) => {
          const authUrl = data?.auth_url;
          if (!authUrl) {
            fallbackLocal();
            return;
          }
          // Prefer a new tab (mobile/webview friendly). Fallback to top-level nav.
          const popup = window.open(authUrl, '_blank');
          if (popup && !popup.closed) return;
          try {
            window.top.location.href = authUrl;
          } catch (_) {
            window.location.href = authUrl;
          }
        })
        .catch(() => {
          fallbackLocal();
        });
    },

    async saveTraceConfig() {
      this.traceConfig.review_days = Math.min(90, Math.max(1, Number(this.traceConfig.review_days || 7)));
      this.traceConfig.task_done_archive_days = Math.min(90, Math.max(1, Number(this.traceConfig.task_done_archive_days || 7)));
      try {
        const saved = await CRMAPI.updateTraceabilityConfig({
          matching_strategy: this.traceConfig.mode,
          manual_review_days: this.traceConfig.review_days,
          strict_mapping: this.traceConfig.strict,
          task_done_archive_days: this.traceConfig.task_done_archive_days,
          revenue_baseline_target_mtd:
            this.traceConfig.revenue_baseline_target_mtd === '' || this.traceConfig.revenue_baseline_target_mtd == null
              ? null
              : Number(this.traceConfig.revenue_baseline_target_mtd),
        });
        this.traceConfig.mode = saved?.matching_strategy || this.traceConfig.mode;
        this.traceConfig.key = saved?.matching_key || 'batch_id';
        this.traceConfig.review_days = Number(saved?.manual_review_days || this.traceConfig.review_days);
        this.traceConfig.strict = saved?.strict_mapping !== false;
        this.traceConfig.task_done_archive_days = Number(saved?.task_done_archive_days || this.traceConfig.task_done_archive_days);
        this.traceConfig.revenue_baseline_target_mtd =
          saved?.revenue_baseline_target_mtd == null ? '' : Number(saved.revenue_baseline_target_mtd);
      } catch (e) {
        this.error = e.message || 'Failed to save traceability settings.';
      }
    },

    productOptionLabel(product) {
      const step = product?.source_step_name ? ` • ${product.source_step_name}` : '';
      return `${product?.name || 'Unnamed'}${step}`;
    },

    parseProductKey() {
      const raw = String(this.mappingDraft.product_key || '');
      if (!raw) return { name: '', source_output_id: null };
      const [source, name] = raw.split('||');
      return { name: name || '', source_output_id: source || null };
    },

    async createMapping() {
      const product = this.parseProductKey();
      const xero = String(this.mappingDraft.xero_description_pattern || '').trim();
      if (!product.name || !xero) return;
      this.savingMapping = true;
      try {
        const payload = {
          biz_e_product_name: product.name,
          biz_e_source_output_id: product.source_output_id,
          xero_description_pattern: xero,
          match_type: 'exact',
          notes: (this.mappingDraft.notes || '').trim() || null,
        };
        const { product_mapping } = await CRMAPI.createProductMapping(payload);
        this.mappings.unshift(product_mapping);
        this.mappingDraft = { product_key: '', xero_description_pattern: '', notes: '' };
      } catch (e) {
        this.error = e.message || 'Failed to create mapping.';
      } finally {
        this.savingMapping = false;
      }
    },

    async deleteMapping(id) {
      if (!confirm('Delete this mapping?')) return;
      try {
        await CRMAPI.deleteProductMapping(id);
        this.mappings = this.mappings.filter((m) => m.id !== id);
      } catch (e) {
        this.error = e.message || 'Failed to delete mapping.';
      }
    },

    mappingStatusClass(mapping) {
      return mapping?.mapping_status === 'stale' ? 'crm-badge--cancelled' : 'crm-badge--active';
    },
  };
}
