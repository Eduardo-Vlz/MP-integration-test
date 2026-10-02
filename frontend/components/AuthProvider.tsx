"use client";
/**
 * Contexto de autenticación y pantalla de login.
 *
 * Dos decisiones que definen el patrón de auth de toda la app:
 *
 * 1. El contexto expone `email` y `logout`, pero NO el token. Los componentes no
 *    lo necesitan y sacarlo del árbol evita que se propague por toda la app;
 *    `lib/api.ts` lo lee de `localStorage` por su cuenta.
 *
 * 2. Mientras no haya sesión, el provider NO renderiza `children`: devuelve el
 *    formulario de login en su lugar. Ese único `if` protege toda la aplicación,
 *    sin necesidad de un `<ProtectedRoute>` en cada página. `ready` evita que el
 *    formulario aparezca durante la hidratación.
 *
 * El login es un atajo de pruebas: sin contraseña, solo email. El backend exige
 * el patrón `test_payer_<dígitos>@testuser.com`, por eso el generador del botón.
 */
import { createContext, useContext, useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";

type AuthCtx = { email: string | null; logout: () => void };
const Ctx = createContext<AuthCtx>({ email: null, logout: () => {} });
export const useAuth = () => useContext(Ctx);

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setEmail(localStorage.getItem("email"));
    setReady(true);
  }, []);

  /** Inicia sesión y persiste token + email en `localStorage`. */
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const res = await api<{ token: string; email: string }>("/auth/login/", { method: "POST", body: { email: input } });
      localStorage.setItem("token", res.token);
      localStorage.setItem("email", res.email);
      setEmail(res.email);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  /** Cierra sesión borrando las credenciales locales. */
  function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("email");
    setEmail(null);
  }

  if (!ready) return null;

  if (!email) {
    return (
      <main className="container narrow">
        <form onSubmit={login} className="card stack">
          <h1>Tienda de prueba</h1>
          <p className="muted">
            Entorno de <b>pruebas</b>. Ingresa el email del comprador de prueba
            (formato <code>test_payer_123456@testuser.com</code>).
          </p>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="test_payer_123456@testuser.com" required />
          <div className="row">
            <button type="button" className="secondary"
              onClick={() => setInput(`test_payer_${Math.floor(Math.random() * 9e9 + 1e9)}@testuser.com`)}>
              Generar email de prueba
            </button>
            <button type="submit">Entrar</button>
          </div>
          {error && <p className="error">{error}</p>}
        </form>
      </main>
    );
  }

  return <Ctx.Provider value={{ email, logout }}>{children}</Ctx.Provider>;
}
