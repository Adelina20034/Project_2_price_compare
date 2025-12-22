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
import sys
import time
import logging
from catalog.models import Product, Category

logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter(
    '[%(levelname)s] %(asctime)s %(name)s:%(lineno)d - %(message)s'
))
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)


def get_driver():
    """Настройка драйвера Chrome"""
    logger.debug("🔧 Инициализация Chrome драйвера...")
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
    driver = webdriver.Chrome(service=service, options=options)
    logger.info("✅ Chrome драйвер инициализирован")
    return driver


def smart_product_search(query):
    """Основная функция поиска"""
    logger.info(f"🔍 Запуск умного поиска: '{query}'")

    driver = get_driver()
    try:
        # 1. Парсим Пятёрочку
        logger.info("🔵 Начинаем парсинг Пятёрочки...")
        pyat_parser = PyaterochkaParser(driver)
        pyat_products = pyat_parser.scrape_search(query)
        logger.info(f"✅ Пятёрочка завершена: {len(pyat_products)} товаров")

        # 2. Парсим Магнит
        logger.info("🔴 Начинаем парсинг Магнита...")
        magnit_parser = MagnitParser(driver)
        magnit_products = magnit_parser.scrape_search(query)
        logger.info(f"✅ Магнит завершен: {len(magnit_products)} товаров")

        # 3. Сопоставляем результаты
        logger.info("🔀 Сравниваем товары из обоих магазинов...")
        result = smart_compare_products(pyat_products, magnit_products)
        logger.info(
            f"✅ Сравнение завершено: пар={len(result['pairs'])}, одиночных={len(result['pyat_single']) + len(result['magnit_single'])}")
        return result
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")


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
        try:
            encoded_query = quote(query, safe='')
            search_url = f"{self.BASE_URL}?text={encoded_query}"
            logger.debug(f"🔗 URL поиска: {search_url}")

            self.driver.get(search_url)
            time.sleep(5)

            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, "div[data-qa^='product-card']")
                    )
                )
                logger.info("✅ Товары загружены (Пятёрочка)")
            except Exception as e:
                logger.warning(f"❌ Товары не загружены (Пятёрочка): {str(e)}")
                return []

            time.sleep(2)
            self._scroll_and_load()
            self._parse_products()

            logger.info(
                f"✅ ИТОГО (Пятёрочка): Спарсено {len(self.products)} товаров")
            return self.products

        except Exception as e:
            logger.error(f"❌ ОШИБКА Пятёрочки: {str(e)}", exc_info=True)
            return []

    def _scroll_and_load(self):
        """Прокручивает страницу для загрузки всех товаров"""
        logger.debug("📜 Начинаем прокрутку страницы...")
        previous_count = 0
        scroll_attempts = 0

        while scroll_attempts < self.MAX_SCROLL_ATTEMPTS:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            current_products = soup.find_all(
                'div', attrs={'data-qa': re.compile('^product-card')})
            current_count = len(current_products)

            if current_count == previous_count:
                break

            previous_count = current_count
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(self.SCROLL_WAIT)
            scroll_attempts += 1

        logger.info(
            f"✅ Прокрутка завершена. Всего товаров: {current_count}, потребовалось {scroll_attempts} прокруток")

    def _parse_products(self):
        """Парсит товары со страницы"""
        logger.debug("📄 Начинаем парсинг товаров...")

        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        product_elements = soup.find_all(
            'div', attrs={'data-qa': re.compile('^product-card')})

        if not product_elements:
            logger.warning("⚠️ Товары не найдены на странице (Пятёрочка)")
            return

        for i, elem in enumerate(product_elements):
            try:
                name = self.extract_product_name(elem)
                if not name:
                    logger.debug(f"  ⚠️ [{i+1}] Название не найдено")
                    continue

                price = self.extract_product_price(elem)
                if not price:
                    logger.debug(
                        f"  ⚠️ [{i+1}] {name[:40]}... - цена не найдена")
                    continue

                if self.add_product(name, price, page=1):
                    logger.debug(f"  ✅ [{i+1}] {name[:50]}... - {price}₽")

            except Exception as e:
                logger.debug(f"  ⚠️ Ошибка при парсинге товара: {str(e)}")
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
        current_page = 1
        try:
            encoded_query = quote(query, safe='')
            logger.debug(f"🔗 Запрос: '{encoded_query}'")

            while True:
                logger.info(f"📄 Парсим страницу {current_page} Магнита...")
                url = f"{self.BASE_URL}?term={encoded_query}&page={current_page}"

                self.driver.get(url)
                time.sleep(self.PAGE_WAIT)

                if not self._parse_page():
                    logger.debug(f"📍 Достигнута последняя страница Магнита")
                    break

                current_page += 1
                time.sleep(1)

            logger.info(
                f"✅ ИТОГО (Магнит): Спарсено {len(self.products)} товаров")
            return self.products

        except Exception as e:
            logger.error(f"❌ ОШИБКА Магнита: {str(e)}", exc_info=True)
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
            logger.debug("⚠️ Товары не найдены на этой странице")
            return False

        logger.debug(f"📊 Найдено товаров на странице: {len(product_elements)}")

        for i, elem in enumerate(product_elements):
            try:
                name = self.extract_product_name(elem)
                if not name:
                    logger.debug(f"  ⚠️ [{i+1}] Название не найдено")
                    continue

                price = self.extract_product_price(elem)
                if not price:
                    logger.debug(f"  ✅ [{i+1}] {name[:50]}... - {price}₽")
                    continue

                if self.add_product(name, price, page=self.products[-1]['page'] + 1 if self.products else 1):
                    logger.debug(f"  ✅ {name[:50]}... - {price}₽")

            except Exception as e:
                logger.debug(f"  ⚠️ Ошибка при парсинге: {str(e)[:50]}")
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
    logger.info(
        f"🔍 СРАВНЕНИЕ ТОВАРОВ: {len(pyat_products)} из Пятёрочки vs {len(magnit_products)} из Магнита")

    pairs = []
    used_pyat_indices = set()  # Индексы товаров Пятёрочки, которые нашли пару
    used_magnit_indices = set()  # Индексы товаров Магнита, которые нашли пару

    # НАХОДИМ ПАРЫ
    logger.info("🔍 Ищем пары товаров...")
    pairs_found = 0

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
            pairs_found += 1

            logger.debug(
                f"  ✅ Пара {pairs_found}: {pyat_prod['name'][:40]}... ↔ {best_match['name'][:40]}... ({best_similarity}%)")

    logger.info(f"✅ Найдено пар: {pairs_found}")
    # НАХОДИМ ОДИНОЧНЫЕ ТОВАРЫ
    logger.info("🔎 Ищем товары без пары...")

    pyat_single = []
    for idx, prod in enumerate(pyat_products):
        if idx not in used_pyat_indices:
            pyat_single.append(prod)
            logger.debug(f"  📌 Пятёрочка (нет пары): {prod['name'][:50]}...")

    magnit_single = []
    for idx, prod in enumerate(magnit_products):
        if idx not in used_magnit_indices:
            magnit_single.append(prod)
            logger.debug(f"  📌 Магнит (нет пары): {prod['name'][:50]}...")

    # СОРТИРУЕМ ПАРЫ ПО СХОДСТВУ
    pairs.sort(key=lambda x: x['similarity'], reverse=True)

    logger.info(f"📊 ИТОГИ СРАВНЕНИЯ:")
    logger.info(f"   ✅ Пар: {len(pairs)}")
    logger.info(f"   📌 Только в Пятёрочке: {len(pyat_single)}")
    logger.info(f"   📌 Только в Магните: {len(magnit_single)}")

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

    logger.info(f"💾 Начинаем сохранение результатов в БД для '{query}'...")

    category: Category
    category = Category.objects.get(name=query.capitalize())

    stats = {
        'created': 0,
        'updated': 0,
        'errors': 0,
        'categories_added': 0
    }
    logger.info("📊 Обработка ПАРНЫХ ТОВАРОВ...")
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
                logger.debug(
                    f"  ✓ Найдено: {name_pyat[:50]}... / {name_mag[:50]}...")

                price_pyat_changed = product.price_pyat != price_pyat
                price_mag_changed = product.price_mag != price_mag

                if price_pyat_changed:
                    product.price_pyat = price_pyat

                if price_mag_changed:
                    product.price_mag = price_mag

                if price_pyat_changed or price_mag_changed:
                    product.save()
                    stats['updated'] += 1
                    logger.debug(f"    🔄 Обновлены цены")

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
                logger.info(
                    f"  ✨ НОВЫЙ (пара): {name_pyat[:50]}... / {name_mag[:50]}...")

            if not product.categories.filter(id=category.id).exists():
                product.categories.add(category)
                stats['categories_added'] += 1

        except Exception as e:
            stats['errors'] += 1
            logger.error(f"  ❌ Ошибка сохранения парного товара: {str(e)}")

    logger.info("🏪 Обработка товаров ТОЛЬКО В ПЯТЁРОЧКЕ...")
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
                    logger.debug(f"    🔄 Обновлена цена")

            except Product.DoesNotExist:
                product, _ = Product.objects.get_or_create(
                    name_pyat=name_pyat,
                    price_pyat=price_pyat,
                    name_mag=None,
                    price_mag=None,
                    created_at=timezone.now()
                )
                stats['created'] += 1
                logger.info(f"  ✨ НОВЫЙ (Пятёрочка): {name_pyat[:50]}...")

            if not product.categories.filter(id=category.id).exists():
                product.categories.add(category)
                stats['categories_added'] += 1

        except Exception as e:
            stats['errors'] += 1
            logger.error(f"  ❌ Ошибка сохранения товара Пятёрочки: {str(e)}")

    logger.info("🏪 Обработка товаров ТОЛЬКО В МАГНИТЕ...")
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
                    logger.debug(f"    🔄 Обновлена цена")

            except Product.DoesNotExist:
                product, _ = Product.objects.get_or_create(
                    name_pyat=None,
                    price_pyat=None,
                    name_mag=name_mag,
                    price_mag=price_mag,
                    created_at=timezone.now()
                )
                stats['created'] += 1
                logger.info(f"  ✨ НОВЫЙ (Магнит): {name_mag[:50]}...")

            if not product.categories.filter(id=category.id).exists():
                product.categories.add(category)
                stats['categories_added'] += 1

        except Exception as e:
            stats['errors'] += 1
            logger.error(f"  ❌ Ошибка сохранения товара Магнита: {str(e)}")

    logger.info(f"\n✨ СТАТИСТИКА СОХРАНЕНИЯ:")
    logger.info(f"   ✨ Создано новых: {stats['created']}")
    logger.info(f"   🔄 Обновлено: {stats['updated']}")
    logger.info(f"   📁 Добавлено в категории: {stats['categories_added']}")
    logger.info(f"   ❌ Ошибок: {stats['errors']}")
