/**
 * Node unit tests for the CRM customer page's Edit details form.
 * Run: node --test tests/js/crm-customer-detail.test.js
 *
 * customer-detail.js declares a global `crmCustomerDetail()` Alpine factory, loaded here into a
 * vm sandbox with a stub CRMAPI. Bug under test: the edit form is in the page from the start
 * (hidden with x-show), so Alpine evaluates `editForm.addresses[kind].line1` for both address
 * types on load. The initial form was `{}`, so every customer page threw "Cannot read properties
 * of undefined (reading 'POBOX')" -- the same fault MR !538 fixes on the customers list.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');

const SRC = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'features', 'crm', 'frontend', 'js', 'customer-detail.js'),
  'utf8'
);
const TEMPLATE = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'features', 'crm', 'frontend', 'templates', 'crm', 'customer_detail.html'),
  'utf8'
);

function makePage() {
  const context = vm.createContext({ CRMAPI: {}, document: { getElementById: () => null }, window: {}, console });
  vm.runInContext(SRC, context);
  const page = context.crmCustomerDetail('contact-1');
  page.$nextTick = (fn) => fn && fn();
  return page;
}

test('every field the hidden edit form binds to exists before Edit details is pressed', () => {
  const page = makePage();
  // Read the bindings from the template itself, so a field added there is checked too.
  const bindings = [...TEMPLATE.matchAll(/x-model="(editForm\.[^"]+)"/g)].map((m) => m[1]);
  assert.ok(bindings.length >= 10, 'expected the edit form bindings in the template');
  for (const kind of ['POBOX', 'STREET']) {
    for (const binding of bindings) {
      const expr = binding.replace('[kind]', `.${kind}`);
      const value = vm.runInNewContext(expr, { editForm: page.editForm });
      assert.equal(value, '', expr);
    }
  }
});

test('Edit details still fills the form from the customer', () => {
  const page = makePage();
  page.customer = {
    name: 'Harbour Spirits Co.',
    email_address: 'orders@harbour.example',
    addresses: [{ type: 'STREET', line1: '1 Quay St', city: 'Wellington' }],
  };
  page.startEdit();
  assert.equal(page.editForm.name, 'Harbour Spirits Co.');
  assert.equal(page.editForm.addresses.STREET.line1, '1 Quay St');
  assert.equal(page.editForm.addresses.POBOX.line1, '');
});
