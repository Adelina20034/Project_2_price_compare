from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class Category(models.Model):
    name = models.CharField("Название категории",
                            max_length=100, unique=True, db_index=True)
    last_parsed_at = models.DateTimeField(
        "Последний парсинг",
        null=True,
        blank=True,
        help_text="Время последнего успешного парсинга"
    )
    is_parsing = models.BooleanField(
        "Идет парсинг",
        default=False,
        help_text="Флаг текущего статуса парсинга"
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    def __str__(self):
        return self.name

    @property
    def needs_update(self, hours=24):
        """
        Проверяет, нужно ли обновить данные категории
        По умолчанию обновляет если прошло более 24 часов
        """
        if not self.last_parsed_at:
            # Если никогда не парсилась - нужно обновить
            return True

        time_diff = timezone.now() - self.last_parsed_at
        return time_diff > timedelta(hours=hours)

    @property
    def hours_since_last_parse(self):
        """Сколько часов прошло с последнего парсинга"""
        if not self.last_parsed_at:
            return None
        time_diff = timezone.now() - self.last_parsed_at
        return time_diff.total_seconds() / 3600


class Product(models.Model):
    categories = models.ManyToManyField(
        Category,
        related_name='products',
        blank=True,
        help_text="Товар может относиться к нескольким категориям"
    )
    name_pyat = models.CharField(
        "Название в Пятерочке", max_length=255, null=True, blank=True, db_index=True)
    price_pyat = models.DecimalField(
        "Цена в Пятерочке", max_digits=10, decimal_places=2, null=True, blank=True)
    name_mag = models.CharField(
        "Название в Магните", max_length=255, null=True, blank=True, db_index=True)
    price_mag = models.DecimalField(
        "Цена в Магните", max_digits=10, decimal_places=2, null=True, blank=True)
    similarity = models.IntegerField(
        "Сходство", default=0, help_text="Процент сходства между товарами (0-100)")

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    def __str__(self):
        name = self.name_pyat or self.name_mag or "Товар"
        return f"{name}"

    @property
    def has_pyat(self):
        """Есть ли товар в Пятёрочке"""
        return self.name_pyat is not None

    @property
    def has_mag(self):
        """Есть ли товар в Магните"""
        return self.name_mag is not None

    @property
    def has_both(self):
        """Есть ли товар в обоих магазинах"""
        return self.has_pyat and self.has_mag

    @property
    def price_difference(self):
        """Разница в цене"""
        if self.has_both and self.price_pyat and self.price_mag:
            return abs(float(self.price_pyat) - float(self.price_mag))
        return 0

    @property
    def cheaper_store(self):
        """Какой магазин дешевле"""
        if not self.has_both:
            return None
        if self.price_pyat < self.price_mag:
            return 'pyat'
        return 'mag'

    @property
    def cheaper_store_name(self):
        """Название магазина который дешевле"""
        if self.cheaper_store == 'pyat':
            return 'Пятёрочка'
        elif self.cheaper_store == 'mag':
            return 'Магнит'
        return None

    @property
    def main_name(self):
        return self.name_pyat or self.name_mag or "Товар без названия"


class CartItem(models.Model):
    """
    Товар в корзине пользователя
    Связывает пару товаров (Product) с пользователем (User)
    """
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='cart_items')
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='cart_items')

    quantity = models.PositiveIntegerField("Количество", default=1)

    added_at = models.DateTimeField("Добавлено", auto_now_add=True)

    def __str__(self):
        return f"{self.product} - {self.user.username}"
