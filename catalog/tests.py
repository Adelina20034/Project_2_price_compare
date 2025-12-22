from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser
from unittest.mock import patch
from decimal import Decimal
from catalog.views import product_list
from catalog.models import Product, Category


class TestCatalogModelsUnit(TestCase):

    def test_category_str_method(self):
        """Unit-тест: Метод __str__ у категории"""
        category = Category.objects.create(name="Молочные продукты")
        self.assertEqual(str(category), "Молочные продукты")

    def test_product_str_method_pyat(self):
        """Unit-тест: __str__ если товар только в Пятерочке"""
        product = Product(name_pyat="Молоко")
        self.assertEqual(str(product), "Молоко")

    def test_product_str_method_both(self):
        """Unit-тест: __str__ приоритет (Пятерочка)"""
        product = Product(name_pyat="Молоко Пят", name_mag="Молоко Маг")
        self.assertEqual(str(product), "Молоко Пят")

    def test_cheaper_store_property(self):
        """Unit-тест: Определение где дешевле"""
        product = Product(
            name_pyat="Test", price_pyat=Decimal("100.00"),
            name_mag="Test", price_mag=Decimal("90.00")
        )
        self.assertEqual(product.cheaper_store, 'mag')
        self.assertEqual(product.cheaper_store_name, 'Магнит')

    def test_has_both_property(self):
        """Unit-тест: Свойство has_both"""
        # Только в Пятерочке
        p1 = Product(name_pyat="X", price_pyat=10)
        self.assertFalse(p1.has_both)

        # В обоих
        p2 = Product(name_pyat="X", price_pyat=10, name_mag="Y", price_mag=12)
        self.assertTrue(p2.has_both)


class TestCatalogViewsUnit(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    @patch('catalog.views.smart_product_search')
    def test_product_list_with_query(self, mock_search):
        """Unit-тест: Функция product_list вызывает поиск"""
        # Настраиваем Mock так, чтобы он возвращал структуру, которую ждет view
        # В твоем view результат парсинга сохраняется в БД,
        # поэтому mock_search может возвращать просто словарь для отчета или None,
        # если логика сохранения внутри view.
        # Допустим, view ожидает словарь results:
        mock_search.return_value = {
            'pairs': [],
            'pyat_single': [],
            'magnit_single': []
        }

        request = self.factory.get('/?q=яблоко')
        request.user = AnonymousUser()

        # Важно: если во view есть логика сохранения в БД, нам нужно замокать и её,
        # или создать Category заранее, если view пытается её создать.
        # Создадим категорию на случай, если view пытается получить её из БД
        Category.objects.get_or_create(name="Яблоко")

        # Если во view используется render, то тест пройдет.
        # Если view вызывает save_results_to_db, лучше замокать и её,
        # но для простого теста вьюхи достаточно проверить вызов поиска.

        response = product_list(request)

        self.assertEqual(response.status_code, 200)
        mock_search.assert_called_once_with('яблоко')

    @patch('catalog.views.smart_product_search')
    def test_product_list_short_query(self, mock_search):
        """Unit-тест: При коротком запросе поиск НЕ вызывается"""
        request = self.factory.get('/?q=hi')
        request.user = AnonymousUser()

        response = product_list(request)

        self.assertEqual(response.status_code, 200)
        mock_search.assert_not_called()
