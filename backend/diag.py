"""SCRIPT DE DEPURACIÓN SUELTO. No forma parte de la app.

Se usó una sola vez para responder una pregunta concreta: ¿por qué
`get_or_create_customer` no reutiliza el customer entre sesiones de prueba?

Para cada email de prueba hace las DOS llamadas que hace `mp.get_or_create_customer`
—`GET /v1/customers/search` y, si no encuentra nada, `POST /v1/customers`— para ver
qué respondía Mercado Pago en cada caso.

No lo ejecuta nadie: la app llama a `shop/mp.py`, que ya hace exactamente esto.
Para reproducir una duda de customers, usa `mp.get_or_create_customer` en el admin o
en `python manage.py shell`, que además lee el Access Token de `backend/.env` solo.

Uso (requiere el venv activo):
    python manage.py shell -c "from django.conf import settings; print(settings.MP_ACCESS_TOKEN[:8])"

Ojo: `from django.conf import settings` solo funciona con `DJANGO_SETTINGS_MODULE`
configurado, de ahí que este archivo esté pensado para correrse con
`python manage.py shell < diag.py`, no con `python diag.py`.
"""
import json

import requests
from django.conf import settings as s

H = {"Authorization": "Bearer " + s.MP_ACCESS_TOKEN, "Content-Type": "application/json"}
BASE = "https://api.mercadopago.com"
#: Sin timeout, `requests` espera indefinidamente y el script parece colgado
#: cuando la red o MP se cuelgan. `shop/mp.py` usa el mismo valor.
TIMEOUT = 30
emails = ["test_payer_2624743753@testuser.com", "test_payer_1234567@testuser.com"]


def show(label, r):
    """Imprime método, status y un recorte del cuerpo, tolerando respuestas no-JSON."""
    try:
        body = json.dumps(r.json(), ensure_ascii=False)[:350]
    except ValueError:
        body = r.text[:350]
    print(f"{label}: {r.status_code} {body}\n")


for e in emails:
    print("=====", e)
    # SEARCH: debe devolver el customer si ya existe para ese email.
    show(
        "SEARCH ",
        requests.get(f"{BASE}/v1/customers/search", headers=H,
                     params={"email": e}, timeout=TIMEOUT),
    )
    # CREATE: si SEARCH no devuelve nada, este es el camino que sigue mp.py.
    show("CREATE ", requests.post(f"{BASE}/v1/customers", headers=H,
                                  json={"email": e}, timeout=TIMEOUT))