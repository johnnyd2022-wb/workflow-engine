/* Sales-to-batch matching (plan 1.1): hybrid review list and manual assignment.
   The server enforces the rules (quantities must add up, whole bottles, batch must be the
   mapped product); this component only presents them. */
function crmMatching() {
  return {
    loading: true,
    error: null,
    notice: null,
    mode: 'fifo',
    pending: [],
    toAssign: [],
    picker: null, // { line, batches: [{...candidate, pick}], error }

    async init() {
      CRMAPI.ensureBackButton && CRMAPI.ensureBackButton('/crm');
      await this.load();
    },

    async load() {
      this.loading = true;
      this.error = null;
      try {
        const data = await CRMAPI.request('/matching');
        this.mode = data.mode;
        this.pending = data.pending_review || [];
        this.toAssign = data.to_assign || [];
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    modeLabel() {
      return { fifo: 'FIFO (automatic)', hybrid: 'Hybrid (automatic, with review)', manual: 'Manual (you pick each batch)' }[this.mode] || this.mode;
    },

    fmtDate(iso) {
      if (!iso) return '—';
      const d = new Date(iso);
      return isNaN(d) ? iso : d.toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', year: 'numeric' });
    },

    async confirm(line) {
      try {
        await CRMAPI.request('/matching/confirm', { method: 'POST', body: { invoice_id: line.invoice_id, line_key: line.line_key } });
        this.notice = `Confirmed ${line.invoice_number || 'sale'}.`;
        await this.load();
      } catch (e) { this.error = e.message; }
    },

    async openPicker(line) {
      this.error = null;
      try {
        const data = await CRMAPI.request('/matching/candidates?product=' + encodeURIComponent(line.product_name));
        const needed = Number(line.quantity || (line.batches || []).reduce((s, b) => s + Number(b.quantity), 0));
        let left = needed;
        const batches = (data.batches || []).map(b => {
          const take = Math.max(0, Math.min(Number(b.available), left));
          left -= take;
          return { ...b, pick: take || '' };
        });
        this.picker = { line, needed, batches, error: null };
      } catch (e) { this.error = e.message; }
    },

    pickedTotal() {
      return (this.picker?.batches || []).reduce((s, b) => s + (Number(b.pick) || 0), 0);
    },

    async savePicker() {
      const picks = this.picker.batches.filter(b => Number(b.pick) > 0)
        .map(b => ({ inventory_item_id: b.inventory_item_id, quantity: String(b.pick) }));
      try {
        const res = await CRMAPI.request('/matching/assign', {
          method: 'POST', body: { invoice_id: this.picker.line.invoice_id, line_key: this.picker.line.line_key, picks },
        });
        this.notice = `Saved ${this.picker.line.invoice_number || 'sale'}${res.presold ? ' (pre-sold: filled from a batch made after the invoice)' : ''}.`;
        this.picker = null;
        await this.load();
      } catch (e) { this.picker.error = e.message; }
    },

    async runNow() {
      try {
        const res = await CRMAPI.request('/matching/run', { method: 'POST' });
        const s = res.summary || {};
        this.notice = `Matching re-run: ${s.allocated || 0} matched, ${s.awaiting_assignment || 0} waiting for a batch, ${s.auto_confirmed || 0} confirmed after review.`;
        await this.load();
      } catch (e) { this.error = e.message; }
    },
  };
}
