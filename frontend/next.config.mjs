/**
 * Configuración de Next.js. Está vacía a propósito.
 *
 * No hay nada que sobreescribir: el proyecto usa el App Router por convención de
 * directorios (`app/page.tsx` → `/`, `app/cart/page.tsx` → `/cart`) y la API vive
 * en Django, no en Next. Las opciones que sí se usan en otros proyectos se
 * omiten aquí porque no aplican:
 *
 * - `images.remotePatterns`: no hay `next/image`; el catálogo muestra texto y emoji.
 * - `rewrites`: no hay proxy a Django; el frontend llama a `http://localhost:8000/api`
 *   directamente y por eso hace falta CORS.
 * - `basePath` / `output: 'export'`: se sirve con `next dev` y `next start` desde la raíz.
 *
 * Si algún día se despliega en producción, lo habitual es cambiar aquí el destino
 * del frontend en lugar de dejarlo apuntando a `localhost`.
 *
 * @type {import('next').NextConfig}
 */
const nextConfig = {};
export default nextConfig;