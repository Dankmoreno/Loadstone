"""Registro de actividad y captura de fallos no previstos.

Loadstone se distribuye como un ejecutable sin consola. Cuando algo falla ahi,
no hay ninguna salida que mirar: la ventana no abre, o un boton no hace nada, y
no queda rastro. Este modulo pone un archivo de registro en una ruta conocida y
engancha `sys.excepthook` para que ningun fallo se pierda.

Se usa el `logging` de la biblioteca estandar en vez de algo mas comodo como
loguru para no anadir otra dependencia a un ejecutable que ya pesa 39 MB; lo
que se gana con una biblioteca externa aqui es sintaxis, no capacidad.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import Callable
from pathlib import Path
from types import TracebackType

from .paths import log_dir

__all__ = ["get_logger", "install_excepthook", "log_file", "setup_logging"]

_FORMATO = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
_FECHA = "%Y-%m-%d %H:%M:%S"
_ARCHIVO = "loadstone.log"
_configurado = False


def log_file() -> Path:
    return log_dir() / _ARCHIVO


def get_logger(nombre: str) -> logging.Logger:
    """Logger del modulo que lo pide, bajo el espacio de nombres de la app."""
    return logging.getLogger(f"loadstone.{nombre}")


def setup_logging(*, debug: bool = False, to_stderr: bool = True) -> Path | None:
    """Prepara el registro. Devuelve el archivo, o `None` si no se pudo abrir.

    Llamarlo dos veces no duplica los mensajes. Si el archivo no se puede
    escribir, por permisos o por un disco lleno, la aplicacion sigue
    funcionando sin registro: no poder anotar algo nunca debe impedir hacerlo.
    """
    global _configurado
    raiz = logging.getLogger("loadstone")
    if _configurado:
        raiz.setLevel(logging.DEBUG if debug else logging.INFO)
        return log_file()

    raiz.setLevel(logging.DEBUG if debug else logging.INFO)
    raiz.propagate = False
    formato = logging.Formatter(_FORMATO, _FECHA)

    destino: Path | None = None
    try:
        carpeta = log_dir()
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / _ARCHIVO
        # Cinco archivos de 1 MB: suficiente para reconstruir lo que paso sin
        # que el registro crezca sin limite en una instalacion olvidada.
        archivo = logging.handlers.RotatingFileHandler(
            destino, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        archivo.setFormatter(formato)
        archivo.setLevel(logging.DEBUG if debug else logging.INFO)
        raiz.addHandler(archivo)
    except OSError:
        destino = None

    if to_stderr:
        consola = logging.StreamHandler(sys.stderr)
        consola.setFormatter(formato)
        # En consola solo lo que merece interrumpir: el resto va al archivo.
        consola.setLevel(logging.DEBUG if debug else logging.WARNING)
        raiz.addHandler(consola)

    _configurado = True
    return destino


def install_excepthook(
    on_error: Callable[[str, str], None] | None = None,
) -> None:
    """Registra los fallos que nadie captura antes de que el proceso muera.

    `on_error` recibe `(resumen, detalle)` y permite a la interfaz grafica
    ensenar un dialogo. Sin el, el fallo solo queda escrito.
    """
    logger = get_logger("crash")
    anterior = sys.excepthook

    def manejar(
        tipo: type[BaseException],
        valor: BaseException,
        traza: TracebackType | None,
    ) -> None:
        # Ctrl+C no es un fallo: se deja pasar al comportamiento normal.
        if issubclass(tipo, KeyboardInterrupt):
            anterior(tipo, valor, traza)
            return

        logger.critical("fallo no capturado", exc_info=(tipo, valor, traza))
        if on_error is not None:
            import traceback

            detalle = "".join(traceback.format_exception(tipo, valor, traza))
            try:
                on_error(f"{tipo.__name__}: {valor}", detalle)
            except Exception:
                # Si hasta el aviso falla, al menos queda escrito: lo que no
                # puede pasar es perder el fallo original por el camino.
                logger.exception("no se pudo mostrar el aviso del fallo")
        anterior(tipo, valor, traza)

    sys.excepthook = manejar
