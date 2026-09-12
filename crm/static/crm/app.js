document.addEventListener("DOMContentLoaded", () => {
  // Retain list filters when opening editors and carry an explicit return link to cards.
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (!link) return;
    const target = new URL(link.href, location.href);
    if (target.origin !== location.origin) return;
    const current = new URL(location.href);
    if (target.pathname === current.pathname && [...target.searchParams.keys()].some(k => /^(edit|create|new_)/.test(k))) {
      for (const [key, value] of current.searchParams) {
        if (!/^(edit|create|new_)/.test(key) && !target.searchParams.has(key)) target.searchParams.set(key, value);
      }
      link.href = target.href;
    }
    if (/^\/children\/\d+\/$/.test(target.pathname) && target.pathname !== current.pathname) {
      current.searchParams.delete("next");
      target.searchParams.set("next", current.pathname + current.search + current.hash);
      link.href = target.href;
    }
  }, true);
  if (window.lucide) lucide.createIcons();

  const backdrop = document.querySelector("[data-modal-backdrop]");
  const modalTriggers = document.querySelectorAll("[data-modal]");
  const dropdownToggles = document.querySelectorAll("[data-dropdown-target]");
  const dropdownMenus = document.querySelectorAll('[id^="dropdown-"]');
  const legacyOverlayModals = [
    ...document.querySelectorAll('.fixed.inset-0[id$="-modal"]:not(.modal)'),
  ];

  legacyOverlayModals.forEach((modal) => {
    modal.classList.add("crm-overlay-modal");
    const panel = [...modal.children].find(
      (child) => child.classList.contains("relative"),
    );
    panel?.classList.add("crm-overlay-panel");
  });

  const closeAllDropdowns = () => {
    dropdownMenus.forEach((menu) => menu.classList.add("hidden"));
    dropdownToggles.forEach((toggle) => toggle.setAttribute("aria-expanded", "false"));
  };

  const hasCommonModalOpen = () => Boolean(
    document.querySelector(".modal.open"),
  );

  const hasLegacyModalOpen = () => legacyOverlayModals.some(
    (modal) => !modal.classList.contains("hidden"),
  );

  const syncModalState = () => {
    const commonOpen = hasCommonModalOpen();
    backdrop?.classList.toggle("hidden", !commonOpen);
    document.body.classList.toggle(
      "modal-open",
      commonOpen || hasLegacyModalOpen(),
    );
  };

  const closeAllModals = () => {
    if (window.crmForms && !window.crmForms.confirmClose()) return false;
    document
      .querySelectorAll(".modal.open")
      .forEach((modal) => modal.classList.remove("open"));
    legacyOverlayModals.forEach((modal) => modal.classList.add("hidden"));
    syncModalState();
    return true;
  };

  const openModal = (id) => {
    const modal = document.getElementById(id);
    if (!modal) return null;

    closeAllDropdowns();
    if (!closeAllModals()) return null;

    if (modal.classList.contains("modal")) {
      modal.classList.add("open");
    } else {
      modal.classList.remove("hidden");
    }

    syncModalState();
    return modal;
  };

  window.crmModal = {
    open: openModal,
    closeAll: closeAllModals,
    sync: syncModalState,
  };

  modalTriggers.forEach((button) => {
    button.addEventListener("click", () => {
      openModal(button.dataset.modal);
    });
  });

  document
    .querySelectorAll("[data-close]")
    .forEach((button) => button.addEventListener("click", closeAllModals));
  backdrop?.addEventListener("click", closeAllModals);

  if (legacyOverlayModals.length) {
    const observer = new MutationObserver(syncModalState);
    legacyOverlayModals.forEach((modal) => {
      observer.observe(modal, {
        attributes: true,
        attributeFilter: ["class"],
      });
    });
  }

  syncModalState();

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
