/**
 * Etiqueta de estado de una orden: texto con emoji y color según `display_status`.
 *
 * Las clases `.badge.approved` / `.pending` / `.rejected` están en `globals.css`.
 * `refunded` y `created` caen en el color por defecto de `.badge`.
 */

/** Estados normalizados que devuelve el backend en `Order.display_status`. */
const LABELS: Record<string, string> = {
  approved: "✅ Aprobado",
  pending: "⏳ Pendiente",
  rejected: "❌ Rechazado",
  refunded: "↩️ Reembolsado",
  created: "Creada",
};

export default function StatusBadge({ status }: { status: string }) {
  // El fallback muestra el valor crudo si llega un estado no previsto.
  return <span className={`badge ${status}`}>{LABELS[status] ?? status}</span>;
}
