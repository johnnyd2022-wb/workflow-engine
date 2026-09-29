/* CRM Configuration page */
function crmConfiguration() {
  return {
    loading: true,
    error: null,
    xero: { connected: false },
    syncing: false,
    syncSummary: null,
    disconnecting: false,
    showDisconnectModal: false,
    showDeleteMappingModal: false,
    mappingToDelete: null,
    deletingMapping: false,
    mappings: [],
    pendingMappings: [],
    finalProducts: [],
    lineItemOptions: [],
    traceConfig: {
      mode: 'fifo',
      key: 'batch_id',
      review_days: 7,
      strict: true,
      task_done_archive_days: 7,
      revenue_baseline_target_mtd: '',
      obfuscate_sales_figures: false,
    },
    savingMapping: false,
    mappingError: null,
    mappingDraft: {
      product_key: '',
      xero_description_pattern: '',
      match_type: 'exact',
      units_per_line: 1,
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
        const mapPhrase = new URLSearchParams(window.location.search).get('map');
        if (mapPhrase) {
          this.mappingDraft.xero_description_pattern = mapPhrase;
          if (!this.lineItemOptions.some((option) => (option.description || option.item_code) === mapPhrase)) {
            this.lineItemOptions.push({ description: mapPhrase, display_label: mapPhrase });
          }
        }
        this.traceConfig = {
          mode: traceCfg?.matching_strategy || 'fifo',
          key: traceCfg?.matching_key || 'batch_id',
          review_days: Number(traceCfg?.manual_review_days || 7),
          strict: traceCfg?.strict_mapping !== false,
          task_done_archive_days: Number(traceCfg?.task_done_archive_days || 7),
          revenue_baseline_target_mtd:
            traceCfg?.revenue_baseline_target_mtd == null ? '' : Number(traceCfg.revenue_baseline_target_mtd),
          obfuscate_sales_figures: traceCfg?.obfuscate_sales_figures === true,
        };
        const params = new URLSearchParams(window.location.search);
        const xeroLine = params.get('xero_line');
        if (xeroLine && this.lineItemOptions.some((option) => (option.description || option.item_code) === xeroLine)) {
          this.mappingDraft.xero_description_pattern = xeroLine;
        }
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
        const result = await CRMAPI.triggerSync();
        this.syncSummary = {
          allocated: Number(result?.sales_allocated || 0),
          unmapped: Number(result?.sales_unmapped || 0),
          insufficientStock: Number(result?.sales_insufficient_stock || 0),
        };
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
          obfuscate_sales_figures: this.traceConfig.obfuscate_sales_figures === true,
        });
        this.traceConfig.mode = saved?.matching_strategy || this.traceConfig.mode;
        this.traceConfig.key = saved?.matching_key || 'batch_id';
        this.traceConfig.review_days = Number(saved?.manual_review_days || this.traceConfig.review_days);
        this.traceConfig.strict = saved?.strict_mapping !== false;
        this.traceConfig.task_done_archive_days = Number(saved?.task_done_archive_days || this.traceConfig.task_done_archive_days);
        this.traceConfig.revenue_baseline_target_mtd =
          saved?.revenue_baseline_target_mtd == null ? '' : Number(saved.revenue_baseline_target_mtd);
        this.traceConfig.obfuscate_sales_figures = saved?.obfuscate_sales_figures === true;
        return true;
      } catch (e) {
        this.error = e.message || 'Failed to save traceability settings.';
        return false;
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

    get draftIsComplete() {
      return Boolean(this.mappingDraft.product_key && String(this.mappingDraft.xero_description_pattern || '').trim());
    },

    get canSaveMappings() {
      return this.pendingMappings.length > 0 || this.draftIsComplete;
    },

    // Xero phrases match case-insensitively on the server, so duplicates are judged the same way here.
    isDuplicateMapping(payload) {
      const key = (mapping) =>
        `${mapping.biz_e_product_name}\u0000${String(mapping.xero_description_pattern || '').trim().toLocaleLowerCase()}`;
      const wanted = key(payload);
      return this.pendingMappings.concat(this.mappings).some((mapping) => key(mapping) === wanted);
    },

    queueMapping() {
      const product = this.parseProductKey();
      const xero = String(this.mappingDraft.xero_description_pattern || '').trim();
      if (!product.name || !xero) return false;
      const payload = {
        biz_e_product_name: product.name,
        biz_e_source_output_id: product.source_output_id,
        xero_description_pattern: xero,
        match_type: this.mappingDraft.match_type === 'contains' ? 'contains' : 'exact',
        units_per_line: Math.max(1, parseInt(this.mappingDraft.units_per_line, 10) || 1),
        notes: (this.mappingDraft.notes || '').trim() || null,
      };
      if (this.isDuplicateMapping(payload)) {
        this.mappingError = 'That mapping is already saved or in the review list.';
        return false;
      }
      this.mappingError = null;
      this.pendingMappings.push(payload);
      this.mappingDraft = { product_key: '', xero_description_pattern: '', match_type: 'exact', units_per_line: 1, notes: '' };
      return true;
    },

    removePendingMapping(index) {
      this.pendingMappings.splice(index, 1);
    },

    async saveMappings() {
      if (this.savingMapping) return;
      // A completed but un-queued form counts as intent to save: queue it rather than ignore the click.
      if (this.draftIsComplete && !this.queueMapping()) return;
      if (this.pendingMappings.length === 0) return;
      this.savingMapping = true;
      this.mappingError = null;
      try {
        const needsPartialMatching = this.pendingMappings.some((mapping) => mapping.match_type === 'contains');
        if (needsPartialMatching && this.traceConfig.strict) {
          const strictBeforeSave = this.traceConfig.strict;
          this.traceConfig.strict = false;
          const configured = await this.saveTraceConfig();
          if (!configured) {
            this.traceConfig.strict = strictBeforeSave;
            this.mappingError = this.error;
            return;
          }
        }
        const { product_mappings } = await CRMAPI.createProductMappings({ mappings: this.pendingMappings });
        this.mappings = [...(product_mappings || []), ...this.mappings];
        this.pendingMappings = [];
      } catch (e) {
        this.mappingError = e.message || 'Failed to save mappings.';
      } finally {
        this.savingMapping = false;
      }
    },

    openDeleteMappingModal(mapping) {
      this.mappingToDelete = mapping;
      this.showDeleteMappingModal = true;
    },

    closeDeleteMappingModal() {
      if (this.deletingMapping) return;
      this.showDeleteMappingModal = false;
      this.mappingToDelete = null;
    },

    async confirmDeleteMapping() {
      const mapping = this.mappingToDelete;
      if (!mapping || this.deletingMapping) return;
      this.deletingMapping = true;
      try {
        await CRMAPI.deleteProductMapping(mapping.id);
        this.mappings = this.mappings.filter((m) => m.id !== mapping.id);
        this.showDeleteMappingModal = false;
        this.mappingToDelete = null;
      } catch (e) {
        this.error = e.message || 'Failed to delete mapping.';
      } finally {
        this.deletingMapping = false;
      }
    },

    mappingStatusClass(mapping) {
      return mapping?.mapping_status === 'stale' ? 'crm-badge--cancelled' : 'crm-badge--active';
    },
  };
}
