from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import quote
from fuzzywuzzy import fuzz
from decimal import Decimal
import re
import time
from catalog.models import Product, Category


def get_driver():
    """Настройка драйвера Chrome"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Скрытие автоматизации
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def smart_product_search(query):
    """Основная функция поиска"""
    print(f"🔍 Запуск умного поиска: '{query}'")

    driver = get_driver()
    try:
        # 1. Парсим Пятёрочку
        pyat_parser = PyaterochkaParser(driver)
        pyat_products = pyat_parser.scrape_search(query)

        # 2. Парсим Магнит
        magnit_parser = MagnitParser(driver)
        magnit_products = magnit_parser.scrape_search(query)

        # 3. Сопоставляем результаты
        result = smart_compare_products(pyat_products, magnit_products)
        return result
    finally:
        driver.quit()
        print("🔚 Браузер закрыт (после обоих магазинов)")


class BaseParser(ABC):
    def __init__(self, driver):
        self.driver = driver
        self.products = []

    @abstractmethod
    def extract_product_name(self, elem):
        """Извлечь название товара из элемента страницы"""
        pass

    @abstractmethod
    def extract_product_price(self, elem):
        """Извлечь цену товара из элемента страницы"""
        pass

    @abstractmethod
    def scrape_search(self, query):
        """Выполнить поиск и вернуть список товаров"""
        pass

    def add_product(self, name: str, price: Decimal, page: int = 1):
        """Универсальный метод добавления товара"""
        if name and price:
            product_dict = {
                'name': name,
                'price': price,
                'page': page
            }
            self.products.append(product_dict)
            return True
        return False

    def get_products(self):
        """Получить все спарсенные товары"""
        return self.products


class PyaterochkaParser(BaseParser):
    BASE_URL = "https://5ka.ru/search/"
    MAX_SCROLL_ATTEMPTS = 20
    SCROLL_WAIT = 2

    def extract_product_name(self, elem):
        """
        Извлекает название товара из карточки Пятёрочки
        Ищет <p> с самым длинным текстом среди всех <p>
        """
        all_p_elements = elem.find_all('p')
        candidates = []

        for p_elem in all_p_elements:
            text = p_elem.get_text(strip=True)

            # Пропускаем пустые
            if not text or len(text) < 5:
                continue

            # Пропускаем только цифры (рейтинг, вес)
            if re.match(r'^\d+[.,]?\d*$', text):
                continue

            # Пропускаем элементы без букв
            if not re.search(r'[а-яА-ЯёЁa-zA-Z]', text):
                continue

            candidates.append({'text': text, 'length': len(text)})

        if candidates:
            best = max(candidates, key=lambda x: x['length'])
            return best['text']

        return None

    def extract_product_price(self, elem):
        """
        Извлекает АКЦИОННУЮ цену товара из карточки Пятёрочки
        На Пятёрочке две цены: старая (до скидки) и акционная (со скидкой)
        Берём АКЦИОННУЮ цену!
        """
        all_spans = elem.find_all('span')
        price_numbers = []

        for span in all_spans:
            text = span.get_text(strip=True)

            # Ищем только span'ы с цифрами (пропускаем ₽, скидки и т.д.)
            if re.match(r'^\d+$', text):
                price_numbers.append(text)

        if not price_numbers:
            return None

        # Берём ВТОРУЮ пару (акционную цену)
        if len(price_numbers) == 4:
            # Две полные пары - берём вторую (акционную)
            rubles, kopecks = price_numbers[2:]
        elif len(price_numbers) == 2:
            rubles, kopecks = price_numbers
        else:
            return None

        # Убедимся, что копейки - ровно 2 цифры
        if len(kopecks) == 1:
            kopecks += '0'
        elif len(kopecks) > 2:
            kopecks = kopecks[:2]

        try:
            price = Decimal(f"{rubles}.{kopecks}")
            return price
        except Exception:
            return None

    def scrape_search(self, query):
        print("🟦 Старт парсинга Пятёрочки...")

        try:
            encoded_query = quote(query, safe='')
            search_url = f"{self.BASE_URL}?text={encoded_query}"

            self.driver.get(search_url)
            time.sleep(5)

            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, "div[data-qa^='product-card']")
                    )
                )
                print("✅ Товары загружены")
            except Exception:
                print("❌ Товары не найдены")
                return []

            time.sleep(2)
            self._scroll_and_load()
            self._parse_products()

            print(
                f"\n✅ ИТОГО: Спарсено {len(self.products)} товаров из Пятёрочки")
            return self.products

        except Exception as e:
            print(f"❌ ОШИБКА Пятерочки: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _scroll_and_load(self):
        """Прокручивает страницу для загрузки всех товаров"""
        previous_count = 0
        scroll_attempts = 0

        while scroll_attempts < self.MAX_SCROLL_ATTEMPTS:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            current_products = soup.find_all(
                'div', attrs={'data-qa': re.compile('^product-card')})
            current_count = len(current_products)

            print(
                f"  Попытка {scroll_attempts + 1}: найдено {current_count} товаров", end="")

            if current_count == previous_count:
                print(" (новых нет) ✓")
                break

            print(" (ищем ещё...)")
            previous_count = current_count
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(self.SCROLL_WAIT)
            scroll_attempts += 1

        print(f"✅ Прокрутка завершена. Всего товаров: {current_count}")

    def _parse_products(self):
        """Парсит товары со страницы"""
        print("📄 Парсим товары со страницы...")

        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        product_elements = soup.find_all(
            'div', attrs={'data-qa': re.compile('^product-card')})

        if not product_elements:
            print("⚠️ Товары не найдены на странице")
            return

        print(f"📊 Найдено карточек товаров: {len(product_elements)}")

        for i, elem in enumerate(product_elements):
            try:
                name = self.extract_product_name(elem)
                if not name:
                    print(f"  ⚠️ [{i+1}] Название не найдено")
                    continue

                price = self.extract_product_price(elem)
                if not price:
                    print(f"  ⚠️ [{i+1}] {name[:40]}... - цена не найдена")
                    continue

                if self.add_product(name, price, page=1):
                    print(f"  ✅ [{i+1}] {name[:50]}... - {price}₽")

            except Exception as e:
                print(f"  ⚠️ Ошибка при парсинге товара: {e}")
                continue


class MagnitParser(BaseParser):
    BASE_URL = "https://magnit.ru/search"
    PAGE_WAIT = 3

    def extract_product_name(self, elem):
        name_elem = elem.find('div', class_=re.compile(
            'unit-catalog-product-preview-title'))

        if name_elem:
            name = name_elem.get_text(strip=True)
            if name:
                return name

        return None

    def extract_product_price(self, elem):
        price_elem = elem.find('span', class_=re.compile(
            'unit-catalog-product-preview-prices__regular'))

        if not price_elem:
            return None

        price_text = price_elem.get_text(strip=True)

        # Извлекаем цифры из текста (может быть "149.99 ₽" или "149,99 ₽")
        numbers = re.findall(r'\d+[.,]\d+|\d+', price_text)

        if not numbers:
            return None

        # Первое число - рубли и копейки
        price_str = numbers[0].replace(',', '.')

        try:
            price = Decimal(price_str)
            return price
        except Exception:
            return None

    def scrape_search(self, query):
        print("🟥 Старт парсинга Магнита...")
        current_page = 1

        try:
            print(f"🔍 Парсим Магнит: запрос '{query}'  ")

            encoded_query = quote(query, safe='')

            while True:
                print(f"\n📄 Парсим страницу {current_page}...")
                url = f"{self.BASE_URL}?term={encoded_query}&page={current_page}"

                self.driver.get(url)
                time.sleep(self.PAGE_WAIT)

                if not self._parse_page():
                    break

                current_page += 1
                time.sleep(1)

            print(
                f"\n✅ ИТОГО: Спарсено {len(self.products)} товаров из Магнита")
            return self.products

        except Exception as e:
            print(f"❌ Ошибка Магнита: {e}")
            return []

    def _parse_page(self) -> bool:
        """
        Парсит одну страницу результатов
        Возвращает True если товары найдены, False если это последняя страница
        """
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        product_elements = soup.find_all(
            'article', attrs={'data-test-id': 'v-product-preview'})

        if not product_elements:
            print("⚠️ Товары не найдены на этой странице")
            return False

        print(f"📊 Найдено товаров на странице: {len(product_elements)}")

        for i, elem in enumerate(product_elements):
            try:
                name = self.extract_product_name(elem)
                if not name:
                    print("  ⚠️ Название не найдено")
                    continue

                price = self.extract_product_price(elem)
                if not price:
                    print(f"  ⚠️ {name[:40]}... - цена не найдена")
                    continue

                if self.add_product(name, price, page=self.products[-1]['page'] + 1 if self.products else 1):
                    print(f"  ✅ {name[:50]}... - {price}₽")

            except Exception as e:
                print(f"  ⚠️ Ошибка при парсинге: {str(e)[:50]}")
                continue

        return True


def smart_compare_products(
    pyat_products: list[dict],
    magnit_products: list[dict],
    similarity_threshold: int = 75
) -> dict:
    """
    Умное сравнение товаров из двух магазинов

    Args:
        pyat_products: Товары из Пятёрочки
        magnit_products: Товары из Магнита
        similarity_threshold: Минимальный % сходства для пары (0-100)

    Returns:
        {
            'pairs': [...],        # Товары с парой
            'pyat_single': [...],  # Только в Пятёрочке
            'magnit_single': [...] # Только в Магните
        }
    """

    pairs = []
    used_pyat_indices = set()  # Индексы товаров Пятёрочки, которые нашли пару
    used_magnit_indices = set()  # Индексы товаров Магнита, которые нашли пару

    # НАХОДИМ ПАРЫ
    print("🔍 Ищем пары товаров...")

    # Для каждого товара из Пятёрочки
    for pyat_idx, pyat_prod in enumerate(pyat_products):

        best_match = None
        best_similarity = 0
        best_magnit_idx = -1

        # Ищем лучший матч в Магните
        for magnit_idx, magnit_prod in enumerate(magnit_products):

            # Пропускаем товары, которые уже использованы в паре
            if magnit_idx in used_magnit_indices:
                continue

            # Считаем сходство
            similarity = fuzz.token_set_ratio(
                pyat_prod['name'].lower(),
                magnit_prod['name'].lower()
            )

            # Если это лучший матч и выше порога
            if similarity > best_similarity and similarity >= similarity_threshold:
                best_similarity = similarity
                best_match = magnit_prod
                best_magnit_idx = magnit_idx

        # Если нашли хорошую пару
        if best_match and best_similarity >= similarity_threshold:

            pairs.append({
                'similarity': best_similarity,
                'pyat': pyat_prod,
                'price_pyat': pyat_prod['price'],
                'magnit': best_match,
                'price_mag': best_match['price'],
            })

            # Отмечаем как использованные
            used_pyat_indices.add(pyat_idx)
            used_magnit_indices.add(best_magnit_idx)

            print(
                f"  ✅ Пара найдена: {pyat_prod['name'][:40]}... ↔ {best_match['name'][:40]}... ({best_similarity}%)")

    # НАХОДИМ ОДИНОЧНЫЕ ТОВАРЫ
    print("\n🔎 Ищем товары без пары...")

    pyat_single = []
    for idx, prod in enumerate(pyat_products):
        if idx not in used_pyat_indices:
            pyat_single.append(prod)
            print(f"  📌 Пятёрочка (нет пары): {prod['name'][:50]}...")

    magnit_single = []
    for idx, prod in enumerate(magnit_products):
        if idx not in used_magnit_indices:
            magnit_single.append(prod)
            print(f"  📌 Магнит (нет пары): {prod['name'][:50]}...")

    # СОРТИРУЕМ ПАРЫ ПО СХОДСТВУ
    pairs.sort(key=lambda x: x['similarity'], reverse=True)

    print(f"\n✅ Найдено пар: {len(pairs)}")
    print(f"📌 Одиночные товары Пятёрочки: {len(pyat_single)}")
    print(f"📌 Одиночные товары Магнита: {len(magnit_single)}")

    return {
        'pairs': pairs,
        'pyat_single': pyat_single,
        'magnit_single': magnit_single
    }


def save_results_to_db(res, query):
    """
    Сохраняет результаты парсинга в базу данных (Product)
    """
    from django.utils import timezone
    category: Category
    category = Category.objects.get(name=query.capitalize())

    stats = {
        'created': 0,
        'updated': 0,
        'errors': 0
    }
    print("📊 ПАРНЫЕ ТОВАРЫ (в обоих магазинах)")

    for pair in res.get('pairs', []):
        try:
            name_pyat = pair.get('pyat').get('name')
            name_mag = pair.get('magnit').get('name')
            price_pyat = pair.get('price_pyat')
            price_mag = pair.get('price_mag')
            try:
                product = Product.objects.get(
                    name_pyat=name_pyat,
                    name_mag=name_mag,
                )
                print(f"✓ Найдено: {name_pyat} / {name_mag}")

                price_pyat_changed = product.price_pyat != price_pyat
                price_mag_changed = product.price_mag != price_mag

                if price_pyat_changed:
                    product.price_pyat = price_pyat

                if price_mag_changed:
                    product.price_mag = price_mag

                if price_pyat_changed or price_mag_changed:
                    product.save()
                    stats['updated'] += 1

            except Product.DoesNotExist:
                product, _ = Product.objects.get_or_create(
                    name_pyat=pair['pyat']['name'],
                    price_pyat=pair['price_pyat'],
                    name_mag=pair['magnit']['name'],
                    price_mag=pair['price_mag'],
                    similarity=pair['similarity'],
                    created_at=timezone.now()
                )
                stats['created'] += 1
                print(f"✨ НОВЫЙ (пара): {name_pyat} / {name_mag}")

            if not product.categories.filter(id=category.id).exists():
                product.categories.add(category)
                stats['categories_added'] += 1
                print(f"   ✅ Добавлено в категорию '{category.name}'")

        except Exception as e:
            stats['errors'] += 1
            print(f"Ошибка сохранения в БД: {e}")

    print("\n🏪 ТОВАРЫ ТОЛЬКО В ПЯТЁРОЧКЕ")
    for item in res.get('pyat_single', []):
        try:
            name_pyat = item.get('name')
            price_pyat = item.get('price')
            try:
                product = Product.objects.get(
                    name_pyat=name_pyat,
                    name_mag__isnull=True,
                )

                if product.price_pyat != price_pyat:
                    product.price_pyat = price_pyat
                    product.save()
                    stats['updated'] += 1

            except Product.DoesNotExist:
                product, _ = Product.objects.get_or_create(
                    name_pyat=name_pyat,
                    price_pyat=price_pyat,
                    name_mag=None,
                    price_mag=None,
                    created_at=timezone.now()
                )
                stats['created'] += 1
                print(f"✨ НОВЫЙ (пятерочка): {name_pyat}")

            if not product.categories.filter(id=category.id).exists():
                product.categories.add(category)
                stats['categories_added'] += 1
                print(f"   ✅ Добавлено в категорию '{category.name}'")

        except Exception as e:
            stats['errors'] += 1
            print(f"Ошибка сохранения в БД: {e}")

    print("\n🏪 ТОВАРЫ ТОЛЬКО В МАГНИТЕ")
    for item in res.get('magnit_single', []):
        try:
            name_mag = item.get('name')
            price_mag = item.get('price')
            try:
                product = Product.objects.get(
                    name_pyat__isnull=True,
                    name_mag=name_mag,
                )

                if product.price_mag != price_mag:
                    product.price_mag = price_mag
                    product.save()
                    stats['updated'] += 1

            except Product.DoesNotExist:
                product, _ = Product.objects.get_or_create(
                    name_pyat=None,
                    price_pyat=None,
                    name_mag=name_mag,
                    price_mag=price_mag,
                    created_at=timezone.now()
                )
                stats['created'] += 1
                print(f"✨ НОВЫЙ (магнит): {name_mag}")

            if not product.categories.filter(id=category.id).exists():
                product.categories.add(category)
                stats['categories_added'] += 1
                print(f"   ✅ Добавлено в категорию '{category.name}'")

        except Exception as e:
            stats['errors'] += 1
            print(f"Ошибка сохранения в БД: {e}")

    print(f"✨ Создано новых: {stats['created']}")
    print(f"🔄 Обновлено: {stats['updated']}")
    print(f"❌ Ошибок: {stats['errors']}")
