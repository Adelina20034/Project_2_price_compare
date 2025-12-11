from django.core.management.base import BaseCommand
from scraping.scrapers import smart_product_search

class Command(BaseCommand):
    help = 'Умный поиск и парсинг по запросу'

    def add_arguments(self, parser):
        parser.add_argument('query', type=str, nargs='?', default='молоко', 
                          help='Поисковый запрос (по умолчанию: молоко)')

    def handle(self, *args, **options):
        query = options['query']
        self.stdout.write(f"🔍 Запуск умного поиска: '{query}'")
        matches = smart_product_search(query)
        self.stdout.write(self.style.SUCCESS(f'✅ Найдено {len(matches)} совпадений'))
