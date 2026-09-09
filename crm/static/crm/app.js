document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) lucide.createIcons();

  const backdrop = document.querySelector("[data-modal-backdrop]");
  const modalTriggers = document.querySelectorAll("[data-modal]");
  const dropdownToggles = document.querySelectorAll("[data-dropdown-target]");
  const dropdownMenus = document.querySelectorAll('[id^="dropdown-"]');

  const syncBackdrop = () => {
    backdrop?.classList.toggle(
      "hidden",
      !document.querySelector(".modal.open"),
    );
  };

  const closeAllModals = () => {
    document
      .querySelectorAll(".modal.open")
      .forEach((modal) => modal.classList.remove("open"));
    syncBackdrop();
  };

  modalTriggers.forEach((button) => {
    button.addEventListener("click", () => {
      closeAllModals();
      document.getElementById(button.dataset.modal)?.classList.add("open");
      syncBackdrop();
    });
  });

  document
    .querySelectorAll("[data-close]")
    .forEach((button) => button.addEventListener("click", closeAllModals));
  backdrop?.addEventListener("click", closeAllModals);
  syncBackdrop();

  const closeAllDropdowns = () => {
    dropdownMenus.forEach((menu) => menu.classList.add("hidden"));
    dropdownToggles.forEach((toggle) => toggle.setAttribute("aria-expanded", "false"));
  };

  const positionDropdown = (toggle, menu) => {
    const rect = toggle.getBoundingClientRect();
    menu.style.top = `${rect.bottom + 8}px`;
    menu.classList.remove("hidden");

    const preferredLeft = toggle.dataset.dropdownAlign === "right"
      ? rect.right - menu.offsetWidth
      : rect.left;
    const maxLeft = Math.max(8, window.innerWidth - menu.offsetWidth - 8);
    menu.style.left = `${Math.min(Math.max(8, preferredLeft), maxLeft)}px`;
  };

  dropdownToggles.forEach((toggle) => {
    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();

      const menu = document.getElementById(toggle.dataset.dropdownTarget);
      if (!menu) return;

      const shouldOpen = menu.classList.contains("hidden");
      closeAllDropdowns();
      if (shouldOpen) {
        positionDropdown(toggle, menu);
        toggle.setAttribute("aria-expanded", "true");
      }
    });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest('[id^="dropdown-"]')) closeAllDropdowns();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeAllDropdowns();
    closeAllModals();
  });

  window.addEventListener("scroll", closeAllDropdowns, true);
  window.addEventListener("resize", closeAllDropdowns);

  const nav = document.getElementById("main-nav");
  nav?.addEventListener(
    "wheel",
    (event) => {
      if (nav.scrollWidth <= nav.clientWidth || event.ctrlKey) return;
      event.preventDefault();
      nav.scrollLeft += event.deltaY;
    },
    { passive: false },
  );

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