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
  async function getChurnRisk() { return request('/analytics/churn-risk'); }

  // ── Product Mappings ──────────────────────────────────────────
  async function getProductMappings()         { return request('/product-mappings'); }
  async function createProductMapping(data)   { return request('/product-mappings', { method: 'POST', body: data }); }
  async function updateProductMapping(id, data){ return request(`/product-mappings/${id}`, { method: 'PUT', body: data }); }
  async function deleteProductMapping(id)     { return request(`/product-mappings/${id}`, { method: 'DELETE' }); }

  return {
    request, csrfToken,
    getXeroStatus, triggerSync, disconnectXero,
    getCustomers, getCustomer, getCustomerInvoices,
    createNote, updateNote, deleteNote,
    getTasks, createTask, updateTask, deleteTask,
    getMonthlySales, getCustomerBreakdown, getChurnRisk,
    getProductMappings, createProductMapping, updateProductMapping, deleteProductMapping,
  };
})();
