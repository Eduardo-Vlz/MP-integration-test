"""SCRIPT DE DEPURACIÓN SUELTO. No forma parte de la app.

Recorre el flujo completo de Checkout API: buscar o crear el customer, guardar (o
reutilizar) una tarjeta, tokenizar de nuevo con `cardId` + CVV y cobrar una order.

Uso mixto, a propósito, porque cada parte sirve para una cosa distinta:

- **Pasos 1 a 4, contra el REST a mano con `requests`.** Sirven para ver **qué
  devuelve la API exactamente**, con el cuerpo crudo. Si fueran por el cliente de la
  app, un cambio de mapeo en `mp.py` escondería justo lo que hay que diagnosticar.
  El paso 3 tokeniza por REST a propósito: es el camino que reproduce el hallazgo
  E01 (tokenizar por REST con los nombres equivocados devuelve 201 sin vencimiento).
- **Paso 5, la order, con `shop/mp.py`.** Es la llamada que hace la app de verdad, así
  que comprobarla aquí valida el cliente real: el SDK, el `RawHttpClient`, el
  timeout, la `X-Idempotency-Key` y la traducción de errores. No se pierde
  visibilidad: `mp.create_order` devuelve `(status_code, body)` con el cuerpo crudo.

Uso (con el venv activo):
    python diag4.py

También funciona dentro de Django, para depurar con el contexto de la app:
    python manage.py shell < diag4.py

AVISO: con el Access Token de `backend/.env` **crea un customer y una tarjeta
reales**, y cobra una order. Usa credenciales de prueba para ensayar.
"""
import json
import os
import sys
import uuid
from pathlib import Path

import requests

# `shop.mp` importa `shop.models`, asi que hace falta Django con el registro de apps
# listo. Se hace idempotente para que el script sirva igual suelto o por `shell`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.apps import apps

if not apps.ready:
    django.setup()

from django.conf import settings as s

from shop import mp  # solo para el paso 5

PK = s.MP_PUBLIC_KEY
H = {"Authorization": "Bearer " + s.MP_ACCESS_TOKEN, "Content-Type": "application/json"}
B = "https://api.mercadopago.com"
EMAIL = "comprador.prueba.mp1@example.com"
CVV = "123"

#: Sin timeout, `requests` espera indefinidamente y el script parece colgado.
TIMEOUT = 30


def get(path, **kw):
    return requests.get(f"{B}{path}", headers=H, timeout=TIMEOUT, **kw)


def post(path, **kw):
    return requests.post(f"{B}{path}", timeout=TIMEOUT, **kw)


def show(label, r, keys=None):
    try:
        d = r.json()
    except ValueError:
        d = {"raw": r.text[:200]}
    if keys and isinstance(d, dict):
        d = {k: d.get(k) for k in keys + ["message", "error", "cause"] if k in d}
    print(f"{label}: {r.status_code} {json.dumps(d, ensure_ascii=False)[:600]}\n")
    return r.status_code, d


# 1) Cliente (reutiliza el existente)
#
# `show(..., keys=...)` imprime y devuelve SOLO esas claves, asi que pedir solo
# "paging" devuelve un dict SIN `results`: el customer parece no existir aunque
# `paging.total` diga 1. Por eso la busqueda pide las dos claves.
_, found = show("1 buscar cliente", get("/v1/customers/search", params={"email": EMAIL}),
                ["paging", "results"])
res = (found or {}).get("results") or []
if res:
    cust = res[0]["id"]
else:
    code, d = show("1 crear cliente", post("/v1/customers", headers=H, json={"email": EMAIL}), ["id"])
    cust = (d or {}).get("id")
    if not cust:
        # MP responde 400 "the customer already exist" cuando la busqueda no lo
        # encuentra. Se reintenta la busqueda antes de rendirse, porque en ese
        # caso el customer SI existe y lo que fallo fue la busqueda.
        print("   la creacion fallo; se vuelve a buscar el customer\n")
        _, found = show("1 re-buscar cliente", get("/v1/customers/search", params={"email": EMAIL}),
                        ["paging", "results"])
        res = (found or {}).get("results") or []
        cust = res[0]["id"] if res else None
    if not cust:
        raise SystemExit(f"No se pudo obtener el customer de {EMAIL}. Ultima respuesta: {d}")
print("cliente:", cust, "\n")

# 2) ¿Ya hay una tarjeta terminada en 0366? Si sí, se reutiliza
code, cards = show("2 listar tarjetas", get(f"/v1/customers/{cust}/cards"))
card_id = None
if code == 200 and isinstance(cards, list):
    for c in cards:
        if c.get("last_four_digits") == "0366":
            card_id = c["id"]
print("tarjeta existente:", card_id, "\n")

# 3) Si no existe, se tokeniza y se guarda
if not card_id:
    tok_body = {"card_number": "5474925432670366", "security_code": CVV,
                "expiration_month": 11, "expiration_year": 2030,
                "cardholder": {"name": "APRO"}}
    code, d = show("3a token de tarjeta",
                   post("/v1/card_tokens", params={"public_key": PK}, json=tok_body),
                   ["id", "last_four_digits"])
    if code == 201:
        code, d = show("3b guardar tarjeta",
                       post(f"/v1/customers/{cust}/cards", headers=H, json={"token": d["id"]}),
                       ["id", "last_four_digits", "expiration_month", "expiration_year"])
        card_id = d.get("id") if code == 201 else None

# 4) Token nuevo con tarjeta guardada (card_id + CVV)
if card_id:
    code, d = show("4 token con tarjeta guardada",
                   post("/v1/card_tokens", params={"public_key": PK},
                        json={"card_id": card_id, "security_code": CVV}),
                   ["id"])

    # 5) Order pagada con la tarjeta guardada - A TRAVES DE shop/mp.py
    #    Esta es la llamada que hace la app, asi que aqui se valida el cliente real.
    if code == 201:
        amount = "10.00"
        # Un SOLO uuid para las dos cosas. La idempotency key DEBE ser el
        # `external_reference` de la orden: si fueran distintos, MP trataria cada
        # reintento como una operacion nueva y el header no cumpliria su razon de
        # ser. Es la misma regla que aplica `shop/mp.py`.
        ref = str(uuid.uuid4())
        payload = {
            "type": "online",
            "processing_mode": "automatic",
            "external_reference": ref,
            "total_amount": amount,
            "payer": {"customer_id": cust},
            "transactions": {"payments": [{
                "amount": amount,
                "payment_method": {"id": "master", "type": "credit_card",
                                   "token": d["id"], "installments": 1},
            }]},
        }
        # `mp.create_order` devuelve `(status_code, body)` con el cuerpo CRUDO, asi
        # que no se pierde nada de la visibilidad del paso 5. Y no lanza: un 402 de
        # MP llega como valor, que es justo lo que se quiere ver aqui.
        status, body = mp.create_order(payload, idempotency_key=ref)
        print(f"5 order (via shop/mp.py, key={ref}): {status}")
        print(f"   body: {json.dumps(body, ensure_ascii=False)[:800]}\n")
        if status >= 400:
            # El app guarda esto en `Order.status_detail` y lo muestra en pantalla.
            print("   aviso: la app responde 402 cuando el pago fue rechazado, y no")
            print("          400; create_order devuelve (status, body) y no lanza.\n")
else:
    print("No hay tarjeta guardada; no se puede probar el pago.")
