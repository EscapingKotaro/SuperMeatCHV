"""Small workflow actions shared by the journal and athlete card."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django import forms
from django.db.models import Q
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.views.decorators.cache import never_cache

from .models import Attendance, AttendanceReason, Child, Group, LessonTrainerAssignment
from .views import log_action, effective_class_dates, page_context


class ReasonEditForm(forms.ModelForm):
    class Meta:
        model = AttendanceReason
        fields = ("date_from", "date_to", "comment")
        widgets = {
            "date_from": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "field"}),
            "date_to": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "field"}),
            "comment": forms.Textarea(attrs={"class": "field", "rows": 3}),
        }

    def clean(self):
        data = super().clean()
        start, end = data.get("date_from"), data.get("date_to")
        if start and end:
            if end < start:
                self.add_error("date_to", "Дата окончания раньше начала")
            elif (end - start).days > 365:
                self.add_error("date_to", "Период не может быть больше года")
        return data


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_reason(request, pk):
    reason = get_object_or_404(AttendanceReason, pk=pk)
    child = Child.objects.select_for_update().get(pk=reason.child_id)
    reason = AttendanceReason.objects.select_for_update().get(pk=pk)
    old_period = f"{reason.date_from:%d.%m.%Y}–{reason.date_to:%d.%m.%Y}"
    marks = list(reason.attendances.select_for_update().all())
    group_ids = {mark.group_snapshot_id or child.group_id for mark in marks}
    group = Group.objects.select_related("trainer").filter(pk=next(iter(group_ids))).first() if len(group_ids) == 1 else None
    form = ReasonEditForm(request.POST if request.method == "POST" else None, instance=reason)
    if request.method == "POST" and form.is_valid():
        dates = []
        if group is None:
            form.add_error(None, "У причины нет действующих отметок одной группы. Оформите новый период через табель; история и документ сохранены.")
        elif any(mark.status not in ("excused", "sick", "frozen") or mark.charge_amount != 0 for mark in marks):
            form.add_error(None, "В отметках причины есть посещения или начисления. Сначала проверьте их в табеле — редактирование ничего не изменило.")
        else:
            dates = effective_class_dates(group, form.cleaned_data["date_from"], form.cleaned_data["date_to"])
            if not dates:
                form.add_error(None, "В выбранном периоде нет занятий группы")
            conflicts = child.attendances.filter(date__in=dates).filter(
                Q(group_snapshot=group) | Q(group_snapshot__isnull=True, child__group=group)
            ).exclude(reason=reason)
            if conflicts.exists():
                days = ", ".join(day.strftime("%d.%m.%Y") for day in sorted(set(conflicts.values_list("date", flat=True))))
                form.add_error(None, f"На эти даты уже есть другие отметки: {days}. Уточните период или исправьте их в табеле.")
        if not form.errors:
            dates = set(dates)
            reason.attendances.exclude(date__in=dates).delete()
            reason.attendances.update(comment=form.cleaned_data["comment"][:255])
            existing_dates = {mark.date for mark in marks}
            assignments = {item.date: item.trainer for item in LessonTrainerAssignment.objects.filter(
                child=child, group=group, date__in=dates,
            ).select_related("trainer")}
            for day in sorted(dates - existing_dates):
                Attendance.objects.create(child=child, group_snapshot=group,
                    trainer_snapshot=assignments.get(day, group.trainer), salary_rate_snapshot=group.salary_rate,
                    date=day, status=reason.kind, reason=reason, comment=form.cleaned_data["comment"][:255])
            form.save()
            log_action(request, "attendance.reason.edit", reason,
                       f"Период причины: {old_period} → {reason.date_from:%d.%m.%Y}–{reason.date_to:%d.%m.%Y}; группа {group}; документ сохранён")
            messages.success(request, "Причина обновлена. Документ сохранён, отметки периода пересчитаны.")
            return redirect(reverse("child_card", args=[child.pk]) + "#absence-reasons")
    return render(request, "crm/reason_edit.html", page_context(request, "attendance", form=form, reason=reason, child=child, group=group))


@login_required
@require_GET
@never_cache
def payment_subscriptions(request):
    try:
        child_id = int(request.GET.get("child_id", ""))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Выберите спортсмена"}, status=400)
    child = get_object_or_404(Child.objects.select_related("group"), pk=child_id)
    subscriptions = child.subscriptions.filter(cancelled_at__isnull=True).select_related("group").order_by("-is_active", "-end_date", "-pk")
    return JsonResponse({"child_id": child.pk, "subscriptions": [
        {"id": sub.pk, "label": f"{sub.group or child.group or 'Без группы'} · {sub.start_date:%d.%m.%Y}–{sub.end_date:%d.%m.%Y}"}
        for sub in subscriptions
    ]})


@login_required
def reason_document(request, pk):
    reason = get_object_or_404(AttendanceReason, pk=pk)
    if not reason.document:
        raise Http404("Документ не прикреплён")
    try:
        return FileResponse(reason.document.open("rb"), as_attachment=True)
    except FileNotFoundError:
        raise Http404("Файл не найден")


@login_required
@require_POST
@transaction.atomic
def cancel_reason(request, pk):
    reason = get_object_or_404(AttendanceReason, pk=pk)
    Child.objects.select_for_update().get(pk=reason.child_id)
    # Preserve the reason and its document as history; never remove visits or debts.
    marks = reason.attendances.filter(
        status__in=(Attendance.Status.EXCUSED, Attendance.Status.SICK, Attendance.Status.FROZEN),
        charge_amount=0,
    )
    count = marks.count()
    marks.delete()
    log_action(request, "attendance.reason.cancel", reason,
               f"Отменены отметки причины {reason}: {count}. Документ сохранён в истории.")
    messages.success(request, f"Отменено отметок: {count}. Можно оформить новый период в табеле.")
    return redirect(reverse("child_card", args=[reason.child_id]) + "#absence-reasons")
