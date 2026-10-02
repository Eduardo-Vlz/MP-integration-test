"""Comando `python manage.py seed_products`: crea 6 productos de ejemplo.

Idempotente: usa `get_or_create` sobre el `name`, así que ejecutarlo dos veces no
duplica nada. Imprime cuántos creó realmente, no cuántos hay en total.
"""
from django.core.management.base import BaseCommand

from shop.models import Product

#: `(name, description, price, emoji)` de los productos de ejemplo.
PRODUCTS = [
    ("Playera básica", "Algodón 100%", "199.00", "👕"),
    ("Taza de cerámica", "350 ml", "129.50", "☕"),
    ("Audífonos", "Bluetooth", "499.00", "🎧"),
    ("Mochila", "Impermeable", "650.00", "🎒"),
    ("Libreta", "Tapa dura", "89.90", "📓"),
    ("Botella térmica", "750 ml", "279.00", "🧴"),
]


class Command(BaseCommand):
    help = "Crea productos de ejemplo"

    def handle(self, *args, **options):
        created = 0
        for name, desc, price, emoji in PRODUCTS:
            _, was_created = Product.objects.get_or_create(
                name=name, defaults={"description": desc, "price": price, "emoji": emoji}
            )
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Productos creados: {created}"))
