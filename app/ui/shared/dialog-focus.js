/**
 * Keyboard behaviour for every modal in the app (GL-U01).
 *
 * The app's modals are built several ways: native <dialog>, Alpine overlays shown with x-show,
 * and older overlays shown by setting style.display. `role="dialog"` and `aria-modal="true"` do
 * nothing on their own, so whichever modal is on top gets the behaviour a modal needs:
 *
 *  - focus moves into it when it opens (its [autofocus], else its first field or button);
 *  - Tab and Shift+Tab stay inside it;
 *  - everything behind it is inert (no clicks, no focus, hidden from screen readers);
 *  - Escape closes it through its own Close or Cancel control, if its own code didn't already;
 *  - when it closes, focus goes back to the control that opened it.
 *
 * Loaded once from base_spa.html; it watches the whole document, so pages need no wiring.
 */
(function () {
  'use strict';
  if (window.__bizeDialogFocus) return;
  window.__bizeDialogFocus = true;

  var MODAL = [
    'dialog[open]',
    '[aria-modal="true"]',
    '.modal-overlay',
    '.ss-overlay',
    '.pt-modal-overlay',
    '.crm-task-sheet-overlay',
    '.crm-lane-sheet-overlay',
    '.core2-inv-sheet-overlay',
    '.core2-health-sheet-overlay',
    '.core2-active-detail-overlay'
  ].join(',');
  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';
  var CLOSE = '[data-dialog-close], [aria-label^="Close"], [aria-label^="close"], .ss-dialog__close, .pp-close, .modal-close';

  var open = [];             // modals currently shown, outermost only, oldest first
  var openers = new Map();   // modal -> the element that had focus when it opened
  var inerted = [];          // elements this script made inert, to undo

  function shown(el) {
    if (!el || !el.isConnected || el.hidden) return false;
    if (el.closest('[hidden]')) return false;
    var style = window.getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
  }

  // Shown is not enough to be a modal: some overlays hide with opacity and pointer-events, and the
  // execute-step modal is also embedded in a page (position: static), where it must not trap focus.
  function isOpenModal(el) {
    if (!shown(el)) return false;
    if (el.tagName === 'DIALOG') {
      try { return el.matches(':modal'); } catch (e) { return false; }
    }
    for (var node = el; node && node !== document.body; node = node.parentElement) {
      var style = window.getComputedStyle(node);
      if (style.opacity === '0' || style.pointerEvents === 'none') return false;
      if (style.position === 'fixed') return true;
    }
    return false;
  }

  function outermost(list) {
    return list.filter(function (el) { return !list.some(function (other) { return other !== el && other.contains(el); }); });
  }

  function currentModals() {
    return outermost(Array.prototype.slice.call(document.querySelectorAll(MODAL)).filter(isOpenModal));
  }

  function focusables(el) {
    return Array.prototype.slice.call(el.querySelectorAll(FOCUSABLE)).filter(function (n) {
      return shown(n) && !n.closest('[inert]');
    });
  }

  function focusInto(modal) {
    if (!shown(modal) || modal.contains(document.activeElement)) return;
    var list = focusables(modal);
    var target = modal.querySelector('[autofocus]') ||
      list.find(function (n) { return !n.matches(CLOSE); }) || list[0];
    if (target) {
      target.focus({ preventScroll: true });
    } else {
      if (!modal.hasAttribute('tabindex')) modal.setAttribute('tabindex', '-1');
      modal.focus({ preventScroll: true });
    }
  }

  // Everything that isn't the top modal or one of its ancestors becomes inert.
  function setBackground(top) {
    inerted.forEach(function (el) { el.inert = false; });
    inerted = [];
    if (!top || top.tagName === 'DIALOG') return; // showModal() already does this for <dialog>
    var node = top;
    while (node && node !== document.body) {
      var parent = node.parentElement;
      if (!parent) break;
      Array.prototype.forEach.call(parent.children, function (sibling) {
        if (sibling === node || sibling.inert || /^(SCRIPT|STYLE|LINK|TEMPLATE)$/.test(sibling.tagName)) return;
        sibling.inert = true;
        inerted.push(sibling);
      });
      node = parent;
    }
  }

  function sync() {
    scheduled = false;
    var now = currentModals();
    now.forEach(function (modal) {
      if (open.indexOf(modal) !== -1) return;
      openers.set(modal, document.activeElement);
      window.requestAnimationFrame(function () { focusInto(modal); });
    });
    var closed = open.filter(function (modal) { return now.indexOf(modal) === -1; });
    open = now;
    // Lift the old inert first: focus() on an inert opener is silently ignored.
    setBackground(open[open.length - 1]);
    closed.forEach(function (modal) {
      var opener = openers.get(modal);
      openers.delete(modal);
      var active = document.activeElement;
      var focusLost = !active || active === document.body || !active.isConnected || modal.contains(active);
      if (focusLost && opener && opener.isConnected && shown(opener)) opener.focus({ preventScroll: true });
    });
  }

  var scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(sync);
  }

  new MutationObserver(schedule).observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['style', 'hidden', 'class', 'open', 'aria-hidden']
  });
  document.addEventListener('htmx:afterSettle', schedule);
  schedule(); // a modal already open when the script loads

  document.addEventListener('keydown', function (event) {
    var top = open[open.length - 1];
    if (!top || !shown(top)) return;
    if (event.key === 'Tab') {
      var list = focusables(top);
      if (!list.length) { event.preventDefault(); return; }
      var first = list[0];
      var last = list[list.length - 1];
      if (!top.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      return;
    }
    if (event.key !== 'Escape' || top.tagName === 'DIALOG') return; // <dialog> closes itself
    // Let the modal's own Escape handler run first; only step in if it is still open.
    window.setTimeout(function () {
      if (!shown(top)) return;
      var close = Array.prototype.slice.call(top.querySelectorAll(CLOSE)).find(shown) ||
        Array.prototype.slice.call(top.querySelectorAll('button')).find(function (b) {
          return shown(b) && /^\s*(cancel|close|×|✕)\s*$/i.test(b.textContent);
        });
      if (close) close.click();
    }, 0);
  });
})();
