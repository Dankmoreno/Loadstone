"""Comparacion del contenido de los archivos en conflicto.

`conflicts` responde que archivos se disputan varios mods. Eso ya es util, pero
se queda en la pregunta anterior a la que importa: de esos archivos, **cuales
cambian de verdad**.

La diferencia no es academica. En una instalacion grande, una parte enorme de
los conflictos son el mismo archivo byte a byte: dos mods que incluyen la copia
sin tocar de un archivo del juego, o el mismo parche de compatibilidad
empaquetado por dos sitios. Ahi el motor se queda con el ultimo y no se pierde
nada, asi que no hay nada que decidir. Separar esos de los conflictos reales es
la diferencia entre una lista de dos mil lineas y una de veinte.

Lo que esto **no** hace es entender el contenido. Compara texto, linea a linea,
no objetos de Clausewitz: si dos mods tocan gobiernos distintos dentro del
mismo archivo, aqui se vera que las lineas difieren, pero decidir si eso se
puede fusionar sin romper nada sigue siendo cosa de quien lee el diff.
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from pathlib import Path

from .conflicts import Conflict
from .logs import get_logger
from .models import Mod

__all__ = [
    "ContentComparison",
    "FileVersion",
    "compare_conflict",
    "real_conflicts",
    "unified_diff",
]


_logger = get_logger("filediff")

# Un archivo de Paradox no llega a esto ni de lejos; lo que lo supera es una
# textura o un modelo, y de esos no hay diff que ensenar.
_MAX_TEXTO = 4 * 1024 * 1024

_CODIFICACIONES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
"""Lo que de verdad aparece en los mods, en orden de probabilidad.

`latin-1` va la ultima y nunca falla: acepta cualquier byte. Esta para que un
archivo con una codificacion rara se pueda seguir comparando en vez de
quedarse sin diff.
"""


@dataclass(slots=True)
class FileVersion:
    """La version que un mod concreto trae de un archivo en disputa."""

    mod: Mod
    path: Path | None
    """`None` si el archivo no se encuentra en disco."""

    size: int = 0
    digest: str = ""
    """SHA-256 del contenido. Vacio si no se pudo leer."""

    @property
    def disponible(self) -> bool:
        return bool(self.digest)


@dataclass(slots=True)
class ContentComparison:
    """Que trae cada mod de un mismo archivo, y si difieren."""

    path: str
    versions: list[FileVersion]

    @property
    def comparable(self) -> bool:
        """Si hay al menos dos versiones legibles que enfrentar."""
        return sum(1 for v in self.versions if v.disponible) >= 2

    @property
    def identicas(self) -> bool:
        """Si todas las versiones legibles son el mismo archivo byte a byte.

        Entonces no hay conflicto real: el motor se queda con una y es la misma
        que habria elegido cualquier otra.

        Exige que sean comparables. Sin eso, un conflicto en el que solo se
        puede leer una version daba "identicas" —un unico digest en el
        conjunto— y se escondia de la lista de conflictos reales, que es justo
        donde tiene que salir para que alguien mire por que falta el archivo.
        """
        if not self.comparable:
            return False
        return len({v.digest for v in self.versions if v.disponible}) == 1

    @property
    def winner(self) -> FileVersion | None:
        """La version que el juego usa: la del ultimo mod en el orden."""
        return self.versions[-1] if self.versions else None


def _resolver(mod: Mod, relativa: str) -> Path | None:
    """La ruta real del archivo dentro del mod.

    `conflicts` guarda las rutas en minusculas para poder compararlas entre
    mods, asi que en un sistema que distingue mayusculas hay que buscar el
    archivo de verdad en vez de confiar en el nombre normalizado.
    """
    if mod.folder is None:
        return None
    directa = mod.folder / relativa
    if directa.is_file():
        return directa

    carpeta = directa.parent
    if not carpeta.is_dir():
        return None
    buscado = directa.name.lower()
    for candidato in carpeta.iterdir():
        if candidato.is_file() and candidato.name.lower() == buscado:
            return candidato
    return None


def _digest(ruta: Path) -> tuple[str, int]:
    resumen = hashlib.sha256()
    total = 0
    with ruta.open("rb") as archivo:
        while bloque := archivo.read(65536):
            resumen.update(bloque)
            total += len(bloque)
    return resumen.hexdigest(), total


def compare_conflict(conflicto: Conflict) -> ContentComparison:
    """Lee las versiones de un archivo en disputa y las compara. No escribe nada."""
    versiones: list[FileVersion] = []
    for mod in conflicto.mods:
        ruta = _resolver(mod, conflicto.path)
        if ruta is None:
            versiones.append(FileVersion(mod=mod, path=None))
            continue
        try:
            digest, tamano = _digest(ruta)
        except OSError:
            _logger.warning("no se pudo leer %s de %s", conflicto.path, mod.name)
            versiones.append(FileVersion(mod=mod, path=ruta))
            continue
        versiones.append(
            FileVersion(mod=mod, path=ruta, size=tamano, digest=digest)
        )
    return ContentComparison(path=conflicto.path, versions=versiones)


def real_conflicts(
    conflictos: list[Conflict],
) -> tuple[list[ContentComparison], list[ContentComparison]]:
    """Separa los conflictos de verdad de los que son el mismo archivo.

    Devuelve `(reales, identicos)`. Es trabajo de disco —lee todos los archivos
    en disputa— asi que se llama desde un hilo.
    """
    reales: list[ContentComparison] = []
    identicos: list[ContentComparison] = []
    for conflicto in conflictos:
        comparacion = compare_conflict(conflicto)
        if comparacion.identicas:
            identicos.append(comparacion)
        else:
            reales.append(comparacion)
    if identicos:
        _logger.info(
            "%s de %s conflictos son el mismo archivo byte a byte",
            len(identicos),
            len(conflictos),
        )
    return reales, identicos


def _leer_texto(ruta: Path) -> list[str] | None:
    """El archivo como lineas, o `None` si es binario o demasiado grande."""
    try:
        if ruta.stat().st_size > _MAX_TEXTO:
            return None
        crudo = ruta.read_bytes()
    except OSError:
        return None
    # Un NUL en los primeros kilobytes es la senal practica de que no es texto.
    if b"\x00" in crudo[:8192]:
        return None
    for codificacion in _CODIFICACIONES:
        try:
            return crudo.decode(codificacion).splitlines(keepends=True)
        except UnicodeDecodeError:
            continue
    return None


def unified_diff(
    antes: FileVersion, despues: FileVersion, *, contexto: int = 3
) -> list[str] | None:
    """Diff en formato unificado entre dos versiones. `None` si no son texto.

    El orden es el de carga: `antes` es el mod que pierde y `despues` el que
    gana, asi que lo que aparece como anadido es lo que el juego acaba usando.
    """
    if antes.path is None or despues.path is None:
        return None
    a = _leer_texto(antes.path)
    b = _leer_texto(despues.path)
    if a is None or b is None:
        return None
    return list(
        difflib.unified_diff(
            a,
            b,
            fromfile=f"{antes.mod.name} (pierde)",
            tofile=f"{despues.mod.name} (gana)",
            n=contexto,
        )
    )
