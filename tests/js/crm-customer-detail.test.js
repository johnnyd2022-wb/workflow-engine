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

test('Invoices tab fetches paginated history instead of stopping at five recent invoices', async () => {
  const calls = [];
  const invoices = Array.from({ length: 25 }, (_, i) => ({ id: `invoice-${i + 1}` }));
  const context = vm.createContext({ CRMAPI: {
    getCustomerInvoices: async (_id, params) => {
      calls.push(params);
      return { invoices: params.page === 1 ? invoices : [{ id: 'invoice-26' }], page: params.page, total: 26 };
    },
  }, document: { getElementById: () => null }, window: {}, console });
  vm.runInContext(SRC, context);
  const detail = context.crmCustomerDetail('contact-1');
  detail.$nextTick = (fn) => fn && fn();
  detail.recentInvoices = [{ id: 'recent-1', date: '2025-01-01', status: 'PAID' }];
  detail.setTab('invoices');
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(detail.invoiceTotal, 26);
  assert.equal(detail.invoices.length, 25);
  assert.equal(detail.lastOrder.id, 'recent-1');
  await detail.loadInvoices(2);
  assert.equal(detail.invoices[0].id, 'invoice-26');
  assert.equal(detail.lastOrder.id, 'recent-1');
  assert.equal(calls.length, 2);
  assert.equal(calls[0].page_size, 25);
  assert.equal(detail.invoiceRangeLabel, 'Showing 26–26 of 26 invoices');
  assert.equal(detail.invoicePageLabel, 'Page 2 of 2');
  assert.match(TEMPLATE, /x-text="invoiceRangeLabel"/);
  assert.match(TEMPLATE, /x-text="invoicePageLabel"/);
});
