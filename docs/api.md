# Referencia de la API

Base URL en desarrollo: `http://localhost:8000/api`
Definición de rutas: `backend/shop/urls.py:22`

## Convenciones

### Autenticación

Todos los endpoints requieren `Authorization: Token <token>` **salvo** los
marcados como públicos. El token es un DRF `Token` creado en el login y guardado
en `localStorage` por el frontend (`frontend/lib/api.ts:42`).

| Endpoint | Auth |
|---|---|
| `POST /auth/login/` | Pública |
| `GET /config/` | Pública |
| `GET /products/` | Pública |
| `POST /webhooks/mp/` | Pública (firma HMAC en su lugar) |
| Resto | `Token` |

### Formato de errores

El cliente HTTP de `lib/api.ts` normaliza cualquier respuesta no-2xx a un
`ApiError` con `status` y `data`. Los errores de Mercado Pago llegan con esta
forma (`views.py`):

```json
{
  "detail": "Error de Mercado Pago",
  "mp_status": 400,
  "mp": { "message": "...", "errors": [{ "code": "...", "message": "..." }] }
}
```

`errorMessage()` (`lib/api.ts:61`) extrae `mp.errors[0].message` para mostrarlo.

### Convenciones de serialización

- Los importes viajan como **string** con 2 decimales (`"499.00"`), no como float,
  para no perder precisión.
- El endpoint devuelve `401` sin cabecera `Token` o con token inválido (DRF por
  defecto), y `403` si falta el permiso.

---

## `POST /auth/login/`

Login simplificado **solo para pruebas**: obtiene o crea un usuario por email y
devuelve su token. No hay contraseña.

Implementación: `LoginView` en `backend/shop/views.py`

**Request**

```json
{ "email": "test_payer_123456@testuser.com" }
```

**Response `200`**

```json
{ "token": "a1b2c3…", "email": "test_payer_123456@testuser.com" }
```

**Errores**

| Código | Causa |
|---|---|
| `400` | Falta `email`. |
| `400` | El email no cumple el patrón `test_payer_\d{1,10}@testuser.com` (si `ENFORCE_TEST_EMAIL=True`). |

Notas:

- El email se normaliza a minúsculas y sin espacios (`views.py`).
- El usuario se crea con `get_or_create`, así que el mismo email siempre devuelve
  la misma sesión.
- El patrón se define en `TEST_EMAIL_RE` (`views.py`).

---

## `GET /config/`

Entrega la Public Key de MP al frontend, que la necesita para instanciar el SDK.
Permite tener las credenciales configuradas **solo en el backend**.

Implementación: `ConfigView` en `backend/shop/views.py`

**Response `200`**

```json
{ "public_key": "TEST-1234-…" }
```

Si está vacía, `useMercadoPago` lanza el error "Falta MP_PUBLIC_KEY en
backend/.env" y el checkout se muestra deshabilitado.

---

## `GET /products/`

Catálogo completo, ordenado por `id`. Público.

Implementación: `ProductListView` en `backend/shop/views.py`

**Response `200`**

```json
[
  {
    "id": 1,
    "name": "Playera básica",
    "description": "Algodón 100%",
    "price": "199.00",
    "emoji": "👕",
    "stock": 100
  }
]
```

---

## `GET /cart/`

Carrito del usuario autenticado con el total recalculado en el servidor.

Implementación: `CartView.get` en `backend/shop/views.py`

**Response `200`**

```json
{
  "items": [
    { "id": 7, "product": { "…": "…" }, "quantity": 2, "subtotal": "398.00" }
  ],
  "total": "398.00"
}
```

`subtotal` y `total` se calculan con `Decimal` para evitar errores de coma
flotante.

---

## `POST /cart/`

Agrega un producto al carrito. Si ya existe, **incrementa** la cantidad en vez de
duplicar la fila (garantizado por `unique_together ("user", "product")`).

Implementación: `CartView.post` en `backend/shop/views.py`

**Request**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `product_id` | int | Sí | Debe existir; si no, `404`. |
| `quantity` | int | No | Por defecto `1`. Se fuerza a un mínimo de 1. |

**Response `200`** — el carrito completo, igual que en `GET /cart/`.

---

## `DELETE /cart/`

Vacía el carrito completo del usuario.

Implementación: `CartView.delete` en `backend/shop/views.py`

**Response `200`** — el carrito ya vacío.

---

## `PATCH /cart/{product_id}/`

Fija la cantidad de una línea concreta.

Implementación: `CartItemView.patch` en `backend/shop/views.py`

**Request**

```json
{ "quantity": 3 }
```

Comportamiento: si `quantity <= 0`, la línea **se elimina** en lugar de guardar un
cero. Es lo que hace que el botón "−" del carrito borre el producto al llegar a 1.

**Response `200`** — el carrito completo.

**Errores**: `404` si la línea no existe para ese usuario.

---

## `DELETE /cart/{product_id}/`

Elimina una línea del carrito.

Implementación: `CartItemView.delete` en `backend/shop/views.py`

**Response `200`** — el carrito completo.

---

## `GET /cards/`

Lista las tarjetas guardadas del usuario: primero la predeterminada, luego por
`id` descendente.

Implementación: `CardListView.get` en `backend/shop/views.py`

**Response `200`**

```json
[
  {
    "id": 1,
    "card_id_mp": "card_hash_abc123",
    "first_six_digits": "547492",
    "last_four_digits": "0366",
    "expiration_month": 11,
    "expiration_year": 2030,
    "payment_method_id": "master",
    "payment_method_type": "credit_card",
    "payment_method_name": "Mastercard",
    "is_default": true
  }
]
```

Solo metadatos: nunca número completo ni CVV.

---

## `POST /cards/`

Guarda una tarjeta en la cuenta de MP del usuario. Crea el customer si no existe.

Implementación: `CardListView.post` en `backend/shop/views.py` →
`mp.save_card()` en `backend/shop/mp.py`

**Request**

| Campo | Tipo | Obligatorio |
|---|---|---|
| `token` | string | Sí — token de un solo uso generado por el SDK. |

**Response `201`** — la tarjeta creada, con la misma forma que en el `GET`.

**Errores**

| Código | Causa |
|---|---|
| `400` | Falta `token`. |
| `502` | MP rechazó la operación (ver forma del error arriba). |

Notas:

- `update_or_create` sobre `card_id_mp` hace la operación idempotente.
- Si es la primera tarjeta del usuario, se marca `is_default=True` automáticamente.
- **Los tokens son de un solo uso**: reenviar el mismo devuelve `400` desde MP.

---

## `DELETE /cards/{id}/`

Elimina la tarjeta en MP y en la base local.

Implementación: `CardDetailView` en `backend/shop/views.py` →
`mp.delete_card()` en `backend/shop/mp.py`

**Response `204`** — sin cuerpo.

Notas:

- El `id` es el de la base local, no el de MP.
- Un `404` de MP se ignora a propósito: la fila local se borra igual, porque lo
  que importa es que el usuario deje de ver la tarjeta.

---

## `GET /orders/`

Lista las órdenes del usuario, más recientes primero, con sus items.

Implementación: `OrderListCreateView.get` en `backend/shop/views.py`

**Response `200`**

```json
[
  {
    "id": 1,
    "total": "498.00",
    "mp_order_id": "ord_01H…",
    "status": "processed",
    "payment_status": "approved",
    "status_detail": "accredited",
    "display_status": "approved",
    "created_at": "2026-09-30T14:22:01Z",
    "items": [
      { "product_name": "Audífonos", "quantity": 1, "unit_price": "499.00" }
    ]
  }
]
```

`status` / `payment_status` son los valores crudos de MP; `display_status` es el
normalizado que usa la UI. Ver
[`estados-y-webhooks.md`](./estados-y-webhooks.md).

---

## `POST /orders/`

Crea la orden y cobra. Es el endpoint central del proyecto.

Implementación: `OrderListCreateView.post` en `backend/shop/views.py`

**Request — tarjeta nueva**

```json
{
  "token": "e0ba…",
  "payment_method_id": "visa",
  "payment_method_type": "credit_card",
  "payer_email": "test_payer_123456@testuser.com",
  "installments": 1
}
```

**Request — tarjeta guardada**

```json
{ "token": "e0ba…", "saved_card_id": "card_hash_abc123", "installments": 1 }
```

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `token` | string | Sí | Token de un solo uso. |
| `saved_card_id` | string | No | `card_id_mp` de una tarjeta del usuario. Si viene, el resto se resuelve desde la base. |
| `payment_method_id` | string | Condicional | Requerido si no hay `saved_card_id` (ej. `visa`, `master`, `amex`). |
| `payment_method_type` | string | No | Tipo detectado por el checkout (`credit_card` o `debit_card`); por defecto `credit_card`. |
| `payer_email` | string | No | Por defecto el email del usuario. Solo se usa sin `saved_card_id`. |
| `installments` | int | No | Número de cuotas; por defecto `1`. El checkout siempre envía `1`, tanto para tarjetas de débito como de crédito. |

El checkout no ofrece selector de cuotas: los pagos con tarjeta se solicitan en una
sola exhibición. El endpoint acepta el valor `installments` recibido y solo usa `1`
por defecto cuando el campo no viene; no fuerza ese valor para llamadas directas a
la API.

**Cómo decide el backend**

1. Sin carrito → `400`.
2. Recalcula el total desde la base (ignora cualquier importe del cliente).
3. Si hay `saved_card_id`, busca la tarjeta **filtrando por `user`**
   (`views.py`) — nadie puede pagar con la tarjeta de otro usuario.
4. Abre una transacción y persiste `Order` + `OrderItem`.
5. Llama a `POST /v1/orders` con `X-Idempotency-Key` = `external_reference`.
6. Si MP devuelve `id` y `status`, los copia a la orden; si no, marca
   `status="failed"` con el cuerpo crudo del error truncado a 200 caracteres.
7. Vacía el carrito si el resultado es `approved` o `pending`.

**Payload enviado a MP** (`views.py`)

```json
{
  "type": "online",
  "processing_mode": "automatic",
  "external_reference": "uuid-de-la-orden",
  "total_amount": "498.00",
  "payer": { "email": "…" },
  "transactions": {
    "payments": [
      {
        "amount": "498.00",
        "payment_method": {
          "id": "visa",
          "type": "credit_card",
          "token": "…",
          "installments": 1
        }
      }
    ]
  }
}
```

Con tarjeta guardada, `payer` es `{ "customer_id": "…" }` en lugar de `{ "email": … }`.

**Response `201`** — la orden creada (misma forma que en `GET /orders/`).

**Errores**

| Código | Causa |
|---|---|
| `400` | Falta `token`, carrito vacío, falta `payment_method_id`, o MP rechazó la orden **sin llegar a crearla**. |
| `402` | MP creó la orden pero **rechazó el pago**. La orden queda persistida como `failed`. |
| `404` | `saved_card_id` no pertenece al usuario. |
| `502` | Fallo de comunicación con MP. |

> [!IMPORTANT] **Un pago rechazado devuelve `402`, no `201`, aunque la orden sí exista en MP.** Es deliberado y es la diferencia entre este endpoint y una API ingenua.
>
> Mercado Pago responde `402` con la order anidada en `data`, así que la orden **sí se creó**: se persiste con `status = "failed"` y el motivo en `status_detail`. Devolver `201` haría que el frontend —que trata cualquier 2xx como éxito— navegara a la pantalla de detalle y el usuario vería una orden rechazada sin ninguna explicación. Con `402` el checkout lo trata como error, muestra el motivo real de MP y **deja el carrito intacto** para poder reintentar.

Cuando MP rechaza, la respuesta trae `order_id` para poder consultar el intento:

```json
{
  "detail": "Mercado Pago rechazó el pago",
  "mp_status": 402,
  "mp": {
    "message": "invalid card token",
    "errors": [{ "code": "PAYMENT_METHOD_ERROR", "details": ["high_risk"] }]
  },
  "order_id": 12
}
```

El `detail` es genérico a propósito: el texto que el usuario necesita está en `mp.message`, y el frontend concatena ambos. `order_id` permite llevar al usuario a la pantalla de esa orden aunque el pago haya fallado.

---

## `GET /orders/{id}/`

Detalle de una orden, solo del usuario autenticado.

Implementación: `OrderDetailView` en `backend/shop/views.py`

**Response `200`** — la orden.

Comportamiento adicional: el backend **re-consulta a MP** antes de responder cuando
el estado de la orden todavía puede cambiar, para que el polling del frontend
reciba el estado más fresco. La decisión la toma `mp.needs_refresh`, y **no** es
simplemente "el estado no es final": una orden puede estar `processed` —estado final
de la *orden*— y aun así tener su pago en `pending`. En ese caso sí hay que volver a
preguntar, o el polling serviría un valor congelado indefinidamente. Si la consulta
falla, devuelve lo último que hay en la base en lugar de un error.

**Errores**: `404` si la orden no existe o pertenece a otro usuario.

---

## `POST /webhooks/mp/`

Notificación de MP cuando cambia el estado de una orden.

Implementación: `WebhookView` en `backend/shop/views.py`

**Request**

```json
{ "type": "order", "data": { "id": "ord_01H…" } }
```

Also acepta `?data.id=` en query string como alternativa.

**Proceso**

1. Extrae el `data.id`. Si no hay, responde `200` (notificación vacía).
2. Valida la firma. Si es inválida → `401`.
3. Busca la orden local por `mp_order_id`.
4. Si existe, re-consulta a MP y actualiza. Si la consulta falla → `500` para que
   MP reintente.
5. Responde `200`.

**Responses**

| Código | Causa |
|---|---|
| `200` | Notificación válida, o sin `data.id`, o la orden no es nuestra. |
| `401` | Firma HMAC inválida. |
| `500` | No se pudo consultar a MP; MP reintentará. |

Notas:

- **Nunca confía en el cuerpo**: el `id` solo sirve para localizar la orden.
  El estado se obtiene siempre de la API de MP.
- Si `MP_WEBHOOK_SECRET` está vacío, la validación devuelve `True` y el endpoint
  acepta cualquier llamada. Es un atajo de pruebas.
- Configuración del lado de MP: evento **Order**, método `POST`, URL pública.

---

## Resumen de códigos de estado

| Código | Significado en esta API |
|---|---|
| `200` | Operación correcta. |
| `201` | Recurso creado (`POST /cards/`, `POST /orders/`). |
| `204` | Eliminación correcta, sin cuerpo (`DELETE /cards/{id}/`). |
| `400` | Datos inválidos o rechazo de MP. |
| `401` | Sin token, token inválido, o firma de webhook incorrecta. |
| `404` | El recurso no existe o no pertenece al usuario. |
| `500` | MP no respondió; el webhook devuelve 500 a propósito para forzar reintento. |
| `502` | MP respondió con error; se traduce a `Bad Gateway`. |