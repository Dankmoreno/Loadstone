from loadstone.core.versions import Compatibility, check_compatibility, parse_version


def test_parse_quita_la_v_y_parte_por_puntos():
    assert parse_version("v4.3.*") == ("4", "3", "*")
    assert parse_version("1.19.0.0") == ("1", "19", "0", "0")
    assert parse_version(None) == ()
    assert parse_version("") == ()


def test_comodin_acepta_cualquier_componente():
    assert check_compatibility("v4.*.*", "v4.5.1", "4.5") is Compatibility.OK
    assert check_compatibility("v*.*.*", "v4.5.1", "4.5") is Compatibility.OK


def test_minor_distinto_es_incompatible_en_stellaris():
    # modsCompatibilityVersion "4.5" => cuentan mayor y menor.
    assert check_compatibility("v4.3.*", "v4.5.1", "4.5") is Compatibility.MISMATCH


def test_parche_distinto_no_importa():
    assert check_compatibility("v4.5.0", "v4.5.1", "4.5") is Compatibility.OK


def test_ck3_solo_compara_la_mayor():
    # modsCompatibilityVersion "1" => a CK3 solo le importa la version mayor,
    # asi que un mod de 1.12 sigue siendo valido en 1.19.
    assert check_compatibility("1.12.5", "1.19.0.4", "1") is Compatibility.OK
    assert check_compatibility("2.0.0", "1.19.0.4", "1") is Compatibility.MISMATCH


def test_sin_datos_no_se_afirma_nada():
    assert check_compatibility(None, "v4.5.1", "4.5") is Compatibility.UNKNOWN
    assert check_compatibility("v4.5.*", None, "4.5") is Compatibility.UNKNOWN


def test_sin_compat_version_se_comparan_los_componentes_del_mod():
    assert check_compatibility("v4.3", "v4.3.9", None) is Compatibility.OK
    assert check_compatibility("v4.3.1", "v4.3.9", None) is Compatibility.MISMATCH
