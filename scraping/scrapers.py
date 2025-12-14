from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import quote
from fuzzywuzzy import fuzz
from decimal import Decimal
import re
import time
from catalog.models import Product, Price, Store


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

    # Создаем магазины в БД, если нет
    pyaterochka, _ = Store.objects.get_or_create(name="Пятёрочка")
    magnit, _ = Store.objects.get_or_create(name="Магнит")

    driver = get_driver()
    try:
        # 1. Парсим Пятёрочку
        pyat_parser = PyaterochkaParser(pyaterochka, driver)
        pyat_products = pyat_parser.scrape_search(query)

        # 2. Парсим Магнит
        magnit_parser = MagnitParser(magnit, driver)
        magnit_products = magnit_parser.scrape_search(query)

        # 3. Сопоставляем результаты
        result = smart_compare_products(pyat_products, magnit_products)

        # 4. Сохраняем в БД для отображения на сайте
        # save_results_to_db(matches)
        return result
    finally:
        driver.quit()
        print("🔚 Браузер закрыт (после обоих магазинов)")


class BaseParser(ABC):
    def __init__(self, store, driver):
        self.store = store
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
                'store': self.store,
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
        except:
            return None

    def scrape_search(self, query):
        print(f"🟦 Старт парсинга Пятёрочки...")

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
            except:
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
        except:
            return None

    def scrape_search(self, query):
        print(f"🟥 Старт парсинга Магнита...")
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
                    print(f"  ⚠️ Название не найдено")
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

            # Вычисляем разницу цен
            price_diff = abs(pyat_prod['price'] - best_match['price'])
            price_diff_percent = (
                price_diff / min(pyat_prod['price'], best_match['price'])) * 100

            # Определяем, где дешевле
            if pyat_prod['price'] < best_match['price']:
                cheaper = 'Пятёрочка'
            elif pyat_prod['price'] > best_match['price']:
                cheaper = 'Магнит'
            else:
                cheaper = 'Одинаково'

            pairs.append({
                'similarity': best_similarity,
                'pyat': pyat_prod,
                'magnit': best_match,
                'price_diff': float(price_diff),
                'price_diff_percent': float(price_diff_percent),
                'cheaper': cheaper
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


def save_results_to_db(matches):
    """
    Сохраняет результаты парсинга в базу данных (Product, Price)
    """
    from django.utils import timezone

    # Проходим по всем результатам (пары и одиночные)
    for match in matches:
        # Список магазинов в текущем match
        items_to_save = []

        if match.get('pyaterochka'):
            items_to_save.append(match['pyaterochka'])

        if match.get('magnit'):
            items_to_save.append(match['magnit'])

        for item in items_to_save:
            try:
                # 1. Создаем или получаем товар
                # Используем update_or_create, чтобы не дублировать
                product, _ = Product.objects.get_or_create(
                    name=item['name'],
                    defaults={'category': 'Найденное'}
                )

                # 2. Сохраняем цену
                Price.objects.create(
                    product=product,
                    store=item['store'],
                    price=item['price'],
                    date=timezone.now()
                )
            except Exception as e:
                print(f"Ошибка сохранения в БД: {e}")
