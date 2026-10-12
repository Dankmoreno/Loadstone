import pytest

from loadstone.core.models import Mod
from loadstone.core.search import SearchOptions, SearchScope, search_mods, select_scope


@pytest.fixture
def mods(tmp_path):
    uno = tmp_path / "uno"
    (uno / "common" / "governments").mkdir(parents=True)
    (uno / "common" / "governments" / "00_gobiernos.txt").write_text(
        "democratic_government = {\n    potential = { always = yes }\n}\n", encoding="utf-8"
    )
    (uno / "localisation").mkdir()
    (uno / "localisation" / "textos_l_spanish.yml").write_text(
        "democratic_government: Gobierno democratico\n", encoding="utf-8"
    )
    (uno / "gfx").mkdir()
    (uno / "gfx" / "icono.dds").write_bytes(b"DDS \x00\x00\x00binario democratic_government")

    dos = tmp_path / "dos"
    (dos / "common" / "governments").mkdir(parents=True)
    (dos / "common" / "governments" / "00_gobiernos.txt").write_text(
        "DEMOCRATIC_GOVERNMENT = { otra_cosa = 1 }\n", encoding="utf-8"
    )
    return [
        Mod(uid="a", name="Mod Uno", folder=uno),
        Mod(uid="b", name="Mod Dos", folder=dos),
    ]


def test_encuentra_en_los_dos_mods(mods):
    hits = search_mods(mods, SearchOptions(query="democratic_government"))
    assert {hit.mod.name for hit in hits} == {"Mod Uno", "Mod Dos"}


def test_distingue_mayusculas_cuando_se_pide(mods):
    hits = search_mods(mods, SearchOptions(query="democratic_government", case_sensitive=True))
    assert {hit.mod.name for hit in hits} == {"Mod Uno"}


def test_da_archivo_y_linea(mods):
    hit = search_mods(mods, SearchOptions(query="potential"))[0]
    assert hit.path.as_posix() == "common/governments/00_gobiernos.txt"
    assert hit.line_number == 2
    assert hit.line == "potential = { always = yes }"


def test_salta_traducciones_por_defecto(mods):
    assert not search_mods(mods, SearchOptions(query="Gobierno democratico"))
    con = search_mods(
        mods, SearchOptions(query="Gobierno democratico", skip_translations=False)
    )
    assert len(con) == 1


def test_ignora_binarios_aunque_la_extension_enganye(mods, tmp_path):
    # El .dds no entra por extension; y aunque entrara, el contenido es binario.
    opciones = SearchOptions(query="democratic_government", extensions=(".dds", ".txt"))
    hits = search_mods(mods, opciones)
    assert all(hit.path.suffix == ".txt" for hit in hits)


def test_busqueda_por_ruta(mods):
    hits = search_mods(mods, SearchOptions(query="common/governments", in_paths=True))
    assert len(hits) == 2
    assert all(hit.line_number == 0 for hit in hits)


def test_regex(mods):
    hits = search_mods(mods, SearchOptions(query=r"always\s*=\s*yes", regex=True))
    assert len(hits) == 1


def test_regex_invalida_avisa(mods):
    with pytest.raises(ValueError, match="invalida"):
        search_mods(mods, SearchOptions(query="[sin cerrar", regex=True))


def test_respeta_el_limite(mods):
    hits = search_mods(mods, SearchOptions(query="government", max_hits=1))
    assert len(hits) == 1


def test_consulta_vacia_no_busca(mods):
    assert search_mods(mods, SearchOptions(query="   ")) == []


def test_mod_sin_carpeta_no_rompe():
    assert search_mods([Mod(uid="x", name="Sin carpeta")], SearchOptions(query="algo")) == []


def test_filtrado_por_ambito(mods):
    activos = select_scope(mods, {"a"}, SearchScope.ACTIVE)
    assert [m.name for m in activos] == ["Mod Uno"]
    inactivos = select_scope(mods, {"a"}, SearchScope.INACTIVE)
    assert [m.name for m in inactivos] == ["Mod Dos"]
    assert len(select_scope(mods, {"a"}, SearchScope.ALL)) == 2
