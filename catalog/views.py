from django.shortcuts import render
from scraping.scrapers import smart_product_search


def product_list(request):
    query = request.GET.get('q', '').strip()
    pairs = []
    pyat_only = []
    magnit_only = []
    pairs_count = 0
    pyat_single_count = 0
    magnit_single_count = 0
    total_products = 0
    error_message = None

    if len(query) > 2:
        try:
            result = smart_product_search(query)

            if result and isinstance(result, dict):
                # result['pairs'] уже список, берём его как есть
                raw_pairs = result.get('pairs', [])
                pairs = raw_pairs  # Просто копируем список пар

                # Обрабатываем pyat_single
                raw_pyat = result.get('pyat_single', [])
                pyat_only = []
                for item in raw_pyat:
                    if isinstance(item, dict) and 'id' in item:
                        pyat_only.append(item)
                    elif isinstance(item, dict):
                        item['id'] = None
                        pyat_only.append(item)

                # Обрабатываем magnit_single
                raw_magnit = result.get('magnit_single', [])
                magnit_only = []
                for item in raw_magnit:
                    if isinstance(item, dict) and 'id' in item:
                        magnit_only.append(item)
                    elif isinstance(item, dict):
                        item['id'] = None
                        magnit_only.append(item)

                pairs_count = len(pairs)
                pyat_single_count = len(pyat_only)
                magnit_single_count = len(magnit_only)
                total_products = len(pairs) * 2 + \
                    len(pyat_only) + len(magnit_only)
            else:
                error_message = "Парсер вернул None или не словарь!"

        except Exception as e:
            error_message = f"Ошибка при поиске: {str(e)}"
            import traceback
            traceback.print_exc()

    context = {
        'query': query,
        'pairs': pairs,
        'pyat_only': pyat_only,
        'magnit_only': magnit_only,
        'pairs_count': pairs_count,
        'pyat_single_count': pyat_single_count,
        'magnit_single_count': magnit_single_count,
        'total_products': total_products,
        'error_message': error_message,
    }

    return render(request, 'catalog/product_list.html', context)
