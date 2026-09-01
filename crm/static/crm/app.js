document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) lucide.createIcons();

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
  document.querySelector("[data-menu-toggle]")?.addEventListener("click", () => {
    document.querySelector("[data-user-menu]")?.classList.toggle("hidden");
  });

  const csrf = () => document.cookie.split("; ").find((row) => row.startsWith("csrftoken="))?.split("=")[1] || "";
  const states = [
    {status: "", symbol: "", css: "bg-slate-100 text-slate-400"},
    {status: "present", symbol: "+", css: "bg-emerald-100 text-emerald-700"},
    {status: "absent", symbol: "×", css: "bg-red-100 text-red-700"},
    {status: "excused", symbol: "У", css: "bg-purple-100 text-purple-700"},
    {status: "frozen", symbol: "❄", css: "bg-blue-100 text-blue-700"},
    {status: "vacation", symbol: "О", css: "bg-amber-100 text-amber-700"},
  ];
  const picker = document.getElementById("attendance-picker");
  let activeAttendance = null;

  async function saveAttendance(button, next) {
      const old = {status: button.dataset.status, symbol: button.textContent, className: button.className};
      button.dataset.status = next.status;
      button.textContent = next.symbol;
      button.className = `attendance-cell mx-auto ${next.css}`;
      const body = new FormData();
      body.append("action", "mark"); body.append("child_id", button.dataset.child);
      body.append("date", button.dataset.date); body.append("status", next.status);
      try {
        const response = await fetch(window.attendanceUrl, {
          method: "POST", body,
          headers: {"X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest"},
        });
        if (!response.ok) throw new Error("save failed");
      } catch (_) {
        button.dataset.status = old.status; button.textContent = old.symbol; button.className = old.className;
        alert("Не удалось сохранить отметку. Обновите страницу и попробуйте снова.");
      }
  }

  document.querySelectorAll("[data-attendance]").forEach((button) => {
    button.addEventListener("click", (event) => {
      activeAttendance = button;
      const rect = event.currentTarget.getBoundingClientRect();
      picker.style.left = `${Math.min(rect.left, window.innerWidth - 220)}px`;
      picker.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - 260)}px`;
      picker.classList.remove("hidden");
    });
    button.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      saveAttendance(button, states[0]);
      picker?.classList.add("hidden");
    });
  });

  picker?.querySelectorAll("[data-mark]").forEach((choice) => {
    choice.addEventListener("click", () => {
      if (!activeAttendance) return;
      const next = states.find((state) => state.status === choice.dataset.mark) || states[0];
      saveAttendance(activeAttendance, next);
      picker.classList.add("hidden");
    });
  });

  document.addEventListener("click", (event) => {
    if (picker && !picker.contains(event.target) && !event.target.closest("[data-attendance]")) {
      picker.classList.add("hidden");
    }
  });

});
