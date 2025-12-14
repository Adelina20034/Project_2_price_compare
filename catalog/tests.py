import pytest
from django.urls import reverse
from catalog.models import Product, Store, Price
from decimal import Decimal
from unittest.mock import patch # Для подмены реального парсинга

# --- ТЕСТЫ МОДЕЛЕЙ (База данных) ---

@pytest.mark.django_db
class TestCatalogModels:
    
    def test_create_store(self):
        """Можно создать магазин"""
        store = Store.objects.create(name="Пятёрочка", url="https://5ka.ru")
        assert store.name == "Пятёрочка"
        assert str(store) == "Пятёрочка" # Проверка метода __str__

    def test_create_product(self):
        """Можно создать товар"""
        product = Product.objects.create(name="Молоко")
        assert product.name == "Молоко"
        assert str(product) == "Молоко"

    def test_create_price(self):
        """Можно создать цену, связанную с товаром и магазином"""
        store = Store.objects.create(name="Магнит")
        product = Product.objects.create(name="Хлеб")
        
        price_obj = Price.objects.create(
            product=product, 
            store=store, 
            price=Decimal("50.00")
        )
        
        assert price_obj.price == Decimal("50.00")
        assert price_obj.product == product


# --- ТЕСТЫ ПРЕДСТАВЛЕНИЙ (Страницы) ---

@pytest.mark.django_db
class TestCatalogViews:
    
    def test_home_page_opens(self, client):
        """Главная страница открывается (без поиска)"""
        url = reverse('product_list')
        response = client.get(url)
        assert response.status_code == 200
        # Проверяем, что контекст пустой (поиска не было)
        assert response.context['query'] == ''
        assert response.context['total_products'] == 0

    def test_search_short_query(self, client):
        """Короткий запрос (< 3 символов) не запускает поиск"""
        url = reverse('product_list')
        response = client.get(url, {'q': 'hi'}) # q=hi
        
        assert response.status_code == 200
        # Поиск не запускался
        assert response.context['total_products'] == 0

    # ТЕСТ: Имитация поиска
    # Мы используем @patch, чтобы НЕ запускать реальный Selenium (это долго),
    # а подсунуть функции smart_product_search готовый ответ.
    @patch('catalog.views.smart_product_search')
    def test_search_execution(self, mock_search, client):
        """Поиск запускается и отображает результаты"""
        
        # 1. Готовим фейковый ответ от парсера
        mock_search.return_value = {
            'pairs': [
                {
                    'similarity': 90,
                    'pyat': {'name': 'Яблоко П', 'price': 100, 'store': 'P'},
                    'magnit': {'name': 'Яблоко М', 'price': 90, 'store': 'M'},
                    'price_diff': 10,
                    'price_diff_percent': 10,
                    'cheaper': 'Магнит'
                }
            ],
            'pyat_single': [{'name': 'Груша', 'price': 200}],
            'magnit_single': []
        }
        
        # 2. Делаем запрос с длинным словом
        url = reverse('product_list')
        response = client.get(url, {'q': 'яблоко'})
        
        # 3. Проверяем
        assert response.status_code == 200
        
        # Функция поиска должна была вызваться 1 раз с аргументом 'яблоко'
        mock_search.assert_called_once_with('яблоко')
        
        # В контексте должны появиться наши фейковые данные
        assert response.context['pairs_count'] == 1
        assert response.context['pyat_single_count'] == 1
        assert response.context['total_products'] == 3 # 1 пара (2 товара) + 1 одиночный
