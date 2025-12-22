from django.urls import path
from . import views

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('check-status/', views.check_parsing_status, name='check_status'),
    path('cart/', views.cart_view, name='cart'),
    path('cart/add/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:item_id>/',
         views.remove_from_cart, name='remove_from_cart'),
    path('cart/update/<int:item_id>/',
         views.update_quantity, name='update_quantity'),
    path('cart/clear/', views.clear_cart, name='clear_cart'),
]
