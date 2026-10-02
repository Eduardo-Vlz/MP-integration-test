"""Registros en el admin de Django.

Es la herramienta principal de depuración: permite inspeccionar `status_detail`
con el motivo textual del rechazo de MP sin abrir el navegador.

Refleja cambios en los modelos (p. ej. `status_detail` en `OrderAdmin`), que
Django avisa mediante `makemigrations --check`.
"""
from django.contrib import admin

from .models import CartItem, MPCustomer, Order, OrderItem, Product, SavedCard


class OrderItemInline(admin.TabularInline):
    """Muestra los items dentro de la orden, sin salir de su página."""

    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Órdenes con sus items en línea y el detalle del rechazo siempre visible."""

    list_display = ("id", "user", "total", "status", "payment_status", "status_detail", "mp_order_id", "created_at")
    inlines = [OrderItemInline]


@admin.register(SavedCard)
class SavedCardAdmin(admin.ModelAdmin):
    """Tarjetas guardadas. Solo se ven metadatos: no hay nada sensible que filtrar."""

    list_display = ("id", "user", "payment_method_name", "last_four_digits", "card_id_mp", "is_default")


admin.site.register(Product)
admin.site.register(CartItem)
admin.site.register(MPCustomer)
