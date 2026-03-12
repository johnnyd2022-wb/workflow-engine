Cursor Instructions — Fix core.html Only
File Scope

Modify only: app/core/frontend/core.html
Do not edit any JS, API, or backend files.

Goal

When a user creates a new process in core.html:

Close the “Create Process” modal immediately

Instantly render the newly entered process in the Processes grid

Persist the process asynchronously via API

Replace the optimistic process with the real one when the API returns

Never hang the page or mutate the DOM in a loop

Required Fixes
1. Remove the Source of the Hang (Mandatory)

Delete entirely from core.html:

All MutationObserver code

All calls to cloneNode()

All calls to replaceChild() used for handler rebinding

All retry loops using setTimeout(overrideCoreJsHandler, …)

These patterns must not exist anywhere in this file.

2. Attach the Create Process Form Handler Once

Add this near the bottom of the <script> block:

document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('#create-process-modal form');
  if (!form) return;

  form.onsubmit = function (e) {
    e.preventDefault();
    return window.createNewProcess(this);
  };
});


Constraints:

Do not override via DOM replacement

Do not observe DOM mutations

Do not rebind more than once

3. Replace createNewProcess With an Optimistic UI Version

In core.html, replace the existing window.createNewProcess function with:

window.createNewProcess = function (form) {
  const formData = new FormData(form);
  const name = formData.get('name')?.trim();
  const description = formData.get('description')?.trim() || '';
  const category = formData.get('category') || 'manufacturing';

  if (!name) {
    showNotification('error', 'Validation Error', 'Please enter a process name');
    return false;
  }

  const tempId = `temp-${Date.now()}`;

  const optimisticProcess = {
    id: tempId,
    name,
    description,
    category,
    created_at: new Date().toISOString(),
    __optimistic: true,
  };

  // Close modal immediately
  window.closeModal('create-process-modal');
  form.reset();

  // Render immediately
  prependProcessCardV2(optimisticProcess);

  // Persist asynchronously
  (async () => {
    try {
      const saved = await CoreAPI.createProcess({
        name,
        description,
        category,
      });

      replaceOptimisticProcessV2(tempId, saved);

      showNotification(
        'success',
        'Process Created',
        `Process "${name}" has been created successfully.`
      );
    } catch (error) {
      removeOptimisticProcessV2(tempId);

      showNotification(
        'error',
        'Failed to Create Process',
        error.message || 'Failed to create process. Please try again.'
      );
    }
  })();

  return false;
};

4. Add Optimistic Rendering Helpers (core.html Only)

Add the following helpers below renderProcessesV2 (do not modify renderProcessesV2 itself):

function prependProcessCardV2(process) {
  const grid = document.getElementById('processes-grid');
  if (!grid) return;

  const card = renderSingleProcessCardV2(process);
  card.dataset.processId = process.id;

  if (process.__optimistic) {
    card.style.opacity = '0.6';
  }

  grid.prepend(card);
}

function replaceOptimisticProcessV2(tempId, realProcess) {
  const card = document.querySelector(`[data-process-id="${tempId}"]`);
  if (!card) return;

  const newCard = renderSingleProcessCardV2(realProcess);
  newCard.dataset.processId = realProcess.id;

  card.replaceWith(newCard);
}

function removeOptimisticProcessV2(tempId) {
  const card = document.querySelector(`[data-process-id="${tempId}"]`);
  if (card) card.remove();
}

5. Extract Single-Card Rendering (Do Not Reload All Processes)

If renderProcessesV2 currently builds cards inline, extract that logic into:

function renderSingleProcessCardV2(process) {
  const div = document.createElement('div');
  div.className = 'process-card';
  div.innerHTML = `
    <div class="process-card-header-content" onclick="navigateToProcess('${process.id}')">
      <h3>${escapeHtml(process.name)}</h3>
      <p>${escapeHtml(process.description || '')}</p>
    </div>
  `;
  return div;
}


This must match the existing markup used elsewhere in core.html.

Explicit Constraints (Must Not Be Violated)

❌ No MutationObserver

❌ No DOM cloning

❌ No form replacement

❌ No full getProcesses() reload on create

❌ No retries or timeouts for handler binding

Acceptance Criteria

Create Process modal closes instantly

New process appears immediately

Backend failure removes the optimistic card

No page freeze

No repeated DOM mutations

CPU usage remains stable

One-Line Summary for Cursor

Fix core.html by removing DOM cloning and mutation observers, binding the create-process form submit handler once, closing the modal immediately, and optimistically rendering the new process card before asynchronously saving it to the backend.