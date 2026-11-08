/* Sales -> Excise (NZ Alcohol orgs): per-month products sold, litres of alcohol and an
   estimate of duty, levy and GST. The server does every calculation; this component only
   picks the month and lays the figures out. */
function crmExcise() {
  return {
    loading: true,
    loadingMonth: false,
    error: null,
    months: [],
    sources: [],
    ratesSource: null,
    // Whether the month shown is past the built-in rates' review date (its own check, not today's).
    get ratesStale() {
      const source = (this.report && this.report.rates_source) || this.ratesSource;
      return !!(source && source.guide && source.guide.out_of_date);
    },
    selected: null,
    report: null,

    async init() {
      try {
        const data = await CRMAPI.request('/excise/months');
        this.months = data.months || [];
        this.sources = data.sources || [];
        this.ratesSource = data.rates_source || null;
        const wanted = new URLSearchParams(window.location.search).get('month');
        const lastFinished = this.months.find((m) => m.complete);
        const pick = this.months.find((m) => m.month === wanted) || lastFinished || this.months[0];
        if (pick) await this.select(pick.month, false);
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    async select(month, push = true) {
      this.selected = month;
      this.loadingMonth = true;
      this.error = null;
      if (push) {
        const url = new URL(window.location.href);
        url.searchParams.set('month', month);
        window.history.replaceState({}, '', url);
      }
      try {
        const data = await CRMAPI.request(`/excise?month=${encodeURIComponent(month)}`);
        if (this.selected === month) this.report = data.report;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loadingMonth = false;
      }
      this.$nextTick(() => {
        const chip = this.$root.querySelector(`[data-month="${month}"]`);
        if (chip && chip.scrollIntoView) chip.scrollIntoView({ block: 'nearest', inline: 'center' });
      });
    },

    shortMonth(m) {
      const [y, mo] = m.month.split('-').map(Number);
      return new Date(y, mo - 1, 1).toLocaleDateString('en-NZ', { month: 'short', year: 'numeric' });
    },

    num(v, dp = 2) {
      if (v == null || v === '') return '—';
      return Number(v).toLocaleString('en-NZ', { minimumFractionDigits: 0, maximumFractionDigits: dp });
    },

    money(v) {
      if (v == null || v === '') return '—';
      return '$' + Number(v).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },

    units(row) {
      return `${this.num(row.units, 4)} ${row.unit}`;
    },

    rateNote(row) {
      if (!row.tariff_item) return 'No Customs product type yet';
      if (!row.rate) return `${row.tariff_item} · no rate for this month`;
      const basis = row.basis === 'per_litre' ? 'per litre' : 'per LAL';
      let note = `${row.tariff_item} · $${row.rate} ${basis}`;
      if (row.levy_cents_per_litre) note += ` · levy class ${row.levy_class} ${row.levy_cents_per_litre}¢ per litre`;
      return note;
    },

    fixLink(p) {
      return p.fix === 'customs' ? '/compliant/nz-alcohol/customs' : '/crm/matching';
    },
  };
}
