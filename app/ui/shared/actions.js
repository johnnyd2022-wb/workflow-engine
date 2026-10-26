// GL-S03 step 2: one delegated listener in place of inline on*="" handlers, so the strict CSP
// (script-src-attr 'none', no 'unsafe-inline') can be enforced. Markup names what to do; nothing
// here evaluates a string.
//
//   data-action="fnName"                 call window.fnName() on click; only names in ACTIONS run
//   data-action-args='["a", 1, "$el"]'   JSON arguments; "$el" stands for the element itself
//   data-action-fallback-href="/"        go here when the function isn't on the page
//   data-action-stop                     the click (and mousedown) goes no further than this element
//   data-dismiss="modal-id"              hide that element and give the page its scroll back
//   data-remove-ancestor="2"             remove the element's nth ancestor (a toast's close button)
//   data-submit-action="fnName"|"none"   on a form: never submit natively; call fnName(form), or
//   data-submit-pass="event"               fnName(event) when the function wants the event
(function () {
  'use strict';

  if (window.__bizeActions) return; // one set of listeners per document, across boosted visits
  window.__bizeActions = true;

  // Every global a template or script may name. A name not listed is ignored, so injected markup
  // can't call an arbitrary page function by naming it.
  var ACTIONS = [
    'addAnotherStep', 'addGuidedInput', 'addGuidedOutput', 'addGuidedPrompt', 'addInput',
    'addInventoryItem', 'addNewStepFromEditView', 'addOutput', 'cancelDeleteInventory',
    'cancelFlows2DeleteProcess', 'cancelResumeDraft', 'clearAllGuidedInputs', 'clearAllGuidedOutputs',
    'closeModal', 'closeNotification', 'closeResetDbModal', 'confirmDeleteInventory',
    'confirmFinishProcess', 'confirmFlows2DeleteProcess', 'confirmResetDb', 'confirmResumeDraft',
    'createProcessFromGuidedFlow', 'createProcessNextStep', 'executeNextStepFromInventory',
    'finishProcess', 'goFromProcessOverviewToStepName', 'handleAccountInfoLogout', 'handleSignup',
    'loadSettings', 'openEditInventoryModal', 'openModal', 'print', 'saveSettings',
    'savePendingStepFromFlowWizard', 'showDeleteInventoryConfirmation', 'smClearTrace',
    'startExecution', 'startNewFromEditView', 'submitExecution', 'toggleInventoryItemDetails',
    'toggleSidebar', 'toggleStep', 'updateInventoryItem', 'updateProcess',
  ];
  var allowed = {};
  ACTIONS.forEach(function (name) { allowed[name] = true; });

  function args(el) {
    var raw = el.getAttribute('data-action-args');
    if (!raw) return [];
    try {
      var list = JSON.parse(raw);
      return (Array.isArray(list) ? list : [list]).map(function (v) { return v === '$el' ? el : v; });
    } catch (_) {
      return [];
    }
  }

  function call(name, list) {
    var fn = allowed[name] ? window[name] : null;
    if (typeof fn !== 'function') return false;
    fn.apply(window, list);
    return true;
  }

  // Everything a click asks for, from the innermost element outwards, up to (and including) `limit`.
  function handle(target, limit) {
    var dismiss = target.closest('[data-dismiss]');
    if (dismiss && (!limit || limit.contains(dismiss))) {
      var box = document.getElementById(dismiss.getAttribute('data-dismiss'));
      if (box) box.style.display = 'none';
      document.body.style.overflow = 'auto';
    }
    var remove = target.closest('[data-remove-ancestor]');
    if (remove && (!limit || limit.contains(remove))) {
      var node = remove;
      for (var i = Number(remove.getAttribute('data-remove-ancestor')) || 1; i > 0 && node; i--) node = node.parentElement;
      if (node) node.remove();
    }
    var el = target.closest('[data-action]');
    if (el && (!limit || limit.contains(el))) {
      if (!call(el.getAttribute('data-action'), args(el)) && el.hasAttribute('data-action-fallback-href')) {
        window.location.href = el.getAttribute('data-action-fallback-href');
      }
    }
  }

  // A "stop" element keeps its click from its ancestors' listeners, as event.stopPropagation() in
  // an inline handler did. That has to happen while capturing, before any ancestor sees it.
  document.addEventListener('click', function (event) {
    var stop = event.target.closest && event.target.closest('[data-action-stop]');
    if (!stop) return;
    handle(event.target, stop);
    event.stopPropagation();
  }, true);
  document.addEventListener('mousedown', function (event) {
    if (event.target.closest && event.target.closest('[data-action-stop]')) event.stopPropagation();
  }, true);

  // Capturing, like the stop above: an inline handler ran before its ancestors' listeners, so an
  // action does too.
  document.addEventListener('click', function (event) {
    if (!event.target.closest || event.target.closest('[data-action-stop]')) return;
    handle(event.target, null);
  }, true);

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!form.hasAttribute || !form.hasAttribute('data-submit-action')) return;
    event.preventDefault();
    var name = form.getAttribute('data-submit-action');
    if (name !== 'none') call(name, [form.getAttribute('data-submit-pass') === 'event' ? event : form]);
  });
})();
