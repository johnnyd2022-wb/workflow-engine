/* Step timing (GL-P07 B1): how long a step takes, and how long it then waits, stored in minutes
   and entered in the unit people think in. Shared by the step editor and the workflow page. */
(function () {
  'use strict';
  var UNITS = [['minutes', 1], ['hours', 60], ['days', 1440], ['weeks', 10080]];
  var LIMIT = 525600; // a year, the API's limit
  var SHORT = { minutes: 'min', hours: 'h', days: 'd', weeks: 'wk' };

  function factor(unit) {
    for (var i = 0; i < UNITS.length; i++) if (UNITS[i][0] === unit) return UNITS[i][1];
    return 1;
  }
  // The largest unit that divides evenly, so 2,880 minutes reads as 2 days.
  function toParts(minutes) {
    if (minutes == null || minutes === '') return { value: '', unit: 'hours' };
    var m = Number(minutes);
    if (m === 0) return { value: '0', unit: 'hours' };
    for (var i = UNITS.length - 1; i >= 0; i--) {
      if (m % UNITS[i][1] === 0) return { value: String(m / UNITS[i][1]), unit: UNITS[i][0] };
    }
    return { value: String(m), unit: 'minutes' };
  }
  // null for blank; NaN for anything that isn't a time from 0 up to a year.
  function toMinutes(value, unit) {
    if (value == null || String(value).trim() === '') return null;
    var n = Number(value);
    if (!isFinite(n) || n < 0) return NaN;
    var m = Math.round(n * factor(unit));
    return m > LIMIT ? NaN : m;
  }
  function words(minutes, short) {
    if (minutes == null) return '';
    if (minutes === 0) return short ? '0' : 'no time';
    var parts = [];
    var rest = minutes;
    [['week', 10080], ['day', 1440], ['hour', 60], ['minute', 1]].forEach(function (u) {
      var n = Math.floor(rest / u[1]);
      if (n && parts.length < 2) {
        parts.push(short ? n + ' ' + SHORT[u[0] + 's'] : n + ' ' + u[0] + (n === 1 ? '' : 's'));
        rest -= n * u[1];
      }
    });
    return parts.join(' ');
  }
  // "Takes 3 hours, then waits 2 days", or what's known of it.
  function summary(duration, wait) {
    if (duration == null && wait == null) return '';
    var text = duration == null ? 'Time not set' : 'Takes ' + words(duration);
    if (wait) text += ', then waits ' + words(wait);
    return text;
  }

  function fields(root) {
    return {
      duration: root.querySelector('[data-timing-value="duration"]'),
      durationUnit: root.querySelector('[data-timing-unit="duration"]'),
      wait: root.querySelector('[data-timing-value="wait"]'),
      waitUnit: root.querySelector('[data-timing-unit="wait"]')
    };
  }
  function read(root) {
    var f = fields(root);
    if (!f.duration) return { duration_minutes: null, wait_minutes: null };
    return {
      duration_minutes: toMinutes(f.duration.value, f.durationUnit.value),
      wait_minutes: toMinutes(f.wait.value, f.waitUnit.value)
    };
  }
  function fill(root, duration, wait) {
    var f = fields(root);
    if (!f.duration) return;
    var d = toParts(duration), w = toParts(wait);
    f.duration.value = d.value; f.durationUnit.value = d.unit;
    f.wait.value = w.value; f.waitUnit.value = w.unit;
    render(root);
  }
  // The running total and, for the timeline, the two bars in proportion.
  function render(root) {
    var t = read(root);
    var total = root.querySelector('[data-timing-total]');
    var bad = isNaN(t.duration_minutes) || isNaN(t.wait_minutes);
    var d = bad ? 0 : t.duration_minutes || 0, w = bad ? 0 : t.wait_minutes || 0;
    if (total) {
      total.classList.toggle('is-invalid', bad);
      total.textContent = bad
        ? 'Enter a time from 0 up to a year.'
        : t.duration_minutes == null && t.wait_minutes == null
          ? 'Optional. The planner uses it to work out when a batch is ready.'
          : 'The next step can start ' + (d + w ? words(d + w) + ' after this one starts.' : 'straight away.');
    }
    var work = root.querySelector('[data-timing-bar="duration"]'), rest = root.querySelector('[data-timing-bar="wait"]');
    if (work && rest) {
      var sum = d + w;
      // Square roots keep a 2-hour step visible beside a 3-week wait.
      var a = sum ? Math.sqrt(d) : 1, b = sum ? Math.sqrt(w) : 1;
      work.style.flexGrow = String(a || 0); rest.style.flexGrow = String(b || 0);
      work.hidden = sum > 0 && !d; rest.hidden = sum > 0 && !w;
      work.querySelector('span').textContent = t.duration_minutes == null ? 'Work' : 'Work · ' + words(d, true);
      rest.querySelector('span').textContent = t.wait_minutes == null ? 'Wait' : 'Wait · ' + words(w, true);
    }
  }

  /* CONCEPT ONLY: three layouts to choose from; the switch goes when one is picked. */
  var STYLE_KEY = 'step-timing-style';
  function applyStyle(root, style) {
    root.dataset.stepTimingStyle = style;
    root.querySelectorAll('[data-timing-style-pick]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.timingStylePick === style));
    });
  }
  function bind(root) {
    if (!root || root.dataset.stepTimingBound) return;
    root.dataset.stepTimingBound = '1';
    var fromUrl = new URLSearchParams(window.location.search).get('timing_style');
    var saved = null;
    try { saved = window.localStorage.getItem(STYLE_KEY); } catch (e) { saved = null; }
    applyStyle(root, ['1', '2', '3'].indexOf(fromUrl) >= 0 ? fromUrl : ['1', '2', '3'].indexOf(saved) >= 0 ? saved : '1');
    root.querySelectorAll('[data-timing-style-pick]').forEach(function (b) {
      b.addEventListener('click', function () {
        applyStyle(root, b.dataset.timingStylePick);
        try { window.localStorage.setItem(STYLE_KEY, b.dataset.timingStylePick); } catch (e) { /* per-viewer only */ }
      });
    });
    root.addEventListener('input', function () { render(root); });
    root.addEventListener('change', function () { render(root); });
    render(root);
  }

  window.StepTiming = Object.freeze({ toParts: toParts, toMinutes: toMinutes, words: words, summary: summary, read: read, fill: fill, bind: bind });
  document.querySelectorAll('[data-step-timing]').forEach(bind);
})();
