"""Registro de juegos soportados y deteccion de instalaciones.

Un juego se identifica por su `launcher-settings.json`, que trae `gameId`,
`rawVersion` y `modsCompatibilityVersion`. Esta en la raiz de la instalacion
(Stellaris, HOI4) o dentro de `launcher/` (CK3, Victoria 3). EU5 ya no lo trae:
abandono el launcher externo, asi que se reconoce por la carpeta de datos.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from pathlib import Path

from .models import BackendKind, GameProfile

__all__ = ["KNOWN_GAMES", "detect_games", "documents_dir", "find_steam_libraries"]


KNOWN_GAMES: dict[str, GameProfile] = {
    game.key: game
    for game in (
        GameProfile(
            key="stellaris",
            display_name="Stellaris",
            game_id="stellaris",
            data_dir_name="Stellaris",
            steam_appid=281990,
            backend=BackendKind.LAUNCHER_V2,
        ),
        GameProfile(
            key="ck3",
            display_name="Crusader Kings III",
            game_id="ck3",
            data_dir_name="Crusader Kings III",
            steam_appid=1158310,
            backend=BackendKind.LAUNCHER_V2,
        ),
        GameProfile(
            key="victoria3",
            display_name="Victoria 3",
            game_id="victoria3",
            data_dir_name="Victoria 3",
            steam_appid=529340,
            backend=BackendKind.LAUNCHER_V2,
        ),
        GameProfile(
            key="hoi4",
            display_name="Hearts of Iron IV",
            game_id="hoi4",
            data_dir_name="Hearts of Iron IV",
            steam_appid=394360,
            backend=BackendKind.LAUNCHER_V2,
        ),
        GameProfile(
            key="eu4",
            display_name="Europa Universalis IV",
            game_id="eu4",
            data_dir_name="Europa Universalis IV",
            steam_appid=236850,
            backend=BackendKind.LAUNCHER_V2,
        ),
        GameProfile(
            key="eu5",
            display_name="Europa Universalis V",
            game_id="eu5",
            data_dir_name="Europa Universalis V",
            # Sin confirmar: EU5 no deja `launcher-settings.json` donde leerlo.
            steam_appid=None,
            backend=BackendKind.PLAYSETS_JSON,
        ),
    )
}

_GAMES_BY_ID = {game.game_id: game for game in KNOWN_GAMES.values()}

# Nombres de carpeta de instalacion tal y como los escribe Steam.
_INSTALL_DIR_NAMES = {
    "Stellaris": "stellaris",
    "Crusader Kings III": "ck3",
    "Victoria 3": "victoria3",
    "Hearts of Iron IV": "hoi4",
    "Europa Universalis IV": "eu4",
    "Europa Universalis V": "eu5",
}


def documents_dir() -> Path:
    """Carpeta `Documentos` del usuario, incluyendo el caso de OneDrive."""
    home = Path.home()
    candidates = [home / "Documents", home / "OneDrive" / "Documents"]
    onedrive = os.environ.get("OneDrive")
    if onedrive:
        candidates.append(Path(onedrive) / "Documents")
    for candidate in candidates:
        if (candidate / "Paradox Interactive").is_dir():
            return candidate
    return candidates[0]


def find_steam_libraries() -> list[Path]:
    """Carpetas `steamapps/common` de todas las bibliotecas de Steam."""
    roots: list[Path] = []
    program_files = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
    ]
    for base in program_files:
        vdf = base / "Steam" / "steamapps" / "libraryfolders.vdf"
        if not vdf.is_file():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.finditer(r'"path"\s*"((?:[^"\\]|\\.)*)"', text):
            library = Path(match.group(1).replace("\\\\", "\\")) / "steamapps" / "common"
            if library.is_dir():
                roots.append(library)
    return roots


def _read_launcher_settings(install: Path) -> dict | None:
    """Lee `launcher-settings.json` de la raiz o de `launcher/`."""
    for candidate in (install / "launcher-settings.json", install / "launcher" / "launcher-settings.json"):
        if not candidate.is_file():
            continue
        try:
            # El archivo trae BOM y, en algunas versiones, comas sobrantes;
            # si el JSON no parsea se cae al modo tolerante.
            text = candidate.read_text(encoding="utf-8-sig", errors="replace")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {
                    key: match.group(1)
                    for key in ("gameId", "rawVersion", "modsCompatibilityVersion")
                    if (match := re.search(rf'"{key}"\s*:\s*"([^"]*)"', text))
                }
        except OSError:
            continue
    return None


def _looks_like_paradox_game(path: Path) -> bool:
    """Reconoce una instalacion sin leer `launcher-settings.json`.

    Hay dos distribuciones en circulacion: la moderna mete el contenido en
    `game/` (CK3, V3, EU5) y la anterior lo deja plano en la raiz, con
    `common/` y `dlc/` (Stellaris, HOI4, EU4).
    """
    if (path / "game").is_dir():
        return True
    return (path / "common").is_dir() and (path / "dlc").is_dir()


def detect_games(extra_roots: list[Path] | None = None) -> dict[str, GameProfile]:
    """Devuelve los juegos conocidos con instalacion y datos ya resueltos.

    Busca instalaciones en las bibliotecas de Steam y en `extra_roots` (para
    copias fuera de Steam). La carpeta de datos se resuelve por nombre bajo
    `Documents/Paradox Interactive`, que es donde viven los mods y los playsets
    independientemente de donde este instalado el juego.
    """
    paradox_data = documents_dir() / "Paradox Interactive"
    found = {key: replace(game) for key, game in KNOWN_GAMES.items()}

    for key, game in found.items():
        data_path = paradox_data / game.data_dir_name
        if data_path.is_dir():
            game.data_path = data_path

    search_roots = find_steam_libraries() + list(extra_roots or [])
    for root in search_roots:
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            # `gameId` es la senal fiable; el nombre de la carpeta solo se usa
            # para los juegos que ya no traen launcher externo, como EU5.
            settings = _read_launcher_settings(child)
            game_id = (settings or {}).get("gameId")
            game = _GAMES_BY_ID.get(game_id) if game_id else None
            if game is None:
                key = _INSTALL_DIR_NAMES.get(child.name)
                candidate = KNOWN_GAMES.get(key) if key else None
                game = candidate if candidate and _looks_like_paradox_game(child) else None
            if game is None:
                continue
            target = found[game.key]
            if target.install_path is not None:
                continue
            target.install_path = child
            if settings:
                target.raw_version = settings.get("rawVersion") or target.raw_version
                target.mods_compat_version = (
                    settings.get("modsCompatibilityVersion") or target.mods_compat_version
                )
    return found
