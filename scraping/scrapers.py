from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from fuzzywuzzy import fuzz
import re
from decimal import Decimal
import time
from catalog.models import Product, Price, Store

def smart_product_search(query):
    """Основная функция поиска"""
    print(f"🔍 Запуск умного поиска: '{query}'")
    
    # Создаем магазины в БД, если нет
    pyaterochka, _ = Store.objects.get_or_create(name="Пятёрочка")
    magnit, _ = Store.objects.get_or_create(name="Магнит")
    
    # 1. Парсим Пятёрочку
    pyat_products = scrape_pyaterochka_search(query, pyaterochka)
    
    # 2. Парсим Магнит
    magnit_products = scrape_magnit_search(query, magnit)
    
    # 3. Сопоставляем результаты
    matches = find_product_matches(pyat_products, magnit_products)
    
    # 4. Сохраняем в БД для отображения на сайте
    save_results_to_db(matches)
    
    return matches

def get_driver():
    """Настройка драйвера Chrome"""
    options = Options()
    # options.add_argument("--headless=new")  # Раскомментируйте для скрытого режима
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled") # Скрытие автоматизации
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def scrape_pyaterochka_search(query, store):
    print(f"🟦 Старт парсинга Пятёрочки...")
    products = []
    driver = get_driver()
    
    try:
        driver.get("https://5ka.ru/special_offers") 
        time.sleep(5)  # <-- Увеличили ожидание загрузки (важно!)

        try:
            # Пытаемся найти поле 3 раза (защита от StaleElement)
            for attempt in range(3):
                try:
                    search_input = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input[data-qa='search-panel-input']"))
                    )
                    
                    # Клик JS
                    driver.execute_script("arguments[0].click();", search_input)
                    
                    # Очистка и ввод
                    search_input.clear()
                    search_input.send_keys(query)
                    search_input.send_keys(Keys.ENTER)
                    break # Если получилось - выходим из цикла попыток
                except Exception as e:
                    print(f"   ⚠️ Попытка {attempt+1}: {e}")
                    time.sleep(2) # Ждем и пробуем снова
            
            print("   ↳ Запрос отправлен, ждем результаты...")
            time.sleep(5) 
            
            # Сбор результатов (как раньше)
            title_elements = driver.find_elements(By.CSS_SELECTOR, "p.css-ijz3vq")
            
            for title_el in title_elements[:10]:
                try:
                    name = title_el.text
                    card = title_el.find_element(By.XPATH, "./ancestor::div[contains(@class, 'chakra-stack')]")
                    rubles = card.find_element(By.CSS_SELECTOR, "span.css-1j4x839").text
                    try:
                        kopeks = card.find_element(By.CSS_SELECTOR, "span.css-30bcam").text
                    except:
                        kopeks = "00"
                    
                    full_price_str = f"{rubles}.{kopeks}"
                    price = Decimal(re.sub(r'[^\d.]', '', full_price_str))
                    
                    if name and price:
                        products.append({'name': name, 'price': price, 'store': store})
                        print(f"  🟦 Найдено: {name} - {price}₽")
                except:
                    continue

        except Exception as e:
            print(f"⚠️ Ошибка поиска Пятёрочки: {e}")

    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
    finally:
        driver.quit()
    return products

def scrape_magnit_search(query, store):
    print(f"🟥 Старт парсинга Магнита...")
    products = []
    driver = get_driver()
    
    try:
        driver.get("https://magnit.ru/katalog/") 
        time.sleep(3)
        
        try:
            search_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[data-test-id='v-input-control']"))
            )
            driver.execute_script("arguments[0].click();", search_input)
            search_input.clear()
            search_input.send_keys(query)
            search_input.send_keys(Keys.ENTER)
            
            print("   ↳ Запрос отправлен, ждем результаты...")
            time.sleep(5)
            
            # Карточки товаров
            cards = driver.find_elements(By.CSS_SELECTOR, "article[data-test-id='v-product-preview']")
            
            for card in cards[:10]:
                try:
                    # Название
                    name = card.find_element(By.CSS_SELECTOR, "div.unit-catalog-product-preview-title").text.strip()
                    
                    # Цена (регулярная или акционная)
                    # Ищем span с ценой. Обычно их два (акция и обычная), берем первый попавшийся с ценой
                    # Селектор: div.unit-catalog-product-preview-prices__regular span
                    
                    price_text = ""
                    try:
                        # Сначала пробуем найти цену по классу обычной цены
                        price_el = card.find_element(By.CSS_SELECTOR, "span.unit-catalog-product-preview-prices__regular span")
                        price_text = price_el.text
                    except:
                        # Если не нашли, ищем любую цену в карточке
                        price_text = card.text

                    # Извлекаем "134.99" из "134.99 ₽"
                    match = re.search(r'(\d+[.,]\d+)', price_text)
                    
                    if match:
                        price = Decimal(match.group(1).replace(',', '.'))
                        products.append({'name': name, 'price': price, 'store': store})
                        print(f"  🟥 Найдено: {name} - {price}₽")
                        
                except Exception as e:
                    continue
                    
        except Exception as e:
             print(f"⚠️ Ошибка сбора товаров Магнита: {e}")

    except Exception as e:
        print(f"❌ Ошибка Магнита: {e}")
    finally:
        driver.quit()
    return products


def find_product_matches(pyat_products, magnit_products, threshold=75):
    """
    Сопоставляет товары по названию.
    Возвращает список словарей:
    {
        'pyaterochka': {...},
        'magnit': {...},
        'similarity': 95,
        'saving': 15.00
    }
    """
    matches = []
    # Копии списков, чтобы удалять найденные
    p_copy = pyat_products[:]
    m_copy = magnit_products[:]
    
    # 1. Ищем пары
    for p_item in pyat_products:
        best_match = None
        best_score = 0
        
        for m_item in m_copy:
            # Сравниваем нормализованные названия
            score = fuzz.token_sort_ratio(
                normalize_name(p_item['name']), 
                normalize_name(m_item['name'])
            )
            
            if score > best_score:
                best_score = score
                best_match = m_item
        
        # Если совпадение хорошее (> 75%)
        if best_score >= threshold and best_match:
            matches.append({
                'pyaterochka': p_item,
                'magnit': best_match,
                'similarity': best_score,
                'saving': abs(p_item['price'] - best_match['price']),
                'cheaper_in': 'Пятёрочка' if p_item['price'] < best_match['price'] else 'Магнит'
            })
            # Удаляем из списков, чтобы не использовать повторно
            if p_item in p_copy: p_copy.remove(p_item)
            if best_match in m_copy: m_copy.remove(best_match)

    # 2. Добавляем оставшиеся без пары (уникальные)
    for p_item in p_copy:
        matches.append({
            'pyaterochka': p_item,
            'magnit': None,
            'similarity': 0
        })
        
    for m_item in m_copy:
        matches.append({
            'pyaterochka': None,
            'magnit': m_item,
            'similarity': 0
        })

    # Сортируем: сначала пары (по схожести), потом одиночные
    return sorted(matches, key=lambda x: x['similarity'], reverse=True)

def normalize_name(name):
    """Очистка названия для улучшения сравнения"""
    # Приводим к нижнему регистру
    name = name.lower()
    # Убираем слова-паразиты, которые мешают сравнению
    words_to_remove = ['пастеризованное', 'ультрапастеризованное', 'бзмж', 'в ассортименте']
    for w in words_to_remove:
        name = name.replace(w, '')
    return name

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
