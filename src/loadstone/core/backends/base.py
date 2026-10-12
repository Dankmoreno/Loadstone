"""Contrato comun de los backends de playsets.

Cada juego guarda sus playsets a su manera, pero todos responden a las mismas
preguntas: que mods hay, que colecciones existen, y como se le dice al juego
cual usar. El nucleo y la GUI hablan solo con esta interfaz.
"""

from __future__ import annotations

import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path

from ..logs import get_logger
from ..models import GameProfile, Mod, Playset

__all__ = ["Backend", "BackendError", "backup_file"]


_logger = get_logger("backend")


class BackendError(RuntimeError):
    """Fallo al leer o escribir los datos del juego, con mensaje presentable."""


def backup_file(path: Path, keep: int = 5) -> Path | None:
    """Copia `path` antes de modificarlo y deja como maximo `keep` copias.

    Loadstone escribe sobre archivos que el juego y el launcher tambien usan,
    asi que ninguna escritura ocurre sin copia previa. Devuelve la ruta de la
    copia, o `None` si el original todavia no existe.
    """
    if not path.is_file():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = path.with_name(f"{path.name}.{stamp}.loadstone-backup")
    shutil.copy2(path, destination)
    _logger.info("copia de seguridad: %s", destination.name)

    existing = sorted(path.parent.glob(f"{path.name}.*.loadstone-backup"))
    for stale in existing[:-keep] if keep > 0 else []:
        try:
            stale.unlink()
        except OSError:
            # Perder una copia vieja no justifica abortar la escritura.
            pass
    return destination


class Backend(ABC):
    """Acceso de lectura y escritura a los playsets de un juego."""

    def __init__(self, game: GameProfile) -> None:
        if not game.has_data_dir:
            raise BackendError(
                f"{game.display_name}: no se encuentra la carpeta de datos "
                f"({game.data_path or 'ruta sin resolver'})"
            )
        self.game = game

    @abstractmethod
    def read_mods(self) -> list[Mod]:
        """Todos los mods conocidos: registrados, en disco, o ambos."""

    @abstractmethod
    def read_playsets(self) -> list[Playset]:
        """Playsets existentes, con su orden y su estado de activacion."""

    @abstractmethod
    def save_playset(self, playset: Playset) -> None:
        """Persiste orden, activaciones y modo de ordenacion de un playset."""

    @abstractmethod
    def activate(self, playset_id: str) -> None:
        """Marca un playset como el activo."""

    def create_playset(self, name: str) -> str:
        """Crea un playset vacio y devuelve su identificador."""
        raise BackendError("este juego no permite crear playsets desde aqui")

    def rename_playset(self, playset_id: str, name: str) -> None:
        raise BackendError("este juego no permite renombrar playsets desde aqui")

    def delete_playset(self, playset_id: str) -> None:
        raise BackendError("este juego no permite borrar playsets desde aqui")

    def set_dlc_enabled(self, playset: Playset, dlc_id: str, enabled: bool) -> None:
        """Marca un DLC como activo o no dentro de un playset."""
        playset.dlcs[dlc_id] = enabled

    def unregister_mod(self, uid: str) -> bool:
        """Quita un mod del registro del juego. `True` si habia algo que quitar.

        Igual que `register_mod`, no hace falta donde el registro es la propia
        carpeta de mods.
        """
        return False

    def register_mod(self, mod: Mod) -> str:
        """Da de alta un mod recien instalado y devuelve su uid definitivo.

        Por defecto no hay nada que registrar: en los juegos que descubren los
        mods escaneando la carpeta, dejar el descriptor en su sitio ya basta.
        """
        return mod.uid

    @abstractmethod
    def apply_to_game(self, playset: Playset) -> Path | None:
        """Escribe lo que el juego lee al arrancar.

        En los juegos con launcher v2 esto es `dlc_load.json`, que es el unico
        archivo que el ejecutable consulta: la base de datos solo alimenta a la
        interfaz del launcher. Devuelve el archivo escrito.
        """
