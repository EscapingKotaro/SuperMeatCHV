from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Role, StaffProfile, has_min_role, role_rank, user_rank, user_role
from .views import can_manage_staff_account, log_action, page_context
from .forms import StaffCreateForm


class StaffEditForm(forms.ModelForm):
    role = forms.ChoiceField(label="Роль", choices=Role.choices)

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "username", "email", "role")

    def __init__(self, *args, actor, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        actor_rank = user_rank(actor)
        self.fields["role"].choices = [
            (value, label)
            for value, label in Role.choices
            if role_rank(value) <= actor_rank
        ]
        self.fields["role"].initial = user_role(self.instance)

    def clean_role(self):
        role = Role(self.cleaned_data["role"])
        if role_rank(role) > user_rank(self.actor):
            raise forms.ValidationError("Нельзя назначить роль выше собственной")
        return role

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            StaffProfile.objects.update_or_create(
                user=user,
                defaults={"role": self.cleaned_data["role"]},
            )
        return user


@login_required
@require_POST
def staff_update_view(request, user_id):
    if not has_min_role(request.user, 1):
        return HttpResponseForbidden("Недостаточно прав")

    user = get_object_or_404(get_user_model(), pk=user_id, is_staff=True)
    if not can_manage_staff_account(request.user, user):
        return HttpResponseForbidden("Недостаточно прав для управления этим аккаунтом")

    try:
        requested_role = Role(request.POST.get("role", ""))
    except ValueError:
        messages.error(request, "Неизвестная роль пользователя")
        return redirect("users")

    if role_rank(requested_role) > user_rank(request.user):
        return HttpResponseForbidden("Нельзя назначить роль выше собственной")

    form = StaffEditForm(request.POST, instance=user, actor=request.user)
    if not form.is_valid():
        messages.error(request, "Проверьте данные пользователя")
        return render(request, "crm/users.html", page_context(
            request, "users", staff_edit_form=form, staff_edit_id=user.pk,
            form=StaffCreateForm(actor=request.user),
            users=get_user_model().objects.select_related("profile").filter(is_staff=True).order_by("-is_active", "last_name", "username"),
        ))

    old_role = user_role(user)
    old_username = user.username
    user = form.save()
    log_action(
        request,
        "user.update",
        user,
        f"Изменён пользователь {old_username}: роль {old_role} → {user_role(user)}",
    )
    messages.success(request, "Пользователь обновлён")
    return redirect("users")
