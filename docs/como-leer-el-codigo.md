# Cómo leer este código

Guía de orientación: **qué se ejecuta, en qué orden y por dónde empezar a leer**. No
repite lo que ya explican los otros documentos; los complementa con las trazas de
ejecución.

| Documento | Responde a |
|---|---|
| Este | ¿Qué corre al arrancar? ¿Qué se llama al hacer clic? ¿Por dónde leo? |
| [`arquitectura.md`](./arquitectura.md) | Por qué el proyecto está diseñado así. |
| [`api.md`](./api.md) | Cómo es cada endpoint, campo por campo. |
| [`backend.md`](./backend.md) / [`frontend.md`](./frontend.md) | Qué hace cada archivo. |
| [`estados-y-webhooks.md`](./estados-y-webhooks.md) | Los estados de Mercado Pago y el ciclo del webhook. |
| [`modelo-de-datos.md`](./modelo-de-datos.md) | Los 6 modelos y sus campos. |

---

## 1. Qué se ejecuta al arrancar

El proyecto son **dos procesos independientes** que hay que levantar por separado.
No hay un comando único: el frontend y el backend no se conocen hasta que uno hace
una petición al otro.

### Backend — `python manage.py runserver`

```
manage.py:26          main() · lo primero que se ejecuta
  ↓
manage.py:34          fija DJANGO_SETTINGS_MODULE=config.settings
  ↓
config/settings.py:19 load_dotenv(BASE_DIR / ".env")  ← aquí entran MP_PUBLIC_KEY
                                                         y MP_ACCESS_TOKEN
  ↓
settings.py:25        INSTALLED_APPS incluye "shop" → Django importa shop/apps.py,
                      models.py, serializers.py, views.py, urls.py
  ↓
config/wsgi.py        get_wsgi_application() ← el servidor de desarrollo usa WSGI
  ↓
config/urls.py:11     path("api/", include("shop.urls"))  ← de aquí en adelante,
                                                          toda URL vive bajo /api/
  ↓
shop/urls.py:30       path("orders/", OrderListCreateView.as_view())
  ↓
shop/views.py    OrderListCreateView.post() ← el código que ejecuta la petición
```

Lo importante de este arranque: **Django no lee `models.py` para tocar la base, usa
las migraciones**. `python manage.py migrate` aplica
`shop/migrations/0001_initial.py`, y por eso hay que ejecutarlo antes de `runserver`.

### Frontend — `pnpm dev`

```
package.json:6        "dev": "next dev"
  ↓
app/layout.tsx:13     RootLayout, el layout raíz del App Router. Envuelve TODO en
                      AuthProvider y monta el Header.
  ↓
components/AuthProvider.tsx:32   lee email de localStorage
  ↓
components/AuthProvider.tsx:60   si NO hay email → devuelve el formulario de login
                                  en lugar de children
                      ↓ (si hay email)
app/<ruta>/page.tsx   la página de la ruta: /, /cart, /checkout, /orders
  ↓
components/Header.tsx:31         escucha el evento "cart-updated" del carrito
```

Ese `if (!email)` de `AuthProvider` es lo que hace que **no exista un
`<ProtectedRoute>`**: una sola comprobación en el layout raíz protege todas las
páginas, incluidas las que se añadan en el futuro.

Las rutas que necesitan el SDK de Mercado Pago pasan por `useMercadoPago()`:

```
lib/useMercadoPago.ts:29   GET /api/config/  → la Public Key, que vive en el backend
lib/useMercadoPago.ts:32   loadMercadoPago() → descarga el script del SDK
lib/useMercadoPago.ts:35   new window.MercadoPago(public_key)
                           → devuelve { mp, error }; mientras mp es null, el botón
                             de pagar queda deshabilitado
```

La Public Key se pide al backend en vez de estar en el bundle para que las
credenciales de MP se configuren en **un solo lugar**.

---

## 2. El viaje de una petición

Toda petición de la app recorre siempre este camino. Tomamos de ejemplo
**agregar un producto al carrito**, que es la más corta:

```
1. NAVEGADOR
   app/page.tsx:23       add(p) → api("/cart/", { method: "POST" })
         ↓
2. FRONTEND
   lib/api.ts:42         lee el token de localStorage por su cuenta
   lib/api.ts:43         fetch() + cabecera "Authorization: Token <token>"
         ↓  (el navegador envía un OPTIONS previo: preflight)
3. BACKEND — capa de framework
   settings.py:41        CorsMiddleware responde al preflight. Va PRIMERO a
                         propósito: si no, CsrfViewMiddleware rechaza antes.
   settings.py:93        TokenAuthentication valida el token → asigna request.user
   settings.py:94        IsAuthenticated: sin token válido, 401 y la vista no corre
         ↓
4. BACKEND — capa de aplicación
   shop/urls.py:26       /api/cart/ → CartView
   shop/views.py     CartView.post() → get_or_create del CartItem
   shop/models.py:79     unique_together garantiza una sola línea por producto
         ↓
5. RESPUESTA — de vuelta hacia arriba
   views.py           return self.get(request)  ← reutiliza CartView.get
   serializers.py:23     ProductSerializer + get_subtotal() calculan el JSON
   lib/api.ts:54         si !res.ok → throw ApiError
   page.tsx:26           window.dispatchEvent("cart-updated") → Header refresca
```

Dos detalles de este recorrido que no son obvios:

- **Las mutaciones del carrito devuelven el carrito entero** (`views.py`).
  Reutilizan `CartView.get` en lugar de escribir la respuesta a mano, para que el
  cliente nunca necesite un segundo fetch.
- **El `finally { setLoaded(true) }`** en `checkout/page.tsx:64` importa: si la
  carga inicial falla, la pantalla quedaría en "Cargando..." para siempre.

---

## 3. El flujo de pago, archivo por archivo

Este es el camino completo de un cobro. Los comentarios `PASO n` del código siguen la
misma numeración.

```
NAVEGADOR
  1. app/checkout/page.tsx:120   se montan los iframes de Secure Fields
                                (PASO 1 del efecto)
  2. app/checkout/page.tsx:143   binChange → getPaymentMethods({bin}) deduce si es
                                débito o crédito y lo guarda en `pm`
  3. app/checkout/page.tsx:213   pay() se ejecuta al enviar el formulario
     · :231  tarjeta guardada  → 1 token con cardId
     · :248  tarjeta nueva     → 1 token con los datos
     · :259  nueva + guardar   → 2 tokens: uno al guardar, otro con cardId
  4. app/checkout/page.tsx:302   POST /api/orders/ con el token
  5. app/orders/[id]/page.tsx:34 si queda "pending", polling cada 5 s

BACKEND
  6.  shop/views.py     OrderListCreateView.post
      · :221  PASO 1  valida el token
      · :230  PASO 2  lee el carrito persistido (no lo que manda el cliente)
      · :248  PASO 3  decide payer: customer_id o email
      · :268  PASO 4  guarda Order + OrderItem en una transacción
      · :283  PASO 5  arma el payload de POST /v1/orders
      · :308  PASO 6  create_order() con X-Idempotency-Key
      · :318  PASO 7  apply_mp_order() o guarda el fallo con su motivo
      · :337  PASO 8  vacía el carrito solo si el pago no falló
  7.  shop/mp.py       create_order → POST /v1/orders
      shop/mp.py       apply_mp_order → copia el estado de MP a la base
  8.  shop/serializers.py:82  display_status normaliza el estado para la UI

MERCADO PAGO
  9.  api.mercadopago.com  responde
 10.  (si hay webhook) POST → backend/shop/views.py → mp.py refresh_order
```

Los comentarios `PASO n` del código usan la misma numeración, así que se puede seguir
esta traza con el archivo abierto al lado.

### Por qué los tokens son de un solo uso

Es la razón de que "tarjeta nueva + guardar" necesite **dos** tokens, y el mejor modo
de entenderlo:

1. El primer token se canjea en `POST /api/cards/`, que lo manda a
   `POST /v1/customers/{id}/cards`. Mercado Pago lo consume al vincular la tarjeta.
2. Para cobrar hace falta un token **nuevo**, esta vez con `{ cardId }`.

Si el segundo falla, la tarjeta **ya quedó guardada**: el frontend recarga la lista,
la selecciona y pide solo el CVV (`page.tsx:274`). No se pierde nada y el usuario
cae en el flujo de tarjeta guardada.

---

## 4. Por dónde empezar a leer

Orden propuesto, de menos a más detalle:

**Nivel 1 — La idea en 10 minutos**

1. `README.md` — qué es y cómo se arranca.
2. `docs/arquitectura.md:18` — el diagrama de capas. Toda decisión del proyecto se
   deriva de la regla de la línea siguiente: *el navegador nunca ve el Access Token
   y el backend nunca ve el número de tarjeta*.

**Nivel 2 — Recorrer una petición completa**

3. `frontend/lib/api.ts` — 128 líneas y todo el acceso a datos pasa por ahí. Empieza
   aquí si quieres entender cómo el frontend habla con Django.
4. `backend/config/settings.py` — sobre todo el bloque `REST_FRAMEWORK` (línea 90),
   que explica la autenticación, y `CORS_ALLOWED_ORIGIN_REGEXES` (línea 100).
5. `backend/shop/urls.py` — la tabla de rutas completa, 33 líneas. Es el mapa del API.

**Nivel 3 — El pago**

6. `frontend/app/checkout/page.tsx` — el archivo más complejo del proyecto, y a
   propósito: reúne selector de método, Secure Fields, tokenización y creación de
   orden. Los comentarios `PASO n` guían la lectura.
7. `backend/shop/views.py` — las 10 clases. Si solo te interesa el cobro, lee
   `OrderListCreateView` (línea 192) y `WebhookView` (línea 359).
8. `backend/shop/mp.py` — el único archivo que habla con Mercado Pago (a través
   del SDK oficial). Empieza por `_call` (línea 80) para ver la capa HTTP, y
   `display_status` para entender el mapeo de estados.

**Nivel 4 — Contexto**

9. `backend/shop/models.py` — 123 líneas con los 6 modelos y el porqué de cada
   decisión (`PROTECT` en vez de `CASCADE`, `Decimal` en vez de `float`).
10. `docs/estados-y-webhooks.md` — qué significa cada estado de MP.

### Si solo quieres entender el pago, lee estos 6 archivos

En este orden, y con nada más:

```
frontend/app/checkout/page.tsx    el usuario pulsa Pagar aquí
backend/shop/views.py             OrderListCreateView.post: qué se cobra y por qué
backend/shop/mp.py                cómo se habla con Mercado Pago
backend/shop/models.py            qué se guarda
backend/shop/serializers.py       qué ve la UI
backend/shop/mp.py                display_status: la traducción a la UI
```

---

## 5. Cómo orientarte en el código

- **Comentarios `PASO n`** en `checkout/page.tsx` y `views.py`: marcan el orden real
  de ejecución dentro de la función. La misma numeración aparece en la sección 3.
- **referencias `ruta:línea`** en la documentación: navegan directo al punto exacto.
- **docstrings de módulo**: cada archivo empieza explicando su responsabilidad y qué
  decide NO hacer. La parte "por qué" suele estar al final.
- **"atajo de pruebas"** en un comentario significa que el código es deliberadamente
  inseguro y está listado en `docs/arquitectura.md:190`. No lo lleves a producción.
- **`backend/diag.py`, `diag2.py`, `diag3.py`** son scripts sueltos de depuración que
  se usaron una vez y **no forman parte de la app**. Nada los importa.

---

## 6. Lo primero que romperse

Si algo falla, estos son los cuatro puntos de comprobación, en orden:

| Síntoma | Dónde mirar |
|---|---|
| "Falta MP_PUBLIC_KEY" | `backend/.env`, y reiniciar `runserver` tras editarla |
| Error de CORS en el navegador | Que el frontend corra en `localhost:3000` (`settings.py:100`) |
| MP rechaza la orden (4xx) | `Order.status_detail` en `/admin`, o el bloque `debug` de `/orders/<id>` |
| La orden se queda en `pending` | Sin webhook configurado; el polling de 5 s debería resolverla |

Detalle completo en [`arquitectura.md`](./arquitectura.md#problemas-frecuentes).