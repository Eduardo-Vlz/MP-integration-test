# Backend

Django 5 + Django REST Framework. Es el dueño de tres cosas: los datos, el
cálculo del importe y el Access Token de Mercado Pago.

## `manage.py`

Punto de entrada estándar. La única línea específica del proyecto es
`DJANGO_SETTINGS_MODULE=config.settings` (`manage.py:7`).

## `config/settings.py`

Configuración única del proyecto.

| Bloque | Contenido |
|---|---|
| `.env` | Se carga con `python-dotenv` desde `BASE_DIR/.env` (línea 7). Los valores por defecto permiten arrancar sin `.env`. |
| Seguridad | `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS = ["*"]` (necesario para ngrok). |
| Apps | Las 6 de Django, DRF con `authtoken`, `corsheaders` y `shop`. |
| Middlewares | `CorsMiddleware` va **primero**, para que las preflight requests no las rechace `CsrfViewMiddleware`. |
| Base de datos | PostgreSQL, todo configurable por variables de entorno. |
| Locale | `es-mx` y `America/Mexico_City`. |
| DRF | `TokenAuthentication` + `IsAuthenticated` por defecto (líneas 76-79). |
| CORS | Regex que acepta solo `localhost` y `127.0.0.1` con cualquier puerto. |
| Mercado Pago | Las tres credenciales + `ENFORCE_TEST_EMAIL`. |

Puntos a tener en cuenta:

- `load_dotenv` se llama antes de leer cualquier variable, así que `.env` tiene
  prioridad solo si se pasa explícitamente; en la práctica sobrescribe el entorno.
- `FRONTEND_ORIGIN` aparece en `.env.example` pero **no se lee** en `settings.py`:
  la expresión regular de CORS es la que manda. Es una inconsistencia del
  repositorio, no un bug en ejecución.
- `DATABASES` no tiene fallback a SQLite: sin PostgreSQL configurado, el backend
  no arranca.

## `config/urls.py`

Solo dos rutas: `/admin/` y `/api/` (delegada a `shop.urls`).

## `config/wsgi.py` y `config/asgi.py`

Puntos de entrada estándar. El proyecto corre con el `runserver` de desarrollo, así
que ASGI no se usa; está presente por completitud.

## `shop/models.py`

Los 6 modelos del negocio. Ver [`modelo-de-datos.md`](./modelo-de-datos.md) para el
detalle campo por campo.

| Modelo | Rol |
|---|---|
| `MPCustomer` | Customer de MP asociado 1:1 a un usuario. |
| `SavedCard` | Metadatos de una tarjeta guardada. Nunca el número completo. |
| `Product` | Catálogo. |
| `CartItem` | Línea de carrito, única por `(user, product)`. |
| `Order` | Cabecera de la orden, con el estado de MP. |
| `OrderItem` | Línea de la orden, con el precio congelado en el momento de comprar. |

Detalles de diseño:

- `Order.external_reference` es un `UUIDField` con `default=uuid.uuid4` y `unique`.
  Sirve como referencia ante MP y como idempotency key.
- `OrderItem.unit_price` **duplica** el precio en lugar de leerlo de `Product`.
  Así una orden histórica no cambia si mañana editas el precio del producto.
- `OrderItem.product` usa `on_delete=PROTECT`: no se puede borrar un producto que
  ya se vendió. Los demás usan `CASCADE`.
- `SavedCard.card_id_mp` es `unique` globalmente, no solo por usuario: un
  `card_id` de MP identifica una tarjeta en todo el ecosistema.
- `related_name` en todas las FKs para poder navegar desde el usuario:
  `user.orders`, `user.cards`, `user.cart_items`, `user.mp_customer`.

## `shop/serializers.py`

Cinco serializers, todos `ModelSerializer`. Su trabajo principal no es validar
sino **calcular**: las entradas no se validan aquí porque las vistas ya lo hacen
con `get_object_or_404` y controles explícitos.

| Serializer | Aporta |
|---|---|
| `ProductSerializer` | — |
| `CartItemSerializer` | Anida el producto y añade `subtotal` con `SerializerMethodField`. |
| `SavedCardSerializer` | Solo campos no sensibles. |
| `OrderItemSerializer` | Aplana `product.name` a `product_name`. |
| `OrderSerializer` | Anida los items y añade `display_status` llamando a `mp.display_status`. |

`get_subtotal` y `get_display_status` son `SerializerMethodField`: campos que se
calculan en el momento de serializar y no se persisten.

## `shop/views.py`

Diez clases `APIView`. Detalle completo de request/response en
[`api.md`](./api.md). Aquí la estructura.

### Utilidad compartida

`mp_error_response(exc)` (línea 23) traduce una excepción `MPError` a un `502`
con el cuerpo original de MP, para que la UI pueda mostrar el motivo real del
rechazo y no un "algo salió mal" genérico.

### Permisos por vista

| Vista | Autenticación | Permiso |
|---|---|---|
| `LoginView` | ninguna | `AllowAny` |
| `ConfigView` | ninguna | `AllowAny` |
| `ProductListView` | ninguna | `AllowAny` |
| `WebhookView` | ninguna | `AllowAny` + firma HMAC |
| Resto | `Token` | `IsAuthenticated` |

### Patrones que se repiten

**Filtrar siempre por `user`.** Cada vista acota las consultas al usuario
autenticado (`CartItem.objects.filter(user=request.user)`). Es lo que impide que
un usuario vea o pague con datos de otro.

**Reutilizar el GET como respuesta.** `CartView.post`, `patch` y `delete`
terminan con `return self.get(request)` / `CartView().get(request)`. Así el
cliente siempre recibe el carrito completo tras cualquier mutación y no tiene
que hacer un segundo fetch.

### `OrderListCreateView.post`

El endpoint más complejo. Decisiones que conviene conocer:

- Calcula el total con `sum(...)` sobre `Decimal("0")`, no desde el request.
- Persiste `Order` + `OrderItem` con `bulk_create` dentro de `transaction.atomic()`
  **antes** de llamar a MP, para que quede registro aunque el cobro falle.
- Llama a `mp.create_order` (que no lanza excepción) en vez de `_ok`, porque aquí
  un rechazo de MP es un resultado esperado que hay que poder mostrar, no una
  excepción a manejar.
- Detecta el éxito comprobando `if "id" in mp_data and "status" in mp_data` en
  lugar de fiarse del código HTTP: es más robusto ante respuestas inesperadas.
- **Un pago rechazado devuelve `402`, no `201`.** Un 402 de MP **sí** trae la order
  dentro de `data`, así que la orden se persiste (con `status = "failed"` y el
  motivo en `status_detail`) pero la respuesta es **402**. Es deliberado: el
  frontend trata cualquier 2xx como éxito, y con un `201` navegaría a la pantalla de
  una orden rechazada sin mostrarle el motivo al usuario. El `400` con `mp` crudo
  queda para los rechazos que ni siquiera crean una order en MP.
- El chequeo de rechazo mira **`order.payment_status` además de `display_status`**.
  No es redundante: `display_status` da `approved` a un `processed` sin mirar el
  pago, así que una order en ese estado con el pago `rejected` se escaparía del `402`.
- Solo vacía el carrito si el resultado es `approved` o `pending`, nunca si
  falló - para que el usuario pueda reintentar con el carrito intacto.

### `OrderDetailView.get`

Un detalle sutil: si el estado de la orden **todavía puede cambiar**, re-consulta a MP. Eso
convierte un GET barato en una llamada externa, y ese es el precio de que el polling del
frontend reciba el estado más fresco. Si la llamada falla se devuelve el último estado
conocido en lugar de un error, porque un fallo de MP al *consultar* no significa que el
pago haya cambiado.

La decisión la toma `mp.needs_refresh`, no `FINAL_ORDER_STATUSES` directamente: una
orden puede estar `processed` —estado final de la *orden*— y aun así tener el pago
`pending`. En ese caso sí hay que volver a preguntar, o el polling serviría un valor
congelado indefinidamente.

## `shop/mp.py`

El único módulo que habla con `api.mercadopago.com`. Aislar el cliente en un solo
archivo tiene dos beneficios: el Access Token aparece en un único lugar, y para
adaptarse a un cambio de la API de MP hay que tocar un solo archivo.

Habla con MP mediante el **SDK oficial `mercadopago`** (`pip install mercadopago`),
no con `requests` a mano. Cada función delega en el recurso que corresponde:

| Necesidad | SDK |
|---|---|
| `GET/POST /v1/customers` | `sdk.customer().search()` / `.create()` |
| Tarjetas del customer | `sdk.card().create()` / `.delete()` |
| `POST/GET /v1/orders` | `sdk.order().create()` / `.get()` |
| Firma del webhook | `WebhookSignatureValidator` |

### Capa HTTP

| Función | Comportamiento |
|---|---|
| `_sdk()` | Instancia `mercadopago.SDK` con el Access Token de `settings`. Cacheada por token con `functools.cache`. |
| `_call(method, *args)` | Envuelve una llamada del SDK y devuelve `(status_code, body)` y **nunca lanza**. |
| `_ok(method, *args)` | Envuelve `_call` y convierte cualquier `>= 400` en `MPError`. |

La distinción es deliberada: para *crear* la orden queremos ver el rechazo
(`create_order` usa `_call`), para el resto preferimos que salte la excepción
(`_ok`).

Cuatro detalles de la configuración del SDK que hay que conocer:

- **`max_retries=0`.** El SDK reintenta por defecto hasta 3 veces ante 423/424/429/5xx.
  Se desactiva a propósito: un rechazo de MP debe ser **un** resultado que mostrar,
  no tres llamadas extra por orden.
- **`connection_timeout=30.0`.** El SDK usa 60 por defecto; el proyecto usa 30.
- **`http_client=RawHttpClient()`.** Ver la sección siguiente.

El SDK ya pone `Authorization: Bearer` y una `x-idempotency-key` aleatoria en cada
petición. Para `POST /v1/orders` esa clave se **sobrescribe** pasando un
`RequestOptions(custom_headers={"x-idempotency-key": …})` propio, que es el único
modo que el SDK ofrece de fijar esa cabecera.

### `RawHttpClient`: por qué no se usa el `HttpClient` del SDK

El `HttpClient` del SDK lanza `MPServerError` cuando la respuesta no se puede parsear
como JSON, y con la excepción **se pierde el texto**. Un `502` de un proxy que devuelve
HTML se convertía en un body genérico con `invalid_response`, que es justo la
información que hace falta para diagnosticar.

`RawHttpClient` lo resuelve conservando el texto bajo la clave `raw`, que es lo que
devolvía el cliente escrito a mano antes de migrar al SDK:

```python
class RawHttpClient(HttpClient):
    def request(self, method, url, maxretries=None, retry_on=None, backoff_factor=None, **kwargs):
        strategy = Retry(total=maxretries or 0, status_forcelist=retry_on,
                         backoff_factor=backoff_factor or 0)
        http = requests.Session()
        http.mount("https://", HTTPAdapter(max_retries=strategy))
        with http as session:
            resp = session.request(method, url, **kwargs)
        result = {"status": resp.status_code, "response": None}
        if resp.status_code != 204 and resp.content:
            try:
                result["response"] = resp.json()
            except ValueError:
                result["raw"] = resp.text      # en vez de lanzar
        return result
```

Replica la lógica de `HttpClient.request` porque no hay otra forma de conservar el
texto: el original lanza **antes** de devolverlo. Los reintentos se siguen respetando,
porque `MPBase` pasa `maxretries` y `retry_on` como argumentos públicos de cada llamada.

> [!WARNING] Esta clase es la parte más frágil del módulo: ata el proyecto al contrato de `HttpClient.request`. Si una versión futura del SDK cambia esa firma, hay que revisarla. Es el precio de no perder el diagnóstico.

`_call` es quien convierte esa clave en el body que ven las vistas:

```python
body = result.get("response")
if body is None and result.get("raw"):
    body = {"raw": result["raw"]}
return result.get("status", 0), body or {}
```

### Por qué `MPError` sigue siendo propia

El SDK tiene una jerarquía de excepciones tipadas por código HTTP
(`MPAuthenticationError`, `MPPaymentError`, `MPNotFoundError`…). `_call` las atrapa
todas y las reconvierte a `MPError(status_code, body)`, y por eso las vistas nunca
dependen de la jerarquía del SDK: si MP cambia sus clases, el frontend no se
enteraría. Además, así `MPConnectionError` (red caída, `status_code` 0) y
`MPServerError` (body no JSON) llegan también como resultado y no como excepción
incontrolada.

### `MPError`

Excepción con dos atributos públicos: `status_code` y `body`. Es lo que permite
que las vistas construyan respuestas con el detalle original de MP.

### Customers y tarjetas

`get_or_create_customer(user)`:

1. Busca un `MPCustomer` local.
2. Si no hay, consulta `sdk.customer().search({"email": …})`.
3. Si MP ya conoce ese email, reutiliza el customer (evita duplicados al reintentar
   un pago).
4. Si no, crea uno con `sdk.customer().create({"email": …})`.
5. Guarda la relación en `MPCustomer`.

`save_card(user, token)`: llama a `sdk.card().create(customer_id, {"token": token})`
y extrae el bloque `payment_method` anidado para guardar `id`, `payment_type_id` y
`name`. Usa `update_or_create`, así que es idempotente. Marca `is_default=True`
si es la primera tarjeta del usuario.

`delete_card(card)`: borra en MP y en local. Un `404` de MP se ignora a
propósito — la tarjeta ya no está en MP, así que borrarla localmente es lo
correcto.

### Orders

| Función | Nota |
|---|---|
| `create_order(payload, idempotency_key)` | Usa `_call`, no `_ok`: devuelve el rechazo para poder mostrarlo. |
| `get_order(mp_order_id)` | `sdk.order().get()` con `_ok`. |
| `apply_mp_order(order, body)` | Traduce la respuesta de MP a campos de `Order`. |
| `refresh_order(order)` | Atajo: `apply_mp_order` + `get_order`. |
| `display_status(order)` | Normaliza el estado de MP a un valor para la UI. |
| `needs_refresh(order)` | Si el estado todavía puede cambiar, o sea si hay que re-consultar a MP. |

`apply_mp_order` es donde la taxonomía de MP se concentra: extrae el primer pago
de `transactions.payments[0]` y separa el estado de la *order* del estado del
*pago*, que son cosas distintas. `status_detail` se trunca a 200 caracteres
porque el campo es `CharField(max_length=200)`.

`FINAL_ORDER_STATUSES` marca los estados de la **order** en los que ya no tiene
sentido re-consultar a MP, y `needs_refresh` lo combina con `payment_status` para
decidir de verdad. `OrderDetailView` usa `needs_refresh`, no el conjunto directamente:
una order `processed` es final, pero si su pago sigue `pending` hay que volver a
preguntar.

`display_status` mapea a cinco valores: `approved`, `pending`, `rejected`,
`refunded`, `created`. El detalle está en
[`estados-y-webhooks.md`](./estados-y-webhooks.md).

> [!IMPORTANT] Las dos funciones consultan **`payment_status` antes que `status`**, y no es decorativo: los dos niveles de estado no siempre coinciden. Una order `processed` con el pago `pending` es el caso que unió a las dos mitades de un bug que ya existía en el proyecto — `display_status` la daba por aprobada y `FINAL_ORDER_STATUSES`izaba que no hacía falta consultarla. El detalle está en [`estados-y-webhooks.md`](./estados-y-webhooks.md).

### `valid_webhook_signature`

Valida la firma del webhook. Si `MP_WEBHOOK_SECRET` está vacío devuelve `True`
—atajo de pruebas documentado—.

El HMAC-SHA256 lo calcula `WebhookSignatureValidator` del SDK, que ya compara con
`hmac.compare_digest` (tiempo constante: un `==` normal permite medir cuánto tarda
la comparación y extraer la firma carácter a carácter). Sus fallos llegan como
`InvalidWebhookSignatureError`, que aquí se traduce al `False` que espera la vista.

Dos detalles NO negociables al delegar en el SDK:

- El `data_id` se pasa como `str(...).lower()`, porque el validador del SDK lo usa
  *tal cual lo recibe* y MP lo manda en minúsculas en la firma aunque el body
  traiga otro formato.
- **No** se pasa `tolerance_seconds`. El SDK puede rechazar por reloj desviado, y
  hasta ahora el proyecto no validaba el timestamp; añadirlo rechazaría
  notificaciones legítimas en pruebas.

## `shop/admin.py`

Registros para inspección manual durante las pruebas:

- `OrderAdmin` con `OrderItemInline`, para ver los items sin salir de la orden.
- `SavedCardAdmin` mostrando método y últimos 4 dígitos.
- `Product`, `CartItem` y `MPCustomer` con el registro por defecto.

Es la herramienta principal para depurar: permite ver `status_detail` con el
motivo textual del rechazo de MP.

## `shop/management/commands/seed_products.py`

Comando `python manage.py seed_products`. Inserta 6 productos con `get_or_create`
sobre el `name`, así que **es idempotente**: ejecutarlo dos veces no duplica nada.
Imprime cuántos creó realmente.

## `shop/migrations/0001_initial.py`

Migración inicial generada por Django 5.2.17. Crea los 6 modelos. Depende del
modelo de usuario activo mediante `swappable_dependency`, por lo que funciona
también con un modelo de usuario personalizado.

## Notas de mantenimiento

- **Para cambiar el payload de MP**: todo está en `views.py`. Si MP modifica
  el contrato de `POST /v1/orders`, ese es el único bloque a ajustar.
- **Para cambiar la lógica de estados**: `mp.display_status` y `mp.needs_refresh`.
  La UI depende de que los cinco valores se mantengan.
- **Para cambiar el código de respuesta de un pago rechazado**: `OrderListCreateView.post`,
  en el bloque `if order.payment_status == "rejected" or mp.display_status(order) == "rejected"`.
  Es la única decisión del proyecto que toca el contrato HTTP del checkout, así que
  conviene localizarla si alguna vez hay que revertirla.
- **Tests**: el proyecto no tiene suite de pruebas. Para añadirla, los puntos
  naturales son `mp._call` (mockear `mercadopago.http.http_client.HttpClient.request`,
  que es donde el SDK hace la petición real; ojo, que con `RawHttpClient` el punto
  a mockear es `requests.Session.request`, que es lo que esa clase usa), las dos
  funciones puras `display_status` y `needs_refresh`, y cada vista con `APIClient` +
  `force_authenticate`.
