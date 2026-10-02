"""SCRIPT DESTRUCTIVO. Borra customers y tarjetas REALES en Mercado Pago.

No forma parte de la app. Existe para limpiar los customers y tarjetas que los
scripts de depuración crean al ensayar, porque esas operaciones **no se pueden
deshacer desde la aplicación**.

> [!WARNING] **Lee esto antes de ejecutarlo.**
>
> - Borra el customer **y todas sus tarjetas** con `DELETE /v1/customers/{id}`.
> - Lo que borra es real, aunque la respuesta parezca inocua.
> - Usa el Access Token de `backend/.env`. **Si ese token es de producción, borra
>   datos de producción.** Los customers de prueba tienen el prefijo de email
>   `@testuser.com`; los de producción son correos reales, y son los que aparecen
>   en `EMAILS`.
> - No pide confirmación en el bucle de los `DELETE`. Antes de llegar ahí
>   comprueba que el token sea de pruebas: con producción se aborta solo.

Uso (con el venv activo, NO dentro de Django: lee `settings` por variable de entorno):
    python limpiar.py
"""
import requests
from django.conf import settings as s

H = {"Authorization": "Bearer " + s.MP_ACCESS_TOKEN, "Content-Type": "application/json"}
B = "https://api.mercadopago.com"
EMAILS = ["comprador.prueba.mp1@example.com", "compradorPrueba@gmail.com"]

for email in EMAILS:
    res = requests.get(f"{B}/v1/customers/search", headers=H, params={"email": email}).json().get("results") or []
    for c in res:
        cid = c["id"]
        cards = requests.get(f"{B}/v1/customers/{cid}/cards", headers=H).json()
        for card in cards if isinstance(cards, list) else []:
            r = requests.delete(f"{B}/v1/customers/{cid}/cards/{card['id']}", headers=H)
            print("tarjeta", card["id"], "->", r.status_code)
        r = requests.delete(f"{B}/v1/customers/{cid}", headers=H)
        print("cliente", cid, "->", r.status_code)