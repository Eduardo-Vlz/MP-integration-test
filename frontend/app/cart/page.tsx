"use client";
/**
 * Carrito con control de cantidad.
 *
 * El botón "−" llama a `update(id, quantity - 1)`; al llegar a 0 el backend
 * ELIMINA la línea en lugar de guardar un cero, que es exactamente el
 * comportamiento esperado aquí sin tener que comprobar nada en la UI.
 *
 * Detalle: `setCart(next)` sustituye el estado con la respuesta del backend, así que
 * el total y los subtotales siempre vienen recalculados por el servidor.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Cart, errorMessage, money } from "@/lib/api";

export default function CartPage() {
  const [cart, setCart] = useState<Cart | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api<Cart>("/cart/").then(setCart).catch((e) => setMsg(errorMessage(e)));
  }, []);

  /** Fija la cantidad de una línea. Con `qty <= 0` el backend la borra. */
  async function update(productId: number, qty: number) {
    const next = await api<Cart>(`/cart/${productId}/`, { method: "PATCH", body: { quantity: qty } });
    setCart(next);
    window.dispatchEvent(new Event("cart-updated"));
  }

  // Una sola condición cubre "cargando" y "error".
  if (!cart) return <p>{msg || "Cargando..."}</p>;

  return (
    <>
      <h1>Carrito</h1>
      {cart.items.length === 0 ? (
        <p>Tu carrito está vacío. <Link href="/">Ver productos</Link></p>
      ) : (
        <div className="card stack">
          {cart.items.map((i) => (
            <div className="row spread" key={i.id}>
              <span>{i.product.emoji} {i.product.name}</span>
              <div className="row">
                <button className="secondary small" onClick={() => update(i.product.id, i.quantity - 1)}>−</button>
                <span>{i.quantity}</span>
                <button className="secondary small" onClick={() => update(i.product.id, i.quantity + 1)}>+</button>
                <b style={{ minWidth: 100, textAlign: "right" }}>{money(i.subtotal)}</b>
              </div>
            </div>
          ))}
          <hr />
          <div className="row spread"><b>Total</b><b>{money(cart.total)}</b></div>
          <Link href="/checkout"><button style={{ width: "100%" }}>Ir a pagar</button></Link>
        </div>
      )}
    </>
  );
}
