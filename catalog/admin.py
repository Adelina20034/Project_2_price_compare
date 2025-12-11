from django.contrib import admin
from .models import Store, Product, Price  # Импортируем наши модели

# Регистрация Магазина
@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'url')  # Что показывать в списке

# Регистрация Товара
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category')
    search_fields = ('name',)       # Добавляем строку поиска

# Регистрация Цены
@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    list_display = ('product', 'store', 'price', 'date')
    list_filter = ('store', 'date') # Фильтры справа
