// Keep the original native select: validation, metadata and change handlers remain intact.
(() => {
  const normalize = value => String(value).toLocaleLowerCase('ru').replace(/ё/g, 'е').trim();
  const matches = (label, query) => normalize(query).split(/\s+/).every(word => normalize(label).includes(word));

  function install(select, doc = document) {
    if (select.disabled || select.dataset.athleteSearchReady) return;
    select.dataset.athleteSearchReady = 'true';
    const options = Array.from(select.options);
    const box = doc.createElement('div');
    box.className = 'space-y-1 mb-2';
    const search = doc.createElement('input');
    search.type = 'search';
    search.className = 'field';
    search.placeholder = 'Найти спортсмена по ФИО';
    search.setAttribute('aria-label', 'Поиск спортсмена в списке ниже');
    search.autocomplete = 'off';
    const hint = doc.createElement('p');
    hint.className = 'text-xs text-slate-500';
    hint.setAttribute('role', 'status');
    box.append(search, hint);
    select.before(box);

    function filter() {
      const selected = new Set(options.filter(option => option.selected));
      const found = options.filter(option => option.value && matches(option.textContent, search.value));
      const foundSet = new Set(found);
      // Keep selected options and the empty prompt even when they do not match.
      // Moving the original nodes also preserves data used by payment/subscription logic.
      const visible = options.filter(option => !option.value || selected.has(option) || foundSet.has(option));
      select.replaceChildren(...visible);
      for (const option of visible) option.selected = selected.has(option);
      if (!selected.size) select.selectedIndex = -1;
      const retained = options.filter(option => option.value && selected.has(option) && !foundSet.has(option)).length;
      hint.textContent = `${found.length ? 'Найдено: ' + found.length + '. Выберите в списке ниже.' : 'Совпадений нет. Измените или очистите поиск.'}${retained ? ' Текущий выбор сохранён.' : ''}`;
    }
    search.addEventListener('input', filter);
    // Enter in the auxiliary search must not accidentally submit a payment.
    search.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); select.focus(); }
    });
    select.addEventListener('change', filter);
    if (select.form) {
      select.form.addEventListener('reset', () => {
        search.value = '';
        select.replaceChildren(...options);
        queueMicrotask(filter);
      });
    }
    filter();
  }
  if (typeof module !== 'undefined') module.exports = { matches, install };
  if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('select[data-athlete-search]').forEach(select => install(select));
  });
})();
