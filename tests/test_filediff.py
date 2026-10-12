"""Pruebas de la comparacion de contenidos entre mods en conflicto."""

from __future__ import annotations

from pathlib import Path

from loadstone.core.conflicts import Conflict
from loadstone.core.filediff import (
    compare_conflict,
    real_conflicts,
    unified_diff,
)
from loadstone.core.models import Mod

RUTA = "common/governments/00_gob.txt"


def _mod_con(raiz: Path, uid: str, contenido: bytes | str, ruta: str = RUTA) -> Mod:
    carpeta = raiz / uid
    archivo = carpeta / ruta
    archivo.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contenido, str):
        archivo.write_text(contenido, encoding="utf-8")
    else:
        archivo.write_bytes(contenido)
    return Mod(uid=uid, name=f"Mod {uid}", folder=carpeta, on_disk=True)


def test_dos_copias_iguales_no_son_un_conflicto_real(tmp_path):
    """El caso mas comun en una instalacion grande, y el que mas ruido mete."""
    texto = "democratic = { always = yes }\n"
    a = _mod_con(tmp_path, "a", texto)
    b = _mod_con(tmp_path, "b", texto)

    comparacion = compare_conflict(Conflict(path=RUTA, mods=[a, b]))

    assert comparacion.identicas
    assert comparacion.comparable
    assert len({v.digest for v in comparacion.versions}) == 1


def test_contenidos_distintos_si_son_conflicto(tmp_path):
    a = _mod_con(tmp_path, "a", "gobierno = { valor = 1 }\n")
    b = _mod_con(tmp_path, "b", "gobierno = { valor = 2 }\n")

    comparacion = compare_conflict(Conflict(path=RUTA, mods=[a, b]))
    assert not comparacion.identicas
    assert comparacion.winner.mod.uid == "b", "gana el ultimo del orden de carga"


def test_separar_los_reales_de_los_identicos(tmp_path):
    igual = "mismo contenido\n"
    a = _mod_con(tmp_path, "a", igual)
    b = _mod_con(tmp_path, "b", igual)
    c = _mod_con(tmp_path, "c", "otra cosa\n", ruta="common/otro.txt")
    d = _mod_con(tmp_path, "d", "distinta\n", ruta="common/otro.txt")

    reales, identicos = real_conflicts(
        [
            Conflict(path=RUTA, mods=[a, b]),
            Conflict(path="common/otro.txt", mods=[c, d]),
        ]
    )

    assert [x.path for x in identicos] == [RUTA]
    assert [x.path for x in reales] == ["common/otro.txt"]


def test_el_diff_ensena_que_gana_y_que_se_pierde(tmp_path):
    a = _mod_con(tmp_path, "a", "linea comun\nvalor = viejo\n")
    b = _mod_con(tmp_path, "b", "linea comun\nvalor = nuevo\n")

    comparacion = compare_conflict(Conflict(path=RUTA, mods=[a, b]))
    diff = unified_diff(comparacion.versions[0], comparacion.versions[1])

    assert diff is not None
    texto = "".join(diff)
    assert "-valor = viejo" in texto
    assert "+valor = nuevo" in texto
    assert "linea comun" in texto
    assert "(pierde)" in texto and "(gana)" in texto


def test_un_archivo_binario_no_tiene_diff(tmp_path):
    """Una textura o un modelo: no hay nada que ensenar linea a linea."""
    a = _mod_con(tmp_path, "a", b"\x89PNG\r\n\x1a\n\x00\x00\x00datos")
    b = _mod_con(tmp_path, "b", b"\x89PNG\r\n\x1a\n\x00\x00\x01otros")

    comparacion = compare_conflict(Conflict(path=RUTA, mods=[a, b]))
    assert not comparacion.identicas, "los bytes difieren"
    assert unified_diff(comparacion.versions[0], comparacion.versions[1]) is None


def test_un_archivo_que_falta_se_marca_como_no_disponible(tmp_path):
    a = _mod_con(tmp_path, "a", "algo\n")
    fantasma = Mod(uid="z", name="Sin contenido", folder=tmp_path / "no-existe")

    comparacion = compare_conflict(Conflict(path=RUTA, mods=[a, fantasma]))
    assert comparacion.versions[0].disponible
    assert not comparacion.versions[1].disponible
    assert not comparacion.comparable, "con una sola version no hay nada que comparar"
    assert not comparacion.identicas


def test_una_codificacion_rara_se_puede_seguir_comparando(tmp_path):
    """Los mods viejos traen cp1252, y sin esto se quedarian sin diff."""
    a = _mod_con(tmp_path, "a", "nombre = Espana\n".encode("cp1252"))
    b = _mod_con(tmp_path, "b", "nombre = Francia\n".encode("cp1252"))

    comparacion = compare_conflict(Conflict(path=RUTA, mods=[a, b]))
    diff = unified_diff(comparacion.versions[0], comparacion.versions[1])
    assert diff is not None
    assert any("Francia" in linea for linea in diff)


def test_tres_mods_con_dos_versiones_distintas(tmp_path):
    igual = "base\n"
    a = _mod_con(tmp_path, "a", igual)
    b = _mod_con(tmp_path, "b", igual)
    c = _mod_con(tmp_path, "c", "cambiado\n")

    comparacion = compare_conflict(Conflict(path=RUTA, mods=[a, b, c]))
    assert not comparacion.identicas
    assert comparacion.winner.mod.uid == "c"
    # Y entre los dos primeros no hay diferencia que ensenar.
    assert comparacion.versions[0].digest == comparacion.versions[1].digest


def test_las_mayusculas_de_la_ruta_no_impiden_encontrar_el_archivo(tmp_path):
    """`conflicts` normaliza a minusculas para poder comparar entre mods."""
    carpeta = tmp_path / "a"
    archivo = carpeta / "common" / "Governments" / "00_Gob.txt"
    archivo.parent.mkdir(parents=True)
    archivo.write_text("contenido\n", encoding="utf-8")
    mod = Mod(uid="a", name="Mod a", folder=carpeta, on_disk=True)

    comparacion = compare_conflict(
        Conflict(path="common/Governments/00_gob.txt", mods=[mod])
    )
    assert comparacion.versions[0].disponible
