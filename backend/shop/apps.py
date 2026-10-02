"""Configuración de la app `shop` que Django carga al arrancar.

Django descubre esta clase automáticamente porque `INSTALLED_APPS` incluye
`"shop"` (settings.py:35). Si el nombre fuera `"shop.apps.ShopConfig"` habría que
escribirlo explícitamente; al omitirlo, Django busca `apps.py` por su cuenta.

El archivo casi no puede decir nada: casi todo el comportamiento de la app está en
`models.py`, `views.py` y `mp.py`. Su única línea que importa es
`default_auto_field`.
"""
from django.apps import AppConfig


class ShopConfig(AppConfig):
    """Configuración de la app: qué clave primaria por defecto usan sus modelos."""

    # Sin esta línea, Django 3.2+ usaría `AutoField` y emitiría el aviso
    # `models.W042`. El modelo concreto importa poco; lo que importa es que el
    # tipo de clave primaria sea explícito y estable entre migraciones.
    default_auto_field = "django.db.models.BigAutoField"

    # El nombre del paquete. Debe coincidir con el directorio `shop/`, no con el
    # de la clase: por eso es "shop" y no "ShopConfig".
    name = "shop"