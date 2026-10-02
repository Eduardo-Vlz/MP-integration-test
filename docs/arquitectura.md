# Arquitectura

## Qué es este proyecto

Una tienda mínima con carrito y checkout que integra **Mercado Pago Checkout API
mediante el recurso `Orders`** (`POST /v1/orders`). Existe para validar, en un
entorno controlado, los cuatro escenarios que una integración real necesita
soportar:

1. Tarjeta nueva, sin guardar.
2. Tarjeta nueva que se guarda para futuras compras.
3. Tarjeta ya guardada (se vuelve a pedir el CVV).
4. Estados pendientes que se resuelven después, vía webhook o polling.

No hay pasarela de pago real, no hay pasarela de correo, no hay checkout por
 redirección: el pago se dispara programáticamente contra `POST /v1/orders`.

## Vista de capas

```
┌──────────────────────────────────────────────────────────────────────┐
│  NAVEGADOR                                                          │
│  app/*  (componentes React)   ·   iframes de Secure Fields de MP    │
└───────────────┬──────────────────────────────┬───────────────────────┘
                │ fetch() + Token              │ nunca sale del iframe
                │ CORS: localhost:3000         │ (número, cvv, expiry)
┌───────────────▼──────────────────────────────▼───────────────────────┐
│  frontend/  Next.js 15 (App Router, todo client-side)               │
│  · Secure Fields montan los iframes → generan un token opaco         │
│  · El token (no los datos) viaja al backend                          │
└───────────────┬──────────────────────────────────────────────────────┘
                │ HTTP + Authorization: Token <token>
                │ CORS validado en Django
┌───────────────▼──────────────────────────────────────────────────────┐
│  backend/  Django 5 + DRF                                           │
│  · Calcula el total (el cliente nunca decide el importe)             │
│  · Persista Order + OrderItem antes de llamar a MP                   │
│  · mp.py: único módulo que habla con api.mercadopago.com             │
└───────────────┬──────────────────────────────┬──────────────────────┘
                │ Bearer MP_ACCESS_TOKEN       │ HTTPS
                │ (solo aquí)                  │
┌───────────────▼──────────────┐   ┌───────────▼──────────────────────┐
│  PostgreSQL                 │   │  api.mercadopago.com            │
│  Product, CartItem,         │   │  /v1/orders, /v1/customers,      │
│  Order, OrderItem,          │   │  /v1/customers/{id}/cards        │
│  SavedCard, MPCustomer      │   │  ── webhook ──► POST /api/webhooks/mp/
└──────────────────────────────┘   └──────────────────────────────────┘
```

La regla que atraviesa todo el diseño: **el navegador nunca ve el Access Token
y el backend nunca ve el número de tarjeta.**

## Estructura del repositorio

### `backend/`

| Ruta | Responsabilidad |
|---|---|
| `manage.py` | Punto de entrada estándar de Django; fija `DJANGO_SETTINGS_MODULE=config.settings`. |
| `config/settings.py` | Configuración: apps, middlewares, PostgreSQL, DRF, CORS y las tres variables de MP. |
| `config/urls.py` | Enruta `/admin/` y monta `shop.urls` bajo `/api/`. |
| `config/wsgi.py`, `config/asgi.py` | Puntos de entrada WSGI/ASGI (por defecto no se usan; `runserver` usa WSGI). |
| `shop/models.py` | Los 6 modelos de negocio. |
| `shop/serializers.py` | Traduce modelos → JSON y añade `subtotal` y `display_status`. |
| `shop/views.py` | Los 10 endpoints como clases `APIView`. |
| `shop/urls.py` | Tabla de rutas de la app. |
| `shop/mp.py` | Cliente HTTP de Mercado Pago: customers, cards, orders y firma de webhook. |
| `shop/admin.py` | Registros en el admin de Django. |
| `shop/management/commands/seed_products.py` | Comando `seed_products`: 6 productos de ejemplo. |
| `shop/migrations/0001_initial.py` | Esquema inicial de la base. |
| `.env.example` | Plantilla de credenciales. |

### `frontend/`

| Ruta | Responsabilidad |
|---|---|
| `app/layout.tsx` | Layout raíz: envuelve todo en `AuthProvider` y monta el `Header`. |
| `app/page.tsx` | Catálogo de productos. |
| `app/cart/page.tsx` | Carrito con control de cantidad. |
| `app/checkout/page.tsx` | Pantalla de pago: es el archivo más complejo del proyecto. |
| `app/orders/page.tsx` | Listado de órdenes. |
| `app/orders/[id]/page.tsx` | Detalle de una orden, con polling cada 5 s si está pendiente. |
| `app/globals.css` | Estilos globales y clases utilitarias (`card`, `row`, `stack`, `badge`…). |
| `components/AuthProvider.tsx` | Contexto de autenticación + pantalla de login. |
| `components/Header.tsx` | Navegación y contador del carrito. |
| `components/StatusBadge.tsx` | Etiqueta de color según el estado de la orden. |
| `lib/api.ts` | Cliente HTTP, tipos TypeScript y formateo de moneda. |
| `lib/useMercadoPago.ts` | Hook que carga el SDK de MP con la Public Key. |
| `next.config.mjs` | Configuración de Next (vacía a propósito). |
| `tsconfig.json` | TypeScript estricto con el alias `@/*` → raíz del proyecto. |

## El flujo de pago, paso a paso

### Escenario A — Tarjeta nueva sin guardar

1. `checkout/page.tsx` monta los Secure Fields en los contenedores `f-card-number`,
   `f-expiration` y `f-cvv-new`. Cada campo es un `<iframe>` de Mercado Pago:
   el React nunca ve lo que el usuario escribe.
2. El evento `binChange` (los primeros 6 dígitos) dispara
   `mp.getPaymentMethods({ bin })` para descubrir el medio de pago. El resultado
   se guarda en el estado `pm` (`{ id: "visa", type: "credit_card" }` o
   `debit_card`, según lo que informe Mercado Pago para ese BIN).
3. `pay()` llama a `mp.fields.createCardToken({ cardholderName, identificationType,
   identificationNumber })` → un token opaco como `e0ba…`.
4. `POST /api/orders/` con `{ token, payment_method_id, payment_method_type,
   payer_email, installments: 1 }`. El checkout no permite elegir cuotas.
5. El backend calcula el total, crea `Order` + `OrderItem`, arma el payload de
   `POST /v1/orders` y lo envía con `X-Idempotency-Key`.
6. La respuesta se copia a la orden local y se redirige a `/orders/<id>`.

### Escenario B — Tarjeta nueva que se guarda

El token de Mercado Pago es **de un solo uso**, así que el flujo necesita dos:

1. Se genera un token y se manda a `POST /api/cards/`. El backend crea el
   customer (si no existe) y guarda la tarjeta vía `POST /v1/customers/{id}/cards`.
2. Se genera un **segundo** token con `{ cardId }` y se cobra con él.
3. Si el segundo token falla, no se pierde nada: la tarjeta ya quedó guardada, el
   frontend recarga la lista, selecciona esa tarjeta y le pide el CVV al usuario.
   LaUI nunca queda en un estado inconsistente.
4. El cobro se solicita en una sola exhibición (`installments: 1`), igual que con
   una tarjeta no guardada.

### Escenario C — Tarjeta guardada

1. `pay()` pide solo el CVV (Secure Field `securityCode`).
2. `mp.fields.createCardToken({ cardId })` → token.
3. `POST /api/orders/` con `{ token, saved_card_id, installments: 1 }`. El backend
   resuelve el `payment_method` desde la base y paga con `{ customer_id }` en vez
   de email; el pago es en una sola exhibición.

### Escenario D — Estados pendientes

- El frontend consulta `GET /api/orders/<id>/` cada 5 s mientras
  `display_status === "pending"` (`app/orders/[id]/page.tsx:34`).
- Si además se configura el webhook, es el mecanismo principal: MP notifica el
  cambio y el backend responde rápido. Ver
  [`estados-y-webhooks.md`](./estados-y-webhooks.md).

## Decisiones de diseño

### El total se calcula en el backend

`views.py` suma `price × quantity` desde la base. El frontend nunca envía un
importe. Un cliente malicioso podría mandar cualquier total si el servidor lo
aceptara.

### Se persiste la orden antes de llamar a MP

`views.py` abre una transacción y guarda `Order` + `OrderItem` antes del
`POST /v1/orders`. Si MP responde con error, la orden queda registrada con
`status="failed"` y el detalle del rechazo — útil para depurar y para que el
usuario tenga un registro. Además `external_reference` es un UUID único que
doble uso como **idempotency key**: reintentar el mismo pago no duplica el cobro.

### Se guarda estado crudo y derivado

`Order` almacena los estados literales de MP (`status`, `payment_status`) y el
serializer expone además `display_status`, un valor normalizado a
`approved | pending | rejected | refunded | created`. Así la UI no necesita
conocer la taxonomía de MP, pero el detalle técnico sigue disponible para
depurar (`app/orders/[id]/page.tsx:64` muestra ambos).

### El webhook nunca confía en el payload

`WebhookView` no lee el estado del cuerpo de la notificación: usa el `id` solo
para localizar la orden y luego **re-consulta a MP** (`views.py`). Si MP
dice otra cosa, la base de datos no. Además devuelve `500` cuando la consulta
falla, para que MP reintente la notificación.

### Todo es client-side

No hay Server Components ni Server Actions: todas las páginas son
`"use client"`. Es coherente con el modelo de datos, porque el estado de sesión
vive en `localStorage` y el SDK de MP necesita `window`. La contrapartida es que
las vistas no se renderizan en el servidor (SEO irrelevante en una tienda de
pruebas).

## Seguridad

| Riesgo | Mitigación |
|---|---|
| Número, CVV y vencimiento robados | Nunca salen de los iframes de MP. El backend solo recibe tokens. |
| Access Token expuesto | Vive únicamente en `backend/.env`, se usa solo en `mp.py`. |
| Importe manipulado | El total se recalcula en el servidor desde el carrito persistido. |
| Datos sensibles en la base | `SavedCard` guarda solo metadatos: últimos 4, primeros 6, vencimiento e ids. Nunca CURP ni RFC. |
| Firma de webhook falsificada | HMAC-SHA256 sobre el manifiesto de MP, con comparación en tiempo constante (`mp.py`). |
| Robar sesión | `ALLOWED_HOSTS=["*"]` y login por email sin contraseña son **atajos deliberados de prueba**. |

### Atajos que NO deben llegar a producción

Estos puntos están así a propósito y son los primeros que hay que cambiar si el
proyecto deja de ser una prueba:

1. **Login por email sin contraseña** (`views.py`) — cualquiera con el email
   obtiene una sesión. En producción: contraseña, OAuth o magic link.
2. **`ALLOWED_HOSTS = ["*"]`** (`settings.py:23`) — acepta cualquier host, lo que
   habilita ataques de Host header. Necesario solo para ngrok.
3. **`DEBUG=True` por defecto** (`settings.py:22`) — filtra variables y trazas.
4. **`SECRET_KEY` con valor de relleno** (`settings.py:21`).
5. **Emails de prueba forzados** (`ENFORCE_TEST_EMAIL`) — una barrera, no un
   control de acceso.

## Puesta en marcha

Requisitos: Python 3.10+, Node 20+, pnpm, PostgreSQL.

```bash
# 1. Credenciales
cp backend/.env.example backend/.env   # y pega tus claves TEST-

# 2. Backend
cd backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_products
python manage.py runserver            # http://localhost:8000

# 3. Frontend
cd frontend
pnpm install
pnpm dev                              # http://localhost:3000
```

`frontend/.env.local` ya apunta a `http://localhost:8000/api`.

## Recorrido de la app

1. Abre http://localhost:3000. El login pide un email con formato
   `test_payer_123456@testuser.com`; hay un botón que genera uno válido.
2. Agrega productos al carrito, ajústalo en `/cart` y pulsa **Ir a pagar**.
3. En `/checkout` elige tarjeta guardada o nueva.
4. El resultado aparece en `/orders/<id>` y en `/admin`.

## Configuración

### `backend/.env`

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `DJANGO_SECRET_KEY` | `dev-only-insecure-key` | Firma de sesiones y tokens. |
| `DJANGO_DEBUG` | `True` | Modo debug. |
| `MP_PUBLIC_KEY` | vacío | Se entrega al frontend vía `GET /api/config/`. |
| `MP_ACCESS_TOKEN` | vacío | Único acceso a la API de MP. |
| `MP_WEBHOOK_SECRET` | vacío | Si falta, el webhook acepta todo (solo pruebas). |
| `ENFORCE_TEST_EMAIL` | `True` | Exige el patrón `test_payer_\d+@testuser.com`. |
| `POSTGRES_DB` / `_USER` / `_PASSWORD` / `_HOST` / `_PORT` | `save_carts` / `root` / `root` / `localhost` / `5432` | Conexión a la base. |

### `frontend/.env.local`

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api` | Base del cliente HTTP. |

## CORS

`settings.py:100` acepta solo `localhost` y `127.0.0.1` con cualquier puerto. Si
moves el frontend a otro origen, ajusta esa expresión regular (o la variable
`FRONTEND_ORIGIN` de `.env.example`, que **no está cableada** en `settings.py`).

## Dependencias

**Backend** (`requirements.txt`): Django ≥5.0, DRF ≥3.15, django-cors-headers,
**mercadopago ≥3.6 (SDK oficial de MP)**, requests (solo para los scripts de
depuración `diag*.py`), python-dotenv, psycopg2-binary.

**Frontend** (`package.json`): Next 15, React 19, `@mercadopago/sdk-js`, TypeScript 5.6.

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| "Falta MP_PUBLIC_KEY en backend/.env" | Variable vacía o `runserver` sin reiniciar tras editarla. |
| Error de CORS en el navegador | El frontend no corre en `localhost:3000`. |
| MP rechaza la orden con 4xx | Email/customer no es de prueba, o credenciales de producción. El detalle queda en `Order.status_detail`. |
| La orden se queda en `pending` | Sin webhook configurado. El polling de 5 s debería resolverla; si no, revisa `status_detail`. |
| `400` al guardar una tarjeta | El token ya se consumió (los tokens son de un solo uso). |