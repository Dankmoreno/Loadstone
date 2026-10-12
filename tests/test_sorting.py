import pytest

from loadstone.core.models import Mod, Playset, PlaysetMod
from loadstone.core.sorting import (
    CycleError,
    minimal_moves,
    sort_alphabetical,
    sort_by_dependencies,
)


def make(uid: str, name: str, *dependencies: str) -> Mod:
    return Mod(uid=uid, name=name, dependencies=list(dependencies))


def playset_of(*uids: str) -> Playset:
    return Playset(
        id="p",
        name="p",
        mods=[PlaysetMod(uid=uid, position=index) for index, uid in enumerate(uids)],
    )


def order(playset: Playset) -> list[str]:
    return [entry.uid for entry in sorted(playset.mods, key=lambda e: e.position)]


def test_no_mueve_nada_si_ya_cumple_las_dependencias():
    mods = {"a": make("a", "Base"), "b": make("b", "Encima", "Base")}
    playset = playset_of("a", "b")
    assert sort_by_dependencies(playset, mods) == []
    assert order(playset) == ["a", "b"]


def test_mueve_el_dependiente_detras_de_su_dependencia():
    mods = {"a": make("a", "Base"), "b": make("b", "Encima", "Base")}
    playset = playset_of("b", "a")
    moved = sort_by_dependencies(playset, mods)
    assert order(playset) == ["a", "b"]
    assert moved == ["Encima"]


def test_conserva_el_orden_de_los_mods_sin_relacion():
    mods = {uid: make(uid, uid.upper()) for uid in ("x", "y", "z")}
    mods["z"] = make("z", "Z", "X")
    playset = playset_of("x", "y", "z")
    assert sort_by_dependencies(playset, mods) == []
    assert order(playset) == ["x", "y", "z"]


def test_dependencia_fuera_del_playset_se_ignora():
    # Instalado pero no incluido: no puede imponer orden. `analyze` lo reporta.
    mods = {"b": make("b", "Encima", "Base"), "a": make("a", "Base")}
    playset = playset_of("b")
    assert sort_by_dependencies(playset, mods) == []
    assert order(playset) == ["b"]


def test_dependencia_por_id_de_workshop():
    base = Mod(uid="a", name="Base", steam_id="123456")
    mods = {"a": base, "b": make("b", "Encima", "123456")}
    playset = playset_of("b", "a")
    sort_by_dependencies(playset, mods)
    assert order(playset) == ["a", "b"]


def test_ciclo_no_toca_el_playset():
    mods = {"a": make("a", "A", "B"), "b": make("b", "B", "A")}
    playset = playset_of("a", "b")
    with pytest.raises(CycleError) as error:
        sort_by_dependencies(playset, mods)
    assert order(playset) == ["a", "b"]
    assert set(error.value.names) == {"A", "B"}


def test_alfabetico_ignora_mayusculas():
    mods = {"a": make("a", "zeta"), "b": make("b", "Alfa")}
    playset = playset_of("a", "b")
    sort_alphabetical(playset, mods)
    assert order(playset) == ["b", "a"]


def test_minimal_moves_solo_cuenta_lo_reubicado():
    # Llevar "a" al final desplaza a los otros tres, pero movido esta uno solo.
    assert minimal_moves(["a", "b", "c", "d"], ["b", "c", "d", "a"]) == ["a"]
    assert minimal_moves(["a", "b"], ["a", "b"]) == []
