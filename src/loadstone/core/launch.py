"""Arrancar el juego desde Loadstone.

La informacion ya estaba delante desde el principio: `launcher-settings.json`
trae `exePath` y `exeArgs`, y hasta ahora solo se leian tres campos de ese
archivo. El unico detalle con miga es que el juego tiene que arrancar
*desvinculado*: si se lanza como proceso hijo, cerrar Loadstone se lo llevaria
por delante.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .logs import get_logger
from .models import GameProfile

__all__ = ["GameLaunchError", "LaunchTarget", "launch_game", "read_launch_target"]

_logger = get_logger("launch")


class GameLaunchError(RuntimeError):
    """No se encontro el ejecutable o el sistema se nego a arrancarlo."""


@dataclass(slots=True)
class LaunchTarget:
    executable: Path
    arguments: list[str] = field(default_factory=list)
    label: str = ""

    @property
    def command(self) -> list[str]:
        return [str(self.executable), *self.arguments]


def _settings_file(install: Path) -> Path | None:
    for candidata in (
        install / "launcher-settings.json",
        install / "launcher" / "launcher-settings.json",
    ):
        if candidata.is_file():
            return candidata
    return None


def _guess_executable(install: Path, game: GameProfile) -> Path | None:
    """Busca el ejecutable cuando no hay `launcher-settings.json`, como en EU5."""
    candidatos = [
        install / f"{game.game_id}.exe",
        install / f"{game.data_dir_name.lower().replace(' ', '')}.exe",
        install / "binaries" / f"{game.game_id}.exe",
    ]
    for candidato in candidatos:
        if candidato.is_file():
            return candidato
    # Ultimo recurso: el unico .exe de la raiz que no sea un instalador o una
    # utilidad de las que acompanan a algunas copias.
    descartar = ("unins", "setup", "install", "dowser", "crash", "rapidcrc")
    sueltos = [
        p
        for p in sorted(install.glob("*.exe"))
        if not any(palabra in p.name.lower() for palabra in descartar)
    ]
    return sueltos[0] if len(sueltos) == 1 else None


def read_launch_target(game: GameProfile) -> LaunchTarget | None:
    """Que ejecutar para este juego, o `None` si no se puede averiguar."""
    if game.install_path is None or not game.install_path.is_dir():
        return None

    ajustes = _settings_file(game.install_path)
    if ajustes is not None:
        try:
            texto = ajustes.read_text(encoding="utf-8-sig", errors="replace")
            datos = json.loads(texto)
        except (OSError, json.JSONDecodeError):
            # El archivo existe pero no parsea: se intenta sacar solo exePath.
            datos = {}
            try:
                match = re.search(r'"exePath"\s*:\s*"([^"]+)"', texto)
            except NameError:  # pragma: no cover - texto siempre existe aqui
                match = None
            if match:
                datos = {"exePath": match.group(1)}

        ruta = datos.get("exePath")
        if isinstance(ruta, str) and ruta:
            # Vienen como "./stellaris.exe", relativas a la instalacion.
            ejecutable = (game.install_path / ruta.lstrip("./")).resolve()
            argumentos = [a for a in datos.get("exeArgs") or [] if isinstance(a, str)]
            if ejecutable.is_file():
                return LaunchTarget(ejecutable, argumentos, datos.get("version", ""))

    adivinado = _guess_executable(game.install_path, game)
    return LaunchTarget(adivinado) if adivinado else None


def launch_game(game: GameProfile, *, extra_args: list[str] | None = None) -> LaunchTarget:
    """Arranca el juego y devuelve lo que se ejecuto.

    El proceso queda suelto a proposito: cerrar Loadstone no debe cerrar la
    partida.
    """
    objetivo = read_launch_target(game)
    if objetivo is None:
        raise GameLaunchError(
            f"{game.display_name}: no se encuentra el ejecutable en "
            f"{game.install_path or 'una instalacion sin detectar'}"
        )

    comando = [*objetivo.command, *(extra_args or [])]
    _logger.info("arrancando %s: %s", game.display_name, " ".join(comando))
    try:
        if sys.platform == "win32":
            # DETACHED_PROCESS deja al juego vivo por su cuenta.
            subprocess.Popen(
                comando,
                cwd=objetivo.executable.parent,
                creationflags=subprocess.DETACHED_PROCESS,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                comando,
                cwd=objetivo.executable.parent,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError as exc:
        raise GameLaunchError(f"no se pudo arrancar {game.display_name}: {exc}") from exc
    return objetivo


def open_in_file_manager(path: Path) -> None:
    """Abre una carpeta, o la carpeta que contiene un archivo."""
    destino = path if path.is_dir() else path.parent
    if not destino.exists():
        raise GameLaunchError(f"no existe {destino}")
    try:
        if sys.platform == "win32":
            os.startfile(destino)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(destino)])
        else:
            subprocess.Popen(["xdg-open", str(destino)])
    except OSError as exc:
        raise GameLaunchError(f"no se pudo abrir {destino}: {exc}") from exc
