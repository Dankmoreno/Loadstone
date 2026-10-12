"""Comparacion de versiones al estilo del launcher de Paradox.

Un mod declara `supported_version="v4.3.*"` y el juego trae
`rawVersion: "v4.5.1"`. Lo que no es obvio es cuanta precision cuenta: el
launcher la saca de `modsCompatibilityVersion`, que vale `4.5` en Stellaris
(importan mayor y menor) pero `1` en CK3 (solo importa la mayor). Comparar
siempre todos los componentes marcaria como incompatibles casi todos los mods
de CK3, asi que la profundidad se toma de ese campo cuando esta disponible.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Compatibility", "check_compatibility", "parse_version"]


class Compatibility(StrEnum):
    OK = "ok"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"
    """Falta el dato del mod o del juego: no se afirma nada."""


def parse_version(raw: str | None) -> tuple[str, ...]:
    """Parte `"v4.3.*"` en `("4", "3", "*")`. Devuelve vacio si no hay nada util."""
    if not raw:
        return ()
    text = raw.strip().lstrip("vV")
    if not text:
        return ()
    return tuple(part.strip() for part in text.split(".") if part.strip())


def check_compatibility(
    supported_version: str | None,
    game_version: str | None,
    compat_version: str | None = None,
) -> Compatibility:
    """Compara la version soportada por un mod con la del juego.

    `compat_version` es `modsCompatibilityVersion` de `launcher-settings.json`
    y fija cuantos componentes se comparan. Un `*` en cualquier posicion acepta
    lo que haya, y si al mod le faltan componentes se asume que no le importan.
    """
    mod_parts = parse_version(supported_version)
    game_parts = parse_version(game_version)
    if not mod_parts or not game_parts:
        return Compatibility.UNKNOWN

    depth = len(parse_version(compat_version)) or len(mod_parts)
    depth = min(depth, len(mod_parts), len(game_parts))
    if depth == 0:
        return Compatibility.UNKNOWN

    for mod_part, game_part in zip(mod_parts[:depth], game_parts[:depth]):
        if mod_part == "*" or game_part == "*":
            continue
        if mod_part != game_part:
            return Compatibility.MISMATCH
    return Compatibility.OK
