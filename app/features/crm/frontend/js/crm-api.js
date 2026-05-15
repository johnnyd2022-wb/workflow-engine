/* CRM API Client — mirrors CoreAPI conventions */
window.CRMAPI = (function () {

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
  }

  async function request(endpoint, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const mutating = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (mutating) headers['X-CSRFToken'] = csrfToken();

    const res = await fetch(`/api/crm${endpoint}`, {
      ...options,
      method,
      headers,
      body: options.body != null ? (typeof options.body === 'string' ? options.body : JSON.stringify(options.body)) : undefined,
    });

    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`;
      try { const e = await res.json(); errMsg = e.error || e.message || errMsg; } catch (_) {}
      const err = new Error(errMsg);
      err.status = res.status;
      throw err;
    }

    return res.json();
  }

  async function orgRequest(endpoint, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const mutating = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (mutating) headers['X-CSRFToken'] = csrfToken();

    const res = await fetch(`/org${endpoint}`, {
      ...options,
      method,
      headers,
      body: options.body != null ? (typeof options.body === 'string' ? options.body : JSON.stringify(options.body)) : undefined,
    });

    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`;
      try { const e = await res.json(); errMsg = e.error || e.message || errMsg; } catch (_) {}
      const err = new Error(errMsg);
      err.status = res.status;
      throw err;
    }

    return res.json();
  }

  function navigate(path) {
    if (window.htmx && typeof window.htmx.ajax === 'function') {
      window.htmx.ajax('GET', path, {
        target: '#page-content',
        swap: 'innerHTML',
        select: '#page-content',
        pushURL: true,
      });
      return;
    }
    window.location.href = path;
  }

  function ensureBackButton(path, hidden = false) {
    const el = document.getElementById('spa-banner-back');
    if (!el) return;
    if (hidden) {
      el.classList.add('spa-banner-back--hidden');
      el.setAttribute('aria-hidden', 'true');
      el.setAttribute('tabindex', '-1');
      el.setAttribute('href', path || '/crm');
      el.onclick = null;
      return;
    }
    el.classList.remove('spa-banner-back--hidden');
    el.removeAttribute('aria-hidden');
    el.removeAttribute('tabindex');
    el.setAttribute('href', path || '/crm');
    el.setAttribute('data-spa-back-explicit', 'true');
    el.onclick = function (evt) {
      evt.preventDefault();
      navigate(path || '/crm');
    };
  }

  // ── Xero ──────────────────────────────────────────────────────
  async function getXeroStatus() { return request('/xero/status'); }
  async function triggerSync()   { return request('/xero/sync', { method: 'POST', body: {} }); }
  async function disconnectXero(){ return request('/xero/disconnect', { method: 'POST', body: {} }); }

  // ── Customers ─────────────────────────────────────────────────
  async function getCustomers(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return request(`/customers${qs ? '?' + qs : ''}`);
  }
  async function getCustomer(id) { return request(`/customers/${id}`); }
  async function getCustomerInvoices(contactId, params = {}) {
    const qs = new URLSearchParams(params).toString();
    return request(`/customers/${contactId}/invoices${qs ? '?' + qs : ''}`);
  }
  async function getOrgInvoices(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return request(`/invoices${qs ? '?' + qs : ''}`);
  }
  async function getCustomerLineItemOptions(contactId) {
    return request(`/customers/${contactId}/line-item-descriptions`);
  }
  async function getOrgLineItemOptions() {
    return request('/line-item-descriptions');
  }
  async function getCustomerLineItemPricing(contactId, params = {}) {
    const qs = new URLSearchParams(params).toString();
    return request(`/customers/${contactId}/line-item-pricing${qs ? '?' + qs : ''}`);
  }
  async function getCustomerInvoiceDefaults(contactId, params = {}) {
    const qs = new URLSearchParams(params).toString();
    return request(`/customers/${contactId}/invoice-defaults${qs ? '?' + qs : ''}`);
  }
  async function getCustomerAnalytics(contactId, params = {}) {
    const qs = new URLSearchParams(params).toString();
    return request(`/customers/${contactId}/analytics${qs ? '?' + qs : ''}`);
  }
  async function createCustomerInvoice(contactId, data) {
    return request(`/customers/${contactId}/invoices`, { method: 'POST', body: data });
  }

  // ── Notes ─────────────────────────────────────────────────────
  async function createNote(contactId, content) {
    return request(`/customers/${contactId}/notes`, { method: 'POST', body: { content } });
  }
  async function updateNote(noteId, content) {
    return request(`/notes/${noteId}`, { method: 'PUT', body: { content } });
  }
  async function deleteNote(noteId) {
    return request(`/notes/${noteId}`, { method: 'DELETE' });
  }

  // ── Tasks ─────────────────────────────────────────────────────
  async function getTasks(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return request(`/tasks${qs ? '?' + qs : ''}`);
  }
  async function createTask(data)       { return request('/tasks', { method: 'POST', body: data }); }
  async function updateTask(id, data)   { return request(`/tasks/${id}`, { method: 'PUT', body: data }); }
  async function deleteTask(id)         { return request(`/tasks/${id}`, { method: 'DELETE' }); }

  // ── Analytics ─────────────────────────────────────────────────
  async function getMonthlySales(months = 12) { return request(`/analytics/monthly-sales?months=${months}`); }
  async function getCustomerBreakdown(topN = 20) { return request(`/analytics/customer-breakdown?top_n=${topN}`); }
  async function getRankings(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return request(`/analytics/rankings${qs ? '?' + qs : ''}`);
  }
  async function getChurnRisk() { return request('/analytics/churn-risk'); }
  async function getOverview() { return request('/overview'); }
  async function getTraceabilityConfig() { return request('/traceability-config'); }
  async function updateTraceabilityConfig(data) { return request('/traceability-config', { method: 'PUT', body: data }); }
  async function getOrgUsers() { return orgRequest('/users'); }

  // ── Product Mappings ──────────────────────────────────────────
  async function getProductMappings()         { return request('/product-mappings'); }
  async function getFinalProducts()           { return request('/final-products'); }
  async function createProductMapping(data)   { return request('/product-mappings', { method: 'POST', body: data }); }
  async function updateProductMapping(id, data){ return request(`/product-mappings/${id}`, { method: 'PUT', body: data }); }
  async function deleteProductMapping(id)     { return request(`/product-mappings/${id}`, { method: 'DELETE' }); }

  return {
    request, csrfToken, navigate, ensureBackButton,
    getXeroStatus, triggerSync, disconnectXero,
    getCustomers, getCustomer, getCustomerInvoices, getOrgInvoices, getCustomerLineItemOptions, getOrgLineItemOptions, getCustomerLineItemPricing, getCustomerInvoiceDefaults, getCustomerAnalytics, createCustomerInvoice,
    createNote, updateNote, deleteNote,
    getTasks, createTask, updateTask, deleteTask,
    getMonthlySales, getCustomerBreakdown, getRankings, getChurnRisk, getOverview, getTraceabilityConfig, updateTraceabilityConfig, getOrgUsers,
    getProductMappings, getFinalProducts, createProductMapping, updateProductMapping, deleteProductMapping,
  };
})();
