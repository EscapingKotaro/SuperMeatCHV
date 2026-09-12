"""Local list destinations: retain filters, never retain editor state."""
from django.urls import reverse


def list_url(request, name, **overrides):
    query = request.GET.copy()
    for key in list(query):
        if key in {"edit", "create", "next"} or key.startswith(("edit_", "new_")):
            query.pop(key)
    for key, value in overrides.items():
        query[key] = str(value)
    encoded = query.urlencode()
    return reverse(name) + ("?" + encoded if encoded else "")


def current_list_url(request):
    name = request.resolver_match.url_name if request.resolver_match else ""
    if name.startswith("trainer_"):
        name = "trainer_list"
    elif name.startswith("group_"):
        name = "group_list"
    if name in {"trainer_list", "group_list", "applications", "newcomers", "calendar", "competitions", "camps", "payments"}:
        return list_url(request, name)
    return ""
