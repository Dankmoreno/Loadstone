"""Diagnostico de una coleccion de mods.

Nada de esto impide jugar por si mismo; son las cosas que el launcher no dice y
que explican la mayoria de los arranques fallidos: entradas que apuntan a
carpetas borradas, mods invisibles para el juego, versiones de otra actualizacion
y dependencias que no estan donde deberian.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from .matching import dependency_index, normalize, suggest_similar
from .models import GameProfile, Mod, Playset
from .versions import Compatibility, check_compatibility

__all__ = ["Issue", "IssueKind", "Severity", "analyze"]


class Severity(StrEnum):
    ERROR = "error"
    """Rompe la carga o deja el mod fuera sin avisar."""

    WARNING = "warning"
    """Probablemente funcione, pero no es lo que el usuario cree."""

    INFO = "info"


class IssueKind(StrEnum):
    DANGLING = "dangling"
    ORPHAN = "orphan"
    UNLINKED = "unlinked"
    PARSE_ERROR = "parse_error"
    VERSION_MISMATCH = "version_mismatch"
    MISSING_DEPENDENCY = "missing_dependency"
    DISABLED_DEPENDENCY = "disabled_dependency"
    DEPENDENCY_ORDER = "dependency_order"
    DUPLICATE = "duplicate"


@dataclass(slots=True)
class Issue:
    kind: IssueKind
    severity: Severity
    message: str
    mod_uid: str | None = None

    def __str__(self) -> str:
        return f"[{self.severity}] {self.message}"


def analyze(
    game: GameProfile,
    mods: list[Mod],
    playset: Playset | None = None,
) -> list[Issue]:
    """Revisa los mods y, si se pasa un playset, tambien su orden y activaciones."""
    issues: list[Issue] = []
    by_uid = {mod.uid: mod for mod in mods}
    by_name = dependency_index(mods)

    for mod in mods:
        if mod.parse_error:
            issues.append(
                Issue(
                    IssueKind.PARSE_ERROR,
                    Severity.ERROR,
                    f"'{mod.name}': descriptor ilegible ({mod.parse_error})",
                    mod.uid,
                )
            )
        if mod.is_dangling:
            issues.append(
                Issue(
                    IssueKind.DANGLING,
                    Severity.ERROR,
                    f"'{mod.name}': el launcher lo lista pero su contenido no esta en disco",
                    mod.uid,
                )
            )
        elif mod.registry_id is None and mod.on_disk:
            issues.append(
                Issue(
                    IssueKind.UNLINKED,
                    Severity.WARNING,
                    f"'{mod.name}': carpeta sin .mod en mod/, el juego no la ve",
                    mod.uid,
                )
            )
        elif mod.is_orphan:
            issues.append(
                Issue(
                    IssueKind.ORPHAN,
                    Severity.INFO,
                    f"'{mod.name}': en disco pero no registrado en el launcher",
                    mod.uid,
                )
            )

        if check_compatibility(
            mod.supported_version, game.raw_version, game.mods_compat_version
        ) is Compatibility.MISMATCH:
            issues.append(
                Issue(
                    IssueKind.VERSION_MISMATCH,
                    Severity.WARNING,
                    f"'{mod.name}': hecho para {mod.supported_version}, "
                    f"el juego esta en {game.raw_version}",
                    mod.uid,
                )
            )

    for steam_id, count in Counter(
        mod.steam_id for mod in mods if mod.steam_id
    ).items():
        if count > 1:
            issues.append(
                Issue(
                    IssueKind.DUPLICATE,
                    Severity.WARNING,
                    f"{count} copias del mismo mod del Workshop (id {steam_id})",
                )
            )

    if playset is None:
        return issues

    positions = {entry.uid: entry.position for entry in playset.mods}
    enabled_uids = set(playset.enabled_uids())
    for entry in sorted(playset.mods, key=lambda m: m.position):
        if not entry.enabled:
            continue
        mod = by_uid.get(entry.uid)
        if mod is None:
            continue
        for dependency in mod.dependencies:
            target = by_name.get(normalize(dependency))
            if target is None:
                # "No esta instalado" es cierto pero no accionable. Casi
                # siempre el mod esta, con otro nombre: una version en el
                # titulo, un prefijo, o una errata de quien lo declaro.
                parecidos = suggest_similar(dependency, mods, limite=1)
                pista = ""
                if parecidos:
                    similar, puntuacion = parecidos[0]
                    # Afirmar que es el mismo mod seria pasarse: lo honesto es
                    # decir que se le parece y cuanto, y que decida el usuario.
                    pista = (
                        f". Lo mas parecido que tienes instalado es "
                        f"'{similar.name}' ({puntuacion:.0f}% de parecido)"
                    )
                issues.append(
                    Issue(
                        IssueKind.MISSING_DEPENDENCY,
                        Severity.ERROR,
                        f"'{mod.name}' necesita '{dependency}', "
                        f"que no esta instalado{pista}",
                        mod.uid,
                    )
                )
            elif target.uid not in enabled_uids:
                issues.append(
                    Issue(
                        IssueKind.DISABLED_DEPENDENCY,
                        Severity.ERROR,
                        f"'{mod.name}' necesita '{target.name}', que esta en el "
                        "playset pero desactivado",
                        mod.uid,
                    )
                )
            elif positions.get(target.uid, -1) > entry.position:
                issues.append(
                    Issue(
                        IssueKind.DEPENDENCY_ORDER,
                        Severity.WARNING,
                        f"'{mod.name}' carga antes de '{target.name}', del que depende",
                        mod.uid,
                    )
                )
    return issues
