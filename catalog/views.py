from pprint import pprint
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db.models import Q
import threading
import time

from scraping.scrapers import smart_product_search, save_results_to_db
from .models import Category, Product, CartItem

PARSING_CACHE = {}
CACHE_TIMEOUT = 43200
debug = True


def is_parsing_active(query):
    """
    Проверяет есть ли активный парсинг для этого запроса
    Возвращает True если парсинг запущен менее 1 часа назад
    """
    if query not in PARSING_CACHE:
        return False

    cached_time = PARSING_CACHE[query]['timestamp']
    elapsed = time.time() - cached_time

    # Если прошло больше часа - забываем о парсинге
    if elapsed > CACHE_TIMEOUT:
        del PARSING_CACHE[query]
        return False

    return True


def mark_parsing_started(query):
    """
    Отмечает что парсинг запущен для этого запроса
    """
    PARSING_CACHE[query] = {
        'timestamp': time.time(),
        'thread_id': threading.current_thread().ident
    }


def run_parser(query):
    """Запускает парсинг"""
    try:
        print(f"\n🔍 НАЧАЛО ПАРСИНГА: {query}")

        # Парсим
        result = smart_product_search(query)

        # Сохраняем в БД
        save_results_to_db(result, query)

        print(f"✅ ПАРСИНГ ЗАВЕРШЁН: {query}")

    except Exception as e:
        print(f"❌ ОШИБКА при парсинге {query}: {e}")
        import traceback
        traceback.print_exc()


def product_list(request):
    query = request.GET.get('q', '').strip()

    pairs = None
    pyat_only = None
    mag_only = None
    total_products = 0
    is_searching = False

    if len(query) > 2:
        is_searching = True

        if not is_parsing_active(query):
            # Отмечаем что парсинг запущен
            mark_parsing_started(query)

            # Запускаем в отдельном потоке
            thread = threading.Thread(
                target=run_parser,
                args=(query,),
                daemon=True
            )
            thread.start()
            print(f"✨ Парсинг запущен для '{query}'")
        else:
            print(f"⏭️  Парсинг уже запущен для '{query}', пропускаем")

        category, category_created = Category.objects.get_or_create(
            name=query.capitalize())
        if category_created:
            print(f"✨ Создана новая категория: '{category.name}'")
        else:
            print(f"🏷️  Используется категория: '{category.name}'")

        if category:
            products = category.products.all().order_by('-updated_at')

            if debug:
                print(f"🏷️ Категория: {category}")
                print(f"📦 Товаров в категориях: {products.count()}")
        else:
            products = Product.objects.all().filter(
                Q(name_pyat__icontains=query) |
                Q(name_mag__icontains=query)
            ).order_by('-updated_at')

        if debug:
            if products:
                pprint(products)
            else:
                print("❌ Ничего не найдено")

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

    # Товары в корзине текущего пользователя
    user_cart_ids = []
    if request.user.is_authenticated:
        user_cart_ids = CartItem.objects.filter(
            user=request.user
        ).values_list('product_id', flat=True)

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
    }
    return render(request, 'catalog/product_list.html', context)


@login_required(login_url='login')
def cart_view(request):
    """
    Страница корзины пользователя с расчетом сумм по магазинам
    """
    # Получаем все товары в корзине пользователя
    cart_items = CartItem.objects.filter(
        user=request.user).select_related('product').order_by('-added_at')

    # Расчет сумм по магазинам
    pyat_total = 0
    mag_total = 0
    total_savings = 0

    for item in cart_items:
        product = item.product

        # Пятёрочка
        if product.price_pyat:
            pyat_total += float(product.price_pyat) * item.quantity

        # Магнит
        if product.price_mag:
            mag_total += float(product.price_mag) * item.quantity

        # Экономия на этом товаре
        if product.has_both:
            savings = abs(float(product.price_pyat) -
                          float(product.price_mag)) * item.quantity
            total_savings += savings

    # Определяем какой магазин дешевле
    if pyat_total > 0 and mag_total > 0:
        cheaper_store = 'Пятёрочка' if pyat_total < mag_total else 'Магнит'
    else:
        cheaper_store = None

    context = {
        'cart_items': cart_items,
        'pyat_total': f"{pyat_total:.2f}",
        'mag_total': f"{mag_total:.2f}",
        'total_savings': f"{total_savings:.2f}",
        'cheaper_store': cheaper_store,
        'cart_count': cart_items.count(),
        'is_empty': cart_items.count() == 0,
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

        if quantity < 1:
            quantity = 1

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

        # Подсчитываем товары в корзине
        cart_count = CartItem.objects.filter(user=request.user).count()

        return JsonResponse({
            'status': 'success',
            'message': f'✓ {product.main_name} добавлен в корзину',
            'cart_count': cart_count,
            'product_id': product_id
        })

    except Exception as e:
        print(f"Ошибка при добавлении в корзину: {e}")
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

        cart_count = CartItem.objects.filter(user=request.user).count()

        return JsonResponse({
            'status': 'success',
            'message': f'✓ {product_name} удален из корзины',
            'cart_count': cart_count
        })

    except CartItem.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Товар не найден в корзине'
        }, status=404)

    except Exception as e:
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

        if quantity < 1:
            quantity = 1
        if quantity > 100:  # Максимум 100
            quantity = 100

        cart_item = CartItem.objects.get(id=item_id, user=request.user)
        cart_item.quantity = quantity
        cart_item.save()

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
        return JsonResponse({
            'status': 'error',
            'message': 'Товар не найден'
        }, status=404)

    except ValueError:
        return JsonResponse({
            'status': 'error',
            'message': 'Некорректное количество'
        }, status=400)


@login_required(login_url='login')
@require_http_methods(["POST"])
def clear_cart(request):
    """Удаляет все товары из корзины пользователя"""
    try:
        CartItem.objects.filter(user=request.user).delete()

        return JsonResponse({
            'status': 'success',
            'message': '✓ Корзина очищена',
            'cart_count': 0
        })

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Ошибка: {str(e)}'
        }, status=500)


@login_required(login_url='login')
def get_cart_count(request):
    """
    Возвращает количество товаров в корзине
    Для обновления счетчика в навигации
    """
    cart_count = CartItem.objects.filter(user=request.user).count()

    return JsonResponse({
        'cart_count': cart_count
    })
