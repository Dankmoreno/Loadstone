"""Ordenacion del orden de carga.

En los juegos de Paradox el ultimo mod gana: lo que carga despues sobrescribe
los archivos de lo que cargo antes. No hay `loadAfter` ni `loadBefore` como en
RimWorld, solo `dependencies`, que el launcher interpreta como "esto tiene que
cargar antes que yo".

Por eso el orden automatico aqui es deliberadamente conservador: respeta las
dependencias declaradas y, para todo lo demas, conserva el orden que el usuario
ya tenia. Reordenar mods que no se declaran nada entre si no mejora nada y
rompe configuraciones que funcionaban.
"""

from __future__ import annotations

from .matching import dependency_index, normalize
from .models import Mod, Playset, PlaysetMod

__all__ = ["CycleError", "minimal_moves", "sort_alphabetical", "sort_by_dependencies"]


def minimal_moves(before: list[str], after: list[str]) -> list[str]:
    """Mods que de verdad cambiaron de sitio entre dos ordenes.

    Comparar posicion por posicion exagera: mover un mod al final empuja una
    casilla a todos los que quedan detras y los contaria como movidos. El
    conjunto honesto es el complemento de la subsecuencia comun mas larga, que
    es la mayor parte de la lista que se puede dejar quieta.
    """
    rows, columns = len(before), len(after)
    lengths = [[0] * (columns + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(columns - 1, -1, -1):
            lengths[i][j] = (
                lengths[i + 1][j + 1] + 1
                if before[i] == after[j]
                else max(lengths[i + 1][j], lengths[i][j + 1])
            )
    kept: set[str] = set()
    i = j = 0
    while i < rows and j < columns:
        if before[i] == after[j]:
            kept.add(before[i])
            i += 1
            j += 1
        elif lengths[i + 1][j] >= lengths[i][j + 1]:
            i += 1
        else:
            j += 1
    return [uid for uid in after if uid not in kept]


class CycleError(ValueError):
    """Dos o mas mods se declaran dependientes en circulo."""

    def __init__(self, names: list[str]) -> None:
        super().__init__("dependencias circulares entre: " + ", ".join(names))
        self.names = names


def _ordered(playset: Playset) -> list[PlaysetMod]:
    return sorted(playset.mods, key=lambda entry: entry.position)


def sort_alphabetical(playset: Playset, mods: dict[str, Mod]) -> None:
    """Ordena por nombre visible, que es lo que hace el launcher en ese modo."""
    entries = sorted(
        playset.mods,
        key=lambda entry: (
            (mods[entry.uid].name if entry.uid in mods else entry.uid).strip().lower(),
            entry.uid,
        ),
    )
    for position, entry in enumerate(entries):
        entry.position = position


def sort_by_dependencies(playset: Playset, mods: dict[str, Mod]) -> list[str]:
    """Reordena para que cada mod cargue despues de sus dependencias.

    Usa el orden actual como criterio de desempate, asi que un playset que ya
    cumple las dependencias no se mueve. Devuelve los nombres de los mods que
    cambiaron de sitio. Si hay un ciclo, no toca nada y lanza `CycleError`.
    """
    entries = _ordered(playset)
    original = [entry.uid for entry in entries]
    rank = {uid: index for index, uid in enumerate(original)}

    # Solo los mods del playset cuentan como candidatos a dependencia: lo que
    # esta instalado pero fuera del playset no puede imponer un orden.
    in_playset = [mods[uid] for uid in original if uid in mods]
    by_name = {alias: mod.uid for alias, mod in dependency_index(in_playset).items()}

    # `dependents[a]` carga despues de `a`; grado = dependencias pendientes.
    dependents: dict[str, list[str]] = {uid: [] for uid in original}
    pending: dict[str, int] = {uid: 0 for uid in original}
    for uid in original:
        mod = mods.get(uid)
        if mod is None:
            continue
        for dependency in mod.dependencies:
            target = by_name.get(normalize(dependency))
            # Una dependencia ausente del playset no es asunto del ordenador;
            # `analysis.analyze` ya la reporta.
            if target is None or target == uid:
                continue
            dependents[target].append(uid)
            pending[uid] += 1

    ready = sorted((uid for uid, count in pending.items() if count == 0), key=rank.__getitem__)
    result: list[str] = []
    while ready:
        uid = ready.pop(0)
        result.append(uid)
        for dependent in dependents[uid]:
            pending[dependent] -= 1
            if pending[dependent] == 0:
                # Reinsertar manteniendo el orden original entre los listos.
                ready.append(dependent)
                ready.sort(key=rank.__getitem__)

    if len(result) != len(original):
        stuck = [uid for uid, count in pending.items() if count > 0]
        raise CycleError([mods[uid].name if uid in mods else uid for uid in stuck])

    by_uid = {entry.uid: entry for entry in entries}
    for position, uid in enumerate(result):
        by_uid[uid].position = position
    return [
        mods[uid].name if uid in mods else uid for uid in minimal_moves(original, result)
    ]
