# Estados y webhooks

Cómo se traduce el vocabulario de Mercado Pago al estado que ve el usuario, y
cómo se mantiene esa información sincronizada.

## Dos niveles de estado

El recurso `Order` de MP tiene **dos** estados distintos que el proyecto guarda
por separado:

| Campo local | Qué representa | Ejemplo |
|---|---|---|
| `Order.status` | Estado de la **order** | `processed`, `failed`, `canceled` |
| `Order.payment_status` | Estado del **pago** dentro de esa order | `approved`, `rejected`, `pending` |

Se separan porque no siempre coinciden: una order puede estar `processed`
mientras su pago sigue `pending`. El backend extrae el pago de
`transactions.payments[0]` en `mp.apply_mp_order` (`backend/shop/mp.py`).

> [!IMPORTANT] Esa línea de arriba no es una curiosidad: **todo lo que se deriva del estado tiene que mirar los dos niveles.** Ignorar `payment_status` produce el error más caro de un checkout —dar por pagado un cobro que no se ha liquidado— y el proyecto ya lo cometió una vez: `display_status` solo miraba `order.status`, así que una order `processed` con el pago `pending` se mostraba como `approved`, el polling no se rearmaba y el carrito ya se había vaciado. De ahí las dos funciones de este documento, `display_status` y `needs_refresh`, consultan siempre `payment_status` antes de decidir.

## `display_status`: la normalización

El frontend no conoce la taxonomía de MP. El backend expone un campo derivado,
`display_status`, calculado en `mp.display_status` (`backend/shop/mp.py`) y
expuesto por `OrderSerializer.get_display_status`.

```python
def display_status(order: Order) -> str:
    # El estado del PAGO va primero: una order `processed` con el pago `pending`
    # no es un pago aprobado.
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
```

### Tabla de equivalencias

| `payment_status` de MP | `status` de la order | `display_status` | Etiqueta en la UI |
|---|---|---|---|
| `approved` | `processed` | `approved` | ✅ Aprobado |
| `pending` | cualquiera | `pending` | ⏳ Pendiente |
| `rejected` | cualquiera | `rejected` | ❌ Rechazado |
| — | `failed`, `canceled`, `expired` | `rejected` | ❌ Rechazado |
| — | `refunded` | `refunded` | ↩️ Reembolsado |
| — | `created`, `processing`, `action_required` + con `mp_order_id` | `pending` | ⏳ Pendiente |
| — | `created` sin `mp_order_id` | `created` | Creada |

Las dos primeras filas son las que se consultan **antes** que `status`, y por eso ganan cuando ambas se contradicen.

Tres detalles de la implementación:

- **El pago manda cuando no es `approved`.** Solo se adelantan `pending` y `rejected`, que son inequívocos. Cualquier otro valor de `payment_status` —incluido vacío, en una orden que aún no tiene transacciones— cae a la cadena de abajo, que decide con el estado de la order.
- **La condición `and order.mp_order_id` importa.** Una orden que nunca llegó a MP no está "pendiente de MP", está sin enviar. Devolver `created` es más honesto que `pending`.
- **`action_required` se muestra como `pending`.** El usuario solo ve "pendiente" y la app sigue preguntando; cuando MP resuelva, pasará a aprobado o rechazado. Es una decisión de UX: el proyecto no implementa un flujo de autenticación 3DS.

## `status_detail`: el motivo textual

Cuando un pago se rechaza, MP devuelve un `status_detail` corto y descriptivo:

| Código | Significado |
|---|---|
| `accredited` | Pago acreditado |
| `cc_rejected_other_reason` | Rechazo general de la tarjeta |
| `cc_rejected_insufficient_amount` | Fondos insuficientes |
| `cc_rejected_bad_filled_security_code` | CVV incorrecto |
| `cc_rejected_expired_card` | Tarjeta vencida |
| `cc_rejected_high_risk` | Rechazo por riesgo |
| `pending_review` | En revisión |

Este valor se trunca a 200 caracteres porque el campo es
`CharField(max_length=200)`. Se muestra en el bloque `.debug` de
`app/orders/[id]/page.tsx:68` y en el admin, en la columna `status_detail` de
`OrderAdmin`. Es la primera cosa que hay que mirar cuando un pago no sale.

## Estados finales

```python
FINAL_ORDER_STATUSES = {"processed", "failed", "canceled", "refunded", "expired"}
PENDING_PAYMENT_STATUSES = {"pending"}


def needs_refresh(order: Order) -> bool:
    if not order.mp_order_id:
        return False
    if order.payment_status in PENDING_PAYMENT_STATUSES:
        return True
    return order.status not in FINAL_ORDER_STATUSES
```

`backend/shop/mp.py`

Cuando `needs_refresh` devuelve `False`, `OrderDetailView` **no** vuelve a consultar
a MP: el resultado ya no va a cambiar, así que es una llamada externa desperdiciada.
También evita que un `GET` del detalle se convierta en una fuente de tráfico
constante hacia MP.

> [!WARNING] `FINAL_ORDER_STATUSES` son estados de la **orden**, no del pago, y por eso `OrderDetailView` no los consulta directamente: usa `needs_refresh`. Decidir solo con `order.status` falla cuando la orden está `processed` —un estado final— pero su pago sigue `pending`. En ese caso hay que volver a preguntar, porque `display_status` es `pending` y el polling del frontend va a seguir insistiendo: si el backend no refrescara, el polling serviría un valor congelado indefinidamente. Ese fue el otro bug que la normalización de estados arrastraba.

## Cómo se sincroniza el estado

Hay tres mecanismos, y están pensados como capas de respaldo.

### 1. Respuesta del POST

Al crear la orden, el backend copia inmediatamente el estado devuelto
(`views.py`). En una tarjeta de prueba que se aprueba al instante, el
resultado ya está listo sin ninguna consulta extra.

### 2. Polling desde el frontend

`app/orders/[id]/page.tsx:34` consulta `GET /api/orders/<id>/` cada 5 s mientras
el estado sea `pending`. El backend re-consulta a MP en cada llamada, así que el
frontend obtiene datos frescos sin hablar nunca con MP.

Funciona **sin configurar nada** y es la razón por la que el README dice que
"sin webhook la página de la orden igual se actualiza".

### 3. Webhook (mecanismo principal)

Es la vía correcta: el backend se entera en cuanto cambia el estado, sin que
ningún navegador esté mirando la página.

#### Configuración

```bash
ngrok http 8000
```

En el panel de Mercado Pago → **Tus integraciones** → **Webhooks**:

| Campo | Valor |
|---|---|
| URL | `https://TU-SUBDOMINIO.ngrok-free.app/api/webhooks/mp/` |
| Evento | **Order** |
| Método | `POST` (POST request) |

La Public Key del webhook se pega en `MP_WEBHOOK_SECRET` en `backend/.env`.
**Sin ella el endpoint acepta cualquier llamada** — es un atajo de pruebas.

> En producción: HTTPS obligatorio, `MP_WEBHOOK_SECRET` siempre configurado,
> `ALLOWED_HOSTS` restringido al dominio real (sin el `*` que habilita ngrok).

#### El flujo

```
MP detecta un cambio
   │
   ├──► POST /api/webhooks/mp/  { "data": { "id": "ord_..." } }
   │      │
   │      ├─ ¿Firma válida?  ── no ──► 401
   │      │   sí
   │      ├─ ¿data.id presente? ── no ──► 200
   │      │   sí
   │      ├─ ¿La orden es nuestra? ── no ──► 200
   │      │   sí
   │      ├─ GET /v1/orders/{id}   ◄── re-consulta, NO confía en el body
   │      │   ├─ fallo ──► 500  (MP reintenta)
   │      │   éxito ──► actualiza Order ──► 200
```

#### Tres decisiones del diseño

**No confía en el payload.** El `data.id` solo sirve para localizar la orden
local. El estado se obtiene siempre con un `GET /v1/orders/{id}`. Si alguien
llegara a mandar una notificación falsificada con un estado inventado, la base de
datos seguiría registrando la verdad.

**Devuelve `500` para forzar el reintento.** Si la consulta a MP falla, responder
`500` le dice a MP "no lo procesé, inténtalo más tarde". Un `200` con el trabajo a
medias perdería la notificación para siempre.

**Responde `200` a lo que no le concierne.** Notificaciones de otros tipos o de
órdenes que no son nuestras se acusan con `200` sin hacer nada. Devolver `4xx`
haría que MP reintentara indefinidamente algo que nunca va a funcionar.

#### Validación de la firma

`mp.valid_webhook_signature` (`backend/shop/mp.py`):

```
manifiesto = "id:{data_id};request-id:{request_id};ts:{ts};"
firma      = HMAC_SHA256(MP_WEBHOOK_SECRET, manifiesto)
```

El manifiesto se construye con los valores de las cabeceras `x-signature` (que
contiene `ts=…,v1=…`) y `x-request-id`. La comparación usa
`hmac.compare_digest`, de **tiempo constante**: un `==` normal filtraría
información por temporización y permitiría reconstruir la firma carácter a
carácter.

Si `MP_WEBHOOK_SECRET` está vacío, la función devuelve `True` sin comprobar nada.

## Idempotencia

Dos mecanismos la garantizan:

1. **`X-Idempotency-Key`** en `POST /v1/orders`, con el valor de
   `Order.external_reference` (`views.py`). Si el backend reintenta la misma
   orden, MP devuelve la orden ya creada en lugar de crear otra.
2. **`update_or_create`** sobre `SavedCard.card_id_mp` (`mp.py`), para que
   guardar dos veces la misma tarjeta no duplique la fila.

Esto importa porque los pagos se reintentan con frecuencia por caídas de red, y
un doble cobro es un problema serio.

## Probar cada estado

Con las tarjetas de prueba de Mercado Pago, el resultado se define por el **nombre
del titular**:

| Nombre del titular | Resultado |
|---|---|
| `APRO` | Aprobado |
| `OTHE` | Rechazo general |
| `FUND` | Fondos insuficientes |
| `SECU` | CVV inválido |
| `EXPI` | Tarjeta vencida |
| `CONT` | Pago pendiente |
| `FORM` | Error de formulario |

Tarjetas de prueba (México):

| Medio | Número | CVV | Vence |
|---|---|---|---|
| Mastercard | 5474 9254 3267 0366 | 123 | 11/30 |
| Visa | 4075 5957 1648 3764 | 123 | 11/30 |
| American Express | 3711 803032 57522 | 1234 | 11/30 |

Para el campo de identificación se acepta cualquier valor de prueba, por ejemplo
`123456789`.

### Rutas para cada estado

| Estado a probar | Flujo |
|---|---|
| `approved` | Titular `APRO`. El carrito se vacía y `/orders/<id>` muestra ✅. |
| `rejected` en el POST | Titular `FUND` o `SECU`. El backend devuelve `400` con `order_id`; el carrito **no** se vacía. |
| `pending` → final | Titular `CONT`. El polling cada 5 s resuelve; con webhook configurado, el webhook lo resuelve. |
| Falla de red | Detener el backend a mitad del POST. La orden queda registrada con `status="failed"`. |

Para inspeccionar el resultado de cualquier caso: la columna `status_detail` del
admin, o el bloque `.debug` en la página de detalle de la orden.

## Diagnóstico

| Síntoma | Dónde mirar |
|---|---|
| La orden se queda en `pending` | `status_detail`. Si está vacío, el polling no ha recibido respuesta de MP. |
| El webhook devuelve `401` | `MP_WEBHOOK_SECRET` no coincide con la clave del panel de MP. |
| El webhook devuelve `500` en bucle | La API de MP no responde o el Access Token expiró. Revisa los logs del backend. |
| El webhook nunca llega | La URL pública no es accesible, o el evento no está en `Order`. Verifica con `ngrok http 8000`. |
| MP rechaza la orden con `4xx` | Email/customer que no es de prueba, o credenciales de producción. |
| La tarjeta se guarda dos veces | No debería ocurrir: `update_or_create` lo evita. Si ocurre, revisa el `card_id` que devuelve MP. |