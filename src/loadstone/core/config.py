"""Configuracion de Loadstone en disco.

Lo unico que Loadstone necesita recordar es donde buscar instalaciones que no
estan en una biblioteca de Steam, que es el caso de cualquier copia movida a
mano. La ruta la decide `paths`, que sigue la convencion de cada sistema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .atomic import atomic_write_json
from .paths import config_file, legacy_config_files

__all__ = ["Config", "config_path"]


def config_path() -> Path:
    return config_file()


@dataclass(slots=True)
class Config:
    extra_roots: list[Path] = field(default_factory=list)
    """Carpetas donde buscar instalaciones, ademas de las de Steam."""

    @classmethod
    def load(cls) -> Config:
        ruta = config_path()
        if not ruta.is_file():
            # El proyecto cambio de nombre dos veces y de convencion de
            # carpetas una. Si queda configuracion de antes se adopta, en vez
            # de que el usuario descubra sin explicacion que el programa ha
            # dejado de encontrar sus juegos.
            ruta = next(
                (vieja for vieja in legacy_config_files() if vieja.is_file()), ruta
            )
            if not ruta.is_file():
                return cls()
        try:
            data = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Una configuracion corrupta no debe impedir arrancar.
            return cls()
        roots = data.get("extra_roots") if isinstance(data, dict) else None
        return cls(extra_roots=[Path(r) for r in roots or [] if isinstance(r, str)])

    def save(self) -> Path:
        ruta = config_path()
        atomic_write_json(
            ruta, {"extra_roots": [str(root) for root in self.extra_roots]}, indent=2
        )
        return ruta

    def add_root(self, root: Path) -> bool:
        """Anade una carpeta de busqueda. Devuelve `False` si ya estaba."""
        resolved = root.expanduser()
        if any(existing == resolved for existing in self.extra_roots):
            return False
        self.extra_roots.append(resolved)
        return True
