"""Modelo de dominio de Loadstone.

Estos tipos no saben nada de sqlite, de JSON ni de Qt. Los backends traducen
desde el formato de cada juego hacia aqui, y la GUI consume solo esto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class BackendKind(StrEnum):
    """Como guarda el juego sus playsets."""

    LAUNCHER_V2 = "launcher_v2"
    """`launcher-v2.sqlite` + `dlc_load.json`: Stellaris, CK3, HOI4, EU4, V3."""

    PLAYSETS_JSON = "playsets_json"
    """`playsets.json` del gestor in-game: EU5 y lo que venga despues."""


class ModSource(StrEnum):
    LOCAL = "local"
    STEAM = "steam"
    PARADOX = "paradox"
    UNKNOWN = "unknown"


class LoadOrderMode(StrEnum):
    CUSTOM = "custom"
    ALPHABETICAL = "alphabetical"


@dataclass(slots=True)
class GameProfile:
    """Un juego concreto instalado en esta maquina."""

    key: str
    """Identificador corto de Loadstone: `stellaris`, `ck3`, `eu5`."""

    display_name: str
    game_id: str
    """`gameId` de `launcher-settings.json`, cuando el juego lo trae."""

    data_dir_name: str
    """Carpeta bajo `Documents/Paradox Interactive`."""

    steam_appid: int | None
    backend: BackendKind
    install_path: Path | None = None
    data_path: Path | None = None
    raw_version: str | None = None
    mods_compat_version: str | None = None

    @property
    def mod_dir(self) -> Path | None:
        """Carpeta donde viven los mods locales y sus `.mod`."""
        return self.data_path / "mod" if self.data_path else None

    @property
    def is_installed(self) -> bool:
        return self.install_path is not None

    @property
    def has_data_dir(self) -> bool:
        return self.data_path is not None and self.data_path.is_dir()


@dataclass(slots=True)
class Mod:
    """Un mod visto por Loadstone, venga del registro del launcher o del disco."""

    uid: str
    """Identidad estable dentro de un juego.

    Es el `id` de la base del launcher cuando el mod esta registrado, y
    `fs:<registry_id>` cuando solo existe en disco. Permite casar ambas
    fuentes sin inventar claves.
    """

    name: str
    registry_id: str | None = None
    """Ruta relativa que el juego lee, tal cual: `mod/1087781345.mod`."""

    descriptor_path: Path | None = None
    folder: Path | None = None
    archive: Path | None = None
    version: str | None = None
    supported_version: str | None = None
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    replace_paths: list[str] = field(default_factory=list)
    steam_id: str | None = None
    pdx_id: str | None = None
    source: ModSource = ModSource.UNKNOWN
    size: int | None = None
    in_registry: bool = False
    """Aparece en la base de datos del launcher."""

    on_disk: bool = False
    """Su contenido existe de verdad (carpeta o archivo comprimido)."""

    parse_error: str | None = None

    @property
    def is_archived(self) -> bool:
        return self.archive is not None

    @property
    def is_orphan(self) -> bool:
        """Esta en disco pero el launcher no lo conoce."""
        return self.on_disk and not self.in_registry

    @property
    def is_dangling(self) -> bool:
        """El launcher lo lista pero su contenido no esta."""
        return self.in_registry and not self.on_disk

    def __str__(self) -> str:
        return self.name or self.uid


@dataclass(slots=True)
class PlaysetMod:
    """Pertenencia de un mod a un playset, con su sitio en el orden."""

    uid: str
    enabled: bool = True
    position: int = 0


@dataclass(slots=True)
class Playset:
    """Una coleccion ordenada de mods."""

    id: str
    name: str
    is_active: bool = False
    load_order: LoadOrderMode = LoadOrderMode.CUSTOM
    mods: list[PlaysetMod] = field(default_factory=list)
    dlcs: dict[str, bool] = field(default_factory=dict)
    """`dlcId -> habilitado`. El juego los lee junto a los mods."""

    def enabled_uids(self) -> list[str]:
        """Uids habilitados en orden de carga: el primero carga primero."""
        return [m.uid for m in sorted(self.mods, key=lambda m: m.position) if m.enabled]

    def renumber(self) -> None:
        """Reasigna `position` 0..n-1 conservando el orden actual."""
        for index, mod in enumerate(sorted(self.mods, key=lambda m: m.position)):
            mod.position = index
