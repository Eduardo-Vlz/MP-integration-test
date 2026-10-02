"""Configuración del proyecto Django.

Las variables de entorno se leen de `BASE_DIR/.env` mediante python-dotenv. Todas
tienen valor por defecto, así que el proyecto arranca sin `.env` (la única
consecuencia visible: `/api/config/` devolverá la Public Key vacía y el checkout
no podrá cargar el SDK de MP).

Bloques: seguridad, apps, middlewares, base de datos, locale, DRF, CORS y las
variables de Mercado Pago.

Referencia: docs/arquitectura.md · Variables: `.env.example`
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = ["*"]  # solo pruebas (permite ngrok)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "shop",
]

MIDDLEWARE = [
    # CorsMiddleware va primero: si no, las preflight requests las rechaza
    # CsrfViewMiddleware antes de llegar a la respuesta de CORS.
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "save_carts"),
        "USER": os.getenv("POSTGRES_USER", "root"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "root"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    # Autenticación por token en vez de sesión: el frontend es una SPA que guarda
    # el token en localStorage y lo envía en la cabecera Authorization.
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

# Solo localhost/127.0.0.1 con cualquier puerto. Si el frontend se mueve a otro
# origen, hay que ajustar esta expresión regular (la variable FRONTEND_ORIGIN de
# `.env.example` NO está cableada aquí).
CORS_ALLOWED_ORIGIN_REGEXES = [r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"]

# --- Mercado Pago ---
# Únicas credenciales del proyecto. El Access Token solo se usa en `shop/mp.py`;
# la Public Key se sirve al frontend vía `GET /api/config/`.
MP_PUBLIC_KEY = os.getenv("MP_PUBLIC_KEY", "")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
# Vacío = el webhook acepta cualquier llamada. Atajo de pruebas, no usar así en producción.
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "")
# Barrera de pruebas: exige emails con el patrón test_payer_<dígitos>@testuser.com.
ENFORCE_TEST_EMAIL = os.getenv("ENFORCE_TEST_EMAIL", "True") == "True"
