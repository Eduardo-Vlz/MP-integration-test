"""Cliente de Mercado Pago (solo backend; usa el Access Token) sobre el SDK oficial.

Único módulo del proyecto que habla con `api.mercadopago.com`. Aislar el cliente
aquí concentra el Access Token en un solo lugar y hace que cualquier adaptación
al contrato de MP afecte a un único archivo.

Habla con MP a través del SDK oficial `mercadopago` (no con `requests` a mano):
`customer()`, `card()` y `order()` cubren Customers, tarjetas y Orders API, y
`WebhookSignatureValidator` valida la firma del webhook.

Estructura:
- Capa HTTP: `_sdk` (instancia compartida), `_call` (no lanza) y `_ok` (lanza
  `MPError` ante `>= 400`), sobre un `RawHttpClient` propio que conserva el cuerpo
  crudo cuando la respuesta no es JSON.
- Customers y tarjetas: `get_or_create_customer`, `save_card`, `delete_card`.
- Orders: `create_order`, `get_order`, `apply_mp_order`, `refresh_order`,
  `display_status`.
- Webhook: `valid_webhook_signature`.

Las excepciones tipadas del SDK (`MPAuthenticationError`, `MPPaymentError`…)
NO salen de este módulo: se atrapan en `_call` y se reconvierten a nuestro
`MPError`, para que las vistas no tengan que conocer la jerarquía del SDK.

Referencia de request/response: docs/api.md · Estados: docs/estados-y-webhooks.md
"""
import functools

import mercadopago
import requests
from django.conf import settings
from mercadopago.config import RequestOptions
from mercadopago.errors import MercadoPagoError
from mercadopago.http.http_client import HttpClient
from mercadopago.webhook import InvalidWebhookSignatureError, WebhookSignatureValidator
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import MPCustomer, Order, SavedCard

#: Estados de la ORDER en los que ya no tiene sentido re-consultar a MP.
#: Ojo: son los estados de la *order*, no los del pago. Para decidir si hay que
#: re-consultar, usar `needs_refresh()`, que también mira `payment_status`.
FINAL_ORDER_STATUSES = {"processed", "failed", "canceled", "refunded", "expired"}

#: Estado del PAGO que todavía puede cambiar.
PENDING_PAYMENT_STATUSES = {"pending"}

#: Timeout de las peticiones a MP, en segundos. El SDK manda con 60 por defecto;
#: el proyecto siempre usó 30.
TIMEOUT_SECONDS = 30.0


class MPError(Exception):
    """Error devuelto por la API de MP.

    Expone `status_code` y `body` para que las vistas puedan construir respuestas
    con el detalle original del rechazo.
    """

    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Mercado Pago {status_code}: {body}")


class RawHttpClient(HttpClient):
    """El cliente HTTP del SDK, pero conservando el cuerpo cuando no es JSON.

    El `HttpClient` del SDK lanza `MPServerError` cuando la respuesta no se puede
    parsear como JSON, y con ella **se pierde el texto**: un 502 de un proxy que
    devuelve HTML se convertía en un body genérico con `invalid_response`. Aquí el
    texto sobrevive bajo la clave `raw`, que es lo que devolvía el cliente escrito
    a mano antes de migrar al SDK.

    Replica la lógica de `HttpClient.request` — la sesión, el adaptador de reintentos
    y la lectura del cuerpo— porque no hay otra forma de conservar el texto: el
    original lanza antes de devolverlo. Los reintentos se siguen respetando a través
    de los argumentos que `MPBase` pasa a cada llamada.

    OJO: si una versión futura del SDK cambia el contrato de `request()`, esta clase
    hay que revisarla. Es el precio de no perder el diagnóstico.
    """

    def request(  # pylint: disable=too-many-arguments
        self, method, url, maxretries=None, retry_on=None, backoff_factor=None, **kwargs
    ):
        strategy = Retry(
            total=maxretries or 0,
            status_forcelist=retry_on,
            backoff_factor=backoff_factor or 0,
        )
        http = requests.Session()
        http.mount("https://", HTTPAdapter(max_retries=strategy))
        with http as session:
            resp = session.request(method, url, **kwargs)

        result = {"status": resp.status_code, "response": None}
        if resp.status_code != 204 and resp.content:
            try:
                result["response"] = resp.json()
            except ValueError:
                # No es JSON: se conserva el texto en vez de lanzar.
                result["raw"] = resp.text
        return result


def _sdk() -> mercadopago.SDK:
    """Instancia del SDK con el Access Token de `settings`, reutilizada entre llamadas.

    Se cachea por token para no reconstruir el cliente HTTP en cada petición. La
    caché es lo que hace seguro leer `settings` aquí: Django ya está configurado
    cuando este módulo se importa.

    `max_retries=0` desactiva los reintentos automáticos del SDK (reintenta por
    defecto hasta 3 veces ante 423/424/429/5xx): un rechazo de MP debe seguir
    siendo UN resultado que mostrar, no tres llamadas extra.
    """
    return _build_sdk(settings.MP_ACCESS_TOKEN)


@functools.cache
def _build_sdk(access_token: str) -> mercadopago.SDK:
    return mercadopago.SDK(
        access_token,
        http_client=RawHttpClient(),
        request_options=RequestOptions(
            connection_timeout=TIMEOUT_SECONDS, max_retries=0
        ),
    )


def _call(method, *args, **kwargs):
    """Ejecuta una llamada del SDK y devuelve `(status_code, body)` y NUNCA lanza.

    El SDK no lanza en `>= 400`: devuelve un `MPResponse` con `status` y
    `response`. Eso permite conservar la convención del proyecto: `create_order`
    devuelve el rechazo para poder mostrarlo y el resto prefiere que salte
    `MPError`.

    Traduce además las excepciones del SDK a ese mismo par:
    - `MPConnectionError` (red caída, `status_code` 0) y `MPServerError` (body no
      JSON) también llegan como resultado, no como excepción.

    Y el caso del cuerpo no-JSON: `RawHttpClient` lo deja en `result["raw"]`, y aquí
    se convierte en `{"raw": texto}` para no perderlo.
    """
    try:
        result = method(*args, **kwargs)
    except MercadoPagoError as exc:
        return exc.status_code, exc.response or {}

    body = result.get("response")
    if body is None and result.get("raw"):
        body = {"raw": result["raw"]}
    return result.get("status", 0), body or {}


def _ok(method, *args, **kwargs):
    """Como `_call`, pero convierte cualquier respuesta `>= 400` en `MPError`."""
    status, body = _call(method, *args, **kwargs)
    if status >= 400:
        raise MPError(status, body)
    return body


# ---------- Customers / Cards ----------
def get_or_create_customer(user) -> str:
    """Devuelve el `customer_id` de MP para el usuario, creándolo si hace falta.

    Antes de crear uno, busca por email en la API de MP para reutilizar un customer
    existente: sin eso, cada reintento de pago generaría un customer duplicado.
    """
    customer = _sdk().customer()
    existing = MPCustomer.objects.filter(user=user).first()
    if existing:
        return existing.customer_id_mp

    # Si el email ya existe como customer en MP, lo reutilizamos
    found = _ok(customer.search, {"email": user.email})
    results = found.get("results") or []
    if results:
        customer_id = results[0]["id"]
    else:
        customer_id = _ok(customer.create, {"email": user.email})["id"]

    MPCustomer.objects.create(user=user, customer_id_mp=customer_id)
    return customer_id


def save_card(user, token: str) -> SavedCard:
    """Guarda la tarjeta en la cuenta de MP y persiste solo sus metadatos.

    `token` es de un solo uso. Usa `update_or_create` sobre `card_id_mp`, así que
    la operación es idempotente. La primera tarjeta del usuario queda marcada como
    `is_default`.
    """
    customer_id = get_or_create_customer(user)
    card = _ok(_sdk().card().create, customer_id, {"token": token})
    pm = card.get("payment_method") or {}
    saved, _ = SavedCard.objects.update_or_create(
        card_id_mp=str(card["id"]),
        defaults={
            "user": user,
            "first_six_digits": card.get("first_six_digits", ""),
            "last_four_digits": card.get("last_four_digits", ""),
            "expiration_month": card.get("expiration_month", 0),
            "expiration_year": card.get("expiration_year", 0),
            "payment_method_id": pm.get("id", ""),
            "payment_method_type": pm.get("payment_type_id", "credit_card"),
            "payment_method_name": pm.get("name", ""),
        },
    )
    if not SavedCard.objects.filter(user=user, is_default=True).exists():
        saved.is_default = True
        saved.save(update_fields=["is_default"])
    return saved


def delete_card(card: SavedCard):
    """Borra la tarjeta en MP y en la base local.

    Un 404 de MP se ignora: si ya no está en MP, borrarla localmente es lo
    correcto, así que la operación sigue siendo idempotente.
    """
    customer = MPCustomer.objects.filter(user=card.user).first()
    if customer:
        status, body = _call(
            _sdk().card().delete, customer.customer_id_mp, card.card_id_mp
        )
        if status >= 400 and status != 404:
            raise MPError(status, body)
    card.delete()


# ---------- Orders ----------
def create_order(payload: dict, idempotency_key: str):
    """Crea la orden en MP. Devuelve `(status_code, body)` sin lanzar excepción.

    `idempotency_key` viaja como `X-Idempotency-Key`: si la misma orden se reintenta
    por una caída de red, MP devuelve la ya creada en lugar de cobrar dos veces.

    Usa `_request` y no `_ok` a propósito, y la diferencia es la clave de la función:
    un rechazo de MP no es una excepción que propagar, es un RESULTADO que hay que
    poder mostrar al usuario (el motivo literal del rechazo). Quien llama —`views.py`
    — decide qué hacer con `status_code`.

    El valor de la idempotency key es `external_reference` de la orden local, un UUID
    generado ANTES de la llamada (`views.py`). Dos peticiones con la misma key son
    la misma orden a ojos de MP.

    La key viaja como `custom_headers` del `RequestOptions` de esta llamada, que es
    como el SDK permite sobrescribir la cabecera: por defecto el SDK genera una
    `x-idempotency-key` aleatoria en cada petición.

    OJO con un detalle del SDK que es fácil no ver: cuando se pasa un
    `RequestOptions` por llamada, **no se heredan los del cliente**. El SDK solo
    rellena el `access_token` que falte; el `connection_timeout` y el `max_retries`
    salen de los valores por defecto de `RequestOptions`, que son 60 s y 3
    reintentos. Por eso aquí se repiten los dos: sin ellos el cobro —la petición
    más importante— se iría con 60 segundos y con los reintentos que este módulo
    desactivó a propósito.

    Referencia del contrato: https://www.mercadopago.com.mx/developers/es/reference/orders/online-payments/create-a-order
    """
    return _call(
        _sdk().order().create,
        payload,
        RequestOptions(
            connection_timeout=TIMEOUT_SECONDS,
            max_retries=0,
            custom_headers={"x-idempotency-key": idempotency_key},
        ),
    )


def get_order(mp_order_id: str):
    """Consulta una orden en MP. Lanza `MPError` si falla.

    A diferencia de `create_order`, aquí un error sí es una excepción: si no se puede
    saber cómo está la orden, no hay valor que devolver. Quien llama
    (`OrderDetailView`, `WebhookView`) decide si propaga o responde con lo último
    que tiene guardado.
    """
    return _ok(_sdk().order().get, mp_order_id)


def apply_mp_order(order: Order, body: dict):
    """Copia el estado de la order de MP a nuestra base.

    Traduce el JSON de MP a las cuatro columnas que la orden local mantiene:

    - `mp_order_id` ← `body["id"]`: el identificador de MP. Sin él no se puede
      re-consultar ni cancelar, así que es lo primero que se guarda.
    - `status` ← `body["status"]`: el estado de la ORDER (`processed`, `failed`…).
    - `payment_status` ← el estado del PAGO, que vive un nivel más abajo, dentro de
      `transactions.payments[0]`. Son cosas distintas: una order puede estar
      `processed` mientras su pago sigue `pending`, y esa diferencia es justamente
      la que `display_status` traduce para la UI.
    - `status_detail`: el texto del rechazo, útil para depurar.

    El `[]` en los defaults hace que, si MP omite un campo, se conserve el valor
    anterior en lugar de borrarlo. `status_detail` se trunca a 200 caracteres, el
    límite del campo en el modelo.
    """
    payments = (body.get("transactions") or {}).get("payments") or []
    payment = payments[0] if payments else {}
    order.mp_order_id = body.get("id", order.mp_order_id)
    order.status = body.get("status", order.status)
    order.payment_status = payment.get("status", "")
    order.status_detail = (payment.get("status_detail") or body.get("status_detail") or "")[:200]
    order.save()


def refresh_order(order: Order):
    """Re-consulta la orden en MP y actualiza la local. No hace nada si no hay `mp_order_id`.

    Es el patrón de sincronización del proyecto y lo usan dos callers:

    - El webhook (`views.py:340`), que nunca confía en el payload y re-consulta.
    - El polling de la página de detalle (`views.py:305`), para que el frontend
      reciba el estado más fresco en cada GET.

    Si la orden nunca llegó a MP (falló antes del POST), no hay nada que consultar:
    por eso la guarda inicial.
    """
    if not order.mp_order_id:
        return order
    apply_mp_order(order, get_order(order.mp_order_id))
    return order


def display_status(order: Order) -> str:
    """Normaliza el estado de MP a `approved | pending | rejected | refunded | created`.

    Existe para que el frontend no tenga que conocer la taxonomía de MP, mientras
    `Order.status` y `Order.payment_status` conservan los valores crudos.

    La condición `and order.mp_order_id` distingue "pendiente de MP" de "todavía
    no se envió a MP", que no son lo mismo.

    **El estado del pago se consulta primero, y es lo correcto por una razón
    concreta:** una order puede estar `processed` mientras su pago sigue `pending`.
    Si solo se mirara `order.status`, ese caso devolvería `approved` y la interfaz
    mostraría como pagado un cobro que todavía no se ha liquidado, el polling no se
    rearmaría (solo se rearma para `pending`) y el carrito ya se habría vaciado. Los
    dos niveles existen en el modelo justamente porque no siempre coinciden.

    Solo se adelantan los dos estados que son inequívocos —`pending` y `rejected`—.
    Cualquier otro valor de `payment_status` cae a la cadena de abajo, que decide
    con el estado de la order.
    """
    if order.payment_status == "pending":
        return "pending"
    if order.payment_status == "rejected":
        return "rejected"

    if order.status == "processed":
        return "approved"
    if order.status in {"failed", "canceled", "expired"}:
        return "rejected"
    if order.status == "refunded":
        return "refunded"
    if order.status in {"created", "processing", "action_required"} and order.mp_order_id:
        return "pending"
    return "created"


def needs_refresh(order: Order) -> bool:
    """¿Vale la pena re-consultar a MP el estado de esta orden?

    Es el otro mitad del mismo problema que `display_status`: decidir solo con
    `order.status` falla cuando la order está `processed` —un estado final— pero su
    pago sigue `pending`. En ese caso hay que volver a preguntar, porque el estado
    que ve la interfaz (`display_status`) es `pending` y el polling del frontend va a
    seguir preguntando: si el backend no refrescara, el polling serviría un valor
    congelado indefinidamente.

    Los dos casos negatively:

    - Sin `mp_order_id` la orden todavía no se envió a MP: no hay nada que consultar.
    - `payment_status` pendiente gana siempre, porque un pago sin liquidar todavía
      puede pasar a `approved` o a `rejected`.
    """
    if not order.mp_order_id:
        return False
    if order.payment_status in PENDING_PAYMENT_STATUSES:
        return True
    return order.status not in FINAL_ORDER_STATUSES


# ---------- Webhook ----------
def valid_webhook_signature(request, data_id: str) -> bool:
    """Valida la firma `x-signature` del webhook.

    Si `MP_WEBHOOK_SECRET` está vacío devuelve `True`: atajo de pruebas documentado,
    que deja el endpoint abierto a cualquier llamada.

    Delega el HMAC-SHA256 en `WebhookSignatureValidator` del SDK, que compara con
    `hmac.compare_digest` (tiempo constante) y encapsula sus fallos en
    `InvalidWebhookSignatureError`; aquí eso se traduce a un simple `False`, que es
    lo que la vista espera.

    Dos detalles NO negociables:
    - `data_id` se pasa a minúsculas: MP lo envía así en la firma aunque el body
      pueda traer otro formato, y el validador del SDK lo usa tal cual.
    - No se pasa `tolerance_seconds`: el SDK puede rechazar por reloj desviado, y
      hasta ahora el proyecto no ha validado el timestamp. Añadirlo en pruebas
      rechazaría notificaciones legítimas.
    """
    secret = settings.MP_WEBHOOK_SECRET
    if not secret:
        return True
    try:
        WebhookSignatureValidator.validate(
            request.headers.get("x-signature", ""),
            request.headers.get("x-request-id", ""),
            str(data_id).lower(),
            secret,
        )
    except InvalidWebhookSignatureError:
        return False
    return True
