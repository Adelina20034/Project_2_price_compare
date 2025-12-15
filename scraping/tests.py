import unittest
from decimal import Decimal
from unittest.mock import MagicMock
from bs4 import BeautifulSoup
from scraping.scrapers import PyaterochkaParser, MagnitParser, BaseParser, smart_compare_products

class TestPyaterochkaParser(unittest.TestCase):
    
    def setUp(self):
        """Запускается перед каждым тестом"""
        # ИСПРАВЛЕНИЕ 1: Убираем mock_store, передаем только driver
        self.mock_driver = MagicMock()
        self.parser = PyaterochkaParser(self.mock_driver)

    def test_extract_price_valid(self):
        """Проверка извлечения цены (обычный кейс)"""
        html = """
        <div class="price-container">
            <span>200</span><span>00</span>
            <span>150</span><span>50</span>
        </div>
        """
        elem = BeautifulSoup(html, 'html.parser')
        price = self.parser.extract_product_price(elem)
        self.assertEqual(price, Decimal('150.50'))

    def test_extract_price_single_pair(self):
        """Проверка, если только одна цена"""
        html = "<div><span>99</span><span>90</span></div>"
        elem = BeautifulSoup(html, 'html.parser')
        price = self.parser.extract_product_price(elem)
        # В твоем коде парсера логика: если 2 цифры - это цена.
        # Если 4 - берем вторую пару.
        self.assertEqual(price, Decimal('99.90'))

    def test_extract_name(self):
        """Проверка извлечения названия"""
        html = """
        <div class="card">
            <p>4.5</p>
            <p>Хлеб</p>
            <p>Хлеб Бородинский нарезка 400г</p>
        </div>
        """
        elem = BeautifulSoup(html, 'html.parser')
        name = self.parser.extract_product_name(elem)
        self.assertEqual(name, "Хлеб Бородинский нарезка 400г")


class TestMagnitParser(unittest.TestCase):
    
    def setUp(self):
        # ИСПРАВЛЕНИЕ 1: Убираем mock_store
        self.mock_driver = MagicMock()
        self.parser = MagnitParser(self.mock_driver)

    def test_extract_price_magnit(self):
        """Проверка парсинга цены Магнита"""
        html = """
        <div class="product">
            <span class="unit-catalog-product-preview-prices__regular">
                129,99 ₽
            </span>
        </div>
        """
        elem = BeautifulSoup(html, 'html.parser')
        price = self.parser.extract_product_price(elem)
        self.assertEqual(price, Decimal('129.99'))

    def test_extract_name_magnit(self):
        html = """
        <div>
            <div class="unit-catalog-product-preview-title">
                Молоко Простоквашино 2.5%
            </div>
        </div>
        """
        elem = BeautifulSoup(html, 'html.parser')
        name = self.parser.extract_product_name(elem)
        self.assertEqual(name, "Молоко Простоквашино 2.5%")


class TestSmartCompare(unittest.TestCase):
    
    def test_smart_compare_logic(self):
        """Проверка алгоритма сопоставления товаров"""
        pyat_data = [
            {'name': 'Яблоки Голден 1кг', 'price': Decimal('100.00'), 'store': 'Pyat'},
            {'name': 'Хлеб Ржаной', 'price': Decimal('50.00'), 'store': 'Pyat'},
        ]
        magnit_data = [
            {'name': 'Яблоки сезонные Голден фасованные 1кг', 'price': Decimal('90.00'), 'store': 'Mag'},
            {'name': 'Масло Сливочное', 'price': Decimal('200.00'), 'store': 'Mag'},
        ]
        
        result = smart_compare_products(pyat_data, magnit_data, similarity_threshold=50)
        
        self.assertEqual(len(result['pairs']), 1)
        
        pair = result['pairs'][0]
        self.assertIn('Яблоки', pair['pyat']['name'])
        self.assertIn('Яблоки', pair['magnit']['name'])
        
        # ИСПРАВЛЕНИЕ 2: Ключа 'cheaper' в твоем новом коде scraper.py НЕТ. 
        # Удаляем эту проверку, либо проверяем цены напрямую.
        # self.assertEqual(pair['cheaper'], 'Магнит') <-- УДАЛИЛИ
        
        # Вместо этого проверим цены, чтобы убедиться, что логика сравнения возможна
        self.assertTrue(pair['price_mag'] < pair['price_pyat']) # 90 < 100

        self.assertEqual(len(result['pyat_single']), 1)
        self.assertEqual(result['pyat_single'][0]['name'], 'Хлеб Ржаной')
        
        self.assertEqual(len(result['magnit_single']), 1)
        self.assertEqual(result['magnit_single'][0]['name'], 'Масло Сливочное')


class TestBaseParser(unittest.TestCase):

    def test_add_product(self):
        """Проверка добавления товара в список"""
        mock_driver = MagicMock()

        class ConcreteParser(BaseParser):
            def extract_product_name(self, elem): return "test"
            def extract_product_price(self, elem): return Decimal(10)
            def scrape_search(self, query): return []

        # ИСПРАВЛЕНИЕ 1: Убираем mock_store
        parser = ConcreteParser(mock_driver)

        success = parser.add_product("Test Item", Decimal("10.50"))

        self.assertTrue(success)
        self.assertEqual(len(parser.products), 1)
        self.assertEqual(parser.products[0]['name'], "Test Item")
        
        success_empty = parser.add_product("", Decimal("0"))
        
        self.assertFalse(success_empty)
        self.assertEqual(len(parser.products), 1)
