const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../crm/static/crm/athlete-remote.js'), 'utf8');

function fixture() {
  const requests = [], controls = [];
  class Option {
    constructor(label, value) { this.textContent = label; this.value = value; this.selected = false; this.attrs = {}; }
    setAttribute(key, value) { this.attrs[key] = value; }
  }
  const chosen = new Option('Анна', '1'); chosen.selected = true;
  const select = { dataset: { athleteRemote: '/lookup/' }, options: [chosen],
    before(...items) { controls.push(...items); }, replaceChildren(...items) { this.options = items; } };
  const document = {
    addEventListener(name, callback) { callback(); }, querySelectorAll() { return [select]; },
    createElement() { return { handlers: {}, value: '', setAttribute() {}, addEventListener(name, callback) { this.handlers[name] = callback; } }; },
  };
  vm.runInNewContext(source, { document, Option, URL, AbortController, location: { href: 'https://crm.test/' },
    setTimeout() { return 1; }, clearTimeout() {},
    fetch(url) { return new Promise((resolve, reject) => requests.push({ url, resolve, reject })); },
  });
  const [input, hint, retry] = controls;
  const search = q => { input.value = q; input.handlers.keydown({ key: 'Enter', preventDefault() {} }); };
  return { select, chosen, hint, retry, requests, search };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const response = results => ({ ok: true, json: async () => ({ results, more: false }) });

test('remote search keeps selected athlete, preserves metadata, ignores stale responses', async () => {
  const f = fixture();
  f.search('Петрова'); f.search('Орлова');
  f.requests[1].resolve(response([{ id: 2, label: 'Орлова', attrs: { 'data-child-status': 'trial', 'data-discount-percent': '15' } }]));
  await flush();
  assert.ok(f.select.options.includes(f.chosen));
  assert.ok(f.chosen.selected);
  assert.equal(f.select.options.find(item => item.value === '2').attrs['data-discount-percent'], '15');
  f.requests[0].resolve(response([{ id: 3, label: 'Устаревший ответ' }]));
  await flush();
  assert.ok(!f.select.options.some(item => item.value === '3'));
});

test('network error keeps selection and offers retry', async () => {
  const f = fixture();
  f.search('Петрова'); f.requests[0].reject(new Error('offline'));
  await flush();
  assert.ok(f.chosen.selected);
  assert.equal(f.retry.hidden, false);
  assert.match(f.hint.textContent, /Текущий выбор сохранён/);
  f.retry.handlers.click();
  assert.equal(f.requests.length, 2);
});
