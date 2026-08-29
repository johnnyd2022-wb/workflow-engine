// Core API client for connecting frontend to backend

function _getRumTraceHeaders(url, method) {
    if (typeof window === 'undefined' || !window.ObservabilityRUM) {
        return {};
    }
    try {
        const headers = window.ObservabilityRUM.getTraceHeaders(url, method);
        return headers && typeof headers === 'object' ? headers : {};
    } catch (_err) {
        return {};
    }
}

window.CoreAPI = window.CoreAPI || {
    baseURL: '/api/core',
    _inFlightGets: new Map(),

    // Several independent widgets on one page (dashboard summary, the notification
    // badge, the findings banner) routinely ask for the same data within milliseconds
    // of each other on page load -- e.g. three separate CoreAPI.getSystemFindings()
    // callers firing off the same /api/core/system-findings request. Dedupe plain,
    // uncancellable GETs by sharing the in-flight promise instead of firing a second
    // identical request; a caller with its own AbortSignal wants its own request
    // lifecycle (e.g. a search box cancelling a stale query) and is excluded.
    async request(endpoint, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        if (method === 'GET' && !options.signal) {
            const existing = this._inFlightGets.get(endpoint);
            if (existing) return existing;
            const promise = this._doRequest(endpoint, options).finally(() => {
                this._inFlightGets.delete(endpoint);
            });
            this._inFlightGets.set(endpoint, promise);
            return promise;
        }
        return this._doRequest(endpoint, options);
    },

    async _doRequest(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const method = (options.method || 'GET').toUpperCase();
        const mutating = ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method);
        const csrfMeta = typeof document !== 'undefined' && document.querySelector
            ? document.querySelector('meta[name="csrf-token"]')
            : null;
        const csrfTok = csrfMeta && csrfMeta.getAttribute('content');
        const traceHeaders = _getRumTraceHeaders(url, method);
        const mergedHeaders = {
            ...(traceHeaders || {}),
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        };
        if (mutating && csrfTok) {
            mergedHeaders['X-CSRFToken'] = csrfTok;
        }
        const config = {
            ...options,
            headers: mergedHeaders,
        };
        if (options.body instanceof FormData) {
            delete config.headers['Content-Type'];
            config.body = options.body;
        } else if (options.body && typeof options.body === 'object') {
            config.body = JSON.stringify(options.body);
        }
        
        try {
            const response = await fetch(url, config);
            let data;
            try {
                data = await response.json();
            } catch (parseErr) {
                // The response headers arrived but the body read was aborted by a
                // navigation (SPA nav cancels in-flight fetches). Not an error worth
                // logging -- surface it like any other abort.
                if (parseErr && parseErr.name === 'AbortError') throw parseErr;
                console.error(`API request failed: ${endpoint} - invalid JSON`, parseErr);
                throw new Error(response.ok ? 'Invalid response from server.' : `Server error (${response.status}). Please try again.`);
            }
            if (!response.ok) {
                const msg = data.message || data.error || `HTTP error! status: ${response.status}`;
                const details = data.details ? ` ${data.details}` : '';
                const errList = Array.isArray(data.errors) && data.errors.length ? ` ${data.errors.join('; ')}` : '';
                const err = new Error(msg + details + errList);
                err.status = response.status;
                err.body = data;   // e.g. a 409 stale_write carries { current: <server state> }
                throw err;
            }
            return data;
        } catch (error) {
            if (error && error.name === 'AbortError') {
                throw error;
            }
            console.error(`API request failed: ${endpoint}`, error);
            if (error && error.name === 'TypeError') {
                const msg = String(error.message || '').toLowerCase();
                if (
                    msg.indexOf('failed to fetch') !== -1 ||
                    msg.indexOf('load failed') !== -1 ||
                    msg.indexOf('networkerror') !== -1 ||
                    msg.indexOf('network request failed') !== -1
                ) {
                    throw new Error('Network error. Check your connection and that the server is running, then try again.');
                }
            }
            throw error;
        }
    },
    
    // True when a write was rejected because someone else saved first (409 stale_write
    // from an If-Match request). `err.body.current` holds the current server state.
    isStaleWrite(err) {
        return !!(err && err.status === 409 && err.body && err.body.error === 'stale_write');
    },

    // Processes
    async getProcesses(includeSteps = false) {
        const query = includeSteps ? '?include_steps=true' : '';
        return this.request(`/processes${query}`);
    },
    
    async getProcess(processId) {
        return this.request(`/processes/${processId}`);
    },
    
    async createProcess(data) {
        return this.request('/processes', {
            method: 'POST',
            body: data,
        });
    },
    
    // `expectedUpdatedAt` (optional): the `updated_at` this client last read. When given,
    // sends `If-Match`; the server replies 409 { current } if someone else saved since.
    async updateProcess(processId, data, expectedUpdatedAt) {
        return this.request(`/processes/${processId}`, {
            method: 'PUT',
            body: data,
            headers: expectedUpdatedAt ? { 'If-Match': expectedUpdatedAt } : undefined,
        });
    },
    
    async deleteProcess(processId) {
        return this.request(`/processes/${processId}`, {
            method: 'DELETE',
        });
    },
    
    async addStep(processId, stepData) {
        return this.request(`/processes/${processId}/steps`, {
            method: 'POST',
            body: stepData,
        });
    },
    
    async updateStep(processId, stepId, stepData, expectedUpdatedAt) {
        return this.request(`/processes/${processId}/steps/${stepId}`, {
            method: 'PUT',
            body: stepData,
            headers: expectedUpdatedAt ? { 'If-Match': expectedUpdatedAt } : undefined,
        });
    },
    
    async deleteStep(processId, stepId) {
        return this.request(`/processes/${processId}/steps/${stepId}`, {
            method: 'DELETE',
        });
    },

    // `expectedUpdatedAt` (optional): the newest step `updated_at` this client last read
    // (max across the process's steps) -- the reorder's structural-version token.
    async reorderSteps(processId, orders, expectedUpdatedAt) {
        // `orders` can be either an array of step ids (preferred) or an array of {id,...}.
        const stepIds = Array.isArray(orders)
            ? orders.map(o => (o && typeof o === 'object') ? (o.id || o.step_id) : o).filter(Boolean)
            : [];
        return this.request(`/processes/${processId}/steps/reorder`, {
            method: 'POST',
            body: { step_ids: stepIds },
            headers: expectedUpdatedAt ? { 'If-Match': expectedUpdatedAt } : undefined,
        });
    },
    
    // Alias for addStep
    async createStep(processId, stepData) {
        return this.addStep(processId, stepData);
    },
    
    // Executions
    async getExecutions(processId = null, status = null, options = {}) {
        const params = new URLSearchParams();
        if (processId) params.append('process_id', processId);
        if (status) params.append('status', status);
        if (options.count) params.append('count', '1');           // -> { count }
        if (options.limit != null) params.append('limit', String(options.limit));
        if (options.cursor) params.append('cursor', options.cursor);
        const query = params.toString() ? `?${params.toString()}` : '';
        return this.request(`/executions${query}`);
    },
    
    async getExecution(executionId) {
        return this.request(`/executions/${executionId}`);
    },

    /** Single round-trip: execution + process (execute-step SPA). */
    async getExecutionWithProcess(executionId) {
        return this.request(`/executions/${encodeURIComponent(executionId)}/with-process?minimal=1`);
    },
    
    async createExecution(processId) {
        return this.request('/executions', {
            method: 'POST',
            body: { process_id: processId },
        });
    },
    
    async completeStep(executionId, executionStepId, data) {
        return this.request(`/executions/${executionId}/steps/${executionStepId}/complete`, {
            method: 'POST',
            body: data,
        });
    },
    
    // Inventory
    async getInventory(type = null, processId = null, options = {}) {
        const params = new URLSearchParams();
        if (type) params.append('type', type);
        if (processId) params.append('process_id', processId);
        // view=compact drops per-item enrichment (system findings, producing-step
        // hydration, audit history) -- ~20x smaller, for callers that only need the
        // core item fields (e.g. the sourcemap browse grid).
        if (options.compact) params.append('view', 'compact');
        const query = params.toString() ? `?${params.toString()}` : '';
        const signal = options.signal;
        return this.request(`/inventory${query}`, signal ? { signal } : {});
    },
    
    async getOutOfStockRawMaterials() {
        return this.request('/inventory/out-of-stock');
    },
    
    async getExpiredMaterials(options = {}) {
        const signal = options.signal;
        return this.request('/inventory/expired-materials', signal ? { signal } : {});
    },

    async getUntrackedItems(options = {}) {
        const signal = options.signal;
        return this.request('/inventory/untracked-items', signal ? { signal } : {});
    },

    /** Get output ready date findings (outputs not yet usable). */
    async getOutputReadyDate() {
        return this.request('/inventory/output-ready-date');
    },

    /** Get untracked items matching name and unit (for Add to Inventory and execution modal reconciliation).
     * When executionId is provided, includes items with qty 0 that were consumed in that execution. */
    async getMatchingUntracked(name, unit, processId = null, executionId = null, options = {}) {
        const params = new URLSearchParams({ name: name || '', unit: unit || '' });
        if (processId) params.set('process_id', processId);
        if (executionId) params.set('execution_id', executionId);
        const signal = options.signal;
        return this.request(`/inventory/reconcile/matching-untracked?${params.toString()}`, signal ? { signal } : {});
    },

    /** Path A: Add to inventory with optional mapping to an untracked item. */
    async reconcileViaAddition(data) {
        return this.request('/inventory/reconcile/via-addition', {
            method: 'POST',
            body: data,
        });
    },

    /** Path B: Map untracked item to an execution output. */
    async reconcileViaExecution(data) {
        return this.request('/inventory/reconcile/via-execution', {
            method: 'POST',
            body: data,
        });
    },

    // /api/core/system-findings runs the whole system-check suite server-side (a DAG
    // traversal per expired-with-stock raw material -- ~100 queries on a real org). On
    // /core it has several independent callers within one page load: the findings banner's
    // own init, and the hub's journey-CTA state. The in-flight dedupe only helps while a
    // request is still open; a caller that fires just after the first one settled would
    // run the suite a second time. This short settle-window cache collapses that burst
    // without introducing meaningful staleness (findings are a slow-moving health
    // summary). Post-mutation refreshes land well outside the window.
    _systemFindingsCache: null,
    SYSTEM_FINDINGS_TTL_MS: 3000,

    /** Run all system checks and return banner-ready findings. Result is shared for a
     *  few seconds so the several page-load callers trigger one server-side run. */
    async getSystemFindings() {
        const c = this._systemFindingsCache;
        if (c && (Date.now() - c.ts) < this.SYSTEM_FINDINGS_TTL_MS) {
            return c.promise;
        }
        const promise = this.request('/system-findings');
        this._systemFindingsCache = { ts: Date.now(), promise };
        promise.catch(() => {
            // don't cache a rejection past its own settle
            if (this._systemFindingsCache && this._systemFindingsCache.promise === promise) {
                this._systemFindingsCache = null;
            }
        });
        return promise;
    },

    /** Drop the system-findings settle-window cache (call after an action that changes findings). */
    invalidateSystemFindings() {
        this._systemFindingsCache = null;
    },

    // GET /auth/me, shared for a short window so the page-load user/name widgets (sidebar
    // account info + flows2's getCurrentUser, at least) don't each fetch it. Identity is
    // stable within a session; the window is short enough that a role/2FA change picked up
    // on the next navigation. Callers needing a guaranteed-fresh read (audit fields, the
    // 2FA status toggle) fetch /auth/me directly and are intentionally not routed here.
    _meCache: null,
    ME_TTL_MS: 30000,
    async getMe(force) {
        if (force) this._meCache = null;
        const c = this._meCache;
        if (c && (Date.now() - c.ts) < this.ME_TTL_MS) {
            return c.promise;
        }
        const promise = fetch('/auth/me', { method: 'GET', credentials: 'include' }).then((r) => {
            if (r.status === 401) return { _status: 401 };
            if (!r.ok) throw new Error('auth/me ' + r.status);
            return r.json();
        });
        this._meCache = { ts: Date.now(), promise };
        promise.catch(() => {
            if (this._meCache && this._meCache.promise === promise) this._meCache = null;
        });
        return promise;
    },

    /** @deprecated Use getExpiredMaterials() */
    async getCheckNeededItems() {
        return this.getExpiredMaterials();
    },
    
    async createInventoryItem(data) {
        return this.request('/inventory', {
            method: 'POST',
            body: data,
        });
    },

    /** Look up product by barcode for inventory entry. Returns { exists: boolean, name?, unit?, supplier? }. */
    async lookupBarcode(code) {
        if (!code || !String(code).trim()) return { exists: false };
        const trimmed = String(code).trim();
        const encoded = encodeURIComponent(trimmed);
        return this.request(`/inventory/barcode/${encoded}`);
    },

    async getConfigUnits() {
        return this.request('/config/units');
    },

    async inventoryCsvValidate(formData) {
        return this.request('/inventory/csv-validate', {
            method: 'POST',
            body: formData,
        });
    },

    async inventoryCsvCommit(payload) {
        return this.request('/inventory/csv-commit', {
            method: 'POST',
            body: payload,
        });
    },

    async decodeBarcode(formData) {
        return this.request('/inventory/decode-barcode', {
            method: 'POST',
            body: formData,
        });
    },
    
    async updateInventoryItem(itemId, data) {
        return this.request(`/inventory/${itemId}`, {
            method: 'PUT',
            body: data,
        });
    },
    
    async deleteInventoryItem(itemId) {
        return this.request(`/inventory/${itemId}`, {
            method: 'DELETE',
        });
    },

    async recordWastage(entries, opts = {}) {
        const body = { entries };
        if (opts.idempotencyKey) {
            body.idempotency_key = opts.idempotencyKey;
        }
        return this.request('/inventory/wastage', {
            method: 'POST',
            body,
        });
    },

    async getWastageRecords(inventoryItemId = null) {
        const query = inventoryItemId ? `?inventory_item_id=${encodeURIComponent(inventoryItemId)}` : '';
        return this.request(`/inventory/wastage${query}`);
    },

    async traceRawMaterial(rawMaterialId) {
        return this.request(`/inventory/trace/${rawMaterialId}`);
    },
    
    async traceInventoryBackward(inventoryItemId) {
        return this.request(`/inventory/trace-backward/${inventoryItemId}`);
    },
    
    // Execution Metadata
    async getExecutionMetadata() {
        return this.request('/execution-metadata');
    },
    
    // Metrics
    async getMetrics() {
        return this.request('/metrics');
    },

    // Single above-the-fold payload for the /core hub Overview (SQL aggregates +
    // <=20 active-execution summaries). Replaces the metrics + processes + inventory +
    // executions fan-out on first paint. See docs/core-load-performance-design.md.
    async getHubOverview() {
        return this.request('/hub/overview');
    },

    // Dashboard aggregate summary. Accepts an AbortSignal so the landing page can cancel
    // the request cleanly when the user navigates away mid-load (a bare navigation-abort
    // otherwise surfaces as a "Failed to fetch" error).
    async getDashboardSummary(windowDays = 30, options = {}) {
        const days = Number(windowDays) || 30;
        return this.request(`/dashboard/summary?window_days=${encodeURIComponent(days)}`, options);
    },

    // Reset demo DB (test environment only)
    async resetDemoDb() {
        return this.request('/reset-demo-db', {
            method: 'POST',
        });
    },

    // Evidence (execution attachments: images, PDFs)
    async uploadEvidence(formData, options = {}) {
        const signal = options.signal;
        const url = `${this.baseURL}/evidence/upload`;
        // Include CSRF token for mutating multipart uploads.
        const csrfMeta = typeof document !== 'undefined' && document.querySelector
            ? document.querySelector('meta[name="csrf-token"]')
            : null;
        const csrfTok = csrfMeta && csrfMeta.getAttribute('content');
        const headers = {};
        const traceHeaders = _getRumTraceHeaders(url, 'POST');
        Object.assign(headers, traceHeaders || {});
        if (csrfTok) {
            headers['X-CSRFToken'] = csrfTok;
        }
        const config = { method: 'POST', body: formData, headers };
        if (typeof window !== 'undefined' && window.fetch) {
            const fetchOpts = { ...config, credentials: 'same-origin' };
            if (signal) fetchOpts.signal = signal;
            const response = await fetch(url, fetchOpts);
            const raw = await response.text();
            let data;
            try {
                data = raw ? JSON.parse(raw) : {};
            } catch (e) {
                data = { error: raw || `HTTP ${response.status}` };
            }
            if (!response.ok) throw new Error((data && data.error) || `HTTP ${response.status}`);
            return data;
        }
        const reqOpts = { method: 'POST', body: formData };
        if (signal) reqOpts.signal = signal;
        return this.request('/evidence/upload', reqOpts);
    },

    async listEvidence(executionId, options = {}) {
        const signal = options.signal;
        return this.request(`/evidence/list?execution_id=${encodeURIComponent(executionId)}`, signal ? { signal } : {});
    },

    /** Remove evidence (record and file). Use from execution modal before completing the step. */
    async deleteEvidence(evidenceId) {
        return this.request(`/evidence/${encodeURIComponent(evidenceId)}`, { method: 'DELETE' });
    },

    /** Evidence upload limits (single source of truth; use for client-side size check). */
    async getEvidenceConfig(options = {}) {
        const signal = options.signal;
        return this.request('/evidence/config', signal ? { signal } : {});
    },

    /** Compliant augments executions; Core still owns evidence storage and upload. */
    async getCompliantCaptureContext(options = {}) {
        const response = await fetch('/api/compliant/capture-context', {
            credentials: 'same-origin',
            signal: options.signal,
        });
        if (response.status === 404) return { enabled: false };
        if (!response.ok) throw new Error(`Could not load compliance capture context (${response.status})`);
        return response.json();
    },

    getEvidenceDownloadUrl(evidenceId) {
        return `${this.baseURL}/evidence/${encodeURIComponent(evidenceId)}/download`;
    },

    /** Open evidence in browser (inline) without forcing download. Use for View. */
    getEvidenceViewUrl(evidenceId) {
        return `${this.baseURL}/evidence/${encodeURIComponent(evidenceId)}/download?inline=1`;
    },

    // Process step documentation (SOP) – for execution modal and step creation
    async getStepDocumentation(stepId, options = {}) {
        const signal = options.signal;
        return this.request(`/process-docs/${encodeURIComponent(stepId)}`, signal ? { signal } : {});
    },

    /** Create or update inline SOP for a step (admin). Used when defining steps. */
    async createProcessDocInline(processId, stepId, title, contentMarkdown, documentId = null) {
        const body = { process_id: processId, step_id: stepId, title, content_markdown: contentMarkdown };
        if (documentId) body.document_id = documentId;
        return this.request('/process-docs/inline', { method: 'POST', body });
    },

    /** Upload SOP file for a step. formData must include process_id, step_id, file; optional title. */
    async uploadProcessDoc(formData) {
        const url = `${this.baseURL}/process-docs/upload`;
        const csrfMeta = typeof document !== 'undefined' && document.querySelector
            ? document.querySelector('meta[name="csrf-token"]')
            : null;
        const csrfTok = csrfMeta && csrfMeta.getAttribute('content');
        const headers = {};
        const traceHeaders = _getRumTraceHeaders(url, 'POST');
        Object.assign(headers, traceHeaders || {});
        if (csrfTok) {
            headers['X-CSRFToken'] = csrfTok;
        }
        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            credentials: 'same-origin',
            headers,
        });
        let data;
        try {
            data = await response.json();
        } catch (e) {
            throw new Error(response.ok ? 'Invalid response from server.' : `HTTP ${response.status}`);
        }
        if (!response.ok) throw new Error(data.error || data.message || `HTTP ${response.status}`);
        return data;
    },

    getProcessDocDownloadUrl(docId, inline = false) {
        const q = inline ? '?inline=1' : '';
        return `${this.baseURL}/process-docs/${encodeURIComponent(docId)}/download${q}`;
    },

    getProcessDocViewUrl(docId) {
        return this.getProcessDocDownloadUrl(docId, true);
    },

    /** Delete a process step document (admin). Used in create/edit process modal. */
    async deleteProcessDoc(docId) {
        return this.request(`/process-docs/${encodeURIComponent(docId)}`, { method: 'DELETE' });
    },
};

if (typeof window !== 'undefined') {
    window.CoreAPI = CoreAPI;
}

// ---------------------------------------------------------------------------
// Custom expiry mode constants (must match backend)
// ---------------------------------------------------------------------------
if (typeof window !== 'undefined') {
    window.EXPIRY_MODES = window.EXPIRY_MODES || {
        FIXED: 'fixed_duration',
        EXECUTION: 'set_at_execution',
        NONE: 'none'
    };
    window.READY_DATE_MODES = window.READY_DATE_MODES || {
        FIXED: 'fixed_duration',
        EXECUTION: 'set_at_execution',
        NONE: 'none'
    };
}

// ---------------------------------------------------------------------------
// Custom expiry validation helpers (shared by step builder + execution modal)
// ---------------------------------------------------------------------------
if (typeof window !== 'undefined') {
    window.CustomExpiryValidation = window.CustomExpiryValidation || (function () {
        function durationToHours(value, unit) {
            if (value == null || value === '' || isNaN(Number(value)) || Number(value) < 0) return null;
            var v = Number(value);
            switch ((unit || 'days').toLowerCase()) {
                case 'hours': return v;
                case 'days': return v * 24;
                case 'weeks': return v * 24 * 7;
                case 'months': return v * 24 * 30;
                default: return v * 24;
            }
        }

        function formatDurationLabel(value, unit) {
            var v = (value == null) ? '' : String(value);
            var u = (unit || 'days');
            return (v + ' ' + u).trim();
        }

        // Core rule: warn window must be <= expiry window (both in hours).
        function validateWarnNotLongerThanExpiry(opts) {
            opts = opts || {};
            var outputName = opts.outputName || '';
            var warnValue = opts.warnValue;
            var warnUnit = opts.warnUnit || 'days';
            var expiryHours = opts.expiryHours;
            var expiryLabel = opts.expiryLabel || 'the expiry period';

            var warnHours = durationToHours(warnValue, warnUnit);
            if (warnHours == null || expiryHours == null) return { valid: true };
            if (warnHours > expiryHours) {
                var prefix = outputName ? ('For output "' + outputName + '", ') : '';
                var warnLabel = formatDurationLabel(warnValue, warnUnit);
                return {
                    valid: false,
                    message:
                        prefix +
                        'the warn-before-expiry period (' +
                        warnLabel +
                        ') cannot be longer than ' +
                        expiryLabel +
                        '. Please set the warning to the same duration or less.',
                };
            }
            return { valid: true };
        }

        // Validate fixed-duration outputs: warning must not exceed expiry. Returns { valid, message, outputName }.
        function validateFixedExpiryWarning(outputs) {
            for (var i = 0; i < (outputs || []).length; i++) {
                var out = outputs[i] || {};
                var ce = (out.extra_data || {}).custom_expiry;
                if (!ce || ce.mode !== (window.EXPIRY_MODES && window.EXPIRY_MODES.FIXED)) continue;
                var expVal = ce.duration_value;
                var expUnit = ce.duration_unit || 'days';
                var warnVal = ce.warning_value;
                var warnUnit = ce.warning_unit || 'days';
                var expHours = durationToHours(expVal, expUnit);
                if (expHours != null && expHours <= 0) continue;
                var outName = out.name || 'this output';
                var expLabel = 'the expiry period (' + formatDurationLabel(expVal, expUnit) + ')';
                var r = validateWarnNotLongerThanExpiry({
                    outputName: outName,
                    warnValue: warnVal,
                    warnUnit: warnUnit,
                    expiryHours: expHours,
                    expiryLabel: expLabel,
                });
                if (!r.valid) {
                    return { valid: false, outputName: outName, message: r.message };
                }
            }
            return { valid: true };
        }

        return {
            durationToHours: durationToHours,
            formatDurationLabel: formatDurationLabel,
            validateWarnNotLongerThanExpiry: validateWarnNotLongerThanExpiry,
            validateFixedExpiryWarning: validateFixedExpiryWarning,
        };
    })();

    // Ready date validation (days, weeks, months, years) — warn period must not exceed ready period
    window.ReadyDateValidation = window.ReadyDateValidation || (function () {
        function durationToHours(value, unit) {
            if (value == null || value === '' || isNaN(Number(value)) || Number(value) < 0) return null;
            var v = Number(value);
            switch ((unit || 'days').toLowerCase()) {
                case 'days': return v * 24;
                case 'weeks': return v * 24 * 7;
                case 'months': return v * 24 * 30;
                case 'years': return v * 24 * 365;
                default: return v * 24;
            }
        }

        function formatDurationLabel(value, unit) {
            var v = (value == null) ? '' : String(value);
            var u = (unit || 'days');
            return (v + ' ' + u).trim();
        }

        function validateWarnNotLongerThanReadyPeriod(opts) {
            opts = opts || {};
            var warnValue = opts.warnValue;
            var warnUnit = opts.warnUnit || 'days';
            var readyHours = opts.readyHours;
            var readyLabel = opts.readyLabel || 'the ready period';
            var warnHours = durationToHours(warnValue, warnUnit);
            if (warnHours == null || readyHours == null) return { valid: true };
            if (warnHours > readyHours) {
                var warnLabel = formatDurationLabel(warnValue, warnUnit);
                return {
                    valid: false,
                    message: 'The warn-before-ready period (' + warnLabel + ') cannot be longer than ' + readyLabel + '. Please set the warning to the same duration or less.',
                };
            }
            return { valid: true };
        }

        function validateFixedReadyDateWarning(outputs) {
            for (var i = 0; i < (outputs || []).length; i++) {
                var out = outputs[i] || {};
                var rd = (out.extra_data || {}).ready_date;
                if (!rd || rd.mode !== 'fixed_duration') continue;
                var readyVal = rd.duration_value;
                var readyUnit = rd.duration_unit || 'days';
                var warnVal = rd.warning_value;
                var warnUnit = rd.warning_unit || 'days';
                var readyHours = durationToHours(readyVal, readyUnit);
                if (readyHours != null && readyHours <= 0) continue;
                var outName = out.name || 'this output';
                var readyLabel = 'the ready period (' + formatDurationLabel(readyVal, readyUnit) + ')';
                var r = validateWarnNotLongerThanReadyPeriod({
                    warnValue: warnVal,
                    warnUnit: warnUnit,
                    readyHours: readyHours,
                    readyLabel: readyLabel,
                });
                if (!r.valid) {
                    return { valid: false, outputName: outName, message: r.message };
                }
            }
            return { valid: true };
        }

        return {
            durationToHours: durationToHours,
            formatDurationLabel: formatDurationLabel,
            validateWarnNotLongerThanReadyPeriod: validateWarnNotLongerThanReadyPeriod,
            validateFixedReadyDateWarning: validateFixedReadyDateWarning,
        };
    })();

    // Shared invariant: when both expiry and ready date are set, expiry cannot be before ready date
    window.ExpiryReadyDateValidation = window.ExpiryReadyDateValidation || (function () {
        function readyDurationToHours(value, unit) {
            if (value == null || value === '' || isNaN(Number(value)) || Number(value) < 0) return null;
            var v = Number(value);
            switch ((unit || 'days').toLowerCase()) {
                case 'days': return v * 24;
                case 'weeks': return v * 24 * 7;
                case 'months': return v * 24 * 30;
                case 'years': return v * 24 * 365;
                default: return v * 24;
            }
        }
        function expiryDurationToHours(value, unit) {
            if (value == null || value === '' || isNaN(Number(value)) || Number(value) < 0) return null;
            var v = Number(value);
            switch ((unit || 'days').toLowerCase()) {
                case 'hours': return v;
                case 'days': return v * 24;
                case 'weeks': return v * 24 * 7;
                case 'months': return v * 24 * 30;
                default: return v * 24;
            }
        }
        // Step modal: when both are fixed duration, require ready duration <= expiry duration
        function validateExpiryAfterReadyDuration(outputs) {
            for (var i = 0; i < (outputs || []).length; i++) {
                var out = outputs[i] || {};
                var ce = (out.extra_data || {}).custom_expiry;
                var rd = (out.extra_data || {}).ready_date;
                if (!ce || !ce.enabled || (ce.mode || '') !== 'fixed_duration') continue;
                if (!rd || !rd.enabled || (rd.mode || '') !== 'fixed_duration') continue;
                var readyVal = rd.duration_value;
                var readyUnit = rd.duration_unit || 'days';
                var expVal = ce.duration_value;
                var expUnit = ce.duration_unit || 'days';
                var readyHours = readyDurationToHours(readyVal, readyUnit);
                var expHours = expiryDurationToHours(expVal, expUnit);
                if (readyHours == null || expHours == null) continue;
                if (readyHours > expHours) {
                    var outName = out.name || 'this output';
                    return {
                        valid: false,
                        outputName: outName,
                        message: 'For output "' + outName + '", expiry must be on or after the ready date. Increase the expiry period or reduce the ready period so the product is usable for at least one day.',
                    };
                }
            }
            return { valid: true };
        }
        // Execution modal: when both are dates (ISO strings), require ready <= expiry
        function validateExpiryAfterReadyDates(outputName, readyDateIso, expiryDateIso) {
            if (!readyDateIso || !expiryDateIso) return { valid: true };
            var readyMs = window.parseISODate && window.parseISODate(readyDateIso);
            var expiryMs = window.parseISODate && window.parseISODate(expiryDateIso);
            if (readyMs == null || expiryMs == null) return { valid: true };
            if (readyMs > expiryMs) {
                return {
                    valid: false,
                    message: 'For output "' + (outputName || 'this output') + '", expiry date cannot be before the ready date. Set an expiry on or after the date when the output can be used.',
                };
            }
            return { valid: true };
        }
        return {
            validateExpiryAfterReadyDuration: validateExpiryAfterReadyDuration,
            validateExpiryAfterReadyDates: validateExpiryAfterReadyDates,
        };
    })();

    /**
     * Parse an ISO date/datetime string (backend or input). Prefer over string concat to avoid breakage if format changes.
     * @param {string} isoString - ISO 8601 or date-only (e.g. YYYY-MM-DD)
     * @returns {number|null} Timestamp in ms, or null if invalid
     */
    window.parseISODate = function(isoString) {
        if (isoString == null || typeof isoString !== 'string' || !isoString.trim()) return null;
        var s = isoString.trim();
        var t = Date.parse(s);
        if (isNaN(t)) {
            if (/^\d{4}-\d{2}-\d{2}$/.test(s)) t = Date.parse(s + 'T00:00:00.000Z');
            if (isNaN(t)) return null;
        }
        return t;
    };

    window.getExecutionOutputId = function(output) {
        if (!output) return 'out-unknown';
        if (output.id != null && String(output.id).trim() !== '') return String(output.id);
        return output.name ? 'out-' + String(output.name).replace(/\s+/g, '-') : 'out-unknown';
    };

    // Single source of truth for execution expiry UI markup (used by execution-modal.js and render modules)
    window.renderExecutionExpiryUI = function(output, escapeHtml) {
        if (!output || typeof escapeHtml !== 'function') return '';
        var outputId = window.getExecutionOutputId(output);
        var enc = function(s) { return escapeHtml(s == null ? '' : String(s)); };
        return '<div class="execute-output-expiry-input" data-output-id="' + enc(outputId) + '" style="margin-bottom: 12px; padding: 12px 16px; background: hsl(38, 92%, 95%); border: 1px solid var(--warning, #f59e0b); border-radius: var(--radius-md);">' +
            '<div style="display:flex; align-items:center; justify-content:space-between; gap: 12px; margin-bottom: 8px;">' +
            '<div style="font-weight: 700; color: #92400e; font-size: 13px;">Set expiry for this output</div>' +
            '<div style="font-size: 12px; color: #92400e;">Required for compliance</div>' +
            '</div>' +
            '<label style="display:block; font-size: 12px; color: #92400e; margin-bottom: 4px;">Expiry type</label>' +
            '<select class="execute-output-expiry-input-mode form-select" data-output-id="' + enc(outputId) + '" style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px; margin-bottom: 10px;">' +
            '<option value="duration">Duration</option>' +
            '<option value="datetime">Set a specific time and date</option>' +
            '</select>' +
            '<div class="execute-output-expiry-duration-fields" style="display:block; margin-bottom: 10px;">' +
            '<label style="display:block; font-size: 12px; color: #92400e; margin-bottom: 4px;">Duration</label>' +
            '<div style="display:flex; gap: 10px; align-items:center;">' +
            '<input type="number" min="1" class="execute-output-expiry-duration-value" data-output-id="' + enc(outputId) + '" placeholder="30" style="flex:1; width:100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;">' +
            '<select class="execute-output-expiry-duration-unit form-select" data-output-id="' + enc(outputId) + '" style="width: 150px; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;">' +
            '<option value="hours">Hours</option>' +
            '<option value="days" selected>Days</option>' +
            '<option value="weeks">Weeks</option>' +
            '<option value="months">Months</option>' +
            '</select>' +
            '</div>' +
            '</div>' +
            '<div class="execute-output-expiry-datetime-fields" style="display:none; margin-bottom: 0;">' +
            '<label style="display:block; font-size: 12px; color: #92400e; margin-bottom: 4px;">Expiry date and time</label>' +
            '<input type="datetime-local" class="execute-output-expiry-datetime" data-output-id="' + enc(outputId) + '" style="width:100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;">' +
            '<p class="execute-output-expiry-datetime-hint" style="margin: 6px 0 0 0; font-size: 12px; color: #92400e; opacity: 0.9;">Click on the calendar icon to set a date and time</p>' +
            '</div>' +
            '<div class="execute-output-expiry-warning-fields" style="display:none; margin-top: 10px;">' +
            '<label style="display:block; font-size: 12px; color: #92400e; margin-bottom: 4px;">Warn before expiry</label>' +
            '<div style="display:flex; gap: 10px; align-items:center;">' +
            '<input type="number" min="0" class="execute-output-expiry-warning-value" data-output-id="' + enc(outputId) + '" placeholder="7" value="7" style="flex:1; width:100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;">' +
            '<select class="execute-output-expiry-warning-unit form-select" data-output-id="' + enc(outputId) + '" style="width: 150px; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;">' +
            '<option value="hours">Hours</option>' +
            '<option value="days" selected>Days</option>' +
            '<option value="weeks">Weeks</option>' +
            '<option value="months">Months</option>' +
            '</select>' +
            '</div>' +
            '<div class="execute-output-expiry-warning-hint" style="margin-top: 6px; font-size: 12px; color: #92400e; opacity: 0.9;">Shown as a warning when this amount of time remains until expiry. Must be the same or less than the expiry period.</div>' +
            '<div class="execute-output-expiry-validation-error" style="display:none; margin-top: 8px; font-size: 12px; color: var(--danger, #dc2626);" role="alert" aria-live="polite"></div>' +
            '</div>' +
            '</div>';
    };

    // Single place for building custom_expiry_input from modal DOM (used by both execution modals)
    window.collectExecutionOutputExpiryPayload = function(modal, outputId) {
        if (!modal || !outputId) return null;
        var id = String(outputId).trim();
        var matchById = function(el) { return (el.dataset.outputId || '').trim() === id; };
        var modeSel = Array.from(modal.querySelectorAll('.execute-output-expiry-input-mode')).find(matchById);
        var inputMode = modeSel ? (modeSel.value || 'duration') : 'duration';
        if (inputMode === 'duration') {
            var vEl = Array.from(modal.querySelectorAll('.execute-output-expiry-duration-value')).find(matchById);
            var uEl = Array.from(modal.querySelectorAll('.execute-output-expiry-duration-unit')).find(matchById);
            var wvEl = Array.from(modal.querySelectorAll('.execute-output-expiry-warning-value')).find(matchById);
            var wuEl = Array.from(modal.querySelectorAll('.execute-output-expiry-warning-unit')).find(matchById);
            var vRaw = vEl ? (vEl.value || '').trim() : '';
            var v = vRaw !== '' ? parseInt(vRaw, 10) : null;
            var u = (uEl ? (uEl.value || 'days') : 'days').trim();
            var wvRaw = wvEl ? (wvEl.value || '').trim() : '';
            var wv = wvRaw !== '' ? parseInt(wvRaw, 10) : 7;
            var wu = (wuEl ? (wuEl.value || 'days') : 'days').trim();
            if (v && v > 0) {
                return { mode: 'duration', duration_value: v, duration_unit: u, warning_value: wv, warning_unit: wu };
            }
            return null;
        }
        if (inputMode === 'datetime') {
            var dtEl = Array.from(modal.querySelectorAll('.execute-output-expiry-datetime')).find(matchById);
            var raw = dtEl ? (dtEl.value || '').trim() : '';
            if (raw) {
                var d = new Date(raw);
                if (!isNaN(d.getTime())) {
                    var wvEl2 = Array.from(modal.querySelectorAll('.execute-output-expiry-warning-value')).find(matchById);
                    var wuEl2 = Array.from(modal.querySelectorAll('.execute-output-expiry-warning-unit')).find(matchById);
                    var wv2 = wvEl2 && (wvEl2.value || '').trim() !== '' ? parseInt((wvEl2.value || '').trim(), 10) : 7;
                    var wu2 = (wuEl2 ? (wuEl2.value || 'days') : 'days').trim();
                    return { mode: 'datetime', expiry_at: d.toISOString(), warning_value: wv2, warning_unit: wu2 };
                }
            }
            return null;
        }
        return null;
    };

    // Single place for "maybe add custom_expiry_input to outPayload" (used by js/ and shared/ execution-modal)
    window.applyExecutionOutputExpiryToPayload = function(modal, outputId, outputDef, outPayload) {
        if (!modal || !outputId || !outputDef || !outPayload) return;
        var ce = outputDef.extra_data && outputDef.extra_data.custom_expiry;
        if (!ce || !ce.enabled || ce.mode !== 'set_at_execution' || typeof window.collectExecutionOutputExpiryPayload !== 'function') return;
        var payload = window.collectExecutionOutputExpiryPayload(modal, outputId);
        if (payload) outPayload.custom_expiry_input = payload;
    };

    // Ready date at execution: single date-of-availability picker (used when step output ready_date.mode === 'set_at_execution')
    window.renderExecutionReadyDateUI = function(output, escapeHtml) {
        if (!output || typeof escapeHtml !== 'function') return '';
        var outputId = window.getExecutionOutputId(output);
        var enc = function(s) { return escapeHtml(s == null ? '' : String(s)); };
        return '<div class="execute-output-ready-date-input" data-output-id="' + enc(outputId) + '" style="margin-bottom: 12px; padding: 12px 16px; background: hsl(220, 92%, 95%); border: 1px solid var(--info, #3b82f6); border-radius: var(--radius-md);">' +
            '<div style="font-weight: 700; color: #1e40af; font-size: 13px; margin-bottom: 8px;">Set date of availability for this output</div>' +
            '<label style="display:block; font-size: 12px; color: #1e40af; margin-bottom: 4px;">Date when this output can be used</label>' +
            '<input type="date" class="execute-output-ready-date-date" data-output-id="' + enc(outputId) + '" style="width:100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;">' +
            '<p style="margin: 6px 0 0 0; font-size: 12px; color: #1e40af; opacity: 0.9;">Required — output cannot be consumed before this date.</p>' +
            '</div>';
    };

    window.collectExecutionOutputReadyDatePayload = function(modal, outputId) {
        if (!modal || !outputId) return null;
        var id = String(outputId).trim();
        var matchById = function(el) { return (el.dataset.outputId || '').trim() === id; };
        var dateEl = Array.from(modal.querySelectorAll('.execute-output-ready-date-date')).find(matchById);
        var raw = dateEl ? (dateEl.value || '').trim() : '';
        if (!raw) return null;
        var ts = window.parseISODate && window.parseISODate(raw);
        if (ts == null) return null;
        return { date: new Date(ts).toISOString() };
    };

    /**
     * Centralized renderer for ready date status (single source for copy; avoids drift).
     * @param {{ state: string, readyDate: string, outputName: string, severity: string, detail?: string, processStep?: string }} opts
     * @param {function(string): string} escapeHtml
     * @returns {string} HTML for one item
     */
    window.renderReadyDateStatus = function(opts, escapeHtml) {
        if (!opts || typeof escapeHtml !== 'function') return '';
        var state = (opts.state && opts.state.trim()) ? opts.state.trim() : 'Not ready';
        var readyDate = opts.readyDate;
        var readyFrom = readyDate
            ? (function() {
                var t = window.parseISODate && window.parseISODate(readyDate);
                return t != null ? escapeHtml(new Date(t).toLocaleDateString(undefined, { dateStyle: 'medium' })) : escapeHtml(String(readyDate));
            })()
            : '—';
        var outputName = escapeHtml(opts.outputName || '—');
        var severityColor = (opts.severity === 'amber') ? 'var(--warning, #f59e0b)' : 'var(--error, #ef4444)';
        var detail = (opts.detail && opts.detail.trim()) ? escapeHtml(opts.detail.trim()) : 'Output not yet ready.';
        var processStep = (opts.processStep && opts.processStep.trim()) ? '<p style="margin: 0 0 4px 0; color: var(--text-secondary); font-size: 12px;">' + escapeHtml(opts.processStep) + '</p>' : '';
        return '<p style="margin: 0 0 4px 0; font-weight: 600;">' + outputName + '</p>' +
            processStep +
            '<p style="margin: 4px 0 0 0; font-size: 12px;">&#x26A0;&#xFE0F; Ready from: ' + readyFrom + '</p>' +
            '<p style="margin: 2px 0 0 0; font-size: 12px;"><span style="color: ' + severityColor + ';">Status: ' + escapeHtml(state) + '</span></p>' +
            '<p style="margin: 2px 0 0 0; font-size: 12px; color: var(--text-secondary);">Detail: ' + detail + '</p>';
    };

    window.applyExecutionOutputReadyDateToPayload = function(modal, outputId, outputDef, outPayload) {
        if (!modal || !outputId || !outputDef || !outPayload) return;
        var rd = outputDef.extra_data && outputDef.extra_data.ready_date;
        if (!rd || !rd.enabled || rd.mode !== 'set_at_execution' || typeof window.collectExecutionOutputReadyDatePayload !== 'function') return;
        var payload = window.collectExecutionOutputReadyDatePayload(modal, outputId);
        if (payload) outPayload.ready_date_input = payload;
    };

    /**
     * Show the styled "product not yet ready" confirmation modal (replaces browser confirm).
     * @param {Array<{inputName: string, itemName: string, reason: string}>} notReadyUsed
     * @returns {Promise<boolean>} Resolves to true if user clicks "Use anyway", false if Cancel or backdrop.
     */
    window.showReadyDateConfirmModal = function(notReadyUsed) {
        var modal = document.getElementById('ready-date-confirm-modal');
        var bodyEl = document.getElementById('ready-date-confirm-body');
        if (!modal || !bodyEl) return Promise.resolve(false);
        function escapeHtml(text) {
            if (text == null) return '';
            var div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        var count = (notReadyUsed || []).length;
        var summaryHtml = '<p class="ready-date-confirm-summary" style="margin: 0 0 12px 0; font-weight: 600; font-size: 14px;">' + count + ' output(s) are not yet ready for use.</p>';
        var listHtml = '<ul style="margin: 0; padding-left: 20px;">' +
            (notReadyUsed || []).map(function(u) {
                return '<li style="margin-bottom: 6px;"><strong>' + escapeHtml(u.inputName) + ':</strong> ' + escapeHtml(u.itemName) + ' &mdash; <span style="color: var(--text-secondary);">' + escapeHtml(u.reason) + '</span></li>';
            }).join('') + '</ul>';
        // nosemgrep: innerhtml-string-concat -- audited: all dynamic values here go through escapeHtml()
        bodyEl.innerHTML = summaryHtml + listHtml;
        modal.style.display = 'flex';
        return new Promise(function(resolve) {
            var resolved = false;
            function done(useAnyway) {
                if (resolved) return;
                resolved = true;
                modal.style.display = 'none';
                resolve(useAnyway);
            }
            var cancelBtn = document.getElementById('ready-date-confirm-cancel');
            var useBtn = document.getElementById('ready-date-confirm-use');
            function onCancel() { done(false); }
            function onUse() { done(true); }
            function onBackdrop(ev) {
                if (ev.target === modal) onCancel();
            }
            if (cancelBtn) cancelBtn.addEventListener('click', onCancel, { once: true });
            if (useBtn) useBtn.addEventListener('click', onUse, { once: true });
            modal.addEventListener('click', onBackdrop, { once: true });
        });
    };
}
