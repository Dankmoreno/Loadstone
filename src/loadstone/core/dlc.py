"""Los DLC instalados y su estado en un playset.

Dije antes que esto no se podia hacer con garantias, y me equivocaba a medias.
Lo que falta no es el mapeo, que si es determinista: cada DLC trae un archivo
`.dlc` dentro de `dlc/<carpeta>/` con todo lo necesario.

    name = "Utopia"
    archive = "dlc/dlc014_utopia/dlc014.zip"
    pops_id = "utopia"
    category = "expansion"

`pops_id` es exactamente la clave que usa `playsets_dlcs.dlcId` en la base del
launcher, asi que la correspondencia entre lo que el launcher guarda y lo que
hay en disco queda cerrada.

**Lo que sigue sin confirmar** es el formato que `dlc_load.json` espera en
`disabled_dlcs`. La instalacion de referencia lo tenia vacio y las copias que
hace el propio launcher solo guardan mods, asi que se usa la ruta de la carpeta
(`dlc/dlc014_utopia`), que es la forma documentada por la comunidad. Si
estuviera equivocada, el efecto es que el juego ignore la entrada y cargue el
DLC igualmente: molesto, pero no destructivo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .clausewitz import ClausewitzError, parse, read_text
from .logs import get_logger

__all__ = ["Dlc", "scan_dlc"]

_logger = get_logger("dlc")


@dataclass(slots=True)
class Dlc:
    id: str
    """`pops_id`: la clave con la que el launcher lo referencia."""

    name: str
    folder: str
    """Ruta relativa a la instalacion, que es lo que lee el juego."""

    path: Path
    category: str = ""
    steam_id: str | None = None
    thumbnail: Path | None = None

    @property
    def is_expansion(self) -> bool:
        return self.category.lower() in ("expansion", "major_expansion")


def _dlc_root(install: Path) -> Path | None:
    """La carpeta `dlc/`, que esta en la raiz o bajo `game/` segun el juego."""
    for base in (install / "dlc", install / "game" / "dlc"):
        if base.is_dir():
            return base
    return None


def _from_json(archivo: Path) -> Dlc | None:
    """Lee el formato de EU5, que abandono el script de Clausewitz.

    Trae los mismos campos con otros nombres: `pops_id` sigue siendo la clave,
    y `path` da directamente la ruta relativa que antes habia que deducir del
    archivo comprimido.
    """
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        _logger.warning("no se pudo leer %s: %s", archivo.name, exc)
        return None
    if not isinstance(datos, dict):
        return None

    carpeta = archivo.parent
    identificador = str(datos.get("pops_id") or datos.get("name") or carpeta.name)
    miniatura = datos.get("picture")
    steam_id = datos.get("steam_id")
    return Dlc(
        id=identificador,
        # El nombre interno es un identificador en minusculas; sin una tabla de
        # localizacion es lo unico legible que hay.
        name=str(datos.get("name") or carpeta.name),
        folder=str(datos.get("path") or f"dlc/{carpeta.name}"),
        path=carpeta,
        category="",
        steam_id=str(steam_id) if steam_id else None,
        thumbnail=(carpeta / miniatura) if isinstance(miniatura, str) and miniatura else None,
    )


def scan_dlc(install: Path | None) -> list[Dlc]:
    """Lee los DLC instalados. Lista vacia si no se encuentra la instalacion."""
    if install is None or not install.is_dir():
        return []

    raiz = _dlc_root(install)
    if raiz is None:
        return []

    resultado: list[Dlc] = []
    # Se recorre por carpeta y no por patron: Victoria 3 trae los dos formatos
    # en la misma carpeta, y buscarlos por separado contaba cada DLC dos veces.
    for carpeta in sorted(p for p in raiz.iterdir() if p.is_dir()):
        moderno = next(iter(sorted(carpeta.glob("*.dlc.json"))), None)
        if moderno is not None:
            entrada = _from_json(moderno)
            if entrada is not None:
                resultado.append(entrada)
            continue

        archivo = next(
            (p for p in sorted(carpeta.glob("*.dlc")) if not p.name.endswith(".dlc.json")),
            None,
        )
        if archivo is None:
            continue
        try:
            bloque = parse(read_text(archivo))
        except (ClausewitzError, OSError) as exc:
            _logger.warning("no se pudo leer %s: %s", archivo.name, exc)
            continue
        # `pops_id` es la clave buena; si faltara, el nombre de la carpeta sin
        # el prefijo numerico da el mismo valor en todos los casos vistos.
        identificador = bloque.get_str("pops_id") or carpeta.name.split("_", 1)[-1]
        nombre = bloque.get_str("name") or carpeta.name
        archivo_zip = bloque.get_str("archive")
        relativa = (
            archivo_zip.rsplit("/", 1)[0]
            if archivo_zip and "/" in archivo_zip
            else f"dlc/{carpeta.name}"
        )
        miniatura = bloque.get_str("thumbnail")

        resultado.append(
            Dlc(
                id=identificador,
                name=nombre,
                folder=relativa,
                path=carpeta,
                category=bloque.get_str("category") or "",
                steam_id=bloque.get_str("steam_id"),
                thumbnail=(carpeta / miniatura) if miniatura else None,
            )
        )
    _logger.info("%d DLC encontrados en %s", len(resultado), install.name)
    return resultado
