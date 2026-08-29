document.addEventListener('DOMContentLoaded', () => {
    if (window.lucide) lucide.createIcons();

    const backdrop = document.querySelector('[data-modal-backdrop]');
    const closeAll = () => {
        document.querySelectorAll('.modal.open').forEach(x => x.classList.remove('open'));
        backdrop?.classList.add('hidden');
    };

    document.querySelectorAll('[data-modal]').forEach(b => b.addEventListener('click', () => {
        document.getElementById(b.dataset.modal)?.classList.add('open');
        backdrop?.classList.remove('hidden');
    }));

    document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', closeAll));
    backdrop?.addEventListener('click', closeAll);

    document.querySelector('[data-menu-toggle]')?.addEventListener('click', () =>
        document.querySelector('[data-user-menu]')?.classList.toggle('hidden'));

    document.querySelectorAll('[data-save]').forEach(b => b.addEventListener('click', () => {
        closeAll();
        const t = document.getElementById('toast');
        t.classList.remove('hidden');
        t.classList.add('flex');
        setTimeout(() => {
            t.classList.add('hidden');
            t.classList.remove('flex');
        }, 2200);
    }));

    // Функция получения CSRF из cookie
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    // Обработчик кликов по ячейкам отметок
    document.querySelectorAll('[data-attendance]').forEach(btn => {
        btn.addEventListener('click', function() {
            const childId = this.dataset.childId;
            const date = this.dataset.date;
            const currentState = Number(this.dataset.state || 0);
            const newState = (currentState + 1) % 6; // 0-5
            const statusMap = {
                0: '',          // нет отметки
                1: 'present',   // +
                2: 'absent',    // ×
                3: 'frozen',    // ❄
                4: 'vacation',  // О
                5: 'excused',   // У (уважительная)
            };
            const newStatus = statusMap[newState];

            // Отправляем AJAX
            fetch('/attendance/update/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken'),
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `child_id=${childId}&date=${date}&status=${newStatus}`
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Обновляем визуально
                    this.dataset.state = newState;
                    const visualMap = {
                        0: ['', 'bg-slate-100 text-slate-400'],
                        1: ['+', 'bg-emerald-100 text-emerald-700'],
                        2: ['×', 'bg-red-100 text-red-700'],
                        3: ['❄', 'bg-blue-100 text-blue-700'],
                        4: ['О', 'bg-amber-100 text-amber-700'],
                        5: ['У', 'bg-yellow-100 text-yellow-700'],
                    };
                    const [symbol, colorClasses] = visualMap[newState];
                    this.textContent = symbol;
                    this.className = 'attendance-cell ' + colorClasses;
                } else {
                    alert('Ошибка сохранения');
                }
            })
            .catch(error => {
                console.error('Ошибка:', error);
                alert('Ошибка сети');
            });
        });
    });
});