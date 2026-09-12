(() => {
  const form = document.querySelector('[data-payment-form]');
  if (!form) return;
  const field = name => form.querySelector(`[data-payment-${name}]`);
  const child = field('child'), subscriptions = field('subscription');
  const status = field('load-status'), retry = field('retry'), submit = field('submit');
  const group = field('working-group'), groupWrap = field('working-group-wrap');
  let version = 0, readyFor = '';
  let loadedFor = '', initialSubscription = form.dataset.initialSubscription || '';
  let controller;

  async function load() {
    const current = ++version, childId = child.value;
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;
    readyFor = '';
    loadedFor = '';
    submit.disabled = true;
    subscriptions.disabled = true;
    subscriptions.replaceChildren(new Option(childId ? 'Загрузка…' : 'Сначала выберите спортсмена', ''));
    retry.hidden = true;
    retry.classList.toggle('hidden', true);
    status.textContent = childId ? 'Загружаем абонементы…' : 'Сначала выберите спортсмена.';
    if (!childId) return;
    const timeout = setTimeout(() => requestController.abort(), 15000);
    try {
      const url = new URL(form.dataset.subscriptionsUrl, location.href);
      url.searchParams.set('child_id', childId);
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: requestController.signal });
      if (!response.ok || response.redirected) throw new Error('load');
      const data = await response.json();
      if (current !== version) return;
      if (String(data.child_id) !== childId || !Array.isArray(data.subscriptions)) throw new Error('child');
      subscriptions.replaceChildren(new Option('Автоматически / предоплата без привязки', ''));
      for (const item of data.subscriptions) subscriptions.add(new Option(item.label, String(item.id)));
      subscriptions.disabled = false;
      loadedFor = childId;
      readyFor = childId;
      submit.disabled = false;
      status.textContent = data.subscriptions.length
        ? `Найдено абонементов: ${data.subscriptions.length}. Выберите нужный или оставьте автоматическую привязку.`
        : 'Неотменённых абонементов нет. Можно принять предоплату без привязки.';
      if (initialSubscription) {
        if (data.subscriptions.some(item => String(item.id) === initialSubscription)) {
          subscriptions.value = initialSubscription;
        } else {
          const unavailable = new Option('Ранее выбранный абонемент недоступен — выберите другой вариант', initialSubscription);
          unavailable.disabled = true;
          subscriptions.add(unavailable);
          subscriptions.value = initialSubscription;
          readyFor = '';
          submit.disabled = true;
          status.textContent = 'Выберите другой абонемент или явно укажите предоплату без привязки.';
        }
        initialSubscription = '';
      }
    } catch {
      if (current !== version) return;
      subscriptions.replaceChildren(new Option('Не удалось загрузить абонементы', ''));
      status.textContent = 'Не удалось загрузить список. Повторите попытку; если вход истёк, обновите страницу. Оплата не отправлена.';
      retry.hidden = false;
      retry.classList.toggle('hidden', false);
    } finally {
      clearTimeout(timeout);
    }
  }

  function syncGroup(reset = true) {
    const isTrial = child.selectedOptions[0]?.dataset.childStatus === 'trial';
    groupWrap?.classList.toggle('hidden', !isTrial);
    if (group) { group.required = isTrial; if (reset || !isTrial) group.value = ''; }
  }
  child.addEventListener('change', () => { initialSubscription = ''; syncGroup(); load(); });
  subscriptions.addEventListener('change', () => {
    if (loadedFor === child.value) { readyFor = child.value; submit.disabled = false; }
  });
  retry.addEventListener('click', load);
  form.addEventListener('submit', event => {
    if (!child.value || readyFor !== child.value || submit.disabled) event.preventDefault();
  });
  syncGroup(false);
  load();
})();
