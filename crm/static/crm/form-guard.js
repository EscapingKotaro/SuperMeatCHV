// Protect modal drafts and explicitly opted-in inline forms.
document.addEventListener("DOMContentLoaded", () => {
  const selector = '.modal, .fixed.inset-0[id$="-modal"]';
  const baselines = new WeakMap();
  const touched = new Set();
  const protectedForm = form => form && (form.closest(selector) || form.hasAttribute('data-guard-draft'));
  const snapshot = (form) => JSON.stringify([...form.elements]
    .filter(el => el.name && !["hidden", "submit", "button"].includes(el.type))
    .map(el => [el.name, el.type === "file"
      ? [...el.files].map(file => [file.name, file.size, file.lastModified])
      : el.type === "checkbox" || el.type === "radio" ? el.checked
      : el.multiple ? [...el.selectedOptions].map(option => option.value) : el.value]));
  const remember = (form) => {
    baselines.set(form, snapshot(form));
    touched.delete(form);
  };
  const forms = () => [...document.querySelectorAll("form")].filter(protectedForm);
  forms().forEach(remember);
  const dirty = () => [...touched].filter(form => form.isConnected && snapshot(form) !== baselines.get(form));
  const confirmClose = (scope = 'modal') => {
    const changed = dirty().filter(form => scope === 'all' || form.closest(selector));
    if (!changed.length) return true;
    if (!window.confirm("Есть несохранённые изменения. Продолжить без сохранения?")) return false;
    changed.forEach(remember);
    return true;
  };
  window.crmForms = { confirmClose, markSaved: remember };

  document.addEventListener("focusin", event => {
    const form = event.target.form;
    // Capture values populated by a modal opener before the first user edit.
    if (protectedForm(form) && !touched.has(form)) remember(form);
  });
  for (const name of ["input", "change"]) document.addEventListener(name, event => {
    const form = event.target.form;
    if (protectedForm(form)) touched.add(form);
  });
  document.addEventListener("reset", event => {
    if (event.target.matches("form")) queueMicrotask(() => remember(event.target));
  });
  let submitting = false;
  document.addEventListener("submit", event => {
    if (event.defaultPrevented) return;
    const otherDrafts = dirty().filter(form => form !== event.target);
    if (otherDrafts.length && !window.confirm("В других формах есть несохранённые изменения. Продолжить? Они не будут сохранены.")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    // AJAX submissions remain protected until their success callback marks them saved.
    queueMicrotask(() => {
      if (!event.defaultPrevented) {
        otherDrafts.forEach(remember);
        submitting = true;
      }
    });
  }, true);
  window.addEventListener("pageshow", () => { submitting = false; });
  window.addEventListener("beforeunload", event => {
    if (submitting || !dirty().length) return;
    event.preventDefault();
    event.returnValue = "";
  });
  document.addEventListener("click", event => {
    const target = event.target.closest('[data-close], [data-reason-close], [data-modal-backdrop], a[href], [onclick]');
    if (!target) return;
    const link = target.closest("a[href]");
    const closes = target.matches('[data-close], [data-reason-close], [data-modal-backdrop]')
      || (target.getAttribute("onclick") || "").includes("classList.add('hidden')");
    const navigates = link && !link.hasAttribute("download") && link.target !== "_blank"
      && !/^(#|tel:|mailto:)/i.test(link.getAttribute("href")) && !event.ctrlKey && !event.metaKey && !event.shiftKey;
    if ((closes || navigates) && !confirmClose(navigates ? 'all' : 'modal')) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !confirmClose()) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
});
