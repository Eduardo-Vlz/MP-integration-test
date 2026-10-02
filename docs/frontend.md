# Frontend

Next.js 15 con App Router, React 19 y TypeScript estricto. Toda la lógica de
pago vive aquí, junto con los iframes de Secure Fields de Mercado Pago.

## Enfoque general

Cada página es un Client Component (`"use client"`) que carga sus datos con
`useEffect` al montar. No hay Server Components, Server Actions ni fetching en el
servidor. Es coherente con el diseño: la sesión vive en `localStorage`, el SDK de
MP requiere `window`, y los datos dependen del usuario autenticado.

Consecuencia: las páginas se renderizan vacías en el servidor y se rellenan en el
cliente. Para una tienda de pruebas es aceptable; en producción condicionaría el
diseño (y el SEO).

## Configuración

### `next.config.mjs`

Vacío a propósito. Sin imágenes remotas, sin rewrites, sin headers propios. El
backend es la única fuente de datos y no se sirve nada desde el filesystem
público.

### `tsconfig.json`

TypeScript en modo `strict`. Lo relevante:

- `strict: true` —obligatorio para que los tipos de `lib/api.ts` sirvan de algo.
- `paths: { "@/*": ["./*"] }` — es lo que permite los imports `@/lib/api` y
  `@/components/Header`. **El alias apunta a la raíz**, no a `src/`, porque no hay
  carpeta `src`.
- `moduleResolution: "bundler"` y `isolatedModules: true` — lo que exige Next 15.
- `jsx: "preserve"` — Next transforma el JSX en el build.

### `package.json`

| Dependencia | Versión | Para qué |
|---|---|---|
| `next` | ^15.1.0 | Framework. |
| `react` / `react-dom` | ^19.0.0 | Runtime. |
| `@mercadopago/sdk-js` | ^0.0.3 | Secure Fields, tokens y catálogo de medios de pago. |

Scripts: `dev`, `build`, `start`.

## `lib/api.ts`

Capa de acceso a datos del frontend.

### `API_URL`

Base de las peticiones. Lee `NEXT_PUBLIC_API_URL` y si no existe usa
`http://localhost:8000/api`. El prefijo `NEXT_PUBLIC_` es obligatorio: Next solo
inyecta en el bundle las variables que empiezan así.

### `ApiError`

Extiende `Error` con dos campos: `status` y `data`. Al extending de `Error` puede
lanzarse con `throw` y seguir siendo capturable con `try/catch` normal, y su
`message` ya es legible por defecto.

### `api<T>()`

El fetch central. Characteristics:

- **Lee el token de `localStorage`** en cada llamada, en lugar de recibirlo como
  argumento. Evita que cada consumidor tenga que acordarse.
- Adjunta `Authorization: Token <token>` solo si hay token.
- Trata `204` como `null` en vez de intentar `res.json()` sobre un cuerpo vacío.
- Usa `catch(() => null)` al parsear: una respuesta con HTML de error (por ejemplo
  un 502 del proxy de desarrollo) no revienta el `await`.
- Lanza `ApiError` con cualquier respuesta no-2xx.

### `errorMessage()`

Convierte cualquier excepción en texto para la UI. La parte interesante es que
inspecciona `e.data.mp` para extraer el mensaje real de Mercado Pago. Sin esto,
un rechazo de MP se mostraría como el genérico "Error 400" y no habría forma de
saber qué pasó sin abrir las herramientas de desarrollo.

### Tipos

Los tipos reflejan lo que devuelve DRF, no los modelos Django:

- `Product`, `CartItem`, `Cart`
- `SavedCard` — incluye `card_id_mp` porque es lo que el backend espera en
  `saved_card_id`.
- `Order` — con `display_status` restringido a la unión
  `"approved" | "pending" | "rejected" | "refunded" | "created"`. Esa restricción
  es lo que permite que `StatusBadge` sea exhaustivo sin `any`.

Nota: `price`, `total`, `subtotal` y `unit_price` son `string` porque el backend
los serializa con 2 decimales para no perder precisión.

### `money()`

`Intl.NumberFormat("es-MX")` en pesos. Centralizar el formateo evita que cada
página use un formato distinto.

## `lib/useMercadoPago.ts`

Hook que instancia el SDK de MP una sola vez para toda la app.

Secuencia dentro del `useEffect`:

1. `GET /api/config/` para obtener la `public_key`.
2. Falla rápido si viene vacía, con un mensaje que señala `backend/.env`.
3. `loadMercadoPago()` inyecta el script del SDK.
4. `new MercadoPago(public_key, { locale: "es-MX" })`.

Dos detalles:

- **`public_key` se pide al backend** en lugar de estar en el bundle del frontend.
  Así las credenciales de MP se configuran en un solo lugar.
- **Guardia `cancelled`** en el cleanup del efecto: si el componente se desmonta
  antes de que terminen las llamadas asíncronas, se aborta la actualización de
  estado en lugar de avisar a React sobre un componente inexistente.

Devuelve `{ mp, error }`. Casi todas las vistas renderizan igual: si `mp` es
`null`, el botón de pagar queda deshabilitado.

## `components/AuthProvider.tsx`

Contexto de autenticación y pantalla de login en el mismo archivo.

### El contexto

```ts
type AuthCtx = { email: string | null; logout: () => void };
```

Expuesto con `useAuth()`. Deliberadamente **no expone el token**: los componentes
no necesitan leerlo, y mantenerlo fuera del contexto evita que se propague por el
árbol de React. `lib/api.ts` lo lee de `localStorage` por su cuenta.

### El trick del login gate

Mientras no haya email, el provider **no renderiza `children`**: devuelve el
formulario de login en su lugar. Un solo `if (!email) return <form/>` en el
provider protege toda la app, sin necesidad de un `<ProtectedRoute>` en cada
página. `ready` evita un parpadeo de ese formulario durante la hidratación,
mientras se lee el `localStorage`.

### Generador de email de prueba

Un botón crea un email aleatorio con el formato requerido. Existe porque el login
rechaza cualquier email que no cumpla `test_payer_\d+@testuser.com`, y bloquearía
a quien no conozca la convención.

### `login()` y `logout()`

Guardan y borran `token` y `email` de `localStorage`. No hay expiración ni
renovación: el token de DRF no expira, lo cual es aceptable en pruebas.

## `components/Header.tsx`

Navegación, email del usuario y contador del carrito.

### Sincronización del contador por evento

```ts
window.addEventListener("cart-updated", refresh);
```

El carrito vive en el backend y varias páginas lo modifican. En vez de un estado
global o revalidaciones de Next, las páginas que mutan el carrito lanzan
`window.dispatchEvent(new Event("cart-updated"))` y el Header escucha.

Es un bus de eventos mínimo, adecuado a la escala del proyecto. En una app con
estado compartido (Zustand, Context, server cache) sería mejor, porque el
`dispatch` desde cada página es fácil de olvidar.

El cleanup del `useEffect` quita el listener para no filtrar suscripciones.

## `components/StatusBadge.tsx`

Mapea `display_status` a una etiqueta con emoji y color:

| Estado | Etiqueta | Clase CSS |
|---|---|---|
| `approved` | ✅ Aprobado | `.badge.approved` |
| `pending` | ⏳ Pendiente | `.badge.pending` |
| `rejected` | ❌ Rechazado | `.badge.rejected` |
| `refunded` | ↩️ Reembolsado | (color por defecto) |
| `created` | Creada | (color por defecto) |

El fallback `?? status` muestra el valor crudo si llega algo no previsto.

## `app/layout.tsx`

Layout raíz: importa los estilos globales, envuelve en `AuthProvider` y monta el
`Header`. Como el login gate vive en el provider, este archivo es también lo que
garantiza que **ninguna página se renderice sin sesión**.

También exporta los `metadata` del sitio.

## `app/page.tsx` — Catálogo

Carga los productos al montar y los pinta en una rejilla. `add()` postea al
carrito y lanza `cart-updated` para que el Header actualice el contador.

Los mensajes de éxito y error comparten el estado `msg` y se muestran en un único
`<p className="muted">`, sin temporizador: el mensaje persiste hasta la siguiente
acción.

## `app/cart/page.tsx` — Carrito

Control de cantidad con dos botones. El botón "−" llama a
`update(id, quantity - 1)`; cuando la cantidad llega a 0 el backend **elimina la
línea** en lugar de guardar un cero (`views.py`), que es exactamente el
comportamiento que la UI espera sin tener que comprobar nada.

Mientras no haya respuesta, devuelve `<p>{msg || "Cargando..."}</p>`: una sola
condición cubre ambos estados.

## `app/checkout/page.tsx` — Pago

El archivo más complejo del proyecto. 234 líneas y cuatro responsabilidades
distintas.

### Estado

| Variable | Para qué |
|---|---|
| `cart` / `cards` / `loaded` | Datos cargados en paralelo. |
| `selected` | `"new"` o un `card_id_mp`. Decide qué campos se montan. |
| `name`, `idType`, `idNumber`, `email` | Datos que el SDK necesita para tokenizar. |
| `save` | Checkbox de "guardar esta tarjeta". |
| `pm` | Medio de pago detectado desde el BIN. `null` = aún no se sabe. |
| `busy`, `error`, `info` | Estado de la petición. |

### `selected` como modo único

En lugar de tres booleanos (`isNew`, `showCvv`, …), un solo string decide qué se
muestra. La tarjeta predeterminada se selecciona automáticamente al cargar, así
el caso común es el más rápido.

### Carga inicial

`Promise.all` para carrito y tarjetas en paralelo. En `finally` se marca
`loaded`, que es lo que dispara el montaje de los Secure Fields.

### Tipos de identificación

`mp.getIdentificationTypes()` alimenta el `<select>` de identificación una vez que
el SDK está listo. El `catch(() => {})` es deliberado: si falla, el campo queda
vacío y el checkout sigue siendo utilizable.

### Montaje de Secure Fields

Es el bloque más delicado:

- Tarjeta nueva → monta `cardNumber`, `expirationDate` y `securityCode`.
- Tarjeta guardada → monta **solo** `securityCode`.

Cada campo es un `<iframe>` de MP montado dentro de un contenedor `<div>` con id.
**React nunca controla su contenido.** El `div` es un punto de anclaje vacío.

- El evento `binChange` dispara `mp.getPaymentMethods({ bin })` con los primeros
  6 dígitos y guarda el medio de pago detectado. Si no reconoce el BIN, deja `pm`
  en `null` y `pay()` lanza un error explicativo. El tipo (`credit_card` o
  `debit_card`) se toma de la respuesta de Mercado Pago para ese BIN.
- La función de limpieza llama a `unmount()` en cada campo montado, envuelto en
  `try/catch` porque el SDK lanza si el iframe ya desapareció. Sin este cleanup,
  cambiar entre tarjeta nueva y guardada dejaría iframes huérfanos en el DOM.

### Débito, crédito y cuotas

El checkout admite tarjetas de débito y crédito que Mercado Pago identifica a
partir del BIN. No muestra un selector de cuotas: en todos los casos de pago,
incluidas las tarjetas guardadas, envía `installments: 1` para solicitar un pago
en una sola exhibición.

### `pay()` y los dos tokens

La lógica del "token nuevo + guardar" es la parte más sutil:

1. Se genera un token y se envía a `POST /api/cards/`. **Ese token queda
   consumido.**
2. Se genera un segundo token con `{ cardId }` para el cobro.
3. Si el segundo token falla, no hay error para el usuario: la tarjeta ya quedó
   guardada, así que se recarga la lista, se selecciona esa tarjeta y se le pide
   solo el CVV. El `return` temprano es lo que evita intentar cobrar con un token
   gastado.

### Redirección

Tras `POST /orders/` se lanza `cart-updated` y se navega a `/orders/<id>`, que se
encarga del seguimiento.

## `app/orders/page.tsx` — Listado

Lista las órdenes con total y `StatusBadge`, cada una enlazando a su detalle.
Formatea `created_at` con `toLocaleString("es-MX")`.

## `app/orders/[id]/page.tsx` — Detalle con polling

El polling está implementado con `setTimeout` recursivo en lugar de
`setInterval`:

```ts
async function load() {
  const o = await api<Order>(`/orders/${id}/`);
  setOrder(o);
  if (o.display_status === "pending") timer = setTimeout(load, 5000);
}
```

`setInterval` debería esperar entre invocaciones sin depender de la anterior: si
una petición tarda más de 5 s, se acumularían. Con `setTimeout` encadenado, la
siguiente consulta se agenda **después** de recibir la respuesta, así nunca hay
peticiones solapadas.

Además solo reprograma si el estado sigue siendo `pending`: una orden terminada
deja de consultar sola.

El cleanup marca `stopped` y limpia el temporizador, para que navegar fuera
mientras está pendiente no produzca un `setState` en un componente desmontado.

La tarjeta incluye un bloque `.debug` con `mp_order_id`, `status`,
`payment_status` y `status_detail`: los valores crudos de MP, útiles para
depurar por qué una orden quedó como quedó.

## `app/globals.css`

38 líneas de CSS puro con variables CSS. Sin framework ni CSS-in-JS.

Convenciones de clases:

| Clase | Significado |
|---|---|
| `.container` / `.narrow` | Ancho máximo del contenido. |
| `.row` / `.stack` | Flex horizontal / vertical. |
| `.spread` | `justify-content: space-between`. |
| `.card` | Superficie elevada. |
| `.grid` | Rejilla del catálogo, responsive con `auto-fill`. |
| `.two-cols` | Checkout en dos columnas; colapsa a una bajo 760 px. |
| `.field` | Contenedor de un Secure Field. `.field iframe { width: 100% }` hace que el iframe de MP ocupe el hueco. |
| `.option` | Tarjeta seleccionable del checkout, con `.active` para la elegida. |
| `.badge` + modificadores | Etiquetas de estado. |
| `.error`, `.muted`, `.small`, `.debug` | Utilidades de texto. |

Los colores de marca viven en variables (`:root`), lo que permite cambiar la
paleta entera editando seis líneas.

## Notas de mantenimiento

- **Añadir un campo a un tipo**: actualizar el tipo en `lib/api.ts` y el
  serializer en `backend/shop/serializers.py`. Los tipos son la documentación que
  el compilador usa para detectar discrepancias.
- **Cambiar el flujo de pago**: `pay()` en `app/checkout/page.tsx` es el único
  punto de entrada, y `OrderListCreateView.post` el único del backend.
- **El SDK de MP está tipado como `any`** en todo el proyecto. Es pragmático
  (el paquete no trae tipos completos) pero si se quisiera tipado estricto,
  `useMercadoPago` sería el lugar natural para centralizar una interfaz propia.