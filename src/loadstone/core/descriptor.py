"""Lectura de descriptores de mods y escaneo de la carpeta `mod/`.

El juego solo ve los `.mod` que estan directamente en `mod/`: cada uno apunta
con `path=` a una carpeta o con `archive=` a un `.zip`. Dentro de la carpeta hay
un `descriptor.mod` casi identico, que es el que el autor del mod empaqueta.
Cuando los dos existen, el de `mod/` manda, porque es el que el juego lee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .clausewitz import Block, ClausewitzError, parse, read_text
from .models import Mod, ModSource

__all__ = [
    "Descriptor",
    "dump_descriptor",
    "load_descriptor",
    "scan_mod_dir",
    "steam_id_from_filename",
]


@dataclass(slots=True)
class Descriptor:
    """Contenido de un `.mod`, ya normalizado."""

    name: str = ""
    path: str | None = None
    archive: str | None = None
    picture: str | None = None
    remote_file_id: str | None = None
    supported_version: str | None = None
    version: str | None = None
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    replace_paths: list[str] = field(default_factory=list)
    user_dir: str | None = None

    @classmethod
    def from_block(cls, block: Block) -> Descriptor:
        return cls(
            name=block.get_str("name") or "",
            path=block.get_str("path"),
            archive=block.get_str("archive"),
            picture=block.get_str("picture"),
            remote_file_id=block.get_str("remote_file_id"),
            supported_version=block.get_str("supported_version"),
            version=block.get_str("version"),
            tags=block.get_list("tags"),
            dependencies=block.get_list("dependencies"),
            replace_paths=[v for v in block.get_all("replace_path") if isinstance(v, str)],
            user_dir=block.get_str("user_dir"),
        )


def load_descriptor(path: Path) -> Descriptor:
    """Parsea un descriptor del disco. Propaga `ClausewitzError` si esta roto."""
    return Descriptor.from_block(parse(read_text(path)))


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump_descriptor(descriptor: Descriptor) -> str:
    """Serializa un descriptor en el formato que escribe el propio launcher.

    El orden de las claves y los tabuladores dentro de los bloques imitan a los
    `.mod` que genera Paradox: asi un descriptor escrito por Loadstone no se
    distingue de uno suyo en un diff.
    """
    lines: list[str] = []
    if descriptor.path:
        lines.append(f"path={_quote(descriptor.path)}")
    if descriptor.archive:
        lines.append(f"archive={_quote(descriptor.archive)}")
    lines.append(f"name={_quote(descriptor.name)}")
    if descriptor.version:
        lines.append(f"version={_quote(descriptor.version)}")
    if descriptor.picture:
        lines.append(f"picture={_quote(descriptor.picture)}")
    if descriptor.remote_file_id:
        lines.append(f"remote_file_id={_quote(descriptor.remote_file_id)}")
    for key, values in (("tags", descriptor.tags), ("dependencies", descriptor.dependencies)):
        if values:
            lines.append(f"{key}={{")
            lines.extend(f"\t{_quote(value)}" for value in values)
            lines.append("}")
    for replace_path in descriptor.replace_paths:
        lines.append(f"replace_path={_quote(replace_path)}")
    if descriptor.supported_version:
        lines.append(f"supported_version={_quote(descriptor.supported_version)}")
    if descriptor.user_dir:
        lines.append(f"user_dir={_quote(descriptor.user_dir)}")
    return "\n".join(lines) + "\n"


def _resolve(raw: str | None, data_path: Path) -> Path | None:
    """Convierte una ruta de descriptor en `Path`.

    Los descriptores usan barras normales y suelen ser absolutas, pero las
    escritas a mano vienen relativas al directorio de datos del juego
    (`mod/mi_mod`), asi que se admiten ambas.
    """
    if not raw:
        return None
    candidate = Path(raw.replace("\\", "/"))
    if not candidate.is_absolute():
        candidate = data_path / candidate
    return candidate


def _guess_source(descriptor: Descriptor) -> ModSource:
    # Sin acceso al registro del launcher, `remote_file_id` es la unica pista:
    # lo pone el Workshop de Steam al publicar.
    return ModSource.STEAM if descriptor.remote_file_id else ModSource.LOCAL


def steam_id_from_filename(nombre: str) -> str | None:
    """Deduce el id del Workshop del nombre de un descriptor.

    El launcher nombra los `.mod` de los mods suscritos con el id delante:
    `1087781345.mod`, o `2458656056_255_tradition_slots.mod`. Es la ultima
    oportunidad de identificarlos cuando el descriptor no trae
    `remote_file_id` y la base del launcher tampoco lo guardo.
    """
    raiz = nombre.rsplit("/", 1)[-1].removesuffix(".mod")
    digitos = raiz.split("_", 1)[0]
    # Los ids del Workshop son largos; exigirlo evita confundir con un mod
    # local que empiece por un numero corto.
    return digitos if digitos.isdigit() and len(digitos) >= 6 else None


def scan_mod_dir(mod_dir: Path, data_path: Path | None = None) -> list[Mod]:
    """Devuelve todos los mods visibles en `mod_dir`.

    Incluye tres casos que el launcher trata distinto y que conviene distinguir
    en la UI:

    - `.mod` con contenido presente: el caso normal.
    - `.mod` cuyo `path`/`archive` ya no existe: entrada colgada.
    - carpeta con `descriptor.mod` pero sin `.mod` en `mod/`: el juego no la ve,
      tipicamente un mod descomprimido a mano.
    """
    if not mod_dir.is_dir():
        return []
    base = data_path or mod_dir.parent
    mods: list[Mod] = []
    claimed: set[Path] = set()

    for descriptor_file in sorted(mod_dir.glob("*.mod")):
        registry_id = f"mod/{descriptor_file.name}"
        parse_error: str | None = None
        try:
            descriptor = load_descriptor(descriptor_file)
        except (ClausewitzError, OSError) as exc:
            descriptor = Descriptor(name=descriptor_file.stem)
            parse_error = str(exc)

        folder = _resolve(descriptor.path, base)
        archive = _resolve(descriptor.archive, base)
        if folder is not None:
            claimed.add(folder)
        on_disk = bool((folder and folder.is_dir()) or (archive and archive.is_file()))

        mods.append(
            Mod(
                uid=f"fs:{registry_id}",
                name=descriptor.name or descriptor_file.stem,
                registry_id=registry_id,
                descriptor_path=descriptor_file,
                folder=folder if folder and folder.is_dir() else None,
                archive=archive if archive and archive.is_file() else None,
                version=descriptor.version,
                supported_version=descriptor.supported_version,
                tags=descriptor.tags,
                dependencies=descriptor.dependencies,
                replace_paths=descriptor.replace_paths,
                steam_id=descriptor.remote_file_id
                or steam_id_from_filename(descriptor_file.name),
                source=_guess_source(descriptor),
                on_disk=on_disk,
                parse_error=parse_error,
            )
        )

    # Carpetas con descriptor propio que ningun `.mod` reclama.
    for child in sorted(mod_dir.iterdir()):
        if not child.is_dir() or child in claimed:
            continue
        inner = child / "descriptor.mod"
        if not inner.is_file():
            continue
        try:
            descriptor = load_descriptor(inner)
            parse_error = None
        except (ClausewitzError, OSError) as exc:
            descriptor = Descriptor(name=child.name)
            parse_error = str(exc)
        mods.append(
            Mod(
                uid=f"fs:unlinked:{child.name}",
                name=descriptor.name or child.name,
                registry_id=None,
                descriptor_path=inner,
                folder=child,
                version=descriptor.version,
                supported_version=descriptor.supported_version,
                tags=descriptor.tags,
                dependencies=descriptor.dependencies,
                replace_paths=descriptor.replace_paths,
                steam_id=descriptor.remote_file_id,
                source=_guess_source(descriptor),
                on_disk=True,
                parse_error=parse_error,
            )
        )
    return mods
