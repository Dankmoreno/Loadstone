"""Deteccion de mods desactualizados comparando con el Workshop.

Paradox no guarda en ninguna parte la version del Workshop de la que salio un
mod instalado, asi que no hay un numero que comparar. Lo que si hay son dos
senales independientes:

- el **tamano**: el Workshop publica el tamano del paquete, y si no coincide
  con lo que ocupa en disco, el contenido ha cambiado.
- la **fecha**: la de la ultima actualizacion publicada frente a la del archivo
  mas reciente del mod en disco.

Ninguna es concluyente por si sola. El tamano cambia si editaste el mod a mano,
y las fechas se pierden al copiar carpetas con herramientas que no las
conservan. Por eso el resultado dice siempre en que senal se apoya, y se usa el
tamano como principal por ser el menos fragil.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from .models import Mod
from .workshop_api import WorkshopItem, published_file_details

__all__ = ["UpdateState", "UpdateStatus", "check_updates", "local_mtime", "local_size"]

# Margen para no marcar como viejo un mod que se actualizo casi a la vez que se
# instalo, y para absorber diferencias de huso y de redondeo del sistema.
_MARGEN = timedelta(hours=12)


class UpdateState(StrEnum):
    UP_TO_DATE = "al_dia"
    OUTDATED = "desactualizado"
    REMOVED = "retirado"
    """Ya no esta en el Workshop: borrado, oculto o baneado."""

    UNKNOWN = "sin_datos"
    """No viene del Workshop, o Steam no contesto por el."""


@dataclass(slots=True)
class UpdateStatus:
    mod: Mod
    state: UpdateState
    reason: str = ""
    remote: WorkshopItem | None = None
    local_size: int | None = None
    local_updated: datetime | None = None

    @property
    def remote_title(self) -> str | None:
        return self.remote.title if self.remote else None


def local_size(mod: Mod) -> int | None:
    """Lo que ocupa el mod en disco."""
    if mod.archive and mod.archive.is_file():
        return mod.archive.stat().st_size
    if mod.folder and mod.folder.is_dir():
        return _tamano_carpeta(mod.folder)
    return mod.size


def _tamano_carpeta(carpeta: Path) -> int:
    total = 0
    for elemento in carpeta.rglob("*"):
        try:
            if elemento.is_file():
                total += elemento.stat().st_size
        except OSError:
            # Un archivo que desaparece a mitad del recorrido no invalida el resto.
            continue
    return total


def local_mtime(mod: Mod) -> datetime | None:
    """Fecha del archivo mas reciente del mod."""
    objetivo = mod.archive if mod.archive and mod.archive.is_file() else mod.folder
    if objetivo is None or not objetivo.exists():
        return None
    if objetivo.is_file():
        return datetime.fromtimestamp(objetivo.stat().st_mtime, tz=UTC)

    ultimo = 0.0
    for elemento in objetivo.rglob("*"):
        try:
            ultimo = max(ultimo, elemento.stat().st_mtime)
        except OSError:
            continue
    return datetime.fromtimestamp(ultimo, tz=UTC) if ultimo else None


def check_updates(
    mods: list[Mod],
    *,
    timeout: int = 30,
    details: dict[str, WorkshopItem] | None = None,
) -> list[UpdateStatus]:
    """Compara los mods instalados con lo publicado en el Workshop.

    `details` permite inyectar la respuesta de Steam en las pruebas y evitar
    la llamada de red.
    """
    con_id = [mod for mod in mods if mod.steam_id]
    if details is None:
        details = (
            published_file_details([mod.steam_id for mod in con_id if mod.steam_id],
                                   timeout=timeout)
            if con_id
            else {}
        )

    resultado: list[UpdateStatus] = []
    for mod in mods:
        if not mod.steam_id:
            resultado.append(
                UpdateStatus(mod, UpdateState.UNKNOWN, "no viene del Workshop")
            )
            continue

        remoto = details.get(mod.steam_id)
        if remoto is None:
            resultado.append(
                UpdateStatus(mod, UpdateState.UNKNOWN, "Steam no devolvio datos")
            )
            continue
        if not remoto.available:
            resultado.append(
                UpdateStatus(
                    mod, UpdateState.REMOVED, "ya no esta publicado en el Workshop", remoto
                )
            )
            continue

        tamano = local_size(mod)
        fecha = local_mtime(mod)
        resultado.append(_comparar(mod, remoto, tamano, fecha))
    return resultado


def _comparar(
    mod: Mod, remoto: WorkshopItem, tamano: int | None, fecha: datetime | None
) -> UpdateStatus:
    if remoto.file_size and tamano and remoto.file_size != tamano:
        diferencia = remoto.file_size - tamano
        signo = "mas" if diferencia > 0 else "menos"
        return UpdateStatus(
            mod,
            UpdateState.OUTDATED,
            f"el Workshop pesa {abs(diferencia):,} bytes {signo}".replace(",", "."),
            remoto,
            tamano,
            fecha,
        )

    if remoto.time_updated and fecha and remoto.time_updated > fecha + _MARGEN:
        return UpdateStatus(
            mod,
            UpdateState.OUTDATED,
            f"actualizado en el Workshop el {remoto.time_updated:%Y-%m-%d}, "
            f"tu copia es del {fecha:%Y-%m-%d}",
            remoto,
            tamano,
            fecha,
        )

    if remoto.file_size and tamano:
        return UpdateStatus(mod, UpdateState.UP_TO_DATE, "mismo tamano", remoto, tamano, fecha)
    return UpdateStatus(
        mod, UpdateState.UNKNOWN, "sin tamano con el que comparar", remoto, tamano, fecha
    )
