from django.db import models

class Store(models.Model):
    name = models.CharField("Название", max_length=100)
    url = models.URLField("Сайт", blank=True)

    def __str__(self):
        return self.name

class Product(models.Model):
    name = models.CharField("Название", max_length=255)
    # category = models.CharField("Категория", max_length=100, blank=True)
    # image_url = models.URLField("Картинка", blank=True)

    def __str__(self):
        return self.name

class Price(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='prices')
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    price = models.DecimalField("Цена", max_digits=10, decimal_places=2)
    date = models.DateTimeField("Дата", auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} - {self.price}"
