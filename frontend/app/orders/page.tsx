"use client";
/**
 * Listado de órdenes del usuario, con total y estado.
 *
 * Cada fila enlaza a su detalle, que es quien hace el seguimiento del pago.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import StatusBadge from "@/components/StatusBadge";
import { api, errorMessage, money, Order } from "@/lib/api";

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Order[]>("/orders/").then(setOrders).catch((e) => setError(errorMessage(e)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!orders) return <p>Cargando...</p>;

  return (
    <>
      <h1>Mis órdenes</h1>
      {orders.length === 0 && <p>Aún no tienes órdenes.</p>}
      <div className="stack">
        {orders.map((o) => (
          <Link key={o.id} href={`/orders/${o.id}`} className="card row spread">
            <span>Orden #{o.id} <span className="muted small">{new Date(o.created_at).toLocaleString("es-MX")}</span></span>
            <span className="row"><b>{money(o.total)}</b><StatusBadge status={o.display_status} /></span>
          </Link>
        ))}
      </div>
    </>
  );
}
