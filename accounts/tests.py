import pytest
from django.urls import reverse
from django.contrib.auth.models import User

@pytest.mark.django_db
class TestAuthSystem:

    def test_register_page_opens(self, client):
        """Проверяет, что страница регистрации доступна и открывается (код 200)"""
        url = reverse('register')
        response = client.get(url)
        
        assert response.status_code == 200
        assert 'form' in response.context

    def test_registration_full_flow(self, client):
        """Проверяет успешную регистрацию: создание пользователя и автоматический вход"""
        url = reverse('register')
        data = {
            'username': 'new_test_user',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        
        response = client.post(url, data)
        
        # Должен быть редирект после успеха
        assert response.status_code == 302
        # Пользователь должен появиться в БД
        assert User.objects.filter(username='new_test_user').exists()
        # Пользователь должен быть авторизован (сессия создана)
        assert '_auth_user_id' in client.session

    def test_login_success(self, client):
        """Проверяет успешный вход с правильным паролем"""
        User.objects.create_user(username='login_user', password='password123')
        
        url = reverse('login')
        data = {'username': 'login_user', 'password': 'password123'}
        
        response = client.post(url, data)
        
        assert response.status_code == 302
        assert '_auth_user_id' in client.session

    def test_login_fail_wrong_password(self, client):
        """Проверяет, что с неверным паролем войти нельзя"""
        User.objects.create_user(username='user', password='correct_password')
        
        url = reverse('login')
        data = {'username': 'user', 'password': 'WRONG_password'}
        
        response = client.post(url, data)
        
        # Редиректа нет (остаемся на странице входа), сессия не создана
        assert response.status_code == 200
        assert '_auth_user_id' not in client.session

    def test_logout(self, client):
        """Проверяет выход из системы"""
        user = User.objects.create_user(username='logout_test', password='123')
        client.force_login(user)
        
        url = reverse('logout')
        client.post(url)
        
        # Сессия должна быть очищена
        assert '_auth_user_id' not in client.session
