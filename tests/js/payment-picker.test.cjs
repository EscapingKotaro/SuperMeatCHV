const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup(initial = {}) {
  const nodes = {};
  for (const name of ['child', 'subscription', 'load-status', 'retry', 'submit', 'working-group', 'working-group-wrap']) {
    nodes[name] = { value: '', events: {}, options: [], selectedOptions: [{ dataset: { childStatus: 'trial' } }],
      classList: { toggle() {} }, addEventListener(name, fn) { this.events[name] = fn; },
      replaceChildren(...options) { this.options = options; this.value = ''; }, add(option) { this.options.push(option); } };
  }
  const requests = [];
  nodes.child.value = initial.child || '';
  nodes['working-group'].value = initial.group || '';
  const form = { dataset: { subscriptionsUrl: '/payments/subscriptions/', initialSubscription: initial.subscription || '' }, events: {},
    querySelector: selector => nodes[selector.slice(14, -1)],
    addEventListener(name, fn) { this.events[name] = fn; } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../crm/static/crm/payment-picker.js'), 'utf8'), {
    document: { querySelector: () => form }, location: { href: 'https://crm.example/payments/' }, URL,
    AbortController, Option: function(label, value) { this.label = label; this.value = value; },
    setTimeout: () => 1, clearTimeout() {},
    fetch: url => new Promise((resolve, reject) => requests.push({ url, resolve, reject })),
  });
  const select = id => { nodes.child.value = id; nodes.child.events.change(); };
  const resolve = async (index, id, list = []) => {
    requests[index].resolve({ ok: true, redirected: false, json: async () => ({ child_id: id, subscriptions: list }) });
    for (let i = 0; i < 5; i++) await Promise.resolve();
  };
  return { nodes, form, requests, select, resolve };
}

test('nothing submitted before a child is selected and loaded', () => {
  const ui = setup();
  assert.equal(ui.requests.length, 0);
  assert.equal(ui.nodes.submit.disabled, true);
  let prevented = false;
  ui.form.events.submit({ preventDefault() { prevented = true; } });
  assert.ok(prevented);
});

test('switching children clears group and ignores stale response', async () => {
  const ui = setup();
  ui.select('1'); ui.nodes['working-group'].value = 'old'; ui.select('2');
  assert.equal(ui.nodes['working-group'].value, '');
  await ui.resolve(1, 2, [{ id: 22, label: 'Второй' }]);
  await ui.resolve(0, 1, [{ id: 11, label: 'Первый' }]);
  assert.equal(ui.nodes.subscription.options[1].value, '22');
  assert.equal(ui.nodes.submit.disabled, false);
});

test('network error blocks payment; retry can load empty list for prepayment', async () => {
  const ui = setup(); ui.select('1');
  ui.requests[0].reject(new Error('network'));
  for (let i = 0; i < 5; i++) await Promise.resolve();
  assert.equal(ui.nodes.retry.hidden, false);
  assert.equal(ui.nodes.submit.disabled, true);
  ui.nodes.retry.events.click();
  await ui.resolve(1, 1);
  assert.equal(ui.nodes.submit.disabled, false);
  assert.equal(ui.nodes.subscription.options.length, 1);
});

test('mismatched child response never enables payment', async () => {
  const ui = setup(); ui.select('1');
  await ui.resolve(0, 2, [{ id: 22, label: 'Чужой' }]);
  assert.equal(ui.nodes.submit.disabled, true);
  assert.equal(ui.nodes.retry.hidden, false);
});

test('validation retry restores subscription and working group', async () => {
  const ui = setup({ child: '1', subscription: '7', group: '3' });
  await ui.resolve(0, 1, [{ id: 7, label: 'Абонемент' }]);
  assert.equal(ui.nodes.subscription.value, '7');
  assert.equal(ui.nodes['working-group'].value, '3');
  assert.equal(ui.nodes.submit.disabled, false);
});

test('unavailable previous subscription requires explicit replacement', async () => {
  const ui = setup({ child: '1', subscription: '7' });
  await ui.resolve(0, 1);
  assert.equal(ui.nodes.submit.disabled, true);
  ui.nodes.subscription.value = '';
  ui.nodes.subscription.events.change();
  assert.equal(ui.nodes.submit.disabled, false);
});
