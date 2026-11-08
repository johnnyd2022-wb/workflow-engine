// Customs → Settings: each product's Customs setup, the rates in force, how often to lodge and
// how often to count. Every change is validated by the server; this page collects it.
(function () {
  'use strict';

  function init() {
    var page = document.querySelector('[data-customs-settings-root]');
    if (!page || page.dataset.bound === '1' || !window.CustomsUI) return;
    page.dataset.bound = '1';
    var U = window.CustomsUI;
    var el = U.el, api = U.api, money = U.money, fmtDate = U.fmtDate;
    var fail = U.failer(page);
    var categories = null;
    var source = null;
    var guide = null;

    function categorySelect(id, name, value) {
      var sel = el('select', { name: 'excise_category', id: id + '-type', 'aria-label': 'Product type for ' + name });
      sel.append(el('option', { value: '', text: 'Choose a product type…' }));
      var groups = {};
      (categories || []).forEach(function (c) {
        if (!groups[c.group]) { groups[c.group] = el('optgroup', { label: c.group }); sel.append(groups[c.group]); }
        groups[c.group].append(el('option', { value: c.key, text: c.label }));
      });
      sel.value = value || '';
      return sel;
    }
    function missing(p) {
      var out = [];
      if (!p.excise_category && !p.tariff_item) out.push('product type');
      if (!p.pack_volume_ml) out.push('pack size');
      return out;
    }
    function field(label, input, suffix) {
      return el('label', { className: 'customs-field' }, [el('span', { className: 'customs-field__label', text: label }), suffix ? el('span', { className: 'customs-field__with' }, [input, el('span', { className: 'customs-field__suffix', text: suffix })]) : input]);
    }

    async function loadProducts() {
      if (categories === null) {
        var cat = await api('GET', '/api/compliant/nz-alcohol/excise/categories');
        categories = cat.categories; source = cat.source; guide = cat.guide;
        renderRates();
      }
      var data = await api('GET', '/api/compliant/nz-alcohol/excise/products');
      var wrap = page.querySelector('[data-excise-products]'); wrap.replaceChildren();
      var summary = page.querySelector('[data-products-summary]');
      var products = data.products || [];
      if (!products.length) {
        wrap.append(el('p', { className: 'customs-empty', text: 'No products yet. Each workflow\'s final output appears here once the workflow exists.' }));
        renderRates(products);
        return;
      }
      // Unfinished first: they are why an entry can't be worked out.
      products.sort(function (a, b) { return (missing(b).length > 0) - (missing(a).length > 0) || a.name.localeCompare(b.name); });
      var todo = products.filter(function (p) { return missing(p).length; }).length;
      if (summary) summary.textContent = todo ? U.plural(todo, 'product') + ' still need setting up before their removals can go on an entry.' : (products.length === 1 ? 'Your product is set up for Customs.' : 'All ' + products.length + ' products are set up for Customs.');
      products.forEach(function (p) {
        var id = 'product-' + U.slug(p.name);
        var gaps = missing(p);
        var f = el('form', { className: 'customs-product' + (gaps.length ? ' customs-product--todo' : ''), id: id });
        var head = el('div', { className: 'customs-product__head' }, [
          el('strong', { className: 'customs-product__name', text: p.name }),
          el('span', { className: 'customs-chip customs-chip--' + (gaps.length ? 'open' : 'complete'), text: gaps.length ? 'Needs ' + gaps.join(' and ') : 'Ready' }),
        ]);
        if (p.workflow) head.append(el('span', { className: 'customs-product__from', text: 'From ' + p.workflow }));
        var type = categorySelect(id, p.name, p.excise_category);
        var vol = el('input', { name: 'pack_volume_ml', id: id + '-vol', type: 'number', min: '1', step: '1', placeholder: '700', 'aria-label': 'Pack size in mL for ' + p.name });
        var abv = el('input', { name: 'abv_fallback', id: id + '-abv', type: 'number', min: '0', max: '100', step: '0.1', placeholder: '—', 'aria-label': 'Fallback ABV for ' + p.name });
        var tar = el('input', { name: 'tariff_item', id: id + '-tariff', placeholder: 'Optional', maxlength: '100', 'aria-label': 'Tariff item override for ' + p.name });
        vol.value = p.pack_volume_ml || ''; tar.value = p.tariff_item || ''; abv.value = p.abv_fallback || '';
        var save = el('button', { type: 'submit', className: 'workspace-button', text: 'Save' });
        var fields = el('div', { className: 'customs-product__fields' }, [
          field('Product type', type), field('Pack size', vol, 'mL'), field('ABV fallback', abv, '%'), field('Tariff item override', tar),
        ]);
        f.append(head, fields, el('div', { className: 'customs-product__actions' }, [save]));
        f.addEventListener('submit', async function (e) {
          e.preventDefault(); fail(''); save.disabled = true;
          try {
            await api('PUT', '/api/compliant/nz-alcohol/excise/products', { name: p.name, excise_category: type.value, pack_volume_ml: vol.value, tariff_item: tar.value, abv_fallback: abv.value });
            await loadProducts();
            var again = document.getElementById(id); if (again) again.classList.add('customs-product--saved');
          } catch (err) { fail(err.message); save.disabled = false; }
        });
        wrap.append(f);
      });
      renderRates(products);
      if (window.location.hash) {
        var target = document.getElementById(window.location.hash.slice(1));
        if (target) { target.classList.add('customs-product--focus'); target.scrollIntoView({ block: 'center' }); }
      }
    }

    // The rates in force for the product types this org uses, from the built-in table.
    function renderRates(products) {
      var wrap = page.querySelector('[data-builtin-rates]');
      if (!wrap || !categories) return;
      wrap.replaceChildren();
      if (source) {
        var src = page.querySelector('[data-rates-source]');
        src.replaceChildren(document.createTextNode('From '), el('a', { href: source.url, target: '_blank', rel: 'noopener', text: source.title }), document.createTextNode(', checked ' + fmtDate(source.checked) + '. Updated every 1 July.'));
        var stale = page.querySelector('[data-rates-stale]');
        if (stale) stale.remove();
        if (guide && guide.out_of_date) {
          src.after(el('p', { className: 'customs-attention', role: 'note', 'data-rates-stale': '', text: 'These rates are out of date: Customs set new rates on ' + fmtDate(guide.next_review) + ' and they aren\'t built in yet. Until they are, add each new rate below from Customs\' table.' }));
        }
      }
      var used = {};
      (products || []).forEach(function (p) { if (p.excise_category) used[p.excise_category] = (used[p.excise_category] || []).concat(p.name); });
      var keys = Object.keys(used);
      if (!keys.length) { wrap.append(el('p', { className: 'excise-hint', text: 'Choose a product type for a product to see the rates it pays.' })); return; }
      var table = el('table', { className: 'customs-rates-table' });
      var hr = el('tr');
      ['Product type', 'Strength', 'Excise item', 'Rate today'].forEach(function (h) { hr.append(el('th', { scope: 'col', text: h })); });
      table.append(el('thead', {}, [hr]));
      var body = el('tbody');
      keys.forEach(function (key) {
        var c = categories.find(function (x) { return x.key === key; });
        if (!c) return;
        c.bands.forEach(function (b, i) {
          var row = el('tr');
          var strength = b.abv_up_to ? 'Over ' + Number(b.abv_above) + '% to ' + Number(b.abv_up_to) + '%' : 'Over ' + Number(b.abv_above) + '%';
          var name = el('td', { 'data-label': 'Product type' });
          if (i === 0) name.append(el('strong', { text: c.label }), el('span', { className: 'customs-rates-table__used', text: used[key].join(', ') }));
          row.append(name, el('td', { 'data-label': 'Strength', text: strength }), el('td', { className: 'mono', 'data-label': 'Excise item', text: b.item }), el('td', { className: 'num', 'data-label': 'Rate today', text: b.rate ? '$' + Number(b.rate).toLocaleString('en-NZ', { maximumFractionDigits: 4 }) + (b.basis === 'per_litre' ? ' per litre' : ' per LAL') : '—' }));
          body.append(row);
        });
      });
      table.append(body);
      wrap.append(el('div', { className: 'customs-table-wrap' }, [table]));
    }

    async function loadOverrides() {
      var data = await api('GET', '/api/compliant/nz-alcohol/excise/rates');
      var wrap = page.querySelector('[data-excise-rates]'); wrap.replaceChildren();
      if (!data.rates.length) { wrap.append(el('p', { className: 'excise-hint', text: 'No overrides: every product pays the built-in rate for its type.' })); return; }
      var ul = el('ul', { className: 'customs-plain-list' });
      data.rates.forEach(function (r) { ul.append(el('li', { text: r.tariff_item + ': ' + money(r.rate_per_lal) + ' per LAL from ' + fmtDate(r.effective_from) })); });
      wrap.append(ul);
    }

    async function loadSettings() {
      var periods = await api('GET', '/api/compliant/nz-alcohol/excise/periods');
      var s = periods.settings || {};
      document.getElementById('excise-frequency').value = s.frequency || 'monthly';
      document.getElementById('excise-tracking-from').value = s.tracking_from || '';
      var pos = await api('GET', '/api/compliant/nz-alcohol/excise/position');
      var y = pos.year || {};
      var line = 'Duty over the last 12 months: ' + U.wholeMoney(y.duty) + '. ';
      if (y.twelve_monthly_allowed) line += 'Under ' + U.wholeMoney(y.twelve_monthly_limit) + ', so Customs can let you lodge yearly or six-monthly.';
      else if (y.six_monthly_allowed) line += 'Under ' + U.wholeMoney(y.six_monthly_limit) + ', so Customs can let you lodge six-monthly.';
      else line += 'Over ' + U.wholeMoney(y.six_monthly_limit) + ': Customs needs monthly entries.';
      if (y.monthly_until && y.monthly_until > U.todayIso()) line += ' New licensees lodge monthly for their first six months (until ' + fmtDate(y.monthly_until) + ').';
      page.querySelector('[data-lodging-eligibility]').textContent = line;
      var st = pos.stocktake || {};
      document.getElementById('customs-stocktake-frequency').value = st.frequency || 'annual';
      document.getElementById('customs-stocktake-tolerance').value = st.bulk_tolerance_percent || '0.5';
      page.querySelector('[data-stocktake-next]').textContent = st.next_due
        ? (st.overdue ? 'The stocktake was due ' + fmtDate(st.next_due) + '.' : 'Next stocktake due ' + fmtDate(st.next_due) + '.') + (st.last_completed_on ? ' Last counted ' + fmtDate(st.last_completed_on) + '.' : '')
        : 'No stocktake yet: the first one sets the schedule.';
    }

    page.querySelector('[data-excise-settings]').addEventListener('submit', async function (e) {
      e.preventDefault(); fail('');
      try { await api('PUT', '/api/compliant/nz-alcohol/excise/settings', { frequency: document.getElementById('excise-frequency').value, tracking_from: document.getElementById('excise-tracking-from').value || null }); await loadSettings(); }
      catch (err) { fail(err.message); }
    });
    page.querySelector('[data-stocktake-settings]').addEventListener('submit', async function (e) {
      e.preventDefault(); fail('');
      try { await api('PUT', '/api/core/stocktake-settings', { frequency: document.getElementById('customs-stocktake-frequency').value, bulk_tolerance_percent: document.getElementById('customs-stocktake-tolerance').value || '0.5' }); await loadSettings(); }
      catch (err) { fail(err.message); }
    });
    page.querySelector('[data-excise-rate-form]').addEventListener('submit', async function (e) {
      e.preventDefault(); fail(''); var f = e.currentTarget;
      try { await api('POST', '/api/compliant/nz-alcohol/excise/rates', { tariff_item: f.tariff_item.value, rate_per_lal: f.rate_per_lal.value, effective_from: f.effective_from.value }); f.reset(); await loadOverrides(); }
      catch (err) { fail(err.message); }
    });

    Promise.all([loadProducts(), loadOverrides(), loadSettings()])
      .catch(function (err) { fail(err.message); })
      .finally(function () { page.setAttribute('aria-busy', 'false'); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  document.addEventListener('htmx:afterSwap', init);
})();
