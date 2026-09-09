import mimetypes

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import Child


DOCUMENTS = {
    "certificate": {
        "file_field": "certificate",
        "expiry_field": "certificate_valid_until",
        "label": "Справка",
    },
    "insurance": {
        "file_field": "insurance",
        "expiry_field": "insurance_valid_until",
        "label": "Страховка",
    },
    "permission": {
        "file_field": "permission",
        "expiry_field": "permission_valid_until",
        "label": "Разрешение",
    },
}


class ChildDocumentUploadForm(forms.Form):
    document = forms.FileField(required=True)
    valid_until = forms.DateField(required=True, input_formats=["%Y-%m-%d"])
    note = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, document_kind="certificate", **kwargs):
        self.document_kind = document_kind
        super().__init__(*args, **kwargs)

    def clean_document(self):
        uploaded = self.cleaned_data["document"]
        if uploaded.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Размер документа не должен превышать 10 МБ")
        if (
            self.document_kind == "certificate"
            and uploaded.content_type
            and not uploaded.content_type.startswith("image/")
        ):
            raise forms.ValidationError("Справка должна быть изображением")
        return uploaded


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
    expiry_field = config["expiry_field"]
    label = config["label"]

    if action == "upload":
        form = ChildDocumentUploadForm(
            request.POST,
            request.FILES,
            document_kind=kind,
        )
        if not form.is_valid():
            messages.error(
                request,
                f"Не удалось сохранить {label.lower()}. Проверьте файл и срок действия.",
            )
            return redirect("child_card", child_id=child.pk)

        current_file = getattr(child, file_field)
        old_name = current_file.name if current_file else ""
        old_storage = current_file.storage if old_name else None

        setattr(child, file_field, form.cleaned_data["document"])
        setattr(child, expiry_field, form.cleaned_data["valid_until"])
        update_fields = [file_field, expiry_field]

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
                f"действует до {form.cleaned_data['valid_until']:%d.%m.%Y}"
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
            setattr(child, expiry_field, None)
            update_fields = [file_field, expiry_field]

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
    return FileResponse(
        file_field.open("rb"),
        content_type=content_type,
    )
