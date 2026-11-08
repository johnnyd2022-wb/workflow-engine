/**
 * Node unit tests for the CRM customers list's New customer form.
 * Run: node --test tests/js/crm-customers.test.js
 *
 * customers.js declares a global `crmCustomers()` Alpine factory, loaded here into a vm sandbox
 * with a stub CRMAPI. Bug under test: the New customer sheet is in the page from the start
 * (hidden), so Alpine evaluates `newCustomer.form.address.line1` on load. The initial form was
 * `{}`, so every visit to /crm/customers threw "Cannot read properties of undefined (reading
 * 'line1')".
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');

const SRC = fs.readFileSync(
  path.join(__dirname, '..', '..', 'app', 'features', 'crm', 'frontend', 'js', 'customers.js'),
  'utf8'
);
const ADDRESS = ['line1', 'line2', 'city', 'region', 'postal_code', 'country'];

function makePage(settings) {
  const CRMAPI = {
    ensureBackButton() {},
    async getContactSyncSettings() {
      return settings;
    },
  };
  const document = { getElementById: () => null };
  const context = vm.createContext({ CRMAPI, document, window: {}, console });
  vm.runInContext(SRC, context);
  const page = vm.runInContext('crmCustomers()', context);
  page.$nextTick = (fn) => fn();
  return page;
}

test('every field the hidden New customer sheet binds to exists before it is opened', () => {
  const form = makePage().newCustomer.form;
  for (const field of ['name', 'first_name', 'last_name', 'email_address', 'phone_number']) {
    assert.equal(form[field], '', field);
  }
  for (const part of ADDRESS) assert.equal(form.address[part], '', `address.${part}`);
});

test('opening the sheet gives a fresh blank form that follows the Sales default', async () => {
  const page = makePage({ sync_contacts_to_xero: true, xero: { connected: true, can_write_contacts: true } });
  page.newCustomer.form.address.line1 = 'left over';
  await page.openNewCustomer();
  assert.equal(page.newCustomer.open, true);
  assert.equal(page.newCustomer.form.sync, true);
  assert.deepEqual(Object.keys(page.newCustomer.form.address), ADDRESS);
  assert.equal(page.newCustomer.form.address.line1, '');
});
