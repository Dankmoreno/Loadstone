"""Notas personales sobre cada mod.

Con doscientos mods, lo que se olvida no es cual esta activo sino *por que*:
que este rompe los gobiernos, que aquel hay que cargarlo despues del otro, que
el de mas alla se probo y no funciono. Esa informacion no vive en ningun sitio
del juego, asi que la guarda Loadstone.

Se indexan por `registry_id` (`mod/1087781345.mod`) y no por el `id` de la base
del launcher, porque ese identificador cambia si el launcher reconstruye su
base y la nota se perderia.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .atomic import atomic_write_json
from .logs import get_logger
from .paths import history_dir

__all__ = ["Notes"]

_logger = get_logger("notes")


def _notes_file(game_key: str) -> Path:
    # Junto al historial: ambos son datos del usuario sobre un juego concreto.
    return history_dir().parent / "notes" / f"{game_key}.json"


@dataclass(slots=True)
class Notes:
    """Las notas de un juego."""

    game_key: str
    path: Path = field(init=False)
    _data: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.path = _notes_file(self.game_key)
        self.reload()

    def reload(self) -> None:
        self._data = {}
        if not self.path.is_file():
            return
        try:
            datos = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _logger.warning("notas ilegibles en %s", self.path)
            return
        if isinstance(datos, dict):
            self._data = {
                str(k): str(v) for k, v in datos.items() if isinstance(v, str) and v.strip()
            }

    def get(self, registry_id: str | None) -> str:
        return self._data.get(registry_id, "") if registry_id else ""

    def set(self, registry_id: str | None, texto: str) -> bool:
        """Guarda o borra una nota. `True` si cambio algo."""
        if not registry_id:
            return False
        limpio = texto.strip()
        if limpio == self._data.get(registry_id, ""):
            return False
        if limpio:
            self._data[registry_id] = limpio
        else:
            self._data.pop(registry_id, None)
        atomic_write_json(self.path, self._data, indent=2, sort_keys=True)
        return True

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, registry_id: object) -> bool:
        return isinstance(registry_id, str) and registry_id in self._data
