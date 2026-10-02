"use client";
/**
 * Pantalla de pago. El archivo más complejo del proyecto: reúne cuatro
 * responsabilidades (selector de método de pago, Secure Fields, tokenización y
 * creación de la orden).
 *
 * ## `selected` como modo único
 * Un solo string —`"new"` o un `card_id_mp`— decide qué se muestra, en lugar de
 * varios booleanos. La tarjeta predeterminada se selecciona al cargar, así que el
 * caso común es el más rápido.
 *
 * ## Secure Fields
 * Los campos de MP son iframes montados dentro de contenedores `<div>` con id.
 * React nunca controla su contenido; el `div` es solo un punto de anclaje vacío.
 * El evento `binChange` consulta los medios de pago a partir de los primeros 6
 * dígitos y guarda el detectado en `pm`; si no lo reconoce, `pay()` lo explica.
 *
 * Detalle completo del flujo: docs/arquitectura.md
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { api, Cart, errorMessage, money, Order, SavedCard } from "@/lib/api";
import { useMercadoPago } from "@/lib/useMercadoPago";

/** Medio de pago detectado a partir del BIN. `null` = aún no se sabe. */
type PM = { id: string; type: string } | null;

export default function CheckoutPage() {
  const router = useRouter();
  const { email: userEmail } = useAuth();
  const { mp, error: mpError } = useMercadoPago();

  const [cart, setCart] = useState<Cart | null>(null);
  const [cards, setCards] = useState<SavedCard[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<string>("new"); // "new" o card_id_mp

  // formulario de tarjeta nueva
  const [name, setName] = useState("");
  const [idTypes, setIdTypes] = useState<{ id: string; name: string }[]>([]);
  const [idType, setIdType] = useState("");
  const [idNumber, setIdNumber] = useState("");
  const [email, setEmail] = useState(userEmail ?? "");
  const [save, setSave] = useState(false);
  const [pm, setPm] = useState<PM>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  /** Recarga la lista de tarjetas guardadas y la devuelve. */
  const loadCards = useCallback(async () => {
    const list = await api<SavedCard[]>("/cards/");
    setCards(list);
    return list;
  }, []);

  // Carga inicial: carrito + tarjetas guardadas en paralelo.
  // `loaded` marca el final en ambos casos y es lo que dispara el montaje de los
  // Secure Fields: deben esperar a que haya datos para no montar un campo en un
  // carrito vacío.
  useEffect(() => {
    (async () => {
      try {
        // `Promise.all` lanza las dos peticiones a la vez en lugar de esperar una
        // para luego lanzar la otra. Cada `api()` usa el token de `localStorage`.
        const [c, list] = await Promise.all([api<Cart>("/cart/"), loadCards()]);
        setCart(c);
        // Modo inicial del selector: la tarjeta predeterminada si la hay, si no la
        // primera, y si no hay ninguna tarjeta guardada, el formulario de tarjeta
        // nueva. Así el caso más común (pagar con la predeterminada) es el más rápido.
        setSelected(
          list.length
            ? (list.find((x) => x.is_default) ?? list[0]).card_id_mp
            : "new",
        );
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        // Se marca `loaded` incluso si falló: si no, la pantalla se quedaría en
        // "Cargando..." para siempre y los Secure Fields no se montarían nunca.
        setLoaded(true);
      }
    })();
  }, [loadCards]);

  // Tipos de identificación desde MP. El `catch` vacío es deliberado: si falla, el
  // campo queda vacío y el checkout sigue siendo utilizable.
  //
  // El `if (!mp) return` es imprescindible: los tipos vienen del SDK, que puede no
  // haber cargado todavía (`mp` es null mientras lo hace).
  useEffect(() => {
    if (!mp) return;
    mp.getIdentificationTypes()
      .then((types: any[]) => {
        setIdTypes(types ?? []);
        // Se preselecciona el primero: la identificación es obligatoria para
        // tokenizar, así que tener un valor por defecto evita un paso al usuario.
        if (types?.length) setIdType(types[0].id);
      })
      .catch(() => {});
  }, [mp]);

  /**
   * Monta los Secure Fields según el modo y los desmonta al cambiar.
   *
   * - Tarjeta nueva → `cardNumber`, `expirationDate` y `securityCode`.
   * - Tarjeta guardada → solo `securityCode` (el CVV se vuelve a pedir siempre).
   *
   * El cleanup llama a `unmount()` en cada campo dentro de un `try/catch`, porque
   * el SDK lanza si el iframe ya desapareció. Sin este cleanup, alternar entre
   * tarjeta nueva y guardada dejaría iframes huérfanos en el DOM.
   *
   * Los `PASO n` marcan el orden real de ejecución. Ojo con el caso de la tarjeta
   * nueva: montar los campos NO es pedir nada al usuario todavía; el token se genera
   * mucho después, al pulsar Pagar, en `pay()`.
   */
  useEffect(() => {
    if (!mp || !loaded || !cart?.items.length) return;
    const mounted: any[] = [];
    // PASO 1 — Montar los iframes de MP. `mp.fields.create(...)` devuelve un campo
    // y `.mount("id")` lo inserta dentro del `<div>` con ese id del JSX de abajo.
    // El `div` es un contenedor VACÍO: React nunca escribe dentro, solo le pasa el
    // punto de anclaje al SDK. Por eso el número de tarjeta nunca pasa por React,
    // por `localStorage` ni por este código.
    if (selected === "new") {
      // Tarjeta nueva: los tres campos que hacen falta para tokenizar.
      const num = mp.fields
        .create("cardNumber", { placeholder: "Número de tarjeta" })
        .mount("f-card-number");
      const exp = mp.fields
        .create("expirationDate", { placeholder: "MM/AA" })
        .mount("f-expiration");
      const cvv = mp.fields
        .create("securityCode", { placeholder: "CVV" })
        .mount("f-cvv-new");
      // PASO 2 — Escuchar el BIN. `binChange` dispara cada vez que los primeros 6
      // dígitos son válidos, y con ellos MP revela el medio de pago (visa, master,
      // amex) y si es de débito o crédito. Ese dato NO se puede pedir al usuario:
      // se deduce de la tarjeta.
      num.on("binChange", async ({ bin }: { bin?: string }) => {
        if (!bin) return setPm(null);
        try {
          const { results } = await mp.getPaymentMethods({ bin });
          // El primer resultado es el medio de pago exacto de ese BIN.
          if (results?.length)
            setPm({ id: results[0].id, type: results[0].payment_type_id });
        } catch {
          // Si la consulta falla se anula el medio: `pay()` lo detecta y explica el
          // problema en vez de mandar un `payment_method_id` equivocado.
          setPm(null);
        }
      });
      mounted.push(num, exp, cvv);
    } else {
      // Tarjeta guardada: solo el CVV. El número y el vencimiento ya los conoce MP
      // por el `cardId`, y pedir el CVV de nuevo es una exigencia de seguridad que
      // aplica también a compras recurrentes.
      mounted.push(
        mp.fields
          .create("securityCode", { placeholder: "CVV" })
          .mount("f-cvv-saved"),
      );
    }
    // Al cambiar de modo (o al desmontar la página) se desmontan los iframes. Sin
    // este cleanup, los iframes del modo anterior seguirían en el DOM.
    return () => {
      mounted.forEach((m) => {
        try {
          m.unmount();
        } catch {}
      });
    };
  }, [mp, loaded, cart, selected]);

  /** Elimina una tarjeta guardada y selecciona la siguiente disponible. */
  async function removeCard(card: SavedCard) {
    if (
      !confirm(
        `¿Eliminar ${card.payment_method_name} terminada en ${card.last_four_digits}?`,
      )
    )
      return;
    try {
      await api(`/cards/${card.id}/`, { method: "DELETE" });
      const list = await loadCards();
      setSelected(list.length ? list[0].card_id_mp : "new");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  /**
   * Genera el token y crea la orden.
   *
   * El caso "tarjeta nueva + guardar" necesita DOS tokens porque los de Mercado
   * Pago son de un solo uso:
   *
   * 1. Se genera un token y se manda a `POST /api/cards/`. Ese token queda consumido.
   * 2. Se genera un segundo con `{ cardId }` para el cobro.
   *
   * Si el segundo token falla no hay error para el usuario: la tarjeta ya quedó
   * guardada, así que se recarga la lista, se selecciona y se le pide solo el CVV.
   * El `return` temprano es lo que evita intentar cobrar con un token gastado.
   *
   * Este es el punto donde el número de tarjeta se convierte en un token opaco.
   * Hasta aquí el usuario escribió dentro de iframes de Mercado Pago; a partir de
   * aquí solo viaja `token: "e0ba…"`. El objeto `body` que se arma abajo es la
   * ÚNICA información de la tarjeta que sale del navegador hacia Django.
   */
  async function pay(e: React.FormEvent) {
    // Sin esto, el navegador recargaría la página al enviar el formulario.
    e.preventDefault();
    // `mp` es `null` mientras carga el SDK (ver `useMercadoPago`): sin instancia no
    // hay forma de generar un token.
    if (!mp) return;
    setBusy(true);
    setError("");
    setInfo("");
    try {
      // `body` es lo que se enviará a `POST /api/orders/`. Las tres ramas producen
      // las mismas claves: `token` siempre, y (`saved_card_id`) o
      // (`payment_method_id` + `payment_method_type` + `payer_email`). El backend
      // distingue los casos por la presencia de `saved_card_id`.
      let body: Record<string, unknown>;

      // Todas las rutas del checkout cobran en una sola exhibición, también con tarjetas guardadas.
      if (selected !== "new") {
        // PASO 1 (tarjeta guardada) — Un solo token, generado con `cardId` en vez de
        // con los datos de la tarjeta: Mercado Pago ya conoce el número y el
        // vencimiento, solo necesita el CVV que se acaba de escribir. `selected`
        // contiene el `card_id_mp`, que es exactamente lo que el backend espera
        // como `saved_card_id`.
        const t = await mp.fields.createCardToken({ cardId: selected });
        body = { token: t.id, saved_card_id: selected, installments: 1 };
      } else {
        // PASO 2 (tarjeta nueva) — Sin `pm` no se sabe si la tarjeta es de débito o
        // de crédito, dato que Mercado Pago exige en el payload. Mejor un error
        // claro aquí que un 400 más adelante con un mensaje incomprensible.
        if (!pm)
          throw new Error(
            "No se pudo identificar la tarjeta. Revisa el número.",
          );
        // Token con los tres campos del iframe más el titular y la identificación,
        // que sí los escribe React porque ninguno es sensible.
        const t = await mp.fields.createCardToken({
          cardholderName: name,
          identificationType: idType,
          identificationNumber: idNumber,
        });

        if (save) {
          // El token es de un solo uso: se consume al guardar y se genera otro (cardId + CVV) para cobrar
          // PASO 3 — Canjea el token por una tarjeta real en la cuenta de MP. El
          // backend crea el customer si hace falta y responde 201 con la tarjeta ya
          // persistida, incluido su `card_id_mp`.
          const card = await api<SavedCard>("/cards/", {
            method: "POST",
            body: { token: t.id },
          });
          try {
            // PASO 4 — Segundo token, ahora con `cardId`. El primero ya está
            // gastado, así que es imprescindible generar otro para poder cobrar.
            const t2 = await mp.fields.createCardToken({
              cardId: card.card_id_mp,
            });
            body = {
              token: t2.id,
              saved_card_id: card.card_id_mp,
              installments: 1,
            };
          } catch {
            // La tarjeta YA está guardada: recuperamos ese camino en lugar de fallar.
            // Se recarga la lista, se selecciona la tarjeta recién guardada y se
            // vuelve al formulario de solo CVV. El `return` evita incluso intentar
            // el POST de la orden con un token que ya falló.
            await loadCards();
            setSelected(card.card_id_mp);
            setInfo("Tarjeta guardada. Ahora escribe el CVV y presiona Pagar.");
            return;
          }
        } else {
          body = {
            token: t.id,
            payment_method_id: pm.id,
            payment_method_type: pm.type,
            payer_email: email,
            installments: 1,
          };
        }
      }

      // PASO 6 — El cobro. El backend IGNORA cualquier importe que pudiera venir
      // aquí y recalcula el total desde el carrito persistido; luego guarda la orden
      // y llama a `POST /v1/orders`. Responde 201 con la orden ya actualizada con el
      // estado de MP, o 400 con el motivo literal del rechazo si falló.
      //
      // Tras crear la orden, el backend ya vació el carrito, así que hay que refrescar
      // el contador del Header antes de navegar a la página de seguimiento.
      const order = await api<Order>("/orders/", { method: "POST", body });
      // Evento que escucha `Header.tsx` para volver a pedir el carrito: sin él, el
      // contador seguiría mostrando productos que ya se pagaron.
      window.dispatchEvent(new Event("cart-updated"));
      router.push(`/orders/${order.id}`);
    } catch (err) {
      // Un único punto de error para toda la función: el token rechazado por el SDK,
      // el 400 del backend y el 502 con el detalle de Mercado Pago llegan todos
      // aquí. `errorMessage()` extrae el motivo real cuando viene de MP.
      setError(errorMessage(err));
    } finally {
      // Rehabilita el botón pase lo que pase; si se quedara en `true`, la app
      // quedaría bloqueada sin poder reintentar.
      setBusy(false);
    }
  }

  if (!loaded) return <p>Cargando...</p>;
  // El checkout sin carrito no tiene nada que cobrar: es la única defensa de la UI,
  // aunque el backend también rechaza el POST con "El carrito está vacío".
  if (!cart || cart.items.length === 0)
    return (
      <p>
        Tu carrito está vacío. <Link href="/">Ver productos</Link>
      </p>
    );

  return (
    <>
      <h1>Pago</h1>
      {mpError && <p className="error">{mpError}</p>}
      <div className="two-cols">
        <form onSubmit={pay} className="card stack">
          <h2>Método de pago</h2>

          {cards.map((c) => (
            <label
              key={c.id}
              className={`option ${selected === c.card_id_mp ? "active" : ""}`}
            >
              <input
                type="radio"
                name="pm"
                checked={selected === c.card_id_mp}
                onChange={() => setSelected(c.card_id_mp)}
              />
              <span>
                💳 {c.payment_method_name} •••• {c.last_four_digits}{" "}
                <span className="muted small">
                  vence {String(c.expiration_month).padStart(2, "0")}/
                  {c.expiration_year}
                </span>
              </span>
              <button
                type="button"
                className="secondary small"
                onClick={() => removeCard(c)}
              >
                Eliminar
              </button>
            </label>
          ))}
          <label className={`option ${selected === "new" ? "active" : ""}`}>
            <input
              type="radio"
              name="pm"
              checked={selected === "new"}
              onChange={() => setSelected("new")}
            />
            <span>➕ Usar una tarjeta nueva</span>
          </label>

          {selected === "new" ? (
            <div className="stack">
              <div className="field" id="f-card-number" />
              <div className="row">
                <div className="field" id="f-expiration" style={{ flex: 1 }} />
                <div className="field" id="f-cvv-new" style={{ flex: 1 }} />
              </div>
              <input
                placeholder="Titular (como aparece en la tarjeta)"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
              <div className="row">
                {idTypes.length > 0 && (
                  <select
                    value={idType}
                    onChange={(e) => setIdType(e.target.value)}
                  >
                    {idTypes.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                )}
                <input
                  placeholder="Número de identificación"
                  value={idNumber}
                  onChange={(e) => setIdNumber(e.target.value)}
                  style={{ flex: 1 }}
                />
              </div>
              <input
                type="email"
                placeholder="Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
              <label className="row">
                <input
                  type="checkbox"
                  checked={save}
                  onChange={(e) => setSave(e.target.checked)}
                />
                Guardar esta tarjeta para futuras compras
              </label>
            </div>
          ) : (
            <div className="stack">
              <span className="muted small">
                Por seguridad, vuelve a escribir el CVV de la tarjeta:
              </span>
              <div className="field" id="f-cvv-saved" />
            </div>
          )}

          {info && <p className="muted">{info}</p>}
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={!mp || busy}>
            {busy ? "Procesando..." : `Pagar ${money(cart.total)}`}
          </button>
        </form>

        <aside className="card stack">
          <h2>Resumen</h2>
          {cart.items.map((i) => (
            <div className="row spread" key={i.id}>
              <span>
                {i.quantity} × {i.product.name}
              </span>
              <span>{money(i.subtotal)}</span>
            </div>
          ))}
          <hr />
          <div className="row spread">
            <b>Total</b>
            <b>{money(cart.total)}</b>
          </div>
        </aside>
      </div>
    </>
  );
}
