"""SCRIPT DE DEPURACIÓN SUELTO. No forma parte de la app.

Comprueba qué emails acepta Mercado Pago para crear un customer, porque el proyecto
exige el patrón `test_payer_<dígitos>@testuser.com` (`TEST_EMAIL_RE` en
`backend/shop/views.py:33`) y no estaba claro si el filtro era del login o también
de la API.

Método: lanza `POST /v1/customers` con cuatro formatos de email distintos y compara
los status. Con el Access Token de pruebas de `backend/.env`, así que no toca la
cuenta de producción.

Resultado esperado de la prueba: los emails que no son del usuario de pruebas
(`testuser.com`) se rechazan, porque el customer solo puede pertenecer al comprador
de prueba.

Uso (con el venv activo):
    python manage.py shell < diag3.py

Igual que `diag.py`, importa `django.conf.settings`, así que necesita
`DJANGO_SETTINGS_MODULE`; por eso no se ejecuta con `python diag3.py`.
"""
import json

import requests
from django.conf import settings as s

H = {"Authorization": "Bearer " + s.MP_ACCESS_TOKEN, "Content-Type": "application/json"}
emails = [
    "comprador.prueba.mp1@example.com",  # email normal
    "compradorPrueba@gmail.com",  # email normal
    "test_user_1234567@testuser.com",  # formato clásico de usuarios de prueba
    "test_payer_9876543210@testuser.com",  # formato de la doc
]
for e in emails:
    r = requests.post(
        "https://api.mercadopago.com/v1/customers",
        headers=H,
        json={"email": e},
        timeout=30,  # sin esto la llamada puede colgarse para siempre
    )
    d = r.json()
    print(
        e,
        "->",
        r.status_code,
        json.dumps(
            {k: d.get(k) for k in ("id", "live_mode", "message")}, ensure_ascii=False
        ),
    )