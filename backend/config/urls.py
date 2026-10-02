"""Rutas raíz del proyecto.

El admin sirve para inspeccionar órdenes y tarjetas guardadas durante las pruebas;
todo el API cuelga de `/api/` y se delega en `shop.urls`.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("shop.urls")),
]
