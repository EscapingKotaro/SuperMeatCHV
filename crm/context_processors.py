from .models import Role, user_role


def crm_role_context(request):
    if not request.user.is_authenticated:
        return {
            "current_role": None,
            "is_boss": False,
            "is_senior": False,
        }

    role = user_role(request.user)

    return {
        "current_role": role,
        "is_boss": role == Role.BOSS,
        "is_senior": role in (Role.SENIOR, Role.BOSS),
    }