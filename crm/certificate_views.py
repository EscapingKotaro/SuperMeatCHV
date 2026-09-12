import calendar
import mimetypes

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Child


DOCUMENTS = {
    "certificate": {
        "file_field": "certificate",
        "start_field": "certificate_valid_from",
        "expiry_field": "certificate_valid_until",
        "label": "Справка",
    },
    "insurance": {
        "file_field": "insurance",
        "start_field": "insurance_valid_from",
        "expiry_field": "insurance_valid_until",
        "label": "Страховка",
    },
    "permission": {
        "file_field": "permission",
        "start_field": "permission_valid_from",
        "expiry_field": "permission_valid_until",
        "label": "Разрешение",
    },
}


def _add_calendar_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


class ChildDocumentUploadForm(forms.Form):
    document = forms.FileField(label="Файл", required=True)
    valid_from = forms.DateField(label="Действует с", required=False, input_formats=["%Y-%m-%d"], widget=forms.DateInput(attrs={"type": "date"}))
    valid_until = forms.DateField(label="Действует до", required=False, input_formats=["%Y-%m-%d"], widget=forms.DateInput(attrs={"type": "date"}))
    note = forms.CharField(label="Комментарий к справке", max_length=255, required=False)

    def __init__(self, *args, document_kind="certificate", has_document=False, **kwargs):
        self.document_kind = document_kind
        super().__init__(*args, **kwargs)
        self.fields["document"].required = not has_document
        for field in self.fields.values():
            field.widget.attrs["class"] = "field"

    def clean_document(self):
        uploaded = self.cleaned_data["document"]
        if uploaded is None:
            return None
        if uploaded.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Размер документа не должен превышать 10 МБ")
        if (
            self.document_kind == "certificate"
            and uploaded.content_type
            and not uploaded.content_type.startswith("image/")
        ):
            raise forms.ValidationError("Справка должна быть изображением")
        return uploaded

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get("valid_from") or timezone.localdate()
        valid_until = cleaned_data.get("valid_until")

        if valid_until is None:
            valid_until = _add_calendar_months(valid_from, 6)
        elif valid_until < valid_from:
            self.add_error(
                "valid_until",
                "Дата окончания не может быть раньше даты начала",
            )

        cleaned_data["valid_from"] = valid_from
        cleaned_data["valid_until"] = valid_until
        return cleaned_data


def _document_config(kind):
    return DOCUMENTS.get(kind)


@login_required
@require_POST
def child_certificate_manage_view(request, child_id):
    child = get_object_or_404(Child, pk=child_id)
    action = request.POST.get("action")
    kind = request.POST.get("kind", "certificate")
    config = _document_config(kind)
    if config is None:
        return HttpResponseBadRequest("Неизвестный тип документа")

    file_field = config["file_field"]
    start_field = config["start_field"]
    expiry_field = config["expiry_field"]
    label = config["label"]

    if action == "upload":
        form = ChildDocumentUploadForm(
            request.POST,
            request.FILES,
            document_kind=kind,
            has_document=bool(getattr(child, file_field)),
        )
        if not form.is_valid():
            messages.error(
                request,
                f"Не удалось сохранить {label.lower()}: " + "; ".join(
                    str(error) for errors in form.errors.values() for error in errors
                ),
            )
            return render(request, "crm/document_retry.html", {
                "form": form, "child": child, "document_label": label,
                "document_kind": kind, "has_document": bool(getattr(child, file_field)),
                "title": "Исправить документ", "page": "clients",
            })

        current_file = getattr(child, file_field)
        old_name = current_file.name if current_file else ""
        old_storage = current_file.storage if old_name else None

        if form.cleaned_data["document"] is not None:
            setattr(child, file_field, form.cleaned_data["document"])
        setattr(child, start_field, form.cleaned_data["valid_from"])
        setattr(child, expiry_field, form.cleaned_data["valid_until"])
        update_fields = [file_field, start_field, expiry_field]

        if kind == "certificate":
            child.certificate_note = form.cleaned_data["note"].strip()
            child.certificate_ok = True
            update_fields.extend(["certificate_note", "certificate_ok"])

        child.save(update_fields=update_fields)

        saved_file = getattr(child, file_field)
        if old_storage and old_name and old_name != saved_file.name:
            old_storage.delete(old_name)

        from .views import log_action
        action_name = (
            "child.certificate.upload"
            if kind == "certificate"
            else "child.document.upload"
        )
        log_action(
            request,
            action_name,
            child,
            (
                f"{label} для {child}: "
                f"{form.cleaned_data['valid_from']:%d.%m.%Y}–"
                f"{form.cleaned_data['valid_until']:%d.%m.%Y}"
            ),
        )
        messages.success(request, f"{label} сохранён")
        return redirect("child_card", child_id=child.pk)

    if action == "delete":
        current_file = getattr(child, file_field)
        if current_file:
            file_name = current_file.name
            storage = current_file.storage
            setattr(child, file_field, "")
            setattr(child, start_field, None)
            setattr(child, expiry_field, None)
            update_fields = [file_field, start_field, expiry_field]

            if kind == "certificate":
                child.certificate_ok = False
                update_fields.append("certificate_ok")

            child.save(update_fields=update_fields)
            storage.delete(file_name)

            from .views import log_action
            action_name = (
                "child.certificate.delete"
                if kind == "certificate"
                else "child.document.delete"
            )
            log_action(
                request,
                action_name,
                child,
                f"{label} для {child} удалён",
            )

        messages.success(request, f"{label} удалён")
        return redirect("child_card", child_id=child.pk)

    return HttpResponseBadRequest("Неизвестное действие с документом")


@login_required
def child_document_view(request, child_id, kind):
    child = get_object_or_404(Child, pk=child_id)
    config = _document_config(kind)
    if config is None:
        raise Http404("Неизвестный тип документа")

    file_field = getattr(child, config["file_field"])
    if not file_field:
        raise Http404("Документ не прикреплён")

    content_type = (
        mimetypes.guess_type(file_field.name)[0]
        or "application/octet-stream"
    )
    try:
        return FileResponse(file_field.open("rb"), content_type=content_type)
    except FileNotFoundError:
        messages.error(request, "Файл документа отсутствует в хранилище. Загрузите его повторно в карточке спортсмена.")
        return redirect("child_card", child_id=child.pk)
