# Modelo de datos

Los 6 modelos de `backend/shop/models.py`. Todos heredan de
`django.db.models.Model` con clave primaria `BigAutoField` (configurado en
`settings.py:88` y en `ShopConfig.default_auto_field`).

## Diagrama de relaciones

```
                        User (django.contrib.auth)
                                    │
        ┌───────────────┬───────────┼───────────────┐
        │               │           │               │
   OneToOne         ForeignKey  ForeignKey     ForeignKey
        │               │           │               │
   MPCustomer      CartItem     SavedCard         Order
        │               │                           │
        │             Product                 OrderItem
        │               │                           │
        │               └────────────┐              │
        │                            │              │
        │                    PROTECT  │    CASCADE   │
        │                            └──────────────┘
        │
   customer_id_mp ──────────►  (api.mercadopago.com)

   SavedCard
        │
   card_id_mp ──────────────►  (api.mercadopago.com)
```

Referencias inversas disponibles desde `user`: `mp_customer`, `cart_items`,
`cards`, `orders`.

## `Product`

Catálogo de la tienda. Lo único que existe íntegramente en este proyecto: nada
de él depende de Mercado Pago.

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `BigAutoField` | PK. |
| `name` | `CharField(120)` | |
| `description` | `TextField` | Opcional. |
| `price` | `DecimalField(10, 2)` | `Decimal`, nunca `float`: los importes no toleran errores de coma flotante. |
| `emoji` | `CharField(8)` | Por defecto `📦`. Campo de presentación. |
| `stock` | `PositiveIntegerField` | Por defecto `100`. **No se usa** en el flujo de compra. |

`__str__` devuelve el nombre.

## `CartItem`

Una línea del carrito. El carrito no tiene modelo propio: es la colección de
`CartItem` del usuario.

| Campo | Tipo | Notas |
|---|---|---|
| `user` | `ForeignKey(User)` | `CASCADE`, `related_name="cart_items"`. |
| `product` | `ForeignKey(Product)` | `CASCADE`. |
| `quantity` | `PositiveIntegerField` | Por defecto `1`. |

`Meta.unique_together = ("user", "product")` garantiza que un producto no tenga
dos líneas. Eso permite que `CartView.post` haga `get_or_create` e incremente la
cantidad existente en lugar de insertar un duplicado.

No tiene `__str__` ni aparece con campos propios en el admin.

## `MPCustomer`

El vínculo entre un usuario y su customer de Mercado Pago. Existe para no crear
un customer nuevo en cada intento de pago.

| Campo | Tipo | Notas |
|---|---|---|
| `user` | `OneToOneField(User)` | `CASCADE`, `related_name="mp_customer"`. |
| `customer_id_mp` | `CharField(64)` | `unique=True`. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

`OneToOne` porque un usuario tiene exactamente un customer. `unique` en
`customer_id_mp` porque el id es único en todo Mercado Pago, no solo entre
usuarios de esta app.

Creado por `mp.get_or_create_customer` (`backend/shop/mp.py`), que primero
busca por email en la API de MP para reutilizar un customer existente.

## `SavedCard`

Metadatos de una tarjeta guardada en la cuenta de MP.

**Nunca almacena el número completo ni el CVV.** Solo lo que MP devuelve como
metadatos y que hace falta para mostrar la tarjeta y construir un token con
`cardId`.

| Campo | Tipo | Notas |
|---|---|---|
| `user` | `ForeignKey(User)` | `CASCADE`, `related_name="cards"`. |
| `card_id_mp` | `CharField(64)` | `unique=True` global. Es el `id` que MP devuelve al guardar la tarjeta. |
| `first_six_digits` | `CharField(6)` | Opcional: el BIN, para identificar el banco emisor. |
| `last_four_digits` | `CharField(4)` | Para mostrar `•••• 0366`. |
| `expiration_month` | `PositiveSmallIntegerField` | |
| `expiration_year` | `PositiveSmallIntegerField` | |
| `payment_method_id` | `CharField(30)` | `visa`, `master`, `amex`. |
| `payment_method_type` | `CharField(30)` | `credit_card`, `debit_card`. |
| `payment_method_name` | `CharField(50)` | Texto visible, p. ej. `Mastercard`. |
| `is_default` | `BooleanField` | Por defecto `False`. |
| `created_at` | `DateTimeField` | `auto_now_add`. |

`is_default` no se usa para elegir automáticamente en el backend: la selección
por defecto la hace el frontend (`app/checkout/page.tsx:67`), que ordena las
tarjetas con `-is_default`. El backend solo lo establece para la primera tarjeta
del usuario.

`__str__` devuelve `Mastercard ****0366`.

## `Order`

La cabecera de una orden de compra. Es el objeto más importante del modelo: su
vida cubre desde el intento de cobro hasta el estado final informado por MP.

| Campo | Tipo | Notas |
|---|---|---|
| `user` | `ForeignKey(User)` | `CASCADE`, `related_name="orders"`. |
| `total` | `DecimalField(10, 2)` | **Calculado en el backend** desde el carrito. El cliente nunca lo envía. |
| `external_reference` | `UUIDField` | `default=uuid.uuid4`, `unique=True`. Referencia para MP **e** idempotency key. |
| `mp_order_id` | `CharField(64)` | Opcional: vacío hasta que MP responde. |
| `status` | `CharField(30)` | Por defecto `created`. Estado de la order en MP. |
| `payment_status` | `CharField(30)` | Opcional. Estado del pago dentro de la order. |
| `status_detail` | `CharField(200)` | Opcional. Motivo textual del rechazo. Truncado a 200. |
| `created_at` | `DateTimeField` | `auto_now_add`. |
| `updated_at` | `DateTimeField` | `auto_now`. |

Notas de diseño:

- `external_reference` con `unique=True` cumple dos papeles: correlación con MP y
  **`X-Idempotency-Key`** (`views.py`). Reintentar el mismo POST no duplica el
  cobro.
- `total` es un `DecimalField` y el payload a MP se arma con `f"{total:.2f}"`, de
  forma que el importe enviado y el guardado tienen siempre el mismo formato.
- `status` y `payment_status` guardan los valores **crudos** de MP. El estado
  normalizado para la UI se calcula al serializar, no se persiste. Así el detalle
  técnico sigue disponible sin ensuciar la base.
- La orden se persiste **antes** de llamar a MP. Si el cobro falla, queda el
  registro con `status="failed"`.

`__str__` devuelve `Order 1 (created)`.

## `OrderItem`

Una línea de la orden.

| Campo | Tipo | Notas |
|---|---|---|
| `order` | `ForeignKey(Order)` | `CASCADE`, `related_name="items"`. |
| `product` | `ForeignKey(Product)` | **`PROTECT`**, no `CASCADE`. |
| `quantity` | `PositiveIntegerField` | |
| `unit_price` | `DecimalField(10, 2)` | Precio **congelado** al comprar. |

Las dos decisiones que importan aquí:

**`unit_price` duplica el precio.** Si mañana cambias el precio de un producto,
las órdenes antiguas deben seguir mostrando lo que se pagó realmente. Referenciar
`product.price` haría que el histórico se reescribiera.

**`on_delete=PROTECT`** impide borrar un producto que ya se vendió. `CASCADE`
borraría en cascada los items —y con ellos, el histórico de órdenes— si alguien
eliminara un producto desde el admin. `PROTECT` convierte ese borrado en un error
claro en lugar de una pérdida silenciosa de datos.

Se insertan con `bulk_create` (`views.py`), una sola consulta para todos los
items en vez de una por línea.

## Resumen de por qué cada modelo existe

| Modelo | Sin él, ¿qué faltaría? |
|---|---|
| `Product` | No hay qué comprar. |
| `CartItem` | No hay carrito persistente entre páginas. |
| `MPCustomer` | Se crearía un customer nuevo en cada intento de pago. |
| `SavedCard` | No habría tarjetas guardadas que reutilizar. |
| `Order` | No habría registro local del pago ni qué mostrar en `/orders/<id>`. |
| `OrderItem` | Una orden no conservaría qué se compró ni por cuánto. |

## Migraciones

`shop/migrations/0001_initial.py` crea los 6 modelos. Depende del modelo de
usuario activo mediante `swigrations.swappable_dependency`, así que el esquema se
genera correctamente también con un `AUTH_USER_MODEL` personalizado.

Para cambiar un modelo: `python manage.py makemigrations shop`. El proyecto no
tiene más migraciones, así que `0001_initial.py` es la referencia del esquema
vigente.

## Lo que deliberadamente no está en el modelo

- **Datos sensibles de tarjeta.** Ni número, ni CVV, ni CURP ni RFC. Solo
  metadatos, y el número nunca llega al servidor: vive en los iframes de MP.
- **Un modelo de sesión.** El estado de autenticación vive en `localStorage` y el
  token de DRF, en la tabla `authtoken_token`.
- **Historial de estados.** Solo se guarda el estado actual. Para un proyecto de
  pruebas es suficiente; en producción, una tabla de eventos daría auditoría.
- **Dirección de envío y datos del comprador.** No hay envío físico en el alcance.
- **Control de stock real.** `Product.stock` existe pero no se decrementa al
  comprar.