import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup

from scraping.scrapers import (
    PyaterochkaParser, 
    MagnitParser, 
    smart_compare_products,
    BaseParser
)

# --- Фикстуры (подготовка данных) ---

@pytest.fixture
def mock_driver():
    """Фейковый драйвер Selenium"""
    return MagicMock()

@pytest.fixture
def mock_store():
    """Фейковый объект магазина (чтобы не лезть в БД)"""
    store = MagicMock()
    store.name = "Test Store"
    return store

# --- Тесты для PyaterochkaParser ---

class TestPyaterochkaParser:
    
    def test_extract_price_valid(self, mock_store, mock_driver):
        """Проверка извлечения цены (обычный кейс)"""
        parser = PyaterochkaParser(mock_store, mock_driver)
        
        # Имитируем HTML с ценой: рубли, копейки, рубли, копейки (2 пары)
        # Вторая пара - акционная
        html = """
        <div class="price-container">
            <span>200</span><span>00</span> <!-- Старая цена -->
            <span>150</span><span>50</span> <!-- Новая цена -->
        </div>
        """
        elem = BeautifulSoup(html, 'html.parser')
        
        price = parser.extract_product_price(elem)
        assert price == Decimal('150.50')

    def test_extract_price_single_pair(self, mock_store, mock_driver):
        """Проверка, если только одна цена (без скидки)"""
        parser = PyaterochkaParser(mock_store, mock_driver)
        html = """
        <div>
            <span>99</span><span>90</span>
        </div>
        """
        elem = BeautifulSoup(html, 'html.parser')
        price = parser.extract_product_price(elem)
        assert price == Decimal('99.90')

    def test_extract_name(self, mock_store, mock_driver):
        """Проверка извлечения названия (самый длинный текст)"""
        parser = PyaterochkaParser(mock_store, mock_driver)
        html = """
        <div class="card">
            <p>4.5</p> <!-- Рейтинг (игнорируем) -->
            <p>Хлеб</p> <!-- Короткое -->
            <p>Хлеб Бородинский нарезка 400г</p> <!-- То что нужно -->
        </div>
        """
        elem = BeautifulSoup(html, 'html.parser')
        name = parser.extract_product_name(elem)
        assert name == "Хлеб Бородинский нарезка 400г"

# --- Тесты для MagnitParser ---

class TestMagnitParser:
    
    def test_extract_price_magnit(self, mock_store, mock_driver):
        """Проверка парсинга цены Магнита"""
        parser = MagnitParser(mock_store, mock_driver)
        
        # Магнит часто ставит цену так
        html = """
        <div class="product">
            <span class="unit-catalog-product-preview-prices__regular">
                129,99 ₽
            </span>
        </div>
        """
        elem = BeautifulSoup(html, 'html.parser')
        price = parser.extract_product_price(elem)
        assert price == Decimal('129.99')

    def test_extract_name_magnit(self, mock_store, mock_driver):
        parser = MagnitParser(mock_store, mock_driver)
        html = """
        <div>
            <div class="unit-catalog-product-preview-title">
                Молоко Простоквашино 2.5%
            </div>
        </div>
        """
        elem = BeautifulSoup(html, 'html.parser')
        name = parser.extract_product_name(elem)
        assert name == "Молоко Простоквашино 2.5%"

# --- Тесты логики сравнения (Smart Compare) ---

def test_smart_compare_logic():
    """Проверка алгоритма сопоставления товаров"""
    
    # 1. Готовим тестовые данные
    pyat_data = [
        {'name': 'Яблоки Голден 1кг', 'price': Decimal('100.00'), 'store': 'Pyat'},
        {'name': 'Хлеб Ржаной', 'price': Decimal('50.00'), 'store': 'Pyat'}, # Без пары
    ]
    
    magnit_data = [
        {'name': 'Яблоки сезонные Голден фасованные 1кг', 'price': Decimal('90.00'), 'store': 'Mag'}, # Пара
        {'name': 'Масло Сливочное', 'price': Decimal('200.00'), 'store': 'Mag'}, # Без пары
    ]
    
    # 2. Запускаем функцию сравнения
    result = smart_compare_products(pyat_data, magnit_data, similarity_threshold=50)
    
    # 3. Проверяем результаты
    
    # Должна быть 1 пара (Яблоки)
    assert len(result['pairs']) == 1
    pair = result['pairs'][0]
    assert 'Яблоки' in pair['pyat']['name']
    assert 'Яблоки' in pair['magnit']['name']
    assert pair['cheaper'] == 'Магнит' # 90 < 100
    
    # Должен быть 1 одиночный товар в Пятерочке (Хлеб)
    assert len(result['pyat_single']) == 1
    assert result['pyat_single'][0]['name'] == 'Хлеб Ржаной'
    
    # Должен быть 1 одиночный товар в Магните (Масло)
    assert len(result['magnit_single']) == 1
    assert result['magnit_single'][0]['name'] == 'Масло Сливочное'

# --- Тест базового класса ---

def test_base_parser_add_product(mock_store, mock_driver):
    """Проверка добавления товара в список"""
    # Создаем фиктивный класс-наследник, так как BaseParser абстрактный
    class ConcreteParser(BaseParser):
        def extract_product_name(self, elem): return "test"
        def extract_product_price(self, elem): return Decimal(10)
        def scrape_search(self, query): return []
        
    parser = ConcreteParser(mock_store, mock_driver)
    
    # Пробуем добавить
    success = parser.add_product("Test Item", Decimal("10.50"))
    
    assert success is True
    assert len(parser.products) == 1
    assert parser.products[0]['name'] == "Test Item"
    assert parser.products[0]['price'] == Decimal("10.50")
    
    # Пробуем добавить с пустыми данными (не должно добавиться)
    success_empty = parser.add_product("", Decimal("0"))
    assert success_empty is False
    assert len(parser.products) == 1  # Количество не изменилось
