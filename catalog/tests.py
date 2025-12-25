import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from catalog.models import Product, Category, CartItem

User = get_user_model()

class TestCatalogModels(TestCase):
    """Тесты для моделей каталога"""
    
    def setUp(self):
        # Создаем категорию для использования в тестах
        self.category = Category.objects.create(name="Молочные продукты")
        
    def test_category_str(self):
        """Проверка строкового представления категории"""
        self.assertEqual(str(self.category), "Молочные продукты")

    def test_product_properties(self):
        """Проверка вычисляемых свойств продукта"""
        
        # 1. Товар только в Пятерочке
        p1 = Product.objects.create(name_pyat="Молоко Простоквашино", price_pyat=50)
        self.assertTrue(p1.has_pyat)
        self.assertFalse(p1.has_mag)
        self.assertFalse(p1.has_both)
        self.assertEqual(p1.main_name, "Молоко Простоквашино")

        # 2. Товар в обоих магазинах
        p2 = Product.objects.create(
            name_pyat="Сыр Российский", price_pyat=100,
            name_mag="Сыр Российский Магнит", price_mag=90
        )
        self.assertTrue(p2.has_both)
        # Разница: 100 - 90 = 10
        self.assertEqual(p2.price_difference, 10.0)
        # Дешевле в магните ('mag')
        self.assertEqual(p2.cheaper_store, 'mag')

    def test_cart_item_creation(self):
        """Проверка создания элемента корзины"""
        user = User.objects.create_user(username='testuser_model', password='password')
        product = Product.objects.create(name_pyat="Хлеб Бородинский")
        cart_item = CartItem.objects.create(user=user, product=product, quantity=2)
        
        self.assertEqual(cart_item.quantity, 2)
        self.assertEqual(cart_item.user, user)
        self.assertEqual(cart_item.product, product)


class TestCatalogViews(TestCase):
    """Тесты для представлений (views) каталога"""
    
    def setUp(self):
        self.factory = RequestFactory()
        # Создаем пользователя и логиним его
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client = Client()
        self.client.force_login(self.user)
        
    @patch('catalog.views.threading.Thread')
    def test_product_list_search_trigger(self, mock_thread):
        """Проверяем, что при поиске создается категория и запускается фоновый поток парсинга"""
        
        # Настройка мока для потока
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        query = 'Яблоки' 
        response = self.client.get(reverse('product_list'), {'q': query})
        
        self.assertEqual(response.status_code, 200)
        
        # Проверяем, что категория создалась в БД (вьюха делает capitalize(), поэтому 'Яблоки')
        self.assertTrue(Category.objects.filter(name='Яблоки').exists())
        
        # Проверяем, что был создан и запущен поток
        self.assertTrue(mock_thread.called)
        mock_thread_instance.start.assert_called_once()

    @patch('catalog.views.threading.Thread')
    def test_product_list_context(self, mock_thread):
        """Проверка контекста страницы при поиске существующего товара"""
        
        # Мокаем поток, чтобы он не запускался реально
        mock_thread.return_value = MagicMock()

        # 1. Создаем товар с русским именем
        Product.objects.create(name_pyat="Зеленое Яблоко", price_pyat=10)
        
        # 2. Выполняем поиск по слову "Яблоко"
        response = self.client.get(reverse('product_list'), {'q': 'Яблоко'})
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_products', response.context)

    def test_add_to_cart_ajax(self):
        """Тест добавления в корзину через POST запрос (AJAX)"""
        product = Product.objects.create(name_pyat="Масло Сливочное", price_pyat=120)
        
        response = self.client.post(reverse('add_to_cart'), {
            'product_id': product.id,
            'quantity': 3
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Проверяем JSON ответ
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'success')
        
        # Проверяем, что товар реально добавился в базу
        item = CartItem.objects.get(user=self.user, product=product)
        self.assertEqual(item.quantity, 3)

    def test_cart_view_calculations(self):
        """Тест правильности расчетов итоговой суммы в корзине"""
        
        # Товар 1: 100р (Пят) vs 110р (Маг)
        p1 = Product.objects.create(
            name_pyat="Гречка", price_pyat=100, 
            name_mag="Гречка Экстра", price_mag=110
        )
        # Товар 2: 50р (Пят) vs 40р (Маг)
        p2 = Product.objects.create(
            name_pyat="Рис", price_pyat=50, 
            name_mag="Рис", price_mag=40
        )
        
        # Добавляем в корзину: 1 шт первого, 2 шт второго
        CartItem.objects.create(user=self.user, product=p1, quantity=1)
        CartItem.objects.create(user=self.user, product=p2, quantity=2)
        
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.status_code, 200)
        
        # Расчет Пятерочка: (100 * 1) + (50 * 2) = 100 + 100 = 200
        # Расчет Магнит: (110 * 1) + (40 * 2) = 110 + 80 = 190
        
        self.assertEqual(response.context['pyat_total'], "200.00")
        self.assertEqual(response.context['mag_total'], "190.00")
        
        # Магнит (190) дешевле Пятерочки (200)
        self.assertEqual(response.context['cheaper_store'], 'Магнит')

    def test_remove_from_cart(self):
        """Тест удаления товара из корзины"""
        p = Product.objects.create(name_pyat="Товар для удаления")
        item = CartItem.objects.create(user=self.user, product=p, quantity=1)
        
        # Отправляем POST запрос на удаление
        response = self.client.post(reverse('remove_from_cart', args=[item.id]))
        
        self.assertEqual(response.status_code, 200)
        
        # Проверяем, что объект удален из базы
        self.assertFalse(CartItem.objects.filter(id=item.id).exists())

    def test_clear_cart(self):
        """Тест полной очистки корзины"""
        p = Product.objects.create(name_pyat="Случайный товар")
        CartItem.objects.create(user=self.user, product=p)
        
        response = self.client.post(reverse('clear_cart'))
        
        self.assertEqual(response.status_code, 200)
        
        # Проверяем, что корзина пользователя пуста
        self.assertEqual(CartItem.objects.filter(user=self.user).count(), 0)
