const test = require('node:test');
const assert = require('node:assert/strict');
const { matches, install } = require('../../crm/static/crm/athlete-search.js');

function fixture() {
  const elements = [];
  const doc = { createElement: () => {
    const el = { value: '', handlers: {}, setAttribute() {}, append() {},
      addEventListener(name, fn) { this.handlers[name] = fn; } };
    elements.push(el); return el;
  } };
  const options = [
    { value: '', textContent: 'Выберите спортсмена', selected: true },
    { value: '1', textContent: 'Орлова Алёна', selected: false, dataset: { childStatus: 'trial' } },
    { value: '2', textContent: 'Иванов Иван', selected: false },
  ];
  const select = { options: [...options], dataset: {}, handlers: {}, before() {},
    replaceChildren(...nodes) { this.options = nodes; },
    addEventListener(name, fn) { this.handlers[name] = fn; },
    focus() { this.focused = true; } };
  install(select, doc);
  return { select, options, search: elements[1], hint: elements[2] };
}

test('search handles case, ё and name words in any order', () => {
  assert.ok(matches('Орлова Алёна', 'алена ОРЛ'));
  assert.ok(matches('Иванов Иван', '  '));
  assert.ok(!matches('Орлова Алёна', 'Иван'));
});
test('filter preserves the prompt, original option metadata and selection', () => {
  const { select, options, search } = fixture();
  search.value = 'алена'; search.handlers.input();
  assert.deepEqual(select.options, options.slice(0, 2));
  assert.equal(select.options[1].dataset.childStatus, 'trial');
  assert.equal(options[0].selected, true);
  search.value = ''; search.handlers.input();
  assert.deepEqual(select.options, options);
});
test('no results does not discard an existing selection, including multiple selection', () => {
  const { select, options, search, hint } = fixture();
  options[0].selected = false;
  options[1].selected = options[2].selected = true;
  search.value = 'несуществующий'; search.handlers.input();
  assert.equal(select.options.length, 3);
  assert.ok(options[1].selected && options[2].selected);
  assert.match(hint.textContent, /Совпадений нет.*выбор сохранён/);
});
test('Enter moves to the select without submitting the form', () => {
  const { select, search } = fixture();
  let prevented = false;
  search.handlers.keydown({ key: 'Enter', preventDefault() { prevented = true; } });
  assert.ok(prevented && select.focused);
});
