"""Serializers: traducen modelos → JSON hacia el frontend.

Su función principal no es validar (eso lo hacen las vistas con `get_object_or_404`
y controles explícitos) sino **calcular** campos derivados en el momento de
serializar: `subtotal` y `display_status`.

Tipos equivalentes en el frontend: docs/api.md
"""
from rest_framework import serializers

from . import mp
from .models import CartItem, Order, OrderItem, Product, SavedCard


class ProductSerializer(serializers.ModelSerializer):
    """Campos públicos del catálogo."""

    class Meta:
        model = Product
        fields = ["id", "name", "description", "price", "emoji", "stock"]


class CartItemSerializer(serializers.ModelSerializer):
    """Línea de carrito con el producto anidado y el subtotal calculado."""

    product = ProductSerializer(read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ["id", "product", "quantity", "subtotal"]

    def get_subtotal(self, obj):
        """Precio por cantidad en formato de 2 decimales, calculado con `Decimal`."""
        return f"{obj.product.price * obj.quantity:.2f}"


class SavedCardSerializer(serializers.ModelSerializer):
    """Metadatos de la tarjeta guardada.

    El orden de `fields` es también una barrera: cualquier campo sensible nuevo
    tendría que añadirse explícitamente para exponerse.
    """

    class Meta:
        model = SavedCard
        fields = [
            "id", "card_id_mp", "first_six_digits", "last_four_digits", "expiration_month",
            "expiration_year", "payment_method_id", "payment_method_type", "payment_method_name",
            "is_default",
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    """Línea de la orden. Aplana `product.name` para no repetir el nombre en cada línea."""

    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = OrderItem
        fields = ["product_name", "quantity", "unit_price"]


class OrderSerializer(serializers.ModelSerializer):
    """Orden con sus items y el estado normalizado para la UI.

    Expone a la vez los valores crudos de MP (`status`, `payment_status`,
    `status_detail`) y el derivado (`display_status`): el primero sirve para
    depurar, el segundo para pintar.
    """

    items = OrderItemSerializer(many=True, read_only=True)
    display_status = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "total", "mp_order_id", "status", "payment_status", "status_detail",
            "display_status", "created_at", "items",
        ]

    def get_display_status(self, obj):
        """Normaliza el estado de MP. Es el único punto donde la UI depende de MP."""
        return mp.display_status(obj)
