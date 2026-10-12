"""Limpieza de restos en la carpeta de mods.

Una carpeta `mod/` acumula tres clases de basura, y conviene no mezclarlas
porque el riesgo de cada una es distinto:

- **descriptor colgado**: un `.mod` que apunta a contenido que ya no esta.
  Borrarlo es seguro: no hay nada que perder.
- **registro fantasma**: una fila en la base del launcher sin descriptor ni
  contenido. Tambien es seguro.
- **carpeta sin enlazar**: contenido con su `descriptor.mod` pero sin `.mod`
  en `mod/`, asi que el juego no lo ve. Aqui si hay algo que perder: puede ser
  un mod que alguien descomprimio a mano y todavia quiere.

Nada se borra si el mod aparece en algun playset, aunque este desactivado.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .logs import get_logger
from .models import Mod, Playset

__all__ = ["CleanupItem", "CleanupKind", "execute_cleanup", "plan_cleanup"]


_logger = get_logger("cleanup")


class CleanupKind(StrEnum):
    DANGLING = "descriptor_colgado"
    GHOST = "registro_fantasma"
    UNLINKED = "carpeta_sin_enlazar"
    ORPHAN_FOLDER = "carpeta_huerfana"
    """Contenido sin `descriptor.mod` y sin ningun `.mod` que lo referencie.

    Es lo que queda cuando se borra un mod a medias: el descriptor desaparece
    y los archivos se quedan. Ni el juego ni el launcher los ven nunca.
    """


@dataclass(slots=True)
class CleanupItem:
    kind: CleanupKind
    mod: Mod
    paths: list[Path] = field(default_factory=list)
    """Lo que se borraria del disco."""

    unregister: bool = False
    """Si ademas hay que quitar su fila del registro del launcher."""

    size: int = 0
    reason: str = ""

    @property
    def is_safe(self) -> bool:
        """Si no se pierde contenido util al aplicarlo."""
        return self.kind in (CleanupKind.DANGLING, CleanupKind.GHOST)


def _directory_size(carpeta: Path) -> int:
    total = 0
    for elemento in carpeta.rglob("*"):
        try:
            if elemento.is_file():
                total += elemento.stat().st_size
        except OSError:
            continue
    return total


def _orphan_folders(mod_dir: Path, mods: list[Mod]) -> list[Path]:
    """Carpetas de `mod/` que no pertenecen a ningun mod conocido.

    No basta con mirar si tienen `descriptor.mod`: tambien hay que descartar
    las que algun `.mod` reclama con `path=`, aunque su descriptor interno
    falte.
    """
    if not mod_dir.is_dir():
        return []
    reclamadas = {
        mod.folder.resolve() for mod in mods if mod.folder is not None
    }
    huerfanas: list[Path] = []
    for hijo in sorted(mod_dir.iterdir()):
        if not hijo.is_dir() or hijo.resolve() in reclamadas:
            continue
        if (hijo / "descriptor.mod").is_file():
            # Tiene descriptor: es un mod sin enlazar, no un resto.
            continue
        huerfanas.append(hijo)
    return huerfanas


def plan_cleanup(
    mods: list[Mod],
    playsets: list[Playset],
    *,
    include_unlinked: bool = False,
    mod_dir: Path | None = None,
) -> list[CleanupItem]:
    """Propone que limpiar, sin tocar nada.

    `include_unlinked` incorpora las carpetas que el juego no ve, que es lo
    unico que puede contener trabajo que alguien quiera conservar.
    `mod_dir` permite ademas detectar carpetas huerfanas, que no aparecen como
    mods porque les falta el descriptor.
    """
    # Un mod referenciado por cualquier playset no se toca, ni desactivado:
    # desactivado hoy puede ser el que se reactive manana.
    en_uso = {entrada.uid for playset in playsets for entrada in playset.mods}

    plan: list[CleanupItem] = []
    for mod in mods:
        if mod.uid in en_uso:
            continue

        if mod.in_registry and not mod.on_disk:
            rutas = [mod.descriptor_path] if mod.descriptor_path else []
            plan.append(
                CleanupItem(
                    kind=CleanupKind.DANGLING if rutas else CleanupKind.GHOST,
                    mod=mod,
                    paths=[p for p in rutas if p and p.exists()],
                    unregister=True,
                    reason="el launcher lo lista pero su contenido no esta",
                )
            )
            continue

        if not mod.in_registry and not mod.on_disk and mod.descriptor_path:
            plan.append(
                CleanupItem(
                    kind=CleanupKind.DANGLING,
                    mod=mod,
                    paths=[mod.descriptor_path],
                    reason="descriptor que apunta a contenido inexistente",
                )
            )
            continue

        if include_unlinked and mod.registry_id is None and mod.folder:
            plan.append(
                CleanupItem(
                    kind=CleanupKind.UNLINKED,
                    mod=mod,
                    paths=[mod.folder],
                    size=_directory_size(mod.folder),
                    reason="carpeta sin .mod en mod/, el juego no la ve",
                )
            )

    if mod_dir is not None:
        for carpeta in _orphan_folders(mod_dir, mods):
            plan.append(
                CleanupItem(
                    kind=CleanupKind.ORPHAN_FOLDER,
                    mod=Mod(uid=f"fs:orphan:{carpeta.name}", name=carpeta.name, folder=carpeta),
                    paths=[carpeta],
                    size=_directory_size(carpeta),
                    reason="contenido sin descriptor; ni el juego ni el launcher lo ven",
                )
            )
    return plan


def execute_cleanup(
    items: list[CleanupItem],
    *,
    unregister: object | None = None,
) -> tuple[int, list[str]]:
    """Borra lo planificado y devuelve `(elementos borrados, errores)`.

    `unregister` es un invocable que recibe el uid del mod y lo quita del
    registro del launcher. Se pasa desde fuera para que este modulo no dependa
    de ningun backend.
    """
    borrados = 0
    errores: list[str] = []
    for item in items:
        fallo = False
        for ruta in item.paths:
            try:
                if ruta.is_dir():
                    shutil.rmtree(ruta)
                elif ruta.exists():
                    ruta.unlink()
            except OSError as exc:
                errores.append(f"{item.mod.name}: no se pudo borrar {ruta.name} ({exc})")
                fallo = True
        if item.unregister and unregister is not None and not fallo:
            try:
                unregister(item.mod.uid)  # type: ignore[operator]
            except Exception as exc:  # noqa: BLE001 - el backend decide su error
                errores.append(f"{item.mod.name}: no se pudo quitar del registro ({exc})")
                fallo = True
        if not fallo:
            borrados += 1
            _logger.info("borrado %s: %s", item.kind, item.mod.name)
    return borrados, errores
