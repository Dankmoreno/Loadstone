"""Escritura de archivos que no se puede quedar a medias.

Loadstone escribe encima de archivos que el juego y el launcher tambien usan,
asi que la escritura va a un temporal y se renombra sobre el destino: o esta el
archivo viejo entero o el nuevo entero, nunca la mitad de cada uno.

En Windows ese renombrado falla mas de lo que parece:

- `PermissionError` si cualquier otro proceso tiene el destino abierto un
  instante. El antivirus abre todo lo que se escribe, el indexador tambien, y
  el propio launcher de Paradox tiene `dlc_load.json` en la mano. Suele durar
  milisegundos, asi que se reintenta con esperas crecientes.
- `PermissionError` permanente si el destino es de solo lectura, que es como
  queda un archivo restaurado desde ciertas copias de seguridad. Ahi no sirve
  esperar: hay que quitar el atributo.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any

__all__ = ["atomic_write_json", "atomic_write_text", "replace_with_retry"]

_INTENTOS = 5
_ESPERA_BASE = 0.05


def _clear_read_only(destino: Path) -> bool:
    """Quita el atributo de solo lectura. `True` si habia que quitarlo."""
    if sys.platform != "win32":
        return False
    try:
        modo = destino.stat().st_mode
        if modo & stat.S_IWRITE:
            return False
        destino.chmod(modo | stat.S_IWRITE)
    except OSError:
        return False
    return True


def replace_with_retry(origen: Path, destino: Path) -> None:
    """Renombra `origen` sobre `destino` aguantando bloqueos pasajeros."""
    intento = 0
    limpiado = False
    while True:
        try:
            os.replace(origen, destino)
            return
        except PermissionError:
            # Quitar el atributo de solo lectura no es un reintento: es quitar
            # la causa, asi que se vuelve a probar sin gastar espera.
            if not limpiado and _clear_read_only(destino):
                limpiado = True
                continue
            if intento >= _INTENTOS - 1:
                raise
            time.sleep(_ESPERA_BASE * 2**intento)
            intento += 1


def atomic_write_text(destino: Path, contenido: str, *, encoding: str = "utf-8") -> None:
    """Escribe texto de forma que el destino nunca quede a medias."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f"{destino.name}.loadstone-tmp")
    try:
        temporal.write_text(contenido, encoding=encoding)
        replace_with_retry(temporal, destino)
    except BaseException:
        # Si algo falla, no dejar el temporal tirado al lado del archivo bueno.
        temporal.unlink(missing_ok=True)
        raise


def atomic_write_json(destino: Path, datos: Any, **kwargs: Any) -> None:
    kwargs.setdefault("ensure_ascii", False)
    atomic_write_text(destino, json.dumps(datos, **kwargs))
