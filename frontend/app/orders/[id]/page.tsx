"use client";
/**
 * Detalle de una orden, con polling mientras el pago siga pendiente.
 *
 * El polling usa `setTimeout` RECURSIVO en lugar de `setInterval`: la siguiente
 * consulta se agenda solo después de recibir la respuesta, así nunca hay peticiones
 * solapadas. Con `setInterval`, una petición que tardara más de 5 s se acumularía.
 *
 * Además solo se reprograma si el estado sigue siendo `pending`: una orden terminada
 * deja de consultar sola.
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import StatusBadge from "@/components/StatusBadge";
import { api, errorMessage, money, Order } from "@/lib/api";

export default function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    // `stopped` evita un setState en un componente ya desmontado si el usuario
    // navega mientras la petición está en vuelo.
    let stopped = false;
    async function load() {
      try {
        const o = await api<Order>(`/orders/${id}/`);
        if (stopped) return;
        setOrder(o);
        // Si sigue pendiente, consultamos de nuevo cada 5 s
        if (o.display_status === "pending") timer = setTimeout(load, 5000);
      } catch (e) {
        if (!stopped) setError(errorMessage(e));
      }
    }
    load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id]);

  if (error) return <p className="error">{error}</p>;
  if (!order) return <p>Cargando...</p>;

  return (
    <div className="card stack narrow-card">
      <h1>Orden #{order.id}</h1>
      <StatusBadge status={order.display_status} />
      {order.display_status === "pending" && <p className="muted">Esperando confirmación de Mercado Pago (se actualiza solo)...</p>}
      <table>
        <tbody>
          {order.items.map((i, idx) => (
            <tr key={idx}><td>{i.quantity} × {i.product_name}</td><td style={{ textAlign: "right" }}>{money(Number(i.unit_price) * i.quantity)}</td></tr>
          ))}
          <tr><td><b>Total</b></td><td style={{ textAlign: "right" }}><b>{money(order.total)}</b></td></tr>
        </tbody>
      </table>
      {/* Valores CRUDOS de MP, útiles para depurar por qué una orden quedó como quedó.
          Mapeo de estados: docs/estados-y-webhooks.md */}
      <div className="debug small">
        <div>Order MP: <code>{order.mp_order_id || "—"}</code></div>
        <div>Estado de la order: <code>{order.status}</code></div>
        <div>Estado del pago: <code>{order.payment_status || "—"}</code></div>
        <div>Detalle: <code>{order.status_detail || "—"}</code></div>
      </div>
      <div className="row">
        <Link href="/">Seguir comprando</Link>
        <Link href="/orders">Mis órdenes</Link>
      </div>
    </div>
  );
}
