"""Modelos de la tienda.

Detalle campo por campo y diagrama de relaciones: docs/modelo-de-datos.md
"""
import uuid

from django.conf import settings
from django.db import models


class MPCustomer(models.Model):
    """Un customer de Mercado Pago por usuario.

    Existe para no crear un customer nuevo en cada intento de pago. `OneToOne`
    porque un usuario tiene exactamente uno; `customer_id_mp` es único global
    porque lo es en todo Mercado Pago, no solo entre usuarios de esta app.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mp_customer")
    customer_id_mp = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} -> {self.customer_id_mp}"


class SavedCard(models.Model):
    """Solo metadatos no sensibles. Nunca se guarda número completo ni CVV.

    El `card_id_mp` es lo que permite generar un token con `cardId` al pagar; el
    resto de campos existe solo para mostrar la tarjeta en la UI.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cards")
    card_id_mp = models.CharField(max_length=64, unique=True)
    first_six_digits = models.CharField(max_length=6, blank=True)
    last_four_digits = models.CharField(max_length=4)
    expiration_month = models.PositiveSmallIntegerField()
    expiration_year = models.PositiveSmallIntegerField()
    payment_method_id = models.CharField(max_length=30)      # visa, master, amex...
    payment_method_type = models.CharField(max_length=30)    # credit_card, debit_card
    payment_method_name = models.CharField(max_length=50)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.payment_method_name} ****{self.last_four_digits}"


class Product(models.Model):
    """Catálogo de la tienda. Lo único que no depende de Mercado Pago.

    `price` es `Decimal` y nunca `float`: los importes no toleran errores de coma
    flotante. `stock` existe pero no se descuenta al comprar.
    """

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    emoji = models.CharField(max_length=8, blank=True, default="📦")
    stock = models.PositiveIntegerField(default=100)

    def __str__(self):
        return self.name


class CartItem(models.Model):
    """Una línea del carrito. El carrito es la colección de líneas del usuario.

    `unique_together` garantiza una sola línea por producto, lo que permite que
    `CartView.post` incremente la cantidad existente en vez de duplicarla.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("user", "product")


class Order(models.Model):
    """Cabecera de una orden de compra, desde el intento de cobro hasta el estado final.

    El ciclo de vida de una orden:
    1. Se persiste con `total` recalculado y `external_reference` como UUID.
    2. Se envía a MP con ese UUID como `X-Idempotency-Key`.
    3. `mp_order_id`, `status` y `payment_status` se van rellenando desde la API.

    `status` y `payment_status` guardan los valores CRUDOS de MP; el estado
    normalizado para la UI (`display_status`) se calcula al serializar, no se
    persiste, para no perder el detalle técnico.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    total = models.DecimalField(max_digits=10, decimal_places=2)
    external_reference = models.UUIDField(default=uuid.uuid4, unique=True)
    mp_order_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=30, default="created")          # estado de la order en MP
    payment_status = models.CharField(max_length=30, blank=True)         # estado del pago dentro de la order
    status_detail = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.pk} ({self.status})"


class OrderItem(models.Model):
    """Una línea de la orden.

    `unit_price` duplica el precio a propósito: si mañana cambia el precio del
    producto, las órdenes antiguas deben seguir mostrando lo que se pagó.

    `product` usa `PROTECT` en lugar de `CASCADE` para que borrar un producto ya
    vendido no destruya en cascada el historial de órdenes; convierte el borrado en
    un error claro en vez de una pérdida silenciosa de datos.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
