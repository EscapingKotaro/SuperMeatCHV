from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AuditEvent, Role, StaffProfile


class UserManagementRegressionTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.manager = users.create_user("edit-manager", password="TestPass123!", is_staff=True)
        self.senior = users.create_user("edit-senior", password="TestPass123!", is_staff=True)
        self.boss = users.create_user("edit-boss", password="TestPass123!", is_staff=True)
        self.admin = users.create_user("edit-admin", password="TestPass123!", is_staff=True)
        self.superuser = users.create_superuser("root-admin", password="TestPass123!")
        for user, role in (
            (self.manager, Role.MANAGER),
            (self.senior, Role.SENIOR),
            (self.boss, Role.BOSS),
            (self.admin, Role.ADMIN),
        ):
            StaffProfile.objects.create(user=user, role=role)

    def payload(self, user, role):
        return {
            "first_name": "Новое",
            "last_name": "Имя",
            "username": user.username,
            "email": "updated@example.test",
            "role": role,
        }

    def test_senior_can_edit_manager(self):
        self.client.login(username="edit-senior", password="TestPass123!")
        response = self.client.post(
            reverse("user_update", args=[self.manager.pk]),
            self.payload(self.manager, Role.SENIOR),
        )
        self.assertRedirects(response, reverse("users"))
        self.manager.refresh_from_db()
        self.manager.profile.refresh_from_db()
        self.assertEqual(self.manager.first_name, "Новое")
        self.assertEqual(self.manager.profile.role, Role.SENIOR)
        self.assertTrue(AuditEvent.objects.filter(
            actor=self.senior, action="user.update", object_id=str(self.manager.pk)
        ).exists())

    def test_senior_cannot_promote_above_own_role(self):
        self.client.login(username="edit-senior", password="TestPass123!")
        response = self.client.post(
            reverse("user_update", args=[self.manager.pk]),
            self.payload(self.manager, Role.BOSS),
        )
        self.assertEqual(response.status_code, 403)
        self.manager.profile.refresh_from_db()
        self.assertEqual(self.manager.profile.role, Role.MANAGER)

    def test_boss_cannot_edit_admin(self):
        self.client.login(username="edit-boss", password="TestPass123!")
        response = self.client.post(
            reverse("user_update", args=[self.admin.pk]),
            self.payload(self.admin, Role.BOSS),
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_promote_boss_to_admin(self):
        self.client.login(username="edit-admin", password="TestPass123!")
        response = self.client.post(
            reverse("user_update", args=[self.boss.pk]),
            self.payload(self.boss, Role.ADMIN),
        )
        self.assertRedirects(response, reverse("users"))
        self.boss.profile.refresh_from_db()
        self.assertEqual(self.boss.profile.role, Role.ADMIN)

    def test_self_and_superuser_are_protected(self):
        self.client.login(username="edit-admin", password="TestPass123!")
        self.assertEqual(self.client.post(
            reverse("user_update", args=[self.admin.pk]),
            self.payload(self.admin, Role.ADMIN),
        ).status_code, 403)
        self.assertEqual(self.client.post(
            reverse("user_update", args=[self.superuser.pk]),
            self.payload(self.superuser, Role.ADMIN),
        ).status_code, 403)

    def test_missing_profile_is_created(self):
        target = get_user_model().objects.create_user(
            "missing-profile", password="TestPass123!", is_staff=True
        )
        self.client.login(username="edit-senior", password="TestPass123!")
        response = self.client.post(
            reverse("user_update", args=[target.pk]),
            self.payload(target, Role.MANAGER),
        )
        self.assertRedirects(response, reverse("users"))
        self.assertEqual(target.profile.role, Role.MANAGER)
