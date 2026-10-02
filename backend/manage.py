#!/usr/bin/env python
"""Punto de entrada de TODOS los comandos de Django: `runserver`, `migrate`,
`seed_products`, `createsuperuser`, `shell`…

Es el primer archivo que se ejecuta al escribir `python manage.py <comando>`, y es
la razón de que los comandos funcionen sin configuración previa: aquí se fija la
variable de entorno `DJANGO_SETTINGS_MODULE`, que le dice a Django dónde leer la
configuración. Ese puntero es lo único que este archivo aporta; todo lo demás
vive en `config/settings.py`.

Cadena de arranque, en orden:
1. Este archivo llama a `main()`.
2. `main()` fija `DJANGO_SETTINGS_MODULE=config.settings` (`setdefault`, no
   `set`: si ya viene definida — p. ej. en un servidor de producción — gana la
   del entorno).
3. `execute_from_command_line` carga Django con esa configuración y despacha el
   subcomando. Ojo: el import de `execute_from_command_line` está DENTRO de
   `main()` a propósito; Django debe estar configurado antes de importarse.
4. Para `runserver` en concreto, Django resuelve la petición en
   `config/urls.py` → `shop/urls.py` → una clase de `shop/views.py`.
"""
import os
import sys


def main():
    """Arranca Django con el comando recibido por línea de comandos.

    El cuerpo es deliberadamente corto: toda la lógica está en Django. Lo único
    que hace este archivo es decidir QUÉ configuración se carga y luego Delegar.
    """
    # Debe ir antes de cualquier import de Django: los módulos de Django leen
    # esta variable al importarse y sin ella no sabrían dónde está la config.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    # `sys.argv` incluye el nombre de este script, que Django interpreta como el
    # subcomando a ejecutar ("runserver", "migrate"...).
    execute_from_command_line(sys.argv)


# Este bloque solo se ejecuta al lanzar el archivo directamente
# (`python manage.py ...`), no al importarlo como módulo.
if __name__ == "__main__":
    main()
