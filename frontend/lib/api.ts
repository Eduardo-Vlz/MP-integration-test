/**
 * Capa de acceso a datos del frontend: cliente HTTP, tipos y formateo de moneda.
 *
 * Los tipos reflejan lo que devuelve DRF, no los modelos Django. Los importes son
 * `string` porque el backend los serializa con 2 decimales para no perder precisión.
 *
 * Referencia de la API: docs/api.md
 */

/** Base de las peticiones. El prefijo `NEXT_PUBLIC_` es obligatorio: Next solo
 *  inyecta en el bundle las variables que empiezan así. */
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

/**
 * Error de una respuesta no-2xx. Extiende `Error` para poder lanzarse con `throw`
 * y seguir siendo capturable con `try/catch` normal; `message` ya es legible.
 */
export class ApiError extends Error {
  status: number;
  data: any;
  constructor(status: number, data: any) {
    super(typeof data?.detail === "string" ? data.detail : `Error ${status}`);
    this.status = status;
    this.data = data;
  }
}

/**
 * Fetch central. Lee el token de `localStorage` por su cuenta (así cada consumidor
 * no tiene que acordarse de pasarlo) y normaliza los errores a `ApiError`.
 *
 * @param path  Ruta relativa a `API_URL`, p. ej. `"/cart/"`.
 * @param opts  `method` y `body` (se serializa a JSON).
 * @throws {ApiError} en cualquier respuesta no-2xx.
 */
export async function api<T = any>(
  path: string,
  opts: { method?: string; body?: unknown } = {},
): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const res = await fetch(`${API_URL}${path}`, {
    method: opts.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Token ${token}` } : {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  // `catch(() => null)` evita que reviente el await si la respuesta no es JSON
  // (típico de un 502 del proxy de desarrollo).
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

/** Texto legible para mostrar un error (incluye detalle de Mercado Pago si viene). */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const mp = e.data?.mp;
    const mpMsg = mp?.errors?.[0]?.message || mp?.message;
    return mpMsg ? `${e.message}: ${mpMsg}` : e.message;
  }
  if (e instanceof Error) return e.message;
  if (typeof e === "object" && e) return JSON.stringify(e);
  return String(e);
}

/** Producto del catálogo. */
export type Product = {
  id: number;
  name: string;
  description: string;
  price: string;
  emoji: string;
  stock: number;
};
/** Línea de carrito. `subtotal` lo calcula el backend. */
export type CartItem = {
  id: number;
  product: Product;
  quantity: number;
  subtotal: string;
};
/** Carrito completo con su total recalculado en el servidor. */
export type Cart = { items: CartItem[]; total: string };
/** Metadatos de una tarjeta guardada. `card_id_mp` es lo que el backend espera
 *  como `saved_card_id`. Nunca incluye número completo ni CVV. */
export type SavedCard = {
  id: number;
  card_id_mp: string;
  last_four_digits: string;
  first_six_digits: string;
  expiration_month: number;
  expiration_year: number;
  payment_method_id: string;
  payment_method_type: string;
  payment_method_name: string;
  is_default: boolean;
};
/**
 * Orden de compra.
 *
 * `status` y `payment_status` son los valores CRUDOS de MP; `display_status` es el
 * normalizado. La unión de tipos de `display_status` es lo que permite que
 * `StatusBadge` sea exhaustivo sin recurrir a `any`.
 *
 * Mapeo completo: docs/estados-y-webhooks.md
 */
export type Order = {
  id: number;
  total: string;
  mp_order_id: string;
  status: string;
  payment_status: string;
  status_detail: string;
  display_status: "approved" | "pending" | "rejected" | "refunded" | "created";
  created_at: string;
  items: { product_name: string; quantity: number; unit_price: string }[];
};

/** Formatea un importe en pesos mexicanos. Centralizado para que toda la app
 *  use el mismo formato. */
export const money = (v: string | number) =>
  new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" }).format(
    Number(v),
  );
