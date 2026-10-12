import pytest

from loadstone.core.clausewitz import ClausewitzError, parse


def test_descriptor_tipico():
    block = parse(
        'name="Mod Menu"\n'
        'path="C:/mods/menu"\n'
        "tags={\n\t\"Utilities\"\n\t\"Mod Menu\"\n}\n"
        'supported_version="v4.3.*"\n'
    )
    assert block.get_str("name") == "Mod Menu"
    assert block.get_list("tags") == ["Utilities", "Mod Menu"]
    assert block.get_str("supported_version") == "v4.3.*"


def test_comentarios_y_llaves_en_la_misma_linea():
    block = parse('# cabecera\nname="X" # al final\ndependencies={ "A" "B" }\n')
    assert block.get_str("name") == "X"
    assert block.get_list("dependencies") == ["A", "B"]


def test_claves_repetidas_se_conservan():
    block = parse('replace_path="common/a"\nreplace_path="common/b"\n')
    assert block.get_all("replace_path") == ["common/a", "common/b"]


def test_primera_clave_gana():
    # El launcher se queda con la primera aparicion; `get` hace lo mismo.
    assert parse('name="uno"\nname="dos"\n').get_str("name") == "uno"


def test_valores_sin_comillas():
    block = parse("version=1.2.3\nenabled=yes\n")
    assert block.get_str("version") == "1.2.3"
    assert block.get_str("enabled") == "yes"


def test_lista_de_bloques_anonimos():
    block = parse("DLC={ { id=1 } { id=2 } }")
    inner = block.get("DLC")
    assert [sub.get_str("id") for _, sub in inner.entries] == ["1", "2"]


def test_escapes_en_cadenas():
    assert parse('name="co\\"milla"').get_str("name") == 'co"milla'


@pytest.mark.parametrize(
    "texto",
    [
        'name="sin cerrar\n',
        "tags={ \"A\"\n",
        'name="x"\n}\n',
        '="huerfano"\n',
    ],
)
def test_scripts_invalidos_informan_la_linea(texto):
    with pytest.raises(ClausewitzError) as error:
        parse(texto)
    assert "linea" in str(error.value)


def test_anidamiento_excesivo_no_revienta_la_pila():
    with pytest.raises(ClausewitzError):
        parse("a=" + "{" * 200 + "}" * 200)
