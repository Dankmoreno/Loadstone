"""Recursos graficos de la interfaz.

Es un paquete de Python y no una carpeta suelta por una razon practica: asi
`importlib.resources` encuentra los archivos igual en desarrollo que dentro del
ejecutable, sin que nadie tenga que calcular rutas relativas a `__file__` ni
mirar si existe `sys._MEIPASS`.

`loadstone.svg` es el original y lo unico que se edita a mano. El `.ico` y el
`.png` se generan con `packaging/hacer_icono.py`.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

__all__ = ["icon_path", "svg_path"]


def _ruta(nombre: str) -> Path | None:
    try:
        with resources.as_file(resources.files(__name__) / nombre) as ruta:
            return ruta if ruta.is_file() else None
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        # Un icono que falta no es motivo para no abrir el programa.
        return None


def icon_path() -> Path | None:
    """El `.ico` multitamano de la ventana y la barra de tareas."""
    return _ruta("loadstone.ico")


def svg_path() -> Path | None:
    """El original vectorial, para pintarlo a cualquier tamano."""
    return _ruta("loadstone.svg")
