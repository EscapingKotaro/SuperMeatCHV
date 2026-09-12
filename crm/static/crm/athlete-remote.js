document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('select[data-athlete-remote]').forEach(select => {
    if (select.disabled) return;
    const input = document.createElement('input');
    input.type = 'search'; input.className = 'field mb-2';
    input.placeholder = 'Поиск по ФИО · от 2 букв';
    input.setAttribute('aria-label', 'Поиск спортсмена');
    const hint = document.createElement('p');
    hint.className = 'text-xs text-slate-500 mb-2'; hint.setAttribute('role', 'status');
    hint.textContent = 'Введите ФИО. Уже выбранные спортсмены сохраняются.';
    const retry = document.createElement('button');
    retry.type = 'button'; retry.className = 'btn btn-soft mb-2'; retry.textContent = 'Повторить поиск'; retry.hidden = true;
    select.before(input, hint, retry);
    let version = 0, timer, controller;
    const kept = () => [...select.options].filter(option => option.selected && option.value);
    async function search() {
      const current = ++version;
      controller?.abort();
      const q = input.value.trim();
      if (q.length < 2) { hint.textContent = 'Введите хотя бы 2 буквы.'; return; }
      controller = new AbortController();
      const requestController = controller;
      const timeout = setTimeout(() => requestController.abort(), 15000);
      retry.hidden = true; hint.textContent = 'Поиск…';
      try {
        const url = new URL(select.dataset.athleteRemote, location.href);
        url.searchParams.set('q', q); url.searchParams.set('scope', select.dataset.scope || 'all');
        if (select.dataset.competition) url.searchParams.set('competition', select.dataset.competition);
        const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: requestController.signal });
        if (!response.ok || response.redirected) throw new Error('lookup');
        const data = await response.json();
        if (current !== version) return;
        if (!Array.isArray(data.results)) throw new Error('lookup');
        const selected = kept(), ids = new Set(selected.map(option => option.value));
        const options = select.multiple ? [] : [new Option('— Выберите спортсмена —', '')];
        options.push(...selected);
        for (const row of data.results) {
          if (ids.has(String(row.id))) continue;
          const option = new Option(row.label, String(row.id));
          for (const [key, value] of Object.entries(row.attrs || {})) if (key.startsWith('data-')) option.setAttribute(key, value);
          options.push(option);
        }
        select.replaceChildren(...options);
        for (const option of select.options) option.selected = ids.has(option.value);
        if (!ids.size && !select.multiple) select.value = '';
        hint.textContent = data.more ? 'Показаны первые 30. Уточните ФИО.' : data.results.length ? `Найдено: ${data.results.length}. Выберите в списке.` : 'Совпадений нет. Измените запрос; текущий выбор сохранён.';
        if (select.multiple) hint.textContent += ' Для выбора нескольких используйте Ctrl / Cmd.';
      } catch {
        if (current !== version) return;
        hint.textContent = 'Поиск не удался. Текущий выбор сохранён. Повторите поиск или обновите вход.';
        retry.hidden = false;
      } finally { clearTimeout(timeout); }
    }
    input.addEventListener('input', () => { ++version; controller?.abort(); clearTimeout(timer); timer = setTimeout(search, 250); });
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); clearTimeout(timer); search(); } });
    retry.addEventListener('click', search);
  });
});
