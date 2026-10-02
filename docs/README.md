# Documentación del proyecto

Documentación técnica de la tienda de pruebas de integración con Mercado Pago
(Checkout API · Orders). El código fuente sigue siendo la referencia definitiva;
estos documentos explican **qué hace cada pieza, por qué existe y cómo encaja con
las demás**.

> **Aviso:** el proyecto está configurado exclusivamente para el entorno de pruebas
de Mercado Pago (credenciales `TEST-`). No usar en producción.

## Documentos

| Documento | Contenido |
|---|---|
| [`como-leer-el-codigo.md`](./como-leer-el-codigo.md) | **Empieza aquí:** qué se ejecuta al arrancar, el viaje de una petición y el orden de lectura sugerido. |
| [`arquitectura.md`](./arquitectura.md) | Estructura del repositorio, capas, flujo completo de pago y decisiones de seguridad. |
| [`api.md`](./api.md) | Referencia de los 10 endpoints: autenticación, cuerpo, respuestas y errores. |
| [`backend.md`](./backend.md) | Documentación módulo por módulo del backend Django. |
| [`frontend.md`](./frontend.md) | Documentación archivo por archivo del frontend Next.js. |
| [`estados-y-webhooks.md`](./estados-y-webhooks.md) | Estados de la Order en MP, mapeo a `display_status`, ciclo de vida del webhook. |
| [`modelo-de-datos.md`](./modelo-de-datos.md) | Los 6 modelos, campos, relaciones y diagrama. |

## Guía rápida

1. [Instalación y arranque](./arquitectura.md#puesta-en-marcha)
2. [Entrar a la app con un email de prueba](./arquitectura.md#recorrido-de-la-app)
3. [Probar un flujo de pago completo](./estados-y-webhooks.md#probar-cada-estado)
4. [Entender por qué el código está escrito así](./arquitectura.md#decisiones-de-diseño)
5. [Saber qué se ejecuta y por dónde leer](./como-leer-el-codigo.md)

## Mapa del repositorio

```
mp-test/
├── README.md                     Guía de instalación y uso (punto de entrada)
├── docs/                         Esta documentación
├── backend/                      Django + DRF (API y secretos de Mercado Pago)
│   ├── config/                   Configuración del proyecto
│   ├── shop/                     App única: modelos, vistas, cliente de MP
│   └── requirements.txt
└── frontend/                     Next.js 15 App Router (interfaz)
    ├── app/                      Rutas y páginas
    ├── components/               Componentes de UI y contexto de auth
    ├── lib/                      Cliente HTTP, tipos y hook del SDK de MP
    └── package.json
```

## Convenciones de documentación

- **Endpoints** se documentan con método, ruta, cuerpo de petición y respuesta real.
- Los **estados de MP** se citan con su nombre literal de la API (`processed`,
  `failed`, `action_required`…) y con el estado normalizado que ve el usuario.
- Cada referencia al código usa el formato `ruta:línea` para navegar directo al
  punto exacto, por ejemplo `backend/shop/views.py`.
- Los valores por defecto son los del repositorio; los secretos **nunca** se
  documentan (viven en `backend/.env`, ignorado por git).