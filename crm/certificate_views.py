from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import Child


class CertificateUploadForm(forms.Form):
    certificate = forms.ImageField(required=True)
    certificate_note = forms.CharField(max_length=255, required=False)

    def clean_certificate(self):
        image = self.cleaned_data["certificate"]
        if image.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Размер изображения не должен превышать 10 МБ")
        return image


@login_required
@require_POST
def child_certificate_manage_view(request, child_id):
    child = get_object_or_404(Child, pk=child_id)
    action = request.POST.get("action")

    if action == "upload":
        form = CertificateUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Не удалось загрузить фото справки. Проверьте формат и размер файла.")
            return redirect("child_card", child_id=child.pk)

        old_name = child.certificate.name if child.certificate else ""
        old_storage = child.certificate.storage if old_name else None

        child.certificate = form.cleaned_data["certificate"]
        child.certificate_note = form.cleaned_data["certificate_note"].strip()
        child.certificate_ok = True
        child.save(update_fields=["certificate", "certificate_note", "certificate_ok"])

        if old_storage and old_name and old_name != child.certificate.name:
            old_storage.delete(old_name)

        from .views import log_action
        log_action(request, "child.certificate.upload", child, f"Загружено фото справки для {child}")
        messages.success(request, "Фото справки сохранено")
        return redirect("child_card", child_id=child.pk)

    if action == "delete":
        if child.certificate:
            file_name = child.certificate.name
            storage = child.certificate.storage
            child.certificate = ""
            child.save(update_fields=["certificate"])
            storage.delete(file_name)

            from .views import log_action
            log_action(request, "child.certificate.delete", child, f"Удалено фото справки для {child}")

        messages.success(request, "Фото справки удалено")
        return redirect("child_card", child_id=child.pk)

    return HttpResponseBadRequest("Неизвестное действие со справкой")
