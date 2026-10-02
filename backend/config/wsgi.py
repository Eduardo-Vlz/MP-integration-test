"""Punto de entrada WSGI: el servidor web entrega cada petición HTTP a este callable.

Django tiene dos interfaces de entrada y aquí solo se usa WSGI:

- WSGI (este archivo): un `application` que recibe una petición y devuelve una
  respuesta. Suficiente y síncrono.
- ASGI (`config/asgi.py`): además soporta conexiones persistentes y async.

En las pruebas da igual cuál se use: `runserver` arranca un servidor de desarrollo
que llama a `get_wsgi_application()`. ASGI solo empezaría a importar si se
sirviera la app con un servidor asíncrono (uvicorn, daphne) o si se usaran
WebSockets; este proyecto no tiene ninguno, así que `asgi.py` es boilerplate
del esqueleto inicial de Django.

Who calls it: `settings.py` apunta aquí con `WSGI_APPLICATION`, y los servidores
de producción (gunicorn, uwsgi) cargan `config.wsgi:application` directamente.
"""
import os

from django.core.wsgi import get_wsgi_application

# Mismo puntero que fija `manage.py`: le dice a Django dónde está la configuración.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# El nombre `application` no es arbitrario: es la convención que los servidores
# WSGI buscan al cargar este módulo.
application = get_wsgi_application()