from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser
from unittest.mock import patch
from catalog.views import product_list
from catalog.models import Store, Product

class TestCatalogModelsUnit(TestCase):
    
    def test_store_str_method(self):
        """Unit-тест: Метод __str__ у магазина"""
        store = Store(name="Пятёрочка")
        self.assertEqual(str(store), "Пятёрочка")

    def test_product_str_method(self):
        """Unit-тест: Метод __str__ у товара"""
        product = Product(name="Молоко")
        self.assertEqual(str(product), "Молоко")


class TestCatalogViewsUnit(TestCase):
    
    def setUp(self):
        self.factory = RequestFactory()

    @patch('catalog.views.smart_product_search')
    def test_product_list_with_query(self, mock_search):
        """Unit-тест: Функция product_list вызывает поиск"""
        # Настраиваем Mock
        mock_search.return_value = {
            'pairs': [{'some': 'data'}],
            'pyat_single': [],
            'magnit_single': []
        }
        
        request = self.factory.get('/?q=яблоко')
        request.user = AnonymousUser()
        
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
