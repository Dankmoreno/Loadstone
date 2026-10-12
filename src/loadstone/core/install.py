"""Instalacion de un mod en la carpeta de datos del juego.

Es el eslabon que falta tanto despues de una descarga con SteamCMD como al
meter un mod a mano desde un zip: en los dos casos hay contenido con su
`descriptor.mod` en algun sitio, y el juego no lo vera hasta que exista un
`mod/<id>.mod` en la carpeta de datos que apunte a el.

Este modulo deja el contenido y el descriptor en su sitio. Darlo de alta en el
registro del launcher es cosa del backend, porque depende del juego.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path

from .clausewitz import ClausewitzError
from .descriptor import dump_descriptor, load_descriptor
from .logs import get_logger
from .models import GameProfile, Mod, ModSource

__all__ = ["InstallError", "install_mod"]

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


_logger = get_logger("install")


class InstallError(RuntimeError):
    """El origen no es un mod instalable, o el destino ya esta ocupado."""


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return slug or "mod"


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _find_mod_root(start: Path) -> Path:
    """Localiza la carpeta que contiene el `descriptor.mod`.

    Un zip puede traer el mod en la raiz o dentro de una carpeta contenedora,
    que es lo que produce comprimir desde el explorador de archivos.
    """
    if (start / "descriptor.mod").is_file():
        return start
    candidates = sorted(start.glob("*/descriptor.mod"))
    if len(candidates) == 1:
        return candidates[0].parent
    if len(candidates) > 1:
        raise InstallError(
            f"el origen contiene {len(candidates)} mods; extrae e instala uno a uno"
        )
    raise InstallError("no se encontro ningun descriptor.mod en el origen")


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            # Un zip puede traer rutas absolutas o `..` y escribir fuera del
            # destino. Se rechaza el archivo entero antes de extraer nada.
            target = Path(member)
            if target.is_absolute() or ".." in target.parts:
                raise InstallError(f"el zip contiene una ruta insegura: {member}")
        bundle.extractall(destination)


def install_mod(
    game: GameProfile,
    source: Path,
    *,
    mod_id: str | None = None,
    remote_file_id: str | None = None,
    overwrite: bool = False,
) -> Mod:
    """Copia un mod a `mod/<id>/` y escribe su `mod/<id>.mod`.

    `source` puede ser una carpeta o un `.zip`. `mod_id` fija el nombre que
    tendran la carpeta y el descriptor; si no se da, se usa el id del Workshop
    cuando exista y, en su defecto, el nombre del mod convertido en slug.
    """
    mod_dir = game.mod_dir
    if mod_dir is None:
        raise InstallError(f"{game.display_name}: sin carpeta de datos")
    if not source.exists():
        raise InstallError(f"no existe el origen: {source}")

    with tempfile.TemporaryDirectory(prefix="loadstone-") as temporary:
        if source.is_file():
            if source.suffix.lower() != ".zip":
                raise InstallError("solo se admiten carpetas o archivos .zip")
            staging = Path(temporary) / "contenido"
            staging.mkdir()
            _extract_zip(source, staging)
            root = _find_mod_root(staging)
        else:
            root = _find_mod_root(source)

        try:
            descriptor = load_descriptor(root / "descriptor.mod")
        except (ClausewitzError, OSError) as exc:
            raise InstallError(f"descriptor.mod ilegible: {exc}") from exc
        if not descriptor.name:
            raise InstallError("el descriptor no declara `name`")

        identifier = str(
            mod_id
            or remote_file_id
            or descriptor.remote_file_id
            or _slugify(descriptor.name)
        )
        target = mod_dir / identifier
        descriptor_file = mod_dir / f"{identifier}.mod"

        if target.exists() or descriptor_file.exists():
            if not overwrite:
                raise InstallError(
                    f"'{identifier}' ya existe en mod/. Usa sobrescribir para reemplazarlo."
                )
            if target.exists():
                shutil.rmtree(target)

        mod_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root, target, dirs_exist_ok=True)

        # El descriptor de `mod/` es el que lee el juego, y se distingue del
        # interno en que lleva `path` apuntando al contenido ya instalado.
        installed = replace(
            descriptor,
            path=target.as_posix(),
            archive=None,
            remote_file_id=remote_file_id or descriptor.remote_file_id,
        )
        descriptor_file.write_text(dump_descriptor(installed), encoding="utf-8")

    _logger.info("instalado '%s' en mod/%s", installed.name, identifier)
    return Mod(
        uid=f"fs:mod/{identifier}.mod",
        name=installed.name,
        registry_id=f"mod/{identifier}.mod",
        descriptor_path=descriptor_file,
        folder=target,
        version=installed.version,
        supported_version=installed.supported_version,
        tags=installed.tags,
        dependencies=installed.dependencies,
        replace_paths=installed.replace_paths,
        steam_id=installed.remote_file_id,
        source=ModSource.STEAM if installed.remote_file_id else ModSource.LOCAL,
        size=_directory_size(target),
        in_registry=False,
        on_disk=True,
    )
