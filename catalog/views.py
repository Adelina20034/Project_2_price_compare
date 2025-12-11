from django.shortcuts import render
from .models import Product, Price
from scraping.scrapers import smart_product_search

def product_list(request):
    query = request.GET.get('q', '').strip()
    matches = []
    
    if len(query) > 2:  # Минимум 3 символа для поиска
        matches = smart_product_search(query)
    
    return render(request, 'catalog/product_list.html', {
        'query': query,
        'matches': matches
    })

def product_detail(request, pk):
    product = Product.objects.get(pk=pk)
    prices = Price.objects.filter(product=product).order_by('price')
    
    return render(request, 'catalog/product_detail.html', {
        'product': product, 
        'prices': prices
    })
