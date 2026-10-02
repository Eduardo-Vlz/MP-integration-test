# Mercado Pago · Checkout API (Orders) — proyecto de pruebas

Django (API) + Next.js (interfaz). Carrito, checkout con tarjeta en una sola
exhibición (sin cuotas), tarjetas guardadas, órdenes y webhook. Débito y crédito.

> Todo corre con credenciales **de prueba** (`TEST-`). Nada de este README aplica
> tal cual a producción: el login por email y `ALLOWED_HOSTS=["*"]` son atajos.

## Documentación

Esta es la guía rápida. El detalle técnico está en [`docs/`](./docs/README.md):

| Documento | Contenido |
|---|---|
| [`docs/como-leer-el-codigo.md`](./docs/como-leer-el-codigo.md) | **Empieza aquí si quieres entender el código:** qué se ejecuta al arrancar y el orden de lectura. |
| [`docs/arquitectura.md`](./docs/arquitectura.md) | Estructura, capas, flujo de pago y decisiones de diseño. |
| [`docs/api.md`](./docs/api.md) | Referencia de los 10 endpoints con request/response. |
| [`docs/backend.md`](./docs/backend.md) | Cada módulo de Django, archivo por archivo. |
| [`docs/frontend.md`](./docs/frontend.md) | Cada componente, página y hook de Next.js. |
| [`docs/estados-y-webhooks.md`](./docs/estados-y-webhooks.md) | Estados de MP, `display_status` y ciclo del webhook. |
| [`docs/modelo-de-datos.md`](./docs/modelo-de-datos.md) | Los 6 modelos, campos y diagrama. |

## Requisitos

- Python 3.10+
- Node 20+ y pnpm (`npm i -g pnpm`)
- **PostgreSQL** — el backend usa `django.db.backends.postgresql`, no SQLite

## 1. Base de datos

```bash
createdb save_carts
```

O con Docker:

```bash
docker run -d --name mp-pg -e POSTGRES_PASSWORD=root -e POSTGRES_DB=save_carts \
  -p 5432:5432 postgres:16
```

## 2. Credenciales

```bash
cp backend/.env.example backend/.env     # Windows: copy
```

Edita `backend/.env` y pega las credenciales **de prueba** de tu aplicación:

- `MP_PUBLIC_KEY` y `MP_ACCESS_TOKEN` (empiezan con `TEST-`)

El frontend obtiene la Public Key desde el backend, así que **solo se configura en
un lugar**. Los datos de conexión a Postgres y `FRONTEND_ORIGIN` ya vienen
rellenados en la plantilla.

## 3. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_products    # 6 productos de ejemplo
python manage.py createsuperuser  # opcional, para /admin
python manage.py runserver        # http://localhost:8000
```

## 4. Frontend

```bash
cd frontend
pnpm install
pnpm dev                          # http://localhost:3000
```

`frontend/.env.local` ya apunta a `http://localhost:8000/api`.

## 5. Probar la app

1. Entra a http://localhost:3000 e inicia sesión con un email de prueba
   `test_payer_123456@testuser.com` (hay un botón para generar uno).
2. Agrega productos → Carrito → Ir a pagar.
3. Sin tarjetas guardadas verás el formulario; con tarjetas guardadas, las verás
   listadas y se te pedirá el CVV otra vez.
4. El resultado aparece en `/orders/<id>` y en `/admin` (modelos `Order`,
   `SavedCard`, `MPCustomer`).

## Tarjetas de prueba (México)

| Tipo | Bandera | Número | CVV | Vence |
|---|---|---|---|---|
| Crédito | Mastercard | `5474 9254 3267 0366` | 123 | 11/30 |
| Crédito | Visa | `4075 5957 1648 3764` | 123 | 11/30 |
| Crédito | American Express | `3711 803032 57522` | 1234 | 11/30 |
| Débito | Mastercard | `5579 0534 6148 2647` | 123 | 11/30 |
| Débito | Visa | `4189 1412 2126 7633` | 123 | 11/30 |

El **nombre del titular** decide el resultado, no el número de tarjeta: cualquier
tarjeta de la tabla se puede combinar con cualquiera de estos escenarios.

| Nombre | Resultado |
|---|---|
| `APRO` | Aprobado |
| `OTHE` | Rechazado por error general |
| `CONT` | Pendiente de pago |
| `CALL` | Rechazado con validación para autorizar |
| `FUND` | Rechazado por importe insuficiente |
| `SECU` | Rechazado por código de seguridad inválido |
| `EXPI` | Rechazado por fecha de vencimiento |
| `FORM` | Rechazado por error de formulario |
| `DUPL` | Rechazado por pago duplicado |
| `LOCK` | Rechazado por tarjeta deshabilitada |

`CONT` es el que sirve para ver el ciclo pendiente → final (necesita webhook, o
esperar los 5 s de sondeo).

Para identificación puedes usar cualquier número de prueba (ej. `123456789`).
Valores vigentes en la [página oficial de tarjetas de prueba](https://www.mercadopago.com.mx/developers/es/docs/checkout-api-orders/integration-test/cards)
de Checkout API — se actualizan sin avisar, así que conviene comprobarla si algo
se comporta raro.

## Webhook (para ver estados pendientes → final)

1. Expón Django: `ngrok http 8000`.
2. En tu aplicación de MP → Webhooks → URL:
   `https://TU-SUBDOMINIO.ngrok-free.app/api/webhooks/mp/` y evento **Order**.
3. (Opcional) copia la clave secreta en `MP_WEBHOOK_SECRET` para validar la firma.

Sin webhook la página de la orden igual consulta a MP cada 5 s mientras esté
pendiente, solo que no te enteras si el pago termina mientras no la estés
mirando.

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/auth/login/` | Inicia sesión con un email de prueba y devuelve un token |
| `GET` | `/api/config/` | Public Key de MP y origen permitido |
| `GET` | `/api/products/` | Catálogo |
| `GET` `POST` `DELETE` | `/api/cart/` | Ver carrito, agregar producto, vaciar carrito |
| `PATCH` `DELETE` | `/api/cart/<product_id>/` | Cambiar cantidad o quitar un producto |
| `GET` `POST` | `/api/cards/` | Listar tarjetas guardadas; tokenizar y guardar una nueva |
| `DELETE` | `/api/cards/<id>/` | Desvincular una tarjeta guardada |
| `GET` `POST` | `/api/orders/` | Listar órdenes del usuario / crear el pago |
| `GET` | `/api/orders/<id>/` | Estado de una orden (reconsulta a MP si sigue pendiente) |
| `POST` | `/api/webhooks/mp/` | Notificaciones de MP |

## Flujos de pago

- **Tarjeta nueva sin guardar:** Secure Fields detecta débito o crédito por BIN →
  token → `POST /api/orders/` en una sola exhibición.
- **Tarjeta nueva + guardar:** token → `POST /api/cards/` (crea el customer si no
  existe y guarda la tarjeta) → segundo token con `card_id` + CVV →
  `POST /api/orders/`. Si el segundo token falla, la tarjeta **queda guardada** y
  se pide el CVV para pagar.
- **Tarjeta guardada:** CVV → token con `card_id` → `POST /api/orders/` con
  `payer.customer_id`, también en una sola exhibición.

## Scripts de diagnóstico (`backend/`)

Sueltos, forman parte del repo pero **no de la app**. Se ejecutan con
`python manage.py shell -c "exec(open('diagN.py', encoding='utf-8').read())"`:

| Script | Para qué |
|---|---|
| `diag.py` | Comprueba `GET /customers/search` + `POST /customers`: si el buscador no devuelve un cliente que ya existe, el siguiente POST da 400. |
| `diag2.py` | `POST /customers` con un Access Token tecleado a mano, para descartar que el problema sea el token. |
| `diag3.py` | `POST /customers` con 4 emails candidatos, para ver qué dominios acepta MP y cuáles devuelve `invalid domain user email`. |
| `diag4.py` | Flujo completo con tarjeta guardada: cliente → tarjeta → token → orden. |
| `limpiar.py` | **Destructivo.** Borra customers y sus tarjetas reales. Aborta si el token no empieza con `TEST-`. |

⚠️ Con credenciales de **producción** estos scripts crean clientes y órdenes
reales en tu cuenta, y no se pueden deshacer.

## Seguridad (por qué está así)

- Número, vencimiento y CVV viven en iframes de Mercado Pago: nunca tocan
  Next.js ni Django.
- El Access Token solo está en el backend, y el total se calcula en el backend.
- La base solo guarda metadatos de la tarjeta (últimos 4, vencimiento, ids).
  No se guarda CURP/RFC.
- El login por email y `ALLOWED_HOSTS=["*"]` son atajos **solo de prueba**.

## Problemas comunes

**"Falta MP_PUBLIC_KEY"** — revisa `backend/.env` y reinicia `runserver`.

**Error de conexión a Postgres** — el backend no usa SQLite. Levanta Postgres
(paso 1) o ajusta `POSTGRES_*` en `backend/.env`.

**CORS** — el frontend debe correr en `http://localhost:3000`, o cambia
`FRONTEND_ORIGIN`.

**El email del payer es rechazado** — MP responde `Error invalid domain user
email` si el email no es de prueba válido. Usa uno tipo
`test_payer_<dígitos>@testuser.com` (esto lo exige `ENFORCE_TEST_EMAIL` en el
login, pero el customer de MP es otro filtro aparte).

**Error 4xx de MP al crear la orden** — se muestra en pantalla y queda en
`Order.status_detail`. Para cambiar el contrato del payload mira primero
`mp.create_order` en `backend/shop/mp.py` y luego la [referencia oficial de
`POST /v1/orders`](https://www.mercadopago.com.mx/developers/es/reference/orders/online-payments/create-a-order).

**Pago rechazado** — la API responde **402** con `mp` y `mp_status`, y el motivo
real de MP aparece en pantalla (lo extrae `errorMessage()` del frontend a partir
de `data.mp`). El carrito **no** se vacía, así que el reintento es un botón. Si no
llegó a crearse la orden en MP, la respuesta es **400** en lugar de 402.