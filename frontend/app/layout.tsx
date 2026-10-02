/**
 * Layout raíz: estilos globales, `AuthProvider` y `Header`.
 *
 * Como el login gate vive en `AuthProvider`, este archivo es también lo que
 * garantiza que ninguna página se renderice sin sesión.
 */
import "./globals.css";
import AuthProvider from "@/components/AuthProvider";
import Header from "@/components/Header";

export const metadata = { title: "Prueba Mercado Pago", description: "Integración de prueba" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>
        <AuthProvider>
          <Header />
          <main className="container">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
