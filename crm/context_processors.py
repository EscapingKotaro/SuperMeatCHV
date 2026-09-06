from django.db.models import Q

from .models import ManagerTask, Role, user_role


def crm_role_context(request):
    if not request.user.is_authenticated:
        return {
            "current_role": None,
            "is_boss": False,
            "is_senior": False,
            "task_notification_count": 0,
        }

    role = user_role(request.user)
    tasks = ManagerTask.objects.filter(is_done=False)

    if role != Role.BOSS:
        tasks = tasks.filter(Q(assignee=request.user) | Q(assignee__isnull=True))

    return {
        "current_role": role,
        "is_boss": role == Role.BOSS,
        "is_senior": role in (Role.SENIOR, Role.BOSS),
        "task_notification_count": tasks.count(),
    }