"use client";
/**
 * Hook que carga el SDK de Mercado Pago una vez y devuelve la instancia `mp`
 * (o `null` mientras carga), junto con un error si no se pudo inicializar.
 *
 * Secuencia: pedir la Public Key al backend → cargar el SDK → instanciarlo.
 *
 * La Public Key se pide a `GET /api/config/` en lugar de estar en el bundle, para
 * que las credenciales de MP se configuren en un solo lugar (el backend).
 *
 * Casi todas las vistas usan el resultado igual: si `mp` es `null`, el botón de
 * pagar queda deshabilitado.
 */
import { useEffect, useState } from "react";
import { loadMercadoPago } from "@mercadopago/sdk-js";
import { api } from "./api";

/** Carga el SDK de Mercado Pago una vez y devuelve la instancia `mp` (o null mientras carga). */
export function useMercadoPago() {
  const [mp, setMp] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    // Si el componente se desmonta antes de terminar las llamadas, se aborta la
    // actualización de estado en lugar de avisar sobre un componente inexistente.
    let cancelled = false;
    (async () => {
      try {
        const { public_key } = await api<{ public_key: string }>("/config/");
        if (!public_key)
          throw new Error("Falta MP_PUBLIC_KEY en backend/.env");
        await loadMercadoPago();
        if (!cancelled)
          setMp(
            new (window as any).MercadoPago(public_key, { locale: "es-MX" }),
          );
      } catch (e: any) {
        if (!cancelled)
          setError(e?.message ?? "No se pudo cargar Mercado Pago");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { mp, error };
}
