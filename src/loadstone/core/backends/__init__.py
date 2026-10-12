"""Seleccion del backend segun el juego."""

from __future__ import annotations

from ..models import BackendKind, GameProfile
from .base import Backend, BackendError, backup_file
from .launcher_v2 import LauncherV2Backend
from .playsets_json import PlaysetsJsonBackend

__all__ = [
    "Backend",
    "BackendError",
    "LauncherV2Backend",
    "PlaysetsJsonBackend",
    "backup_file",
    "get_backend",
]

_BACKENDS = {
    BackendKind.LAUNCHER_V2: LauncherV2Backend,
    BackendKind.PLAYSETS_JSON: PlaysetsJsonBackend,
}


def get_backend(game: GameProfile) -> Backend:
    """Instancia el backend que corresponde a `game`."""
    try:
        backend_class = _BACKENDS[game.backend]
    except KeyError:  # pragma: no cover - solo si se amplia BackendKind
        raise BackendError(f"backend no soportado: {game.backend}") from None
    return backend_class(game)
