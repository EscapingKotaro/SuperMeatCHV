document.addEventListener("DOMContentLoaded", () => {
  // 1. Инициализация иконок Lucide
  if (window.lucide) lucide.createIcons();

  // 2. Модальные окна
  const backdrop = document.querySelector("[data-modal-backdrop]");
  const closeAll = () => {
    document.querySelectorAll(".modal.open").forEach((modal) => modal.classList.remove("open"));
    backdrop?.classList.add("hidden");
  };
  
  document.querySelectorAll("[data-modal]").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById(button.dataset.modal)?.classList.add("open");
      backdrop?.classList.remove("hidden");
    });
  });
  
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", closeAll));
  backdrop?.addEventListener("click", closeAll);

  // 3. Уведомления (Toasts)
  document.querySelectorAll("[data-toast]").forEach((toast) => {
    const close = () => {
      toast.style.transition = "opacity .2s, transform .2s";
      toast.style.opacity = "0";
      toast.style.transform = "translateY(8px)";
      setTimeout(() => toast.remove(), 200);
    };

    toast.querySelector("[data-toast-close]")?.addEventListener("click", close);
    setTimeout(close, 4000);
  });

});