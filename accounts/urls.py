from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Стандартный вход Django
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    # Стандартный выход
    path('logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),
    # Наша кастомная регистрация
    path('register/', views.register, name='register'),
]
