from django.test import SimpleTestCase
from django.urls import reverse


class UiRoutesTests(SimpleTestCase):
    def test_login_page(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Вход в систему")

    def test_all_prototype_pages_render(self):
        expected = {
            "attendance": "Табель",
            "statistics": "Статистика",
            "payments": "Продления",
            "expenses": "Расходы",
            "competitions": "Соревнования",
            "notifications": "Уведомления",
            "boss": "Для руководителя",
            "users": "Пользователи",
            "profile": "Мой профиль",
        }
        for page, title in expected.items():
            with self.subTest(page=page):
                response = self.client.get(reverse("app_page", args=[page]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, title)
