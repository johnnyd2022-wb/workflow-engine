/* CRM Configuration page */
function crmConfiguration() {
  return {
    loading: true,
    error: null,
    // Settings that failed to load are not shown, so their defaults can't be saved over the real ones.
    loadFailed: false,
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

    contactSync: { loaded: false, saving: false, sync_contacts_to_xero: false, xero: { connected: false, can_write_contacts: false }, message: '' },

    // Each settings section edits its own draft and saves only itself, so one section's Save can
    // never carry another section's unsaved edits (all three used to send the whole form).
    draft: {
      matching: { mode: 'fifo', review_days: 7, strict: true },
      customers: { sync: false },
      revenue: { target: '', obfuscate: false },
      tasks: { archive_days: 7 },
    },
    saving: {},
    note: {},
    sectionError: {},
    editing: {},
    showMappingDialog: false,

    // CONCEPT ONLY: the layout switch. Deleted with the two layouts not picked.
    ssStyle: '1',

    readSsStyle() {
      const wanted = new URLSearchParams(window.location.search).get('style');
      if (['1', '2', '3'].includes(wanted)) return wanted;
      try {
        const kept = window.localStorage.getItem('sales-settings-style');
        if (['1', '2', '3'].includes(kept)) return kept;
      } catch (_) {
        // Storage can be blocked; the default layout is fine.
      }
      return '1';
    },

    setSsStyle(style) {
      this.ssStyle = style;
      this.editing = {};
      try {
        window.localStorage.setItem('sales-settings-style', style);
      } catch (_) {
        // Remembering the choice is a convenience only.
      }
    },

    async init() {
      this.ssStyle = this.readSsStyle();
      this.loading = true;
      this.error = null;
      this.loadFailed = false;
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
        ['matching', 'revenue', 'tasks'].forEach((name) => this.resetDraft(name));
        // The overview's "Map" link arrives with the Xero line to map: open the form for it.
        if (mapPhrase || xeroLine) this.openMappingDialog();
      } catch (e) {
        this.error = e.message || 'Sales settings could not load.';
        this.loadFailed = true;
      } finally {
        this.loading = false;
      }
      await this.loadContactSync();
      this.resetDraft('customers');
    },

    // --- sections -------------------------------------------------------------------------

    savedValues(name) {
      const t = this.traceConfig;
      return {
        matching: { mode: t.mode, review_days: Number(t.review_days), strict: t.strict },
        customers: { sync: this.contactSync.sync_contacts_to_xero === true },
        revenue: { target: t.revenue_baseline_target_mtd, obfuscate: t.obfuscate_sales_figures === true },
        tasks: { archive_days: Number(t.task_done_archive_days) },
      }[name];
    },

    resetDraft(name) {
      this.draft[name] = { ...this.savedValues(name) };
    },

    isDirty(name) {
      const saved = this.savedValues(name);
      const draft = this.draft[name];
      return Object.keys(saved).some((key) => String(draft[key] ?? '') !== String(saved[key] ?? ''));
    },

    get dirtySections() {
      return ['matching', 'customers', 'revenue', 'tasks'].filter((name) => this.isDirty(name));
    },

    get dirtyWords() {
      const names = { matching: 'matching', customers: 'customers', revenue: 'revenue', tasks: 'tasks' };
      const list = this.dirtySections.map((name) => names[name]);
      if (list.length <= 1) return list.join('');
      return `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}`;
    },

    async saveSection(name) {
      if (this.saving[name]) return false;
      this.saving = { ...this.saving, [name]: true };
      this.sectionError = { ...this.sectionError, [name]: '' };
      this.note = { ...this.note, [name]: '' };
      const draft = this.draft[name];
      let ok;
      if (name === 'customers') {
        ok = await this.saveContactSyncDefault(draft.sync === true);
      } else {
        const overrides = {
          matching: { mode: draft.mode, review_days: draft.review_days, strict: draft.strict },
          revenue: { revenue_baseline_target_mtd: draft.target, obfuscate_sales_figures: draft.obfuscate === true },
          tasks: { task_done_archive_days: draft.archive_days },
        }[name];
        ok = await this.saveTraceConfig(overrides);
      }
      this.saving = { ...this.saving, [name]: false };
      if (ok) {
        this.resetDraft(name);
        this.editing = { ...this.editing, [name]: false };
        this.note = { ...this.note, [name]: name === 'customers' ? this.contactSync.message : 'Saved.' };
      } else {
        this.sectionError = { ...this.sectionError, [name]: this.error || 'Could not save.' };
        this.error = null;
      }
      return ok;
    },

    async saveAll() {
      for (const name of this.dirtySections) {
        if (!(await this.saveSection(name))) return;
      }
    },

    discard(name) {
      this.resetDraft(name);
      this.sectionError = { ...this.sectionError, [name]: '' };
      this.editing = { ...this.editing, [name]: false };
    },

    discardAll() {
      this.dirtySections.forEach((name) => this.discard(name));
    },

    startEdit(name) {
      this.resetDraft(name);
      this.note = { ...this.note, [name]: '' };
      this.editing = { ...this.editing, [name]: true };
    },

    // Plain words for the read-first layout.
    get matchingWords() {
      return {
        fifo: 'Automatically, oldest batch first',
        manual: 'You choose the batch for each sale',
        hybrid: 'Automatically, then held for review',
      }[this.traceConfig.mode] || this.traceConfig.mode;
    },

    get targetWords() {
      const value = this.traceConfig.revenue_baseline_target_mtd;
      if (value === '' || value == null) return 'Not set';
      return `$${Number(value).toLocaleString('en-NZ')} a month`;
    },

    openMappingDialog() {
      this.mappingError = null;
      this.showMappingDialog = true;
    },

    closeMappingDialog() {
      if (this.savingMapping) return;
      this.showMappingDialog = false;
    },

    async loadContactSync() {
      try {
        const settings = await CRMAPI.getContactSyncSettings();
        Object.assign(this.contactSync, settings, { loaded: true });
      } catch (_) {
        this.contactSync.loaded = true;
      }
    },

    async saveContactSyncDefault(enabled) {
      this.contactSync.saving = true;
      this.contactSync.message = '';
      try {
        const saved = await CRMAPI.updateContactSyncSettings(enabled);
        Object.assign(this.contactSync, saved);
        const parts = [enabled ? 'On.' : 'Off. Customers created in Biz-E stay in Biz-E unless their own page says otherwise.'];
        if (saved.sent) parts.push(`${saved.sent} waiting customer${saved.sent === 1 ? '' : 's'} sent to Xero.`);
        if (saved.failed) parts.push(`${saved.failed} could not be sent; open them to see why and try again.`);
        this.contactSync.message = parts.join(' ');
        return true;
      } catch (e) {
        this.error = e.message || 'Could not save the Xero setting.';
        this.contactSync.sync_contacts_to_xero = !enabled;
        return false;
      } finally {
        this.contactSync.saving = false;
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
        if (result?.ok === false) this.error = result.error || 'The Xero sync did not finish.';
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

    // Sends the saved settings with ``overrides`` (one section's draft) on top.
    async saveTraceConfig(overrides = {}) {
      const next = { ...this.traceConfig, ...overrides };
      next.review_days = Math.min(90, Math.max(1, Number(next.review_days || 7)));
      next.task_done_archive_days = Math.min(90, Math.max(1, Number(next.task_done_archive_days || 7)));
      try {
        const saved = await CRMAPI.updateTraceabilityConfig({
          matching_strategy: next.mode,
          manual_review_days: next.review_days,
          strict_mapping: next.strict,
          task_done_archive_days: next.task_done_archive_days,
          revenue_baseline_target_mtd:
            next.revenue_baseline_target_mtd === '' || next.revenue_baseline_target_mtd == null
              ? null
              : Number(next.revenue_baseline_target_mtd),
          obfuscate_sales_figures: next.obfuscate_sales_figures === true,
        });
        Object.assign(this.traceConfig, next);
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
          const configured = await this.saveTraceConfig({ strict: false });
          if (!configured) {
            this.mappingError = this.error;
            return;
          }
          this.draft.matching.strict = false;
        }
        const { product_mappings } = await CRMAPI.createProductMappings({ mappings: this.pendingMappings });
        this.mappings = [...(product_mappings || []), ...this.mappings];
        this.pendingMappings = [];
        this.showMappingDialog = false;
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
