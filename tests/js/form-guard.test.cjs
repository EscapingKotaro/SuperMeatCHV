const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup({ inline = false } = {}) {
  const events = {}, windowEvents = {};
  const field = { name: 'name', type: 'text', value: 'Начальное' };
  const form = { elements: [field], closest: () => !inline, hasAttribute: name => name === 'data-guard-draft', isConnected: true };
  field.form = form;
  let prompts = 0;
  const window = {
    confirm: () => { prompts++; return false; },
    addEventListener: (name, cb) => { windowEvents[name] = cb; },
  };
  const document = {
    addEventListener: (name, cb) => { events[name] = cb; },
    querySelectorAll: () => [form],
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../crm/static/crm/form-guard.js'), 'utf8'), { document, window, queueMicrotask });
  events.DOMContentLoaded();
  const change = value => { field.value = value; events.input({ target: field }); };
  return { events, windowEvents, field, form, window, change, prompts: () => prompts };
}

test('unchanged form closes silently; reverting a change also closes silently', () => {
  const ui = setup();
  assert.equal(ui.window.crmForms.confirmClose(), true);
  ui.change('Новое'); ui.change('Начальное');
  assert.equal(ui.window.crmForms.confirmClose(), true);
  assert.equal(ui.prompts(), 0);
});

test('cancelled confirmation preserves the draft and blocks closure', () => {
  const ui = setup(); ui.change('Черновик');
  assert.equal(ui.window.crmForms.confirmClose(), false);
  assert.equal(ui.field.value, 'Черновик');
  assert.equal(ui.prompts(), 1);
});

test('Escape cannot reach legacy close handlers after cancellation', () => {
  const ui = setup(); ui.change('Черновик');
  let prevented = false, stopped = false;
  ui.events.keydown({ key: 'Escape', preventDefault: () => { prevented = true; }, stopImmediatePropagation: () => { stopped = true; } });
  assert.ok(prevented && stopped);
});

test('successful AJAX save clears guard, failed AJAX submission does not', async () => {
  const ui = setup(); ui.change('Черновик');
  ui.events.submit({ target: ui.form, defaultPrevented: true });
  await Promise.resolve();
  let blocked = false;
  ui.windowEvents.beforeunload({ preventDefault: () => { blocked = true; } });
  assert.ok(blocked);
  ui.window.crmForms.markSaved(ui.form);
  assert.equal(ui.window.crmForms.confirmClose(), true);
});

test('regular valid submission does not cause an unsaved warning', async () => {
  const ui = setup(); ui.change('Готово');
  ui.events.submit({ target: ui.form, defaultPrevented: false });
  await Promise.resolve();
  ui.windowEvents.beforeunload({ preventDefault: () => assert.fail('Submission must not be blocked') });
});

test('backdrop click is stopped before a legacy handler can hide the form', () => {
  const ui = setup(); ui.change('Черновик');
  let stopped = false, prevented = false;
  const backdrop = { closest: () => null, matches: () => true };
  ui.events.click({ target: { closest: () => backdrop },
    preventDefault: () => { prevented = true; }, stopImmediatePropagation: () => { stopped = true; } });
  assert.ok(stopped && prevented);
});

test('confirmed closure does not ask twice in shared close handler', () => {
  const ui = setup(); ui.change('Черновик');
  let count = 0;
  ui.window.confirm = () => { count++; return true; };
  assert.equal(ui.window.crmForms.confirmClose(), true);
  assert.equal(ui.window.crmForms.confirmClose(), true);
  assert.equal(count, 1);
});

test('inline draft warns on departure, but not on modal close or Escape', () => {
  const ui = setup({ inline: true }); ui.change('Черновик');
  assert.equal(ui.window.crmForms.confirmClose(), true);
  ui.events.keydown({ key: 'Escape', preventDefault: () => assert.fail('Escape must not affect inline draft') });
  assert.equal(ui.window.crmForms.confirmClose('all'), false);
  let blocked = false;
  ui.windowEvents.beforeunload({ preventDefault: () => { blocked = true; } });
  assert.ok(blocked);
});

test('saving a different form cannot silently discard an inline draft', () => {
  const ui = setup({ inline: true }); ui.change('Черновик');
  let prevented = false, stopped = false;
  ui.events.submit({ target: {}, defaultPrevented: false,
    preventDefault: () => { prevented = true; }, stopImmediatePropagation: () => { stopped = true; } });
  assert.ok(prevented && stopped);
  assert.equal(ui.field.value, 'Черновик');
});

test('saving the inline draft itself does not ask for confirmation', async () => {
  const ui = setup({ inline: true }); ui.change('Сохранить');
  ui.events.submit({ target: ui.form, defaultPrevented: false });
  await Promise.resolve();
  assert.equal(ui.prompts(), 0);
  ui.windowEvents.beforeunload({ preventDefault: () => assert.fail('Own save must be allowed') });
});

test('downloads and phone links do not clear or interrupt inline drafts', () => {
  const ui = setup({ inline: true }); ui.change('Черновик');
  for (const [href, download] of [['/file/', true], ['tel:+79990000000', false], ['mailto:test@example.com', false]]) {
    const link = { target: '', closest: () => link, hasAttribute: () => download,
      matches: () => false, getAttribute: name => name === 'href' ? href : '' };
    ui.events.click({ target: { closest: () => link }, preventDefault: () => assert.fail('Must not interrupt') });
  }
  assert.equal(ui.prompts(), 0);
  assert.equal(ui.window.crmForms.confirmClose('all'), false);
});
