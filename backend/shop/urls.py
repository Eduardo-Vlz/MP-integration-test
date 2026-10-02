"""Tabla de rutas de la app, montada bajo `/api/` por `config/urls.py`.

Vistas y endpoint:

- `LoginView`           → `POST   auth/login/`
- `ConfigView`          → `GET    config/`
- `ProductListView`     → `GET    products/`
- `CartView`            → `GET|POST|DELETE       cart/`
- `CartItemView`        → `PATCH|DELETE           cart/<product_id>/`
- `CardListView`        → `GET|POST               cards/`
- `CardDetailView`      → `DELETE                 cards/<pk>/`
- `OrderListCreateView` → `GET|POST               orders/`
- `OrderDetailView`     → `GET                    orders/<pk>/`
- `WebhookView`         → `POST                   webhooks/mp/`

Referencia completa: docs/api.md
"""
from django.urls import path

from . import views

urlpatterns = [
    path("auth/login/", views.LoginView.as_view()),
    path("config/", views.ConfigView.as_view()),
    path("products/", views.ProductListView.as_view()),
    path("cart/", views.CartView.as_view()),
    path("cart/<int:product_id>/", views.CartItemView.as_view()),
    path("cards/", views.CardListView.as_view()),
    path("cards/<int:pk>/", views.CardDetailView.as_view()),
    path("orders/", views.OrderListCreateView.as_view()),
    path("orders/<int:pk>/", views.OrderDetailView.as_view()),
    path("webhooks/mp/", views.WebhookView.as_view()),
]
