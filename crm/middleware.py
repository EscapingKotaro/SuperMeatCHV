from .models import AuditEvent


class AuditActionMiddleware:
    """Записывает успешные изменяющие действия, если view не сделал это сам."""

    mutating_methods = {
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    }

    view_labels = {
        "login": "Вход в CRM",
        "mark_attendance": "Изменение отметки посещения",
        "cancel_attendance": "Отмена отметки посещения",
        "archive_child": "Архивация спортсмена",
        "restore_child": "Восстановление спортсмена",
        "add_trial_child": "Добавление спортсмена на пробное",
        "child_create": "Создание спортсмена",
        "child_edit": "Редактирование карточки спортсмена",
        "child_delete": "Удаление спортсмена",
        "calendar": "Изменение календаря / задачи",
        "trainer_create": "Создание тренера",
        "trainer_edit": "Редактирование тренера",
        "trainer_delete": "Удаление тренера",
        "group_create": "Создание группы",
        "group_edit": "Редактирование группы",
        "group_delete": "Удаление группы",
        "competitions": "Изменение соревнований",
        "expenses": "Изменение расходов",
        "payments": "Изменение оплат / абонементов",
        "applications": "Изменение заявки",
        "newcomers": "Изменение новичка",
        "notifications": "Действие в уведомлениях",
        "users": "Изменение пользователя",
        "profile": "Изменение профиля",
        "boss": "Действие начальника",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, "user", None) and request.user.is_authenticated:
            from .models import expire_trials
            expire_trials()
            from .context_processors import sync_subscription_notifications, sync_today_trials
            sync_subscription_notifications(request.user)
            sync_today_trials(request.user)
        response = self.get_response(request)

        if request.method not in self.mutating_methods:
            return response

        if not (200 <= response.status_code < 400):
            return response

        if getattr(request, "_crm_audit_logged", False):
            return response

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return response

        resolver_match = getattr(
            request,
            "resolver_match",
            None,
        )
        view_name = (
            resolver_match.view_name
            if resolver_match
            else ""
        ) or request.path.strip("/") or "crm"

        try:
            posted_action = (
                request.POST.get("action")
                or ""
            ).strip()
        except Exception:
            posted_action = ""

        action = view_name
        if posted_action:
            action = f"{view_name}.{posted_action}"

        label = self.view_labels.get(
            view_name,
            f"Действие в CRM: {view_name}",
        )
        if posted_action:
            label = f"{label} · {posted_action}"

        AuditEvent.objects.create(
            actor=user,
            action=action[:100],
            description=label[:500],
        )
        request._crm_audit_logged = True

        return response
