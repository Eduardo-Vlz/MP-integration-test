"use client";
/**
 * Catálogo de productos.
 *
 * Carga el catálogo al montar y lo pinta en una rejilla. `add()` postea al carrito
 * y lanza `cart-updated` para que el Header actualice el contador.
 *
 * Los mensajes de éxito y error comparten el estado `msg` y se muestran en un
 * único `<p className="muted">`, sin temporizador: el mensaje persiste hasta la
 * siguiente acción.
 */
import { useEffect, useState } from "react";
import { api, errorMessage, money, Product } from "@/lib/api";

export default function Home() {
  const [products, setProducts] = useState<Product[]>([]);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api<Product[]>("/products/").then(setProducts).catch((e) => setMsg(errorMessage(e)));
  }, []);

  async function add(p: Product) {
    try {
      await api("/cart/", { method: "POST", body: { product_id: p.id, quantity: 1 } });
      window.dispatchEvent(new Event("cart-updated"));
      setMsg(`"${p.name}" agregado al carrito`);
    } catch (e) {
      setMsg(errorMessage(e));
    }
  }

  return (
    <>
      <h1>Productos</h1>
      {msg && <p className="muted">{msg}</p>}
      <div className="grid">
        {products.map((p) => (
          <div className="card stack" key={p.id}>
            <div className="emoji">{p.emoji}</div>
            <b>{p.name}</b>
            <span className="muted small">{p.description}</span>
            <b>{money(p.price)}</b>
            <button onClick={() => add(p)}>Agregar al carrito</button>
          </div>
        ))}
      </div>
    </>
  );
}
