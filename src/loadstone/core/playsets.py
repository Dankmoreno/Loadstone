"""Gestion de playsets: crear, duplicar, renombrar, borrar, exportar e importar.

RimSort llama "instancias" a algo parecido, pero alli una instancia es otra
instalacion del juego con su carpeta de mods. En Paradox eso ya existe y se
llama playset, asi que en vez de inventar un concepto encima se completa el
que el juego trae: lo que faltaba no era otro nivel de agrupacion, sino poder
manipular los playsets sin abrir el launcher.

El formato de intercambio guarda `registry_id` y nombre, no identificadores de
la base del launcher: asi un playset exportado se puede importar en otra
maquina, donde esos identificadores serian distintos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .atomic import atomic_write_json
from .logs import get_logger
from .models import Mod, Playset, PlaysetMod

__all__ = ["PlaysetFile", "export_playset", "import_playset", "read_playset_file"]

_logger = get_logger("playsets")
_VERSION = 1


@dataclass(slots=True)
class PlaysetFile:
    """Un playset en forma portable."""

    name: str
    game: str
    mods: list[tuple[str, str, bool]] = field(default_factory=list)
    """`(registry_id, nombre, activado)` en orden de carga."""

    @property
    def enabled_count(self) -> int:
        return sum(1 for _, _, activado in self.mods if activado)


def export_playset(
    playset: Playset, mods: dict[str, Mod], game_key: str, destino: Path
) -> PlaysetFile:
    """Escribe el playset en un archivo que se puede compartir."""
    entradas: list[tuple[str, str, bool]] = []
    for entrada in sorted(playset.mods, key=lambda e: e.position):
        mod = mods.get(entrada.uid)
        registro = mod.registry_id if mod else None
        if not registro:
            # Sin descriptor no hay forma de volver a encontrarlo en otra
            # maquina, asi que no se exporta una referencia rota.
            continue
        entradas.append((registro, mod.name if mod else registro, entrada.enabled))

    datos = {
        "format": "loadstone-playset",
        "version": _VERSION,
        "game": game_key,
        "name": playset.name,
        "mods": [
            {"registry_id": r, "name": n, "enabled": e} for r, n, e in entradas
        ],
    }
    atomic_write_json(destino, datos, indent=2)
    _logger.info("playset '%s' exportado a %s", playset.name, destino)
    return PlaysetFile(name=playset.name, game=game_key, mods=entradas)


def read_playset_file(origen: Path) -> PlaysetFile:
    """Lee un playset exportado. Lanza `ValueError` si no lo es."""
    try:
        datos = json.loads(origen.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"no se pudo leer {origen.name}: {exc}") from exc
    if not isinstance(datos, dict) or datos.get("format") != "loadstone-playset":
        raise ValueError(f"{origen.name} no es un playset exportado por Loadstone")

    entradas: list[tuple[str, str, bool]] = []
    for bruto in datos.get("mods") or []:
        if not isinstance(bruto, dict):
            continue
        registro = bruto.get("registry_id")
        if isinstance(registro, str) and registro:
            entradas.append(
                (registro, str(bruto.get("name") or registro), bool(bruto.get("enabled", True)))
            )
    return PlaysetFile(
        name=str(datos.get("name") or origen.stem),
        game=str(datos.get("game") or "?"),
        mods=entradas,
    )


def import_playset(
    archivo: PlaysetFile, playset: Playset, mods: list[Mod]
) -> tuple[int, list[str]]:
    """Vuelca el contenido del archivo en un playset existente.

    Devuelve cuantos mods se colocaron y los nombres de los que no estan
    instalados en esta maquina.
    """
    por_registro = {mod.registry_id: mod for mod in mods if mod.registry_id}
    colocados: list[PlaysetMod] = []
    faltantes: list[str] = []

    for registro, nombre, activado in archivo.mods:
        mod = por_registro.get(registro)
        if mod is None:
            faltantes.append(nombre)
            continue
        colocados.append(
            PlaysetMod(uid=mod.uid, enabled=activado, position=len(colocados))
        )

    playset.mods = colocados
    _logger.info(
        "importado '%s': %d colocados, %d sin instalar",
        archivo.name,
        len(colocados),
        len(faltantes),
    )
    return len(colocados), faltantes
