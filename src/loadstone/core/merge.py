"""Generacion de un mod-parche que resuelve conflictos a mano.

La regla del motor no admite matices: cuando dos mods definen el mismo archivo,
gana entero el que carga el ultimo. No hay forma de decir "de este archivo
quiero la version del primero" sin mover el orden de carga, y mover el orden
arrastra los otros doscientos archivos de ese mod.

La salida que usa todo el mundo es un mod-parche: una carpeta con los archivos
elegidos, cargada la ultima, que gana a todos. Esto la construye.

Lo que el parche contiene son archivos **completos**, no fusiones: se elige que
version de cada archivo manda, y esa se copia tal cual. Fusionar de verdad dos
versiones de un archivo de Clausewitz —quedarse con el gobierno que anade uno y
el que anade el otro— pide entender el formato objeto a objeto, y eso es otro
problema. `filediff` ensena el diff para que la eleccion sea informada; la
decision sigue siendo de quien mira.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .descriptor import Descriptor, dump_descriptor
from .install import InstallError, install_mod
from .logs import get_logger
from .models import GameProfile, Mod

__all__ = ["PatchSelection", "build_patch_mod"]


_logger = get_logger("merge")

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


@dataclass(slots=True)
class PatchSelection:
    """De que mod se coge un archivo concreto."""

    path: str
    """Ruta relativa dentro del mod, tal y como la da `conflicts`."""

    source: Path
    """El archivo real que se va a copiar."""

    mod_name: str
    """De quien es, solo para poder contarlo despues."""


def _slug(texto: str) -> str:
    return _SLUG_RE.sub("-", texto.strip().lower()).strip("-") or "parche"


def build_patch_mod(
    game: GameProfile,
    nombre: str,
    selecciones: list[PatchSelection],
    *,
    overwrite: bool = True,
) -> Mod:
    """Construye el mod-parche y lo deja instalado. Devuelve el mod resultante.

    No lo anade a ningun playset ni lo coloca en el orden: eso es decision de
    quien llama, y el sitio donde tiene que ir —el ultimo— depende del playset.

    `supported_version` se copia del juego detectado para que el launcher no lo
    marque como incompatible nada mas crearlo.
    """
    if not selecciones:
        raise InstallError("no hay ningun archivo elegido para el parche")
    if game.mod_dir is None:
        raise InstallError(f"{game.display_name}: sin carpeta de datos")

    with tempfile.TemporaryDirectory(prefix="loadstone-parche-") as temporal:
        raiz = Path(temporal) / "contenido"
        raiz.mkdir(parents=True)

        copiados = 0
        for seleccion in selecciones:
            if not seleccion.source.is_file():
                _logger.warning("se salta %s: ya no esta en disco", seleccion.path)
                continue
            destino = raiz / seleccion.path
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(seleccion.source, destino)
            copiados += 1

        if not copiados:
            raise InstallError("ninguno de los archivos elegidos sigue en disco")

        descriptor = Descriptor(
            name=nombre,
            version="1.0",
            supported_version=game.mods_compat_version or game.raw_version,
            tags=["Fixes"],
        )
        (raiz / "descriptor.mod").write_text(
            dump_descriptor(descriptor), encoding="utf-8"
        )

        mod = install_mod(
            game,
            raiz,
            mod_id=f"loadstone-{_slug(nombre)}",
            overwrite=overwrite,
        )

    _logger.info("parche '%s' creado con %s archivos", nombre, copiados)
    return mod
