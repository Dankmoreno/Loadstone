"""Backend del gestor in-game: `playsets.json`.

Es lo que usa Europa Universalis V, que ya no trae launcher externo ni
`launcher-v2.sqlite`. Toda la informacion vive en un JSON dentro de la carpeta
de datos del juego:

    {
      "file_version": "1.0.0",
      "playsets": [
        {
          "name": "Coleccion inicial",
          "isActive": true,
          "isAutomaticallySorted": true,
          "orderedListMods": [],
          "DLC": [{"paradoxAppId": "d000_shared", "isEnabled": false}]
        }
      ]
    }

Aviso sobre `orderedListMods`: en la instalacion con la que se escribio esto
estaba vacio, asi que la forma de sus elementos esta inferida, no confirmada.
El lector acepta tanto cadenas como objetos, y el escritor reutiliza la forma
que encontro al leer en vez de imponer una; si no hay ninguna de referencia y
hay mods que escribir, falla con un mensaje claro en lugar de corromper el
archivo del juego.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..atomic import atomic_write_json
from ..descriptor import scan_mod_dir
from ..models import BackendKind, GameProfile, LoadOrderMode, Mod, Playset, PlaysetMod
from .base import Backend, BackendError, backup_file

__all__ = ["PlaysetsJsonBackend"]

# Claves con las que un elemento de `orderedListMods` puede identificar un mod.
_ID_KEYS = ("gameRegistryId", "paradoxAppId", "id", "modId", "name", "path")
_ENABLED_KEYS = ("isEnabled", "enabled")


class PlaysetsJsonBackend(Backend):
    kind = BackendKind.PLAYSETS_JSON

    def __init__(self, game: GameProfile) -> None:
        super().__init__(game)
        assert game.data_path is not None  # garantizado por Backend
        self.playsets_path = game.data_path / "playsets.json"
        self._element_template: Any | None = None

    # ---------------------------------------------------------------- lectura

    def _load(self) -> dict:
        if not self.playsets_path.is_file():
            raise BackendError(
                f"{self.game.display_name}: falta {self.playsets_path.name}. "
                "Arranca el juego una vez para que lo cree."
            )
        try:
            data = json.loads(self.playsets_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackendError(f"{self.playsets_path.name} ilegible: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("playsets"), list):
            raise BackendError(f"{self.playsets_path.name} no tiene la forma esperada")
        return data

    def read_mods(self) -> list[Mod]:
        """Mods presentes en `mod/`.

        Este backend no tiene registro propio: el juego descubre los mods
        escaneando la carpeta, asi que el disco es la unica fuente de verdad.
        """
        mod_dir = self.game.mod_dir
        if not mod_dir or not mod_dir.is_dir():
            return []
        mods = scan_mod_dir(mod_dir, self.game.data_path)
        for mod in mods:
            # Sin base de datos intermedia, estar en disco es estar registrado.
            mod.in_registry = True
        return mods

    @staticmethod
    def _entry_uid(element: Any) -> str | None:
        if isinstance(element, str):
            return element
        if isinstance(element, dict):
            for key in _ID_KEYS:
                value = element.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    def _entry_enabled(element: Any) -> bool:
        if isinstance(element, dict):
            for key in _ENABLED_KEYS:
                if isinstance(element.get(key), bool):
                    return bool(element[key])
        return True

    def read_playsets(self) -> list[Playset]:
        data = self._load()
        playsets: list[Playset] = []
        for index, raw in enumerate(data["playsets"]):
            if not isinstance(raw, dict):
                continue
            entries: list[PlaysetMod] = []
            for position, element in enumerate(raw.get("orderedListMods") or []):
                uid = self._entry_uid(element)
                if uid is None:
                    continue
                if self._element_template is None:
                    self._element_template = element
                entries.append(
                    PlaysetMod(uid=uid, enabled=self._entry_enabled(element), position=position)
                )
            dlcs = {
                dlc["paradoxAppId"]: bool(dlc.get("isEnabled"))
                for dlc in raw.get("DLC") or []
                if isinstance(dlc, dict) and isinstance(dlc.get("paradoxAppId"), str)
            }
            playsets.append(
                Playset(
                    # El archivo no asigna ids, asi que el nombre hace de id.
                    # Es lo que la propia UI del juego usa para distinguirlos.
                    id=str(raw.get("name") or f"playset-{index}"),
                    name=str(raw.get("name") or f"Playset {index + 1}"),
                    is_active=bool(raw.get("isActive")),
                    load_order=(
                        LoadOrderMode.ALPHABETICAL
                        if raw.get("isAutomaticallySorted")
                        else LoadOrderMode.CUSTOM
                    ),
                    mods=entries,
                    dlcs=dlcs,
                )
            )
        return playsets

    # --------------------------------------------------------------- escritura

    def _build_element(self, entry: PlaysetMod) -> Any:
        """Crea un elemento de `orderedListMods` copiando la forma observada."""
        template = self._element_template
        if isinstance(template, str) or template is None:
            if not entry.enabled:
                # Una lista de cadenas no tiene donde guardar el apagado.
                raise BackendError(
                    "este formato de playsets.json no sabe representar mods "
                    "desactivados; quita el mod del playset en vez de apagarlo"
                )
            return entry.uid
        element = dict(template)
        for key in _ID_KEYS:
            if key in element:
                element[key] = entry.uid
                break
        else:
            element["name"] = entry.uid
        for key in _ENABLED_KEYS:
            if key in element:
                element[key] = entry.enabled
                break
        return element

    def _write(self, data: dict) -> None:
        backup_file(self.playsets_path)
        # El motor escribe este archivo con tabuladores; conservar el formato
        # evita que comparar la version propia con la del juego sea ilegible.
        atomic_write_json(self.playsets_path, data, indent="\t")

    def _find(self, data: dict, playset_id: str) -> dict:
        for raw in data["playsets"]:
            if isinstance(raw, dict) and str(raw.get("name")) == playset_id:
                return raw
        raise BackendError(f"no existe el playset '{playset_id}'")

    def save_playset(self, playset: Playset) -> None:
        playset.renumber()
        data = self._load()
        # `_load` no rellena la plantilla; leer primero deja ver la forma real.
        self.read_playsets()
        raw = self._find(data, playset.id)
        raw["orderedListMods"] = [
            self._build_element(entry) for entry in sorted(playset.mods, key=lambda m: m.position)
        ]
        raw["isAutomaticallySorted"] = playset.load_order is LoadOrderMode.ALPHABETICAL
        self._write(data)

    def activate(self, playset_id: str) -> None:
        data = self._load()
        target = self._find(data, playset_id)
        for raw in data["playsets"]:
            if isinstance(raw, dict):
                raw["isActive"] = raw is target
        self._write(data)

    def apply_to_game(self, playset: Playset) -> Path | None:
        """Aqui no hay segundo archivo: el juego lee `playsets.json` directamente."""
        self.save_playset(playset)
        self.activate(playset.id)
        return self.playsets_path
