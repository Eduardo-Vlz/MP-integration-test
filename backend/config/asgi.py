"""Punto de entrada ASGI: la alternativa asíncrona a `config/wsgi.py`.

Mismo propósito (`application` como callable de entrada), pero pensado para
peticiones concurrentes en una sola instancia y para conexiones persistentes
(WebSockets, SSE).

**No se usa en este proyecto.** El servidor de desarrollo de `runserver` carga
`config/wsgi.py`, y ninguna parte de la app necesita async. El archivo se conserva
porque forma parte del esqueleto que genera `django-admin startproject` y porque
sería el punto de entrada en cuanto se quisiera servir con uvicorn/daphne.

Consecuencia práctica: ignorarlo sin miedo. Para entender el arranque de este
proyecto basta con `manage.py` y `config/wsgi.py`.
"""
import os

from django.core.asgi import get_asgi_application

# Mismo puntero que fija `manage.py`.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# El nombre `application` sigue la convención de ASGI.
application = get_asgi_application()