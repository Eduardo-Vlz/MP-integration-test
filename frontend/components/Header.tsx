"use client";
/**
 * Navegación, email del usuario y contador del carrito.
 *
 * El carrito vive en el backend y lo modifican varias páginas. En vez de estado
 * global o revalidaciones de Next, las páginas que mutan el carrito lanzan
 * `window.dispatchEvent(new Event("cart-updated"))` y este componente escucha.
 * Es un bus de eventos mínimo, adecuado a la escala del proyecto; con estado
 * compartido (Zustand, Context, server cache) sería más robusto.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, Cart } from "@/lib/api";
import { useAuth } from "./AuthProvider";

export default function Header() {
  const { email, logout } = useAuth();
  const [count, setCount] = useState(0);

  /** Recalcula el número total de unidades en el carrito. */
  const refresh = useCallback(async () => {
    try {
      const cart = await api<Cart>("/cart/");
      setCount(cart.items.reduce((n, i) => n + i.quantity, 0));
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
    // El cleanup quita el listener para no filtrar suscripciones.
    window.addEventListener("cart-updated", refresh);
    return () => window.removeEventListener("cart-updated", refresh);
  }, [refresh]);

  return (
    <header className="header">
      <div className="container row spread">
        <nav className="row">
          <Link href="/"><b>🛍️ Tienda de prueba</b></Link>
          <Link href="/cart">Carrito ({count})</Link>
          <Link href="/orders">Mis órdenes</Link>
        </nav>
        <div className="row">
          <span className="muted small">{email}</span>
          <button className="secondary small" onClick={logout}>Salir</button>
        </div>
      </div>
    </header>
  );
}
