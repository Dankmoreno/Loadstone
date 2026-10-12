from pathlib import Path

from loadstone.core.cleanup import CleanupKind, execute_cleanup, plan_cleanup
from loadstone.core.models import Mod, Playset, PlaysetMod


def test_descriptor_colgado_se_propone(tmp_path):
    descriptor = tmp_path / "colgado.mod"
    descriptor.write_text('name="Colgado"', encoding="utf-8")
    mod = Mod(
        uid="uid-1",
        name="Colgado",
        registry_id="mod/colgado.mod",
        descriptor_path=descriptor,
        in_registry=True,
        on_disk=False,
    )

    plan = plan_cleanup([mod], [])
    assert len(plan) == 1
    assert plan[0].kind is CleanupKind.DANGLING
    assert plan[0].unregister is True
    assert plan[0].is_safe


def test_registro_sin_descriptor_es_fantasma():
    mod = Mod(uid="uid-1", name="Fantasma", in_registry=True, on_disk=False)
    plan = plan_cleanup([mod], [])
    assert plan[0].kind is CleanupKind.GHOST
    assert plan[0].paths == []


def test_un_mod_en_un_playset_no_se_toca(tmp_path):
    mod = Mod(uid="uid-1", name="Colgado", in_registry=True, on_disk=False)
    # Desactivado, pero presente: manana puede volver.
    playset = Playset(id="p", name="P", mods=[PlaysetMod(uid="uid-1", enabled=False)])
    assert plan_cleanup([mod], [playset]) == []


def test_mod_sano_no_se_propone(tmp_path):
    carpeta = tmp_path / "bueno"
    carpeta.mkdir()
    mod = Mod(uid="uid-1", name="Bueno", registry_id="mod/bueno.mod",
              folder=carpeta, in_registry=True, on_disk=True)
    assert plan_cleanup([mod], []) == []


def test_carpeta_sin_enlazar_solo_si_se_pide(tmp_path):
    carpeta = tmp_path / "a_mano"
    carpeta.mkdir()
    (carpeta / "archivo.txt").write_text("hola", encoding="utf-8")
    mod = Mod(uid="fs:x", name="A mano", registry_id=None, folder=carpeta, on_disk=True)

    assert plan_cleanup([mod], []) == []
    plan = plan_cleanup([mod], [], include_unlinked=True)
    assert plan[0].kind is CleanupKind.UNLINKED
    assert plan[0].size == 4
    assert not plan[0].is_safe


def test_carpeta_huerfana_sin_descriptor(tmp_path):
    mod_dir = tmp_path / "mod"
    (mod_dir / "resto").mkdir(parents=True)
    (mod_dir / "resto" / "datos.txt").write_text("abc", encoding="utf-8")

    viva = mod_dir / "viva"
    viva.mkdir()
    (viva / "descriptor.mod").write_text('name="Viva"', encoding="utf-8")
    mod = Mod(uid="uid-1", name="Viva", registry_id="mod/viva.mod",
              folder=viva, in_registry=True, on_disk=True)

    plan = plan_cleanup([mod], [], mod_dir=mod_dir)
    assert [p.kind for p in plan] == [CleanupKind.ORPHAN_FOLDER]
    assert plan[0].mod.name == "resto"
    assert plan[0].size == 3


def test_carpeta_reclamada_por_un_mod_no_es_huerfana(tmp_path):
    mod_dir = tmp_path / "mod"
    carpeta = mod_dir / "reclamada"
    carpeta.mkdir(parents=True)
    # Sin descriptor.mod dentro, pero un .mod la referencia con path=.
    mod = Mod(uid="uid-1", name="Reclamada", registry_id="mod/reclamada.mod",
              folder=carpeta, in_registry=True, on_disk=True)
    assert plan_cleanup([mod], [], mod_dir=mod_dir) == []


def test_ejecutar_borra_y_desregistra(tmp_path):
    descriptor = tmp_path / "colgado.mod"
    descriptor.write_text("x", encoding="utf-8")
    mod = Mod(uid="uid-1", name="Colgado", descriptor_path=descriptor,
              in_registry=True, on_disk=False)

    desregistrados: list[str] = []
    borrados, errores = execute_cleanup(
        plan_cleanup([mod], []), unregister=desregistrados.append
    )

    assert borrados == 1
    assert errores == []
    assert not descriptor.exists()
    assert desregistrados == ["uid-1"]


def test_ejecutar_borra_carpetas_enteras(tmp_path):
    mod_dir = tmp_path / "mod"
    resto = mod_dir / "resto"
    (resto / "dentro").mkdir(parents=True)
    (resto / "dentro" / "a.txt").write_text("hola", encoding="utf-8")

    borrados, errores = execute_cleanup(plan_cleanup([], [], mod_dir=mod_dir))
    assert borrados == 1 and errores == []
    assert not resto.exists()


def test_un_error_al_borrar_se_reporta(tmp_path):
    mod = Mod(uid="uid-1", name="Raro", descriptor_path=Path(tmp_path / "no_existe.mod"),
              in_registry=True, on_disk=False)
    plan = plan_cleanup([mod], [])
    # El descriptor no existe, asi que no hay rutas: se desregistra igualmente.
    borrados, errores = execute_cleanup(plan, unregister=lambda uid: None)
    assert borrados == 1 and errores == []
