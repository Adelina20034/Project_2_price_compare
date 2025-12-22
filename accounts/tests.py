from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser
from unittest.mock import patch, MagicMock
from accounts.views import register  # Импортируем view напрямую


class TestAccountsUnit(TestCase):

    def setUp(self):
        """Создаем фабрику запросов перед каждым тестом"""
        self.factory = RequestFactory()

    def test_register_get_request(self):
        """Unit-тест: GET запрос отдает форму (код 200)"""
        # Создаем фейковый GET запрос
        request = self.factory.get('/register/')
        request.user = AnonymousUser()

        # Вызываем view напрямую
        response = register(request)

        # Проверяем статус ответа
        self.assertEqual(response.status_code, 200)

    @patch('accounts.views.UserCreationForm')  # Подменяем Форму
    @patch('accounts.views.login')            # Подменяем функцию входа
    def test_register_post_success(self, mock_login, MockForm):
        """Unit-тест: Успешная регистрация (без записи в БД)"""
        # 1. Настраиваем Моки (говорим форме: "ты валидна")
        mock_form_instance = MockForm.return_value
        mock_form_instance.is_valid.return_value = True

        # Создаем фейкового юзера, который якобы создался
        mock_user = MagicMock()
        mock_form_instance.save.return_value = mock_user

        # 2. Создаем фейковый POST запрос с данными
        request = self.factory.post('/register/', {
            'username': 'test_user',
            'password': 'password123'
        })
        request.user = AnonymousUser()

        # Замокаем messages, чтобы view не упала при попытке добавить сообщение
        with patch('django.contrib.messages.success') as _:
            response = register(request)

        # 3. Проверки (Assertions)

        # Проверяем, что был редирект (код 302)
        self.assertEqual(response.status_code, 302)
        # Проверяем, куда перенаправили (на главную)
        self.assertEqual(response.url, '/')

        # Проверяем, что логика сработала:
        mock_form_instance.save.assert_called_once()  # Метод save() у формы вызвался
        mock_login.assert_called_once_with(
            request, mock_user)  # Функция login() вызвалась
