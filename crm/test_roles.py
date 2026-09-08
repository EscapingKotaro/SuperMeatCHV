from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Role, StaffProfile


class RoleHierarchyRegressionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.manager = user_model.objects.create_user(
            "role-manager", password="TestPass123!", is_staff=True
        )
        self.senior = user_model.objects.create_user(
            "role-senior", password="TestPass123!", is_staff=True
        )
        self.boss = user_model.objects.create_user(
            "role-boss", password="TestPass123!", is_staff=True
        )
        self.admin = user_model.objects.create_user(
            "role-admin", password="TestPass123!", is_staff=True
        )
        StaffProfile.objects.create(user=self.manager, role=Role.MANAGER)
        StaffProfile.objects.create(user=self.senior, role=Role.SENIOR)
        StaffProfile.objects.create(user=self.boss, role=Role.BOSS)
        StaffProfile.objects.create(user=self.admin, role=Role.ADMIN)

    def test_admin_inherits_boss_and_senior_pages(self):
        self.client.login(username="role-admin", password="TestPass123!")
        for name in ("boss", "users", "salaries", "backup_export"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_senior_and_boss_cannot_create_admin(self):
        for username in ("role-senior", "role-boss"):
            with self.subTest(username=username):
                self.client.login(username=username, password="TestPass123!")
                candidate = f"new-admin-{username}"
                response = self.client.post(
                    reverse("users"),
                    {
                        "action": "create",
                        "username": candidate,
                        "role": Role.ADMIN,
                        "password1": "StrongPass123!",
                        "password2": "StrongPass123!",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertFalse(
                    get_user_model().objects.filter(username=candidate).exists()
                )
                self.client.logout()

    def test_admin_can_create_admin(self):
        self.client.login(username="role-admin", password="TestPass123!")
        response = self.client.post(
            reverse("users"),
            {
                "action": "create",
                "username": "second-role-admin",
                "role": Role.ADMIN,
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertRedirects(response, reverse("users"))
        created = get_user_model().objects.get(username="second-role-admin")
        self.assertEqual(created.profile.role, Role.ADMIN)

    def test_senior_cannot_disable_admin(self):
        self.client.login(username="role-senior", password="TestPass123!")
        response = self.client.post(
            reverse("users"),
            {"action": "toggle", "user_id": self.admin.pk},
        )
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_can_disable_boss(self):
        self.client.login(username="role-admin", password="TestPass123!")
        response = self.client.post(
            reverse("users"),
            {"action": "toggle", "user_id": self.boss.pk},
        )
        self.assertRedirects(response, reverse("users"))
        self.boss.refresh_from_db()
        self.assertFalse(self.boss.is_active)
