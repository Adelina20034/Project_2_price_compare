from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone
import threading
import logging

from scraping.scrapers import smart_product_search, save_results_to_db
from .models import Category, Product, CartItem

logger = logging.getLogger(__name__)

# Константа для интервала обновления (в часах)
REPARSE_INTERVAL_HOURS = 24


@require_http_methods(["GET"])
def check_parsing_status(request):
    """
    Проверяет статус парсинга для запроса
    Возвращает JSON с информацией о статусе
    """
    query = request.GET.get('q', '').strip()

    if not query:
        return JsonResponse({
            'is_parsing': False,
            'query': ''
        })

    try:
        category = Category.objects.get(name=query.capitalize())
        logger.debug("Статус парсинга для '%s': is_parsing=%s",
                     query, category.is_parsing)
        return JsonResponse({
            'is_parsing': category.is_parsing,
            'query': query
        })
    except Category.DoesNotExist:
        logger.debug("Категория '%s' не найдена", query)
        return JsonResponse({
            'is_parsing': False,
            'query': query
        })


def run_parser(query):
    """Запускает парсинг"""
    try:
        logger.info("🔍 НАЧАЛО ПАРСИНГА: '%s'", query)

        # 1️⃣ Получаем категорию и устанавливаем флаг is_parsing = True
        category = Category.objects.get(name=query.capitalize())
        category.is_parsing = True
        category.save()
        logger.info(
            "✅ Флаг парсинга установлен: is_parsing=True для категории '%s'", query)

        # 2️⃣ Парсим
        result = smart_product_search(query)

        # 3️⃣ Сохраняем в БД
        save_results_to_db(result, query)

        # 4️⃣ Устанавливаем флаг is_parsing = False (ПАРСИНГ ЗАВЕРШЕН)
        category.is_parsing = False
        category.last_parsed_at = timezone.now()
        category.save()
        logger.info("✅ ПАРСИНГ ЗАВЕРШЁН: '%s'", query)
        logger.info("✅ Флаг парсинга обновлен: is_parsing=False")
        logger.info("✅ Время последнего парсинга: %r", category.last_parsed_at)

    except Category.DoesNotExist:
        logger.error(
            "❌ ОШИБКА: Категория '%s' не найдена в БД", query)

    except Exception as e:
        logger.error("❌ ОШИБКА при парсинге '%s': %s",
                     query, str(e), exc_info=True)
        try:
            category = Category.objects.get(name=query.capitalize())
            category.is_parsing = False
            category.save()
            logger.warning(
                "⚠️ Флаг парсинга сброшен из-за ошибки: is_parsing=False")
        except Exception as reset_error:
            logger.error("❌ Ошибка при сбросе флага парсинга: %s",
                         str(reset_error))


def _get_category(query):
    category, category_created = Category.objects.get_or_create(
        name=query.capitalize()
    )
    if category_created:
        logger.info("✨ Создана новая категория: '%s'", category.name)
    else:
        logger.debug(
            "🏷️ Используется существующая категория: '%s'", category.name)

    should_parse = False

    if category_created:
        # Новая категория - парсим сразу
        should_parse = True
        logger.info("📌 Новая категория - запускаем парсинг")
    elif category.is_parsing:
        # Уже идет парсинг - не запускаем новый
        should_parse = False
        logger.info("⏳ Парсинг уже идет для '%s'", query)
    elif not category.last_parsed_at:
        # Категория пуста (никогда не парсилась) - парсим
        should_parse = True
        logger.info(
            "📌 Категория никогда не парсилась - запускаем парсинг")
    elif category.needs_update:
        # Прошло более 24 часов - обновляем
        hours_ago = category.hours_since_last_parse
        should_parse = True
        logger.info(
            "📌 Прошло %.1f часов с последнего парсинга - запускаем обновление", hours_ago)
    else:
        # Данные свежие (менее 24 часов)
        hours_ago = category.hours_since_last_parse
        logger.info(
            "✅ Данные свежие (%.1f часов назад) - используем сохраненные данные", hours_ago)
    return category, should_parse


def product_list(request):
    """Основная страница поиска и сравнения товаров"""
    query = request.GET.get('q', '').strip()

    pairs = None
    pyat_only = None
    mag_only = None
    total_products = 0
    is_searching = False
    last_update_info = None

    if len(query) > 2:
        is_searching = True
        logger.info("🔍 Поиск товаров по запросу: '%s'", query)

        # Получаем или создаем статус парсинга
        category, should_parse = _get_category(query)
        # Запускаем парсинг если нужно
        if should_parse and not category.is_parsing:
            category.is_parsing = True
            category.save()

            thread = threading.Thread(
                target=run_parser,
                args=(query,),
                daemon=False  # Не демонический поток
            )
            thread.start()
            logger.info("✨ Парсинг запущен для '%s' в отдельном потоке", query)

        # Получаем товары из категории
        if category:
            products = category.products.all().order_by('-updated_at')
            logger.debug("🏷️ Категория: %s", category)
            logger.debug("📦 Товаров в категориях: %s", products.count())
        else:
            products = Product.objects.all().filter(
                Q(name_pyat__icontains=query) |
                Q(name_mag__icontains=query)
            ).order_by('-updated_at')

        if products.exists():
            logger.debug("📦 Найдено %s товаров для '%s'",
                         products.count(), query)
        else:
            logger.warning("❌ Товары не найдены для запроса '%s'", query)

        # Разделяем на категории
        pairs = products.filter(
            name_pyat__isnull=False,
            name_mag__isnull=False,
        )
        pyat_only = products.filter(
            name_pyat__isnull=False,
            name_mag__isnull=True,
        )
        mag_only = products.filter(
            name_pyat__isnull=True,
            name_mag__isnull=False,
        )

        total_products = products.count()
        logger.info(
            "📊 Результаты поиска: пар=%s, только Пятёрочка=%s, только Магнит=%s, всего=%s", pairs.count(), pyat_only.count(), mag_only.count(), total_products)

        if category.last_parsed_at:
            hours_ago = category.hours_since_last_parse
            last_update_info = f"Последнее обновление: {hours_ago:.1f}ч назад"

        # Если товаров нет и парсинг активен - показываем индикатор
        if total_products == 0 and category.is_parsing:
            is_searching = True
            logger.info(
                "🔄 Парсинг активен и товаров нет, показываем индикатор загрузки")
        else:
            is_searching = category.is_parsing  # Показываем статус парсинга

    # Товары в корзине текущего пользователя
    user_cart_ids = []
    if request.user.is_authenticated:
        user_cart_ids = CartItem.objects.filter(
            user=request.user
        ).values_list('product_id', flat=True)
        if user_cart_ids:
            logger.debug("🛒 Пользователь %s имеет %s товаров в корзине",
                         request.user.username, len(user_cart_ids))

    context = {
        'query': query,
        'pairs': pairs,
        'pairs_count': pairs.count() if pairs else 0,
        'pyat_single_count': pyat_only.count() if pyat_only else 0,
        'magnit_single_count': mag_only.count() if mag_only else 0,
        'pyat_only': pyat_only,
        'magnit_only': mag_only,
        'total_products': total_products,
        'user_cart_ids': list(user_cart_ids),
        'is_searching': is_searching,
        'last_update_info': last_update_info,
    }
    return render(request, 'catalog/product_list.html', context)


@login_required(login_url='login')
def cart_view(request):
    """
    Страница корзины пользователя с расчетом сумм по магазинам
    """
    logger.info("📄 Открыта страница корзины пользователем %s",
                request.user.username)
    # Получаем все товары в корзине пользователя
    cart_items = CartItem.objects.filter(
        user=request.user).select_related('product').order_by('-added_at')

    # Расчет сумм по магазинам
    pyat_total = 0
    mag_total = 0
    only_pyat = 0
    only_mag = 0

    for item in cart_items:
        product = item.product

        if not product.has_pyat:
            if product.has_mag:
                only_mag += float(product.price_mag) * item.quantity
            continue

        if not product.has_mag:
            if product.has_pyat:
                only_pyat += float(product.price_pyat) * item.quantity
            continue

        # Пятёрочка
        if product.price_pyat:
            pyat_total += float(product.price_pyat) * item.quantity

        # Магнит
        if product.price_mag:
            mag_total += float(product.price_mag) * item.quantity

    total_savings = abs(mag_total - pyat_total)

    # Определяем какой магазин дешевле
    if pyat_total > 0 and mag_total > 0:
        cheaper_store = 'Пятёрочка' if pyat_total < mag_total else 'Магнит'
    else:
        cheaper_store = None

    logger.info("💳 Сумма корзины: Пятёрочка=%.2f₽, Магнит=%.2f₽, экономия=%.2f₽",
                pyat_total, mag_total, total_savings)

    context = {
        'cart_items': cart_items,
        'pyat_total': f"{pyat_total:.2f}",
        'mag_total': f"{mag_total:.2f}",
        'total_savings': f"{total_savings:.2f}",
        'cheaper_store': cheaper_store,
        'is_empty': cart_items.count() == 0,
        'only_pyat': f"{only_pyat:.2f}",
        'only_mag': f"{only_mag:.2f}",
    }

    return render(request, 'catalog/cart.html', context)


@login_required(login_url='login')
@require_http_methods(["POST"])
def add_to_cart(request):
    """
    Добавляет товар (Product) в корзину пользователя

    POST параметры:
    - product_id: ID товара из Product модели
    """
    try:
        product_id = request.POST.get('product_id', '')
        quantity = int(request.POST.get('quantity', 1))

        quantity = max(quantity, 1)

        # Получаем товар
        product = get_object_or_404(Product, id=product_id)

        # Добавляем или обновляем количество в корзине
        cart_item, created = CartItem.objects.get_or_create(
            user=request.user,
            product=product,
            defaults={'quantity': quantity}
        )

        if not created:
            # Если уже в корзине - добавляем к количеству
            cart_item.quantity += quantity
            cart_item.save()
            logger.info(
                "📦 Товар '%s' уже в корзине, количество увеличено на %s", product.main_name, quantity)
        else:
            logger.info(
                "➕ Товар '%s' добавлен в корзину (количество: %s)", product.main_name, quantity)

        # Подсчитываем товары в корзине
        cart_count = CartItem.objects.filter(user=request.user).count()

        return JsonResponse({
            'status': 'success',
            'message': f'✓ {product.main_name} добавлен в корзину',
            'cart_count': cart_count,
            'product_id': product_id
        })

    except Exception as e:
        logger.error("❌ Ошибка при добавлении товара в корзину: %s",
                     str(e), exc_info=True)
        return JsonResponse({
            'status': 'error',
            'message': f'Ошибка: {str(e)}'
        }, status=400)


@login_required(login_url='login')
@require_http_methods(["POST"])
def remove_from_cart(request, item_id):
    """
    Удаляет товар из корзины пользователя

    URL: /cart/remove/<item_id>/
    """
    try:
        cart_item = CartItem.objects.get(id=item_id, user=request.user)
        product_name = cart_item.product.main_name

        cart_item.delete()
        logger.info("🗑️ Товар '%s' удален из корзины", product_name)

        cart_count = CartItem.objects.filter(user=request.user).count()

        return JsonResponse({
            'status': 'success',
            'message': f'✓ {product_name} удален из корзины',
            'cart_count': cart_count
        })

    except CartItem.DoesNotExist:
        logger.warning(
            "⚠️ Попытка удалить товар %s, который не найден в корзине", item_id)
        return JsonResponse({
            'status': 'error',
            'message': 'Товар не найден в корзине'
        }, status=404)

    except Exception as e:
        logger.error(
            "❌ Ошибка при удалении товара из корзины: %s", str(e), exc_info=True)
        return JsonResponse({
            'status': 'error',
            'message': f'Ошибка: {str(e)}'
        }, status=500)


@login_required(login_url='login')
@require_http_methods(["POST"])
def update_quantity(request, item_id):
    """
    Изменяет количество товара в корзине

    POST параметры:
    - quantity: новое количество
    """
    try:
        quantity = int(request.POST.get('quantity', 1))

        quantity = max(quantity, 1)
        quantity = min(quantity, 100)

        cart_item = CartItem.objects.get(id=item_id, user=request.user)
        old_quantity = cart_item.quantity
        cart_item.quantity = quantity
        cart_item.save()
        logger.info(
            "🔄 Количество товара '%s' изменено: %s → %s", cart_item.product.main_name, old_quantity, quantity)

        # Пересчитываем суммы
        product = cart_item.product
        pyat_subtotal = float(product.price_pyat or 0) * quantity
        mag_subtotal = float(product.price_mag or 0) * quantity

        return JsonResponse({
            'status': 'success',
            'message': f'Количество изменено на {quantity}',
            'pyat_subtotal': f"{pyat_subtotal:.2f}",
            'mag_subtotal': f"{mag_subtotal:.2f}",
        })

    except CartItem.DoesNotExist:
        logger.warning(
            "⚠️ Попытка обновить количество товара %s, который не найден", item_id)
        return JsonResponse({
            'status': 'error',
            'message': 'Товар не найден'
        }, status=404)

    except ValueError:
        logger.warning("⚠️ Некорректное значение количества")
        return JsonResponse({
            'status': 'error',
            'message': 'Некорректное количество'
        }, status=400)


@login_required(login_url='login')
@require_http_methods(["POST"])
def clear_cart(request):
    """Удаляет все товары из корзины пользователя"""
    try:
        cart_count = CartItem.objects.filter(user=request.user).count()
        CartItem.objects.filter(user=request.user).delete()
        logger.info("🧹 Корзина очищена (%s товаров удалено)", cart_count)

        return JsonResponse({
            'status': 'success',
            'message': '✓ Корзина очищена',
            'cart_count': 0
        })

    except Exception as e:
        logger.error("❌ Ошибка при очистке корзины: %s", str(e), exc_info=True)
        return JsonResponse({
            'status': 'error',
            'message': f'Ошибка: {str(e)}'
        }, status=500)
