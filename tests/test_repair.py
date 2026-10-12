"""Pruebas de la deteccion de mods que faltan en disco."""

from pathlib import Path

from loadstone.core.models import Mod
from loadstone.core.repair import plan_repair


def _registrado_sin_contenido(uid: str, nombre: str, steam: str | None) -> Mod:
    return Mod(uid=uid, name=nombre, steam_id=steam, in_registry=True, on_disk=False)


def test_un_mod_con_id_del_workshop_es_recuperable():
    plan = plan_repair([_registrado_sin_contenido("a", "Falta", "123456789")])
    assert [m.name for m in plan.recuperables] == ["Falta"]
    assert plan.perdidos == []
    assert plan.hay_algo_que_hacer
    assert plan.ids == ["123456789"]


def test_un_mod_sin_id_se_da_por_perdido():
    """Instalado a mano desde un zip: no dejo rastro de donde vino."""
    plan = plan_repair([_registrado_sin_contenido("a", "A mano", None)])
    assert plan.recuperables == []
    assert [m.name for m in plan.perdidos] == ["A mano"]
    assert not plan.hay_algo_que_hacer
    assert plan.total == 1


def test_los_mods_sanos_no_entran_en_el_plan(tmp_path: Path):
    carpeta = tmp_path / "bueno"
    carpeta.mkdir()
    sano = Mod(
        uid="a",
        name="Sano",
        folder=carpeta,
        steam_id="111111111",
        in_registry=True,
        on_disk=True,
    )
    assert plan_repair([sano]).total == 0


def test_el_contenido_que_el_launcher_no_conoce_no_es_cosa_de_aqui(tmp_path: Path):
    """Eso es un huerfano, lo recoge `cleanup`, y no se arregla descargando."""
    carpeta = tmp_path / "suelto"
    carpeta.mkdir()
    huerfano = Mod(uid="fs:x", name="Suelto", folder=carpeta, on_disk=True)
    assert plan_repair([huerfano]).total == 0


def test_los_ids_no_se_repiten():
    """Dos filas del launcher pueden apuntar al mismo item del Workshop."""
    mods = [
        _registrado_sin_contenido("a", "Uno", "999"),
        _registrado_sin_contenido("b", "Otra fila", "999"),
        _registrado_sin_contenido("c", "Dos", "888"),
    ]
    plan = plan_repair(mods)
    assert len(plan.recuperables) == 3
    assert plan.ids == ["999", "888"]


def test_una_instalacion_entera_perdida_se_separa_bien():
    """El caso real: la carpeta mod/ vaciada por completo."""
    mods = [_registrado_sin_contenido(f"u{i}", f"Mod {i}", str(100000 + i)) for i in range(200)]
    mods += [_registrado_sin_contenido("local", "Local", None)]

    plan = plan_repair(mods)
    assert plan.total == 201
    assert len(plan.recuperables) == 200
    assert len(plan.perdidos) == 1
    assert len(plan.ids) == 200


def test_sin_mods_no_hay_nada_que_reparar():
    plan = plan_repair([])
    assert plan.total == 0
    assert not plan.hay_algo_que_hacer
    assert plan.ids == []
