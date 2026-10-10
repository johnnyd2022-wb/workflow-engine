/* Compliance overview. One set of server evidence and actions serves every review concept. */
(function () {
  'use strict';
  window.bize.onPage('[data-compliance-style]', function (root) {
    var canManage = root.dataset.canManage === '1';
    var error = root.querySelector('[data-compliant-error]');
    var retry = root.querySelector('[data-retry]');
    var controller = new AbortController();
    var loading = false;

    function el(tag, text, className) {
      var node = document.createElement(tag);
      if (text != null) node.textContent = text;
      if (className) node.className = className;
      return node;
    }
    function set(selector, text) { root.querySelector(selector).textContent = text; }
    function count(value) { return Math.max(0, Number(value) || 0); }
    function health(framework) {
      var summary = framework.summary_health || {};
      var coverage = framework.evidence_coverage || {};
      var ready = count(summary.evidence_ready == null ? coverage.current_controls : summary.evidence_ready);
      var total = count(summary.total_controls == null ? coverage.total_controls : summary.total_controls);
      return {
        ready: ready, total: total,
        attention: count(summary.needs_attention == null ? total - ready : summary.needs_attention),
        overdue: count(summary.overdue),
        score: count(summary.score == null ? coverage.percent : summary.score)
      };
    }
    function programme(framework) {
      var match = /^(np[123])-food-control$/.exec(framework.slug);
      return match ? match[1].toUpperCase() : null;
    }
    function destination(framework) {
      if (programme(framework)) return '/compliant/nz-alcohol/food-safety';
      if (framework.slug === 'customs-alcohol') return '/compliant/nz-alcohol/customs';
      return canManage ? '/compliant/nz-alcohol/configuration' : null;
    }
    function link(label, href, className) {
      var node = el('a', label, className || 'workspace-link');
      node.href = href;
      // Preserve the former overview’s full-navigation behavior for workspace links.
      node.setAttribute('hx-boost', 'false');
      return node;
    }
    function metric(number, label, href) {
      var node = href ? link('', href, 'compliance-metric') : el('span', '', 'compliance-metric');
      node.appendChild(el('strong', String(number)));
      node.appendChild(el('span', label));
      return node;
    }
    function renderFrameworks(frameworks) {
      var target = root.querySelector('[data-frameworks]');
      target.replaceChildren();
      root.querySelector('[data-empty]').hidden = frameworks.length > 0;
      set('[data-framework-count]', frameworks.length + ' applicable');
      frameworks.forEach(function (framework) {
        var values = health(framework);
        var name = programme(framework);
        var href = destination(framework);
        var card = el('article', null, 'compliance-framework workspace-tile');
        var disclosure = el('details', null, 'compliance-framework-detail');
        // CONCEPT ONLY: Register starts collapsed; Focus and Board keep evidence in view.
        disclosure.open = root.dataset.complianceStyle !== '3';
        var heading = el('summary', null, 'compliance-framework-heading');
        var title = el('div', null, 'compliance-framework-title');
        title.appendChild(el('h3', framework.name));
        title.appendChild(el('span', values.ready + ' / ' + values.total + ' ' + (name ? name + ' checks' : 'controls') + ' with current evidence', 'compliance-framework-coverage'));
        heading.appendChild(title);
        heading.appendChild(el('span', values.overdue ? values.overdue + ' overdue' : values.attention ? values.attention + ' to review' : 'Evidence current', 'compliance-state'));
        disclosure.appendChild(heading);
        var body = el('div', null, 'compliance-framework-body');
        var bar = el('div', null, 'compliance-coverage');
        bar.appendChild(el('span', 'Evidence coverage'));
        bar.appendChild(el('strong', values.score + '%'));
        var progress = el('progress');
        progress.max = 100;
        progress.value = Math.min(100, values.score);
        progress.setAttribute('aria-label', framework.name + ' evidence coverage');
        bar.appendChild(progress);
        body.appendChild(bar);
        var metrics = el('div', null, 'compliance-framework-metrics');
        metrics.appendChild(metric(values.ready, 'current', name ? href + '?filter=ok' : null));
        metrics.appendChild(metric(values.attention, 'to review', name ? href + '?filter=attention' : null));
        metrics.appendChild(metric(values.overdue, 'overdue', name ? href + '?filter=overdue' : null));
        body.appendChild(metrics);
        disclosure.appendChild(body);
        card.appendChild(disclosure);
        if (href) card.appendChild(link(name ? 'Open ' + name : framework.slug === 'customs-alcohol' ? 'Open Customs' : 'Review configuration', href, 'workspace-link compliance-framework-link'));
        else card.appendChild(el('p', 'Ask your admin about this framework.', 'workspace-caption'));
        target.appendChild(card);
      });
    }
    function actionHref(action) {
      if (action.kind === 'profile' || action.kind === 'product') return canManage ? '/compliant/nz-alcohol/configuration' : null;
      if (/^np[123]-food-control$/.test(action.framework_slug || '')) return '/compliant/nz-alcohol/food-safety';
      if (action.framework_slug === 'customs-alcohol') return '/compliant/nz-alcohol/customs?control=' + encodeURIComponent(action.control_id || '');
      return canManage ? '/compliant/nz-alcohol/configuration' : null;
    }
    function renderActions(actions, hasFrameworks) {
      var first = root.querySelector('[data-next-action]');
      var later = root.querySelector('[data-priority-actions]');
      first.replaceChildren();
      later.replaceChildren();
      set('[data-action-count]', actions.length ? actions.length + ' suggested' : '');
      root.querySelector('[data-more-actions]').hidden = actions.length < 2;
      set('[data-more-count]', actions.length > 1 ? '(' + (actions.length - 1) + ')' : '');
      if (!actions.length) {
        first.appendChild(el('h3', hasFrameworks ? 'No next steps suggested' : 'Start with your operation'));
        first.appendChild(el('p', hasFrameworks ? 'Review your obligations below. Evidence status and dates still need your regular review.' : 'Select the frameworks that apply to see your next steps.', 'workspace-caption'));
        return;
      }
      actions.forEach(function (action, index) {
        var href = actionHref(action);
        var item = index ? el('li') : first;
        if (index) item.appendChild(href ? link(action.title, href) : el('strong', action.title));
        else item.appendChild(el('h3', action.title));
        item.appendChild(el('p', action.description, 'workspace-caption'));
        if (action.value) item.appendChild(el('p', action.value, 'compliance-action-value'));
        if (!index && href) item.appendChild(link(action.kind === 'product' ? 'Map products' : action.kind === 'profile' ? 'Set up Compliance' : 'Review evidence', href, 'workspace-button workspace-button--primary'));
        if (!href) item.appendChild(el('p', 'Ask your organisation admin to review this setup.', 'workspace-caption'));
        if (index) later.appendChild(item);
      });
    }
    function renderDataCoverage(coverage, hasFrameworks) {
      root.querySelector('[data-data-coverage]').hidden = !hasFrameworks;
      var gaps = count(coverage.unresolved_live_data_gaps);
      set('[data-data-summary]', 'Data coverage · ' + gaps + ' live-data gap' + (gaps === 1 ? '' : 's'));
      set('[data-data-scope]', coverage.scope || 'Live Production data and recorded evidence support these checks.');
      var facts = root.querySelector('[data-data-facts]');
      facts.replaceChildren();
      [['completed_core_steps_with_captured_data', 'Production steps with captured data'],
        ['active_core_evidence_files', 'Active Production evidence files'],
        ['manual_evidence_records', 'Manual evidence records'],
        ['records_linked_to_core', 'Records linked to Production'],
        ['records_with_evidence_reference', 'Records with an evidence reference'],
        ['alcohol_product_profiles', 'Alcohol product profiles']].forEach(function (item) {
        facts.appendChild(el('dt', item[1]));
        facts.appendChild(el('dd', String(count(coverage[item[0]]))));
      });
    }
    function render(overview) {
      var frameworks = overview.frameworks || [];
      var evidence = overview.evidence_readiness || {};
      var ready = count(evidence.current_controls);
      var total = count(evidence.total_controls);
      var attention = 0, overdue = 0;
      frameworks.forEach(function (framework) { var values = health(framework); attention += values.attention; overdue += values.overdue; });
      set('[data-current-proof]', total ? ready : '—');
      set('[data-proof-total]', total ? 'of ' + total + ' checks with current evidence' : 'No applicable checks yet');
      set('[data-compliant-summary]', total ? attention ? attention + ' to review' + (overdue ? ' · ' + overdue + ' overdue' : '') : 'All checks have current evidence' : 'Configure your obligations to get started');
      set('[data-ready]', total ? ready : '—');
      set('[data-attention]', total ? attention : '—');
      set('[data-overdue]', total ? overdue : '—');
      set('[data-readiness]', 'Evidence coverage, not a legal compliance score. Overdue checks are included in those to review.');
      renderDataCoverage(overview.data_coverage || {}, frameworks.length > 0);
      renderFrameworks(frameworks);
      renderActions(overview.priority_actions || [], frameworks.length > 0);
    }
    async function load() {
      if (loading) return;
      loading = true;
      retry.disabled = true;
      retry.hidden = false;
      root.querySelector('[data-sign-in]').hidden = true;
      var status = 0;
      root.setAttribute('aria-busy', 'true');
      error.hidden = true;
      try {
        var response = await fetch('/api/compliant/overview', { signal: controller.signal });
        status = response.status;
        if (!response.ok) throw new Error('Could not load your evidence. Try again in a moment.');
        render(await response.json());
      } catch (err) {
        if (err.name === 'AbortError') return;
        set('[data-error-title]', status === 401 ? 'Sign in again to check your evidence' : status === 403 ? 'Compliance access unavailable' : 'Readiness could not load');
        set('[data-error-message]', status === 401 ? 'Your session has ended.' : status === 403 ? 'Ask your organisation admin to check your Compliance access.' : 'Check your connection and try again in a moment.');
        retry.hidden = status === 401 || status === 403;
        root.querySelector('[data-sign-in]').hidden = status !== 401;
        set('[data-compliant-summary]', 'Evidence status unavailable');
        set('[data-proof-total]', 'Try again to check your evidence');
        set('[data-framework-count]', 'Unavailable');
        set('[data-action-count]', 'Unavailable');
        root.querySelector('[data-next-action]').replaceChildren(el('p', 'Next steps are unavailable until evidence loads.', 'workspace-caption'));
        error.hidden = false;
      } finally {
        loading = false;
        retry.disabled = false;
        root.setAttribute('aria-busy', 'false');
      }
    }
    retry.addEventListener('click', load);

    // CONCEPT ONLY: remove chooser, query parameter and storage after the founder's pick.
    function setStyle(style, updateUrl) {
      if (!/^[123]$/.test(style || '')) style = '1';
      root.dataset.complianceStyle = style;
      root.querySelectorAll('[data-style-pick]').forEach(function (button) { button.setAttribute('aria-pressed', String(button.dataset.stylePick === style)); });
      root.querySelectorAll('.compliance-framework-detail').forEach(function (detail) { detail.open = style !== '3'; });
      try { sessionStorage.setItem('compliance-design-style', style); } catch (_err) { /* Preferences are optional. */ }
      if (updateUrl) {
        var url = new URL(window.location.href);
        url.searchParams.set('style', style);
        window.history.replaceState(window.history.state, '', url);
      }
    }
    var saved = '1';
    try { saved = sessionStorage.getItem('compliance-design-style') || '1'; } catch (_err) { /* Defaults work without storage. */ }
    setStyle(new URLSearchParams(window.location.search).get('style') || saved, false);
    root.querySelectorAll('[data-style-pick]').forEach(function (button) { button.addEventListener('click', function () { setStyle(button.dataset.stylePick, true); }); });
    load();
    return function () { controller.abort(); };
  });
})();
