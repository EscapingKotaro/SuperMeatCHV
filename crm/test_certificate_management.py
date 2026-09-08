import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import ChildForm
from .models import Child


GIF_1X1 = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


class CertificateManagementTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.user = get_user_model().objects.create_user(
            "certificate-admin", password="TestPass123!", is_staff=True
        )
        self.client.login(username="certificate-admin", password="TestPass123!")
        self.child = Child.objects.create(
            last_name="Петрова", first_name="Анна", birth_year=2016
        )

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def image(self, name):
        return SimpleUploadedFile(name, GIF_1X1, content_type="image/gif")

    def upload(self, name, note=""):
        return self.client.post(
            reverse("child_certificate_manage", args=[self.child.pk]),
            {"action": "upload", "certificate": self.image(name), "certificate_note": note},
        )

    def test_upload_is_visible_from_child_card(self):
        response = self.upload("certificate.gif", "Действительна до июня")
        self.assertRedirects(response, reverse("child_card", args=[self.child.pk]))

        self.child.refresh_from_db()
        self.assertTrue(self.child.certificate)
        self.assertTrue(self.child.certificate_ok)
        self.assertEqual(self.child.certificate_note, "Действительна до июня")
        self.assertTrue(os.path.exists(self.child.certificate.path))

        photo = self.client.get(reverse("child_certificate", args=[self.child.pk]))
        self.assertEqual(photo.status_code, 200)
        self.assertEqual(photo["Content-Type"], "image/gif")

        card = self.client.get(reverse("child_card", args=[self.child.pk]))
        self.assertContains(card, 'enctype="multipart/form-data"')
        self.assertContains(card, "Открыть фото справки")
        self.assertContains(card, "Удалить фото")
        self.assertNotContains(card, "toggle_certificate")
        self.assertNotContains(card, "нажми, чтобы переключить")

    def test_replacement_deletes_old_file_and_delete_removes_new_file(self):
        self.upload("first.gif")
        self.child.refresh_from_db()
        old_path = self.child.certificate.path

        self.upload("second.gif")
        self.child.refresh_from_db()
        new_path = self.child.certificate.path

        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(new_path))

        response = self.client.post(
            reverse("child_certificate_manage", args=[self.child.pk]),
            {"action": "delete"},
        )
        self.assertRedirects(response, reverse("child_card", args=[self.child.pk]))

        self.child.refresh_from_db()
        self.assertFalse(self.child.certificate)
        self.assertFalse(self.child.certificate_ok)
        self.assertFalse(os.path.exists(new_path))

    def test_child_form_does_not_expose_manual_certificate_switch(self):
        form = ChildForm()
        self.assertNotIn("certificate_ok", form.fields)

    def test_invalid_image_does_not_replace_existing_photo(self):
        self.upload("valid.gif")
        self.child.refresh_from_db()
        old_name = self.child.certificate.name
        old_path = self.child.certificate.path

        response = self.client.post(
            reverse("child_certificate_manage", args=[self.child.pk]),
            {
                "action": "upload",
                "certificate": SimpleUploadedFile(
                    "bad.txt", b"not an image", content_type="text/plain"
                ),
                "certificate_note": "Не сохранять",
            },
        )
        self.assertRedirects(response, reverse("child_card", args=[self.child.pk]))

        self.child.refresh_from_db()
        self.assertEqual(self.child.certificate.name, old_name)
        self.assertTrue(os.path.exists(old_path))
        self.assertNotEqual(self.child.certificate_note, "Не сохранять")
