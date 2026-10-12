"""Deteccion de conflictos entre mods, a nivel de archivo.

Esta es la pregunta de fondo de todo gestor de mods de Paradox. La regla del
motor es simple: los mods se cargan en orden y, cuando dos tocan el mismo
archivo, **gana el ultimo**. Lo que no es simple es saber que archivos se
solapan entre doscientos mods.

Alcance, dicho claro: esto compara **rutas de archivo**, no su contenido. Si
dos mods tocan `common/governments/00_governments.txt`, aqui sale; si uno
modifica el gobierno A y el otro el B dentro de ese archivo, el motor se queda
solo con el del ultimo mod y los cambios del primero se pierden, pero para
distinguir ese caso del de "los dos cambian lo mismo" haria falta comparar
objeto a objeto, que es otro proyecto. Lo que si se tiene en cuenta es
`replace_path`, porque reemplaza carpetas enteras y convierte un solapamiento
aparentemente inocente en una sustitucion total.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .logs import get_logger
from .models import Mod

__all__ = ["Conflict", "ConflictReport", "find_conflicts", "index_mod_files"]

_logger = get_logger("conflicts")

# Archivos que todo mod tiene y que no son contenido del juego: que dos mods
# tengan miniatura no es un conflicto.
_IGNORADOS = {"descriptor.mod", "thumbnail.png", "thumbnail.jpg", "readme.md", "license"}

# Solo cuentan las carpetas que el motor carga. Un mod puede traer su `.git`,
# documentacion o archivos sueltos del autor.
_CARPETAS_DE_JUEGO = (
    "common",
    "events",
    "gfx",
    "interface",
    "localisation",
    "localization",
    "map",
    "music",
    "sound",
    "prescripted_countries",
    "history",
    "flags",
    "fonts",
    "dlc_metadata",
)


@dataclass(slots=True)
class Conflict:
    """Un archivo que varios mods del playset definen."""

    path: str
    """Ruta relativa dentro del mod, en minusculas y con barras normales."""

    mods: list[Mod] = field(default_factory=list)
    """En orden de carga: el primero carga antes, el ultimo gana."""

    replaced: bool = False
    """Si el ganador declara `replace_path` sobre esta carpeta."""

    @property
    def winner(self) -> Mod:
        return self.mods[-1]

    @property
    def losers(self) -> list[Mod]:
        return self.mods[:-1]


@dataclass(slots=True)
class ConflictReport:
    conflicts: list[Conflict] = field(default_factory=list)
    scanned: int = 0
    """Mods examinados."""

    def by_pair(self) -> dict[tuple[str, str], int]:
        """Cuantos archivos se disputan cada par de mods.

        Es la vista util cuando hay cientos de conflictos: casi siempre son
        dos o tres mods grandes pisandose, no doscientos problemas distintos.
        """
        cuenta: dict[tuple[str, str], int] = {}
        for conflicto in self.conflicts:
            ganador = conflicto.winner.name
            for perdedor in conflicto.losers:
                clave = (perdedor.name, ganador)
                cuenta[clave] = cuenta.get(clave, 0) + 1
        return dict(sorted(cuenta.items(), key=lambda kv: -kv[1]))

    def for_mod(self, mod: Mod) -> list[Conflict]:
        return [c for c in self.conflicts if any(m.uid == mod.uid for m in c.mods)]


def index_mod_files(mod: Mod) -> set[str]:
    """Rutas relativas del contenido de juego que aporta un mod."""
    carpeta = mod.folder
    if carpeta is None or not carpeta.is_dir():
        return set()

    rutas: set[str] = set()
    for base in _CARPETAS_DE_JUEGO:
        subcarpeta = carpeta / base
        if not subcarpeta.is_dir():
            continue
        for archivo in subcarpeta.rglob("*"):
            try:
                if not archivo.is_file():
                    continue
            except OSError:
                continue
            relativa = archivo.relative_to(carpeta).as_posix().lower()
            if relativa.rsplit("/", 1)[-1] in _IGNORADOS:
                continue
            rutas.add(relativa)
    return rutas


def _replaced_dirs(mod: Mod) -> list[str]:
    return [p.replace("\\", "/").strip("/").lower() for p in mod.replace_paths if p]


def find_conflicts(
    mods_in_order: list[Mod],
    *,
    progress: Callable[[int, int, Mod], None] | None = None,
) -> ConflictReport:
    """Busca archivos definidos por mas de un mod.

    `mods_in_order` debe venir en orden de carga: el ultimo de la lista es el
    que el juego deja ganar.
    """
    indices: list[tuple[Mod, set[str]]] = []
    for posicion, mod in enumerate(mods_in_order):
        if progress is not None:
            progress(posicion, len(mods_in_order), mod)
        rutas = index_mod_files(mod)
        if rutas:
            indices.append((mod, rutas))

    duenos: dict[str, list[Mod]] = {}
    for mod, rutas in indices:
        for ruta in rutas:
            duenos.setdefault(ruta, []).append(mod)

    conflictos: list[Conflict] = []
    for ruta, implicados in duenos.items():
        if len(implicados) < 2:
            continue
        ganador = implicados[-1]
        sustituida = any(
            ruta.startswith(f"{carpeta}/") for carpeta in _replaced_dirs(ganador)
        )
        conflictos.append(Conflict(path=ruta, mods=implicados, replaced=sustituida))

    conflictos.sort(key=lambda c: (-len(c.mods), c.path))
    _logger.info(
        "%d archivos en conflicto entre %d mods", len(conflictos), len(indices)
    )
    return ConflictReport(conflicts=conflictos, scanned=len(indices))


def overridden_files(report: ConflictReport, mod: Mod) -> list[Conflict]:
    """Archivos de `mod` que otro mod posterior pisa."""
    return [c for c in report.conflicts if any(m.uid == mod.uid for m in c.losers)]


def mod_folder_size(mod: Mod) -> int:
    """Tamano en disco, util para el panel de detalle."""
    carpeta: Path | None = mod.folder
    if carpeta is None or not carpeta.is_dir():
        return mod.size or 0
    total = 0
    for archivo in carpeta.rglob("*"):
        try:
            if archivo.is_file():
                total += archivo.stat().st_size
        except OSError:
            continue
    return total
