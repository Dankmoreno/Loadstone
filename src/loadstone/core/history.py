"""Historial de listas de mods, con comparacion y restauracion.

Cada vez que se aplica un playset al juego se guarda una instantanea. Sirve
para dos cosas que duelen cuando faltan: volver a la lista de la semana pasada
que si funcionaba, y ver exactamente que cambio entre dos partidas.

Las instantaneas son JSON independientes del juego y del launcher: guardan el
identificador de registro de cada mod (`mod/1087781345.mod`), no su `id` en la
base, porque esos identificadores sobreviven a que el launcher reconstruya su
base de datos.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .atomic import atomic_write_json
from .logs import get_logger
from .models import Mod, Playset, PlaysetMod
from .paths import history_dir, legacy_history_dirs
from .sorting import minimal_moves

__all__ = ["History", "Snapshot", "SnapshotDiff", "history_root"]


_logger = get_logger("history")


def history_root() -> Path:
    """Donde viven las instantaneas.

    Si todavia no hay ninguna aqui pero quedan de una version anterior, se usa
    la carpeta antigua: perder el historial por un cambio de convencion de
    rutas seria justo lo contrario de para lo que existe.
    """
    actual = history_dir()
    if actual.is_dir():
        return actual
    for vieja in legacy_history_dirs():
        if vieja.is_dir():
            return vieja
    return actual


@dataclass(slots=True)
class SnapshotEntry:
    registry_id: str
    name: str
    enabled: bool = True


@dataclass(slots=True)
class Snapshot:
    id: str
    """Marca de tiempo, que ordena y sirve de nombre de archivo."""

    created: float
    game_key: str
    playset: str
    entries: list[SnapshotEntry] = field(default_factory=list)
    note: str = ""
    path: Path | None = None

    @property
    def enabled_ids(self) -> list[str]:
        return [entry.registry_id for entry in self.entries if entry.enabled]

    @property
    def names(self) -> dict[str, str]:
        return {entry.registry_id: entry.name for entry in self.entries}

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "created": self.created,
            "game": self.game_key,
            "playset": self.playset,
            "note": self.note,
            "mods": [
                {"registry_id": e.registry_id, "name": e.name, "enabled": e.enabled}
                for e in self.entries
            ],
        }

    @classmethod
    def from_json(cls, datos: dict, path: Path | None = None) -> Snapshot:
        return cls(
            id=str(datos.get("id") or (path.stem if path else "?")),
            created=float(datos.get("created") or 0.0),
            game_key=str(datos.get("game") or "?"),
            playset=str(datos.get("playset") or "?"),
            note=str(datos.get("note") or ""),
            entries=[
                SnapshotEntry(
                    registry_id=str(m.get("registry_id") or ""),
                    name=str(m.get("name") or ""),
                    enabled=bool(m.get("enabled", True)),
                )
                for m in datos.get("mods") or []
                if isinstance(m, dict) and m.get("registry_id")
            ],
            path=path,
        )


@dataclass(slots=True)
class SnapshotDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.moved)

    def summary(self) -> str:
        if self.is_empty:
            return "sin cambios"
        partes = []
        for etiqueta, valores in (
            ("anadidos", self.added),
            ("quitados", self.removed),
            ("reubicados", self.moved),
        ):
            if valores:
                partes.append(f"{len(valores)} {etiqueta}")
        return ", ".join(partes)


class History:
    """Las instantaneas de un juego."""

    def __init__(self, game_key: str, root: Path | None = None) -> None:
        self.game_key = game_key
        self.directory = (root or history_root()) / game_key

    def save(
        self,
        playset: Playset,
        mods: dict[str, Mod],
        *,
        note: str = "",
        keep: int = 50,
    ) -> Snapshot:
        """Guarda el estado actual del playset."""
        entradas: list[SnapshotEntry] = []
        for entry in sorted(playset.mods, key=lambda e: e.position):
            mod = mods.get(entry.uid)
            registro = mod.registry_id if mod else None
            if not registro:
                # Sin descriptor no hay nada que restaurar despues.
                continue
            entradas.append(
                SnapshotEntry(
                    registry_id=registro,
                    name=mod.name if mod else registro,
                    enabled=entry.enabled,
                )
            )

        ahora = time.time()
        snapshot = Snapshot(
            id=time.strftime("%Y%m%d-%H%M%S", time.localtime(ahora)),
            created=ahora,
            game_key=self.game_key,
            playset=playset.name,
            entries=entradas,
            note=note,
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        destino = self.directory / f"{snapshot.id}.json"
        # Dos aplicaciones en el mismo segundo no deben pisarse.
        contador = 1
        while destino.exists():
            destino = self.directory / f"{snapshot.id}-{contador}.json"
            contador += 1
        snapshot.id = destino.stem
        snapshot.path = destino
        atomic_write_json(destino, snapshot.to_json(), indent=2)
        self._prune(keep)
        _logger.info(
            "instantanea %s: %d mods de '%s'", snapshot.id, len(entradas), playset.name
        )
        return snapshot

    def _prune(self, keep: int) -> None:
        if keep <= 0:
            return
        archivos = sorted(self.directory.glob("*.json"))
        for viejo in archivos[:-keep]:
            try:
                viejo.unlink()
            except OSError:
                pass

    def list(self) -> list[Snapshot]:
        """Instantaneas de la mas reciente a la mas antigua."""
        if not self.directory.is_dir():
            return []
        resultado: list[Snapshot] = []
        for ruta in sorted(self.directory.glob("*.json"), reverse=True):
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(datos, dict):
                resultado.append(Snapshot.from_json(datos, ruta))
        return resultado

    def get(self, snapshot_id: str) -> Snapshot | None:
        for snapshot in self.list():
            if snapshot.id == snapshot_id:
                return snapshot
        return None

    def set_note(self, snapshot_id: str, note: str) -> bool:
        snapshot = self.get(snapshot_id)
        if snapshot is None or snapshot.path is None:
            return False
        snapshot.note = note
        atomic_write_json(snapshot.path, snapshot.to_json(), indent=2)
        return True


def diff_snapshots(antigua: Snapshot, nueva: Snapshot) -> SnapshotDiff:
    """Compara dos instantaneas por sus mods activos.

    Los reubicados se calculan con la misma medida que usa el ordenador, para
    no contar como movido a todo el que se desplaza una casilla porque otro
    mod cambio de sitio.
    """
    antes = antigua.enabled_ids
    despues = nueva.enabled_ids
    conjunto_antes, conjunto_despues = set(antes), set(despues)
    nombres = {**antigua.names, **nueva.names}

    anadidos = [nombres.get(r, r) for r in despues if r not in conjunto_antes]
    quitados = [nombres.get(r, r) for r in antes if r not in conjunto_despues]

    comunes_antes = [r for r in antes if r in conjunto_despues]
    comunes_despues = [r for r in despues if r in conjunto_antes]
    movidos = [nombres.get(r, r) for r in minimal_moves(comunes_antes, comunes_despues)]
    return SnapshotDiff(added=anadidos, removed=quitados, moved=movidos)


def restore_into(snapshot: Snapshot, playset: Playset, mods: list[Mod]) -> tuple[int, list[str]]:
    """Deja el playset como estaba en la instantanea.

    Devuelve cuantos mods se colocaron y los nombres de los que ya no estan
    instalados, que no se pueden restaurar.
    """
    por_registro = {
        mod.registry_id: mod for mod in mods if mod.registry_id
    }
    posicion = 0
    faltantes: list[str] = []
    nuevas = []
    for entrada in snapshot.entries:
        mod = por_registro.get(entrada.registry_id)
        if mod is None:
            if entrada.enabled:
                faltantes.append(entrada.name or entrada.registry_id)
            continue
        nuevas.append((mod.uid, entrada.enabled, posicion))
        posicion += 1

    playset.mods = [
        PlaysetMod(uid=uid, enabled=enabled, position=pos) for uid, enabled, pos in nuevas
    ]
    return len(nuevas), faltantes
