"""Pruebas de `required_mods`: que hace falta para que un mod funcione."""

from __future__ import annotations

from loadstone.core.matching import required_mods
from loadstone.core.models import Mod


def _mod(uid: str, nombre: str, depende_de: list[str] | None = None) -> Mod:
    return Mod(uid=uid, name=nombre, dependencies=depende_de or [], on_disk=True)


def test_encuentra_una_dependencia_instalada_que_falta_en_la_lista():
    base = _mod("b", "UI Overhaul Dynamic")
    parche = _mod("p", "Parche de UI", ["UI Overhaul Dynamic"])

    faltan = required_mods([parche], [base, parche], ya_presentes={"p"})
    assert [m.uid for m in faltan] == ["b"]


def test_sigue_la_cadena_entera_y_no_un_solo_nivel():
    """Quedarse a medias deja el mismo error con otro nombre."""
    biblioteca = _mod("lib", "Biblioteca")
    parche = _mod("p", "Parche", ["Biblioteca"])
    mod = _mod("m", "Mod Grande", ["Parche"])

    faltan = required_mods([mod], [mod, parche, biblioteca], ya_presentes={"m"})
    assert [m.uid for m in faltan] == ["p", "lib"]


def test_lo_que_ya_esta_en_la_lista_no_se_propone():
    base = _mod("b", "Biblioteca")
    mod = _mod("m", "Mod", ["Biblioteca"])

    assert required_mods([mod], [mod, base], ya_presentes={"m", "b"}) == []


def test_pero_se_siguen_sus_dependencias_igualmente():
    """Estar en la lista no garantiza que lo suyo tambien lo este."""
    profunda = _mod("d", "Profunda")
    base = _mod("b", "Biblioteca", ["Profunda"])
    mod = _mod("m", "Mod", ["Biblioteca"])

    faltan = required_mods([mod], [mod, base, profunda], ya_presentes={"m", "b"})
    assert [m.uid for m in faltan] == ["d"]


def test_una_dependencia_que_no_se_tiene_no_se_inventa():
    """El descriptor solo da un nombre; buscarlo en el Workshop pide clave API."""
    mod = _mod("m", "Mod", ["Algo Que No Tengo"])
    assert required_mods([mod], [mod], ya_presentes={"m"}) == []


def test_un_ciclo_no_cuelga_la_resolucion():
    a = _mod("a", "A", ["B"])
    b = _mod("b", "B", ["A"])

    faltan = required_mods([a], [a, b], ya_presentes={"a"})
    assert [m.uid for m in faltan] == ["b"]


def test_se_resuelve_tambien_por_id_del_workshop():
    """Los autores copian a mano, y a veces ponen el id en vez del nombre."""
    base = Mod(uid="b", name="Biblioteca", steam_id="1234567", on_disk=True)
    mod = _mod("m", "Mod", ["1234567"])

    faltan = required_mods([mod], [mod, base], ya_presentes={"m"})
    assert [m.uid for m in faltan] == ["b"]


def test_varias_semillas_no_repiten_la_misma_dependencia():
    base = _mod("b", "Biblioteca")
    uno = _mod("1", "Uno", ["Biblioteca"])
    dos = _mod("2", "Dos", ["Biblioteca"])

    faltan = required_mods([uno, dos], [uno, dos, base], ya_presentes={"1", "2"})
    assert [m.uid for m in faltan] == ["b"]


def test_sin_dependencias_no_propone_nada():
    solo = _mod("s", "Mod Solitario")
    assert required_mods([solo], [solo], ya_presentes={"s"}) == []
