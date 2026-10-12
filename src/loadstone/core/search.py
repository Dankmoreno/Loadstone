"""Busqueda de texto dentro de los archivos de los mods.

Responde a la pregunta que nadie mas responde: *que mod define esto*. En
Paradox, donde el ultimo mod que carga pisa a los anteriores, saber quien toca
`common/governments/00_governments.txt` es el paso previo a entender cualquier
conflicto.

El escaneo se hace a mano, sin indices: con 200 mods y varios GB lo que importa
es descartar rapido. Por eso se filtra por extension antes de abrir nada, se
ignoran los archivos enormes y se corta en cuanto hay resultados suficientes.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .models import Mod

__all__ = ["SearchHit", "SearchOptions", "SearchScope", "search_mods"]


# Los archivos de script y texto de Clausewitz. El resto (.dds, .png, .ogg,
# .mesh) es binario y no tiene sentido recorrerlo linea a linea.
EXTENSIONES_TEXTO = (
    ".txt",
    ".yml",
    ".yaml",
    ".gui",
    ".gfx",
    ".asset",
    ".mod",
    ".json",
    ".csv",
    ".info",
    ".settings",
    ".sfx",
)

# Las traducciones son la mitad de los archivos de un mod grande y casi nunca
# son lo que se busca, asi que se pueden saltar.
CARPETAS_TRADUCCION = ("localisation", "localization", "localisation_synced")


class SearchScope(StrEnum):
    ACTIVE = "activos"
    INACTIVE = "inactivos"
    ALL = "todos"


@dataclass(slots=True)
class SearchOptions:
    query: str
    regex: bool = False
    case_sensitive: bool = False
    in_paths: bool = False
    """Buscar en la ruta de los archivos en vez de en su contenido."""

    extensions: tuple[str, ...] = EXTENSIONES_TEXTO
    skip_translations: bool = True
    max_hits: int = 500
    max_file_bytes: int = 8 * 1024 * 1024
    """Un archivo de script normal no llega a 1 MB; mas alla casi seguro es
    contenido generado o empaquetado."""


@dataclass(slots=True)
class SearchHit:
    mod: Mod
    path: Path
    """Ruta relativa a la carpeta del mod."""

    line_number: int
    line: str
    absolute: Path = field(compare=False, default_factory=Path)


def _build_matcher(options: SearchOptions) -> Callable[[str], bool]:
    if options.regex:
        banderas = 0 if options.case_sensitive else re.IGNORECASE
        try:
            patron = re.compile(options.query, banderas)
        except re.error as exc:
            raise ValueError(f"expresion regular invalida: {exc}") from exc
        return lambda texto: patron.search(texto) is not None

    if options.case_sensitive:
        aguja = options.query
        return lambda texto: aguja in texto
    aguja = options.query.lower()
    return lambda texto: aguja in texto.lower()


def _candidate_files(carpeta: Path, options: SearchOptions) -> Iterator[Path]:
    for ruta in carpeta.rglob("*"):
        if not ruta.is_file():
            continue
        if options.extensions and ruta.suffix.lower() not in options.extensions:
            continue
        if options.skip_translations and any(
            parte.lower() in CARPETAS_TRADUCCION for parte in ruta.parts
        ):
            continue
        try:
            if ruta.stat().st_size > options.max_file_bytes:
                continue
        except OSError:
            continue
        yield ruta


def _read_lines(ruta: Path) -> list[str]:
    """Lee un archivo de script tolerando las codificaciones de Paradox."""
    try:
        datos = ruta.read_bytes()
    except OSError:
        return []
    # Un cero binario descarta el archivo: no es texto por mucho que lo diga
    # la extension.
    if b"\x00" in datos[:4096]:
        return []
    for codificacion in ("utf-8-sig", "utf-8"):
        try:
            return datos.decode(codificacion).splitlines()
        except UnicodeDecodeError:
            continue
    return datos.decode("cp1252", errors="replace").splitlines()


def search_mods(
    mods: list[Mod],
    options: SearchOptions,
    *,
    progress: Callable[[int, int, Mod], None] | None = None,
) -> list[SearchHit]:
    """Busca en los mods indicados y devuelve los resultados encontrados.

    `progress` recibe `(indice, total, mod)` antes de procesar cada mod, para
    que una interfaz pueda mostrar por donde va sin que este modulo sepa nada
    de Qt.
    """
    if not options.query.strip():
        return []
    coincide = _build_matcher(options)
    resultados: list[SearchHit] = []

    for indice, mod in enumerate(mods):
        if progress is not None:
            progress(indice, len(mods), mod)
        carpeta = mod.folder
        if carpeta is None or not carpeta.is_dir():
            continue

        for ruta in _candidate_files(carpeta, options):
            relativa = ruta.relative_to(carpeta)
            if options.in_paths:
                if coincide(relativa.as_posix()):
                    resultados.append(SearchHit(mod, relativa, 0, relativa.as_posix(), ruta))
                    if len(resultados) >= options.max_hits:
                        return resultados
                continue

            for numero, linea in enumerate(_read_lines(ruta), start=1):
                if coincide(linea):
                    resultados.append(SearchHit(mod, relativa, numero, linea.strip(), ruta))
                    if len(resultados) >= options.max_hits:
                        return resultados
    return resultados


def select_scope(
    mods: list[Mod], enabled_uids: set[str], scope: SearchScope | str
) -> list[Mod]:
    """Filtra los mods segun esten activos o no en el playset.

    Acepta tambien la cadena del valor porque Qt convierte un `StrEnum` a
    cadena plana al guardarlo como dato de un widget: comparar con `is`
    devolveria falso para un valor que viene de la interfaz, y el filtro haria
    justo lo contrario de lo pedido.
    """
    scope = SearchScope(scope)
    if scope is SearchScope.ALL:
        return mods
    activo = scope is SearchScope.ACTIVE
    return [mod for mod in mods if (mod.uid in enabled_uids) == activo]
