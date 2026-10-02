"""SCRIPT DE DEPURACIÓN SUELTO. No forma parte de la app.

Comprueba si el error al crear un customer venía de las credenciales y no del email:
crea UN customer con un Access Token de PRODUCCIÓN, en vez de con el de pruebas de
`backend/.env`, e imprime `live_mode` junto con `message`/`cause` para distinguir un
`401` de credenciales de un `400` por email inválido.

**No necesitas este archivo para nada del proyecto**, y hay dos razones para no
usarlo:

1. El resto del proyecto está en el entorno de pruebas (`TEST-`). Ejecutarlo exige
   tener a mano un token de producción, y el repositorio no debe contener uno.
2. Crear customers reales en la cuenta de producción es una acción con efecto
   externo. Para lo mismo basta `mp.get_or_create_customer(user)` con el token de
   pruebas, que además reutiliza el customer si ya existe.

Si aun así necesitas reproducirlo, el token NO se escribe en el archivo: se pide por
`getpass` para que no quede en el historial del shell ni en un `.py`.

Uso (con el venv activo; lee `settings` por variable de entorno, no importa Django):
    python diag2.py
"""
import getpass
import json

import requests

# `getpass` oculta lo tecleado en consola y devuelve "" si no hay terminal interactiva.
token = getpass.getpass("Pega el Access Token de PRODUCCION (no se mostrará): ").strip()
H = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
r = requests.post(
    "https://api.mercadopago.com/v1/customers",
    headers=H,
    json={"email": "test_payer_1234567@testuser.com"},
    timeout=30,  # sin esto la llamada puede colgarse para siempre
)
d = r.json()
# `live_mode` dice si MP nos reconoció como cuenta real o de pruebas; los demás
# campos son el diagnóstico del rechazo cuando status != 201.
print(
    r.status_code,
    json.dumps(
        {k: d.get(k) for k in ("id", "email", "live_mode", "message", "cause")},
        ensure_ascii=False,
    ),
)