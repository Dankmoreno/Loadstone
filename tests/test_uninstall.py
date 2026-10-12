from pathlib import Path

import pytest

from loadstone.core.models import Mod, Playset, PlaysetMod
from loadstone.core.uninstall import execute_uninstall, plan_uninstall


def _mod_instalado(mod_dir: Path, nombre: str = "Bueno", uid: str = "uid-1") -> Mod:
    """Un mod sano y entero: carpeta con contenido mas su `.mod` en `mod/`."""
    carpeta = mod_dir / uid
    carpeta.mkdir(parents=True)
    (carpeta / "datos.txt").write_text("hola", encoding="utf-8")
    descriptor = mod_dir / f"{uid}.mod"
    descriptor.write_text(f'name="{nombre}"', encoding="utf-8")
    return Mod(
        uid=uid,
        name=nombre,
        registry_id=f"mod/{uid}.mod",
        descriptor_path=descriptor,
        folder=carpeta,
        in_registry=True,
        on_disk=True,
    )


def test_plan_mide_lo_que_borra_y_donde_esta(tmp_path):
    mod_dir = tmp_path / "mod"
    mod = _mod_instalado(mod_dir)
    playset = Playset(id="p1", name="Mi lista", mods=[PlaysetMod(uid="uid-1")])

    plan = plan_uninstall(mod, [playset], mod_dir=mod_dir)

    assert set(plan.paths) == {mod.folder, mod.descriptor_path}
    # Lo de la carpeta mas el propio descriptor: todo lo que deja de ocupar.
    assert plan.size == 4 + mod.descriptor_path.stat().st_size
    assert plan.unregister is True
    assert [p.id for p in plan.playsets] == ["p1"]
    assert not plan.is_steam_managed


def test_un_mod_desactivado_sigue_contando_como_en_el_playset(tmp_path):
    """A diferencia de `cleanup`, estar en un playset no protege: avisa."""
    mod_dir = tmp_path / "mod"
    mod = _mod_instalado(mod_dir)
    playset = Playset(id="p1", name="P", mods=[PlaysetMod(uid="uid-1", enabled=False)])

    plan = plan_uninstall(mod, [playset], mod_dir=mod_dir)
    assert len(plan.playsets) == 1


def test_contenido_de_steam_se_aparta_y_no_se_borra_por_defecto(tmp_path):
    mod_dir = tmp_path / "Documents" / "mod"
    mod_dir.mkdir(parents=True)
    # Lo tipico de un mod suscrito: el descriptor en la carpeta del juego, pero
    # el contenido donde lo deja Steam.
    steam = tmp_path / "steamapps" / "workshop" / "content" / "281990" / "123"
    steam.mkdir(parents=True)
    (steam / "datos.txt").write_text("abc", encoding="utf-8")
    descriptor = mod_dir / "123.mod"
    descriptor.write_text('name="Suscrito"', encoding="utf-8")
    mod = Mod(
        uid="uid-1",
        name="Suscrito",
        descriptor_path=descriptor,
        folder=steam,
        in_registry=True,
        on_disk=True,
    )

    plan = plan_uninstall(mod, [], mod_dir=mod_dir)
    assert plan.paths == [descriptor]
    assert plan.outside_paths == [steam]
    assert plan.is_steam_managed
    # El tamano solo cuenta lo que de verdad se libera.
    assert plan.size == descriptor.stat().st_size

    execute_uninstall([plan])
    assert not descriptor.exists()
    assert steam.exists(), "lo de Steam no se toca sin pedirlo"

    execute_uninstall([plan], include_outside=True)
    assert not steam.exists()


def test_execute_borra_disco_playsets_y_registro(tmp_path):
    mod_dir = tmp_path / "mod"
    mod = _mod_instalado(mod_dir)
    otro = _mod_instalado(mod_dir, nombre="Otro", uid="uid-2")
    playset = Playset(
        id="p1",
        name="P",
        mods=[PlaysetMod(uid="uid-1", position=0), PlaysetMod(uid="uid-2", position=1)],
    )

    guardados: list[Playset] = []
    quitados: list[str] = []
    plan = plan_uninstall(mod, [playset], mod_dir=mod_dir)

    hechos, errores = execute_uninstall(
        [plan],
        save_playset=guardados.append,
        unregister=lambda uid: bool(quitados.append(uid)) or True,
    )

    assert (hechos, errores) == (1, [])
    assert not mod.folder.exists()
    assert not mod.descriptor_path.exists()
    assert quitados == ["uid-1"]
    # El playset se guarda una vez, ya sin el mod y renumerado.
    assert len(guardados) == 1
    assert [(e.uid, e.position) for e in playset.mods] == [("uid-2", 0)]
    # El vecino no se toca.
    assert otro.folder.exists()


def test_un_playset_compartido_se_guarda_una_sola_vez(tmp_path):
    mod_dir = tmp_path / "mod"
    uno = _mod_instalado(mod_dir, nombre="Uno", uid="uid-1")
    dos = _mod_instalado(mod_dir, nombre="Dos", uid="uid-2")
    playset = Playset(
        id="p1",
        name="P",
        mods=[PlaysetMod(uid="uid-1", position=0), PlaysetMod(uid="uid-2", position=1)],
    )

    guardados: list[Playset] = []
    planes = [plan_uninstall(m, [playset], mod_dir=mod_dir) for m in (uno, dos)]
    hechos, errores = execute_uninstall(planes, save_playset=guardados.append)

    assert (hechos, errores) == (2, [])
    assert len(guardados) == 1
    assert playset.mods == []


def test_si_el_playset_no_se_puede_guardar_no_se_borra_nada(tmp_path):
    """Dejar el contenido fuera y la referencia dentro es el peor estado."""
    mod_dir = tmp_path / "mod"
    mod = _mod_instalado(mod_dir)
    playset = Playset(id="p1", name="P", mods=[PlaysetMod(uid="uid-1")])

    def guardar_falla(_playset: Playset) -> None:
        raise RuntimeError("la base del launcher esta ocupada")

    plan = plan_uninstall(mod, [playset], mod_dir=mod_dir)
    hechos, errores = execute_uninstall([plan], save_playset=guardar_falla)

    assert hechos == 0
    assert "ocupada" in errores[0]
    assert mod.folder.exists(), "el disco no se toca si los playsets no cedieron"


def test_un_fallo_de_borrado_no_arrastra_a_los_demas(tmp_path, monkeypatch):
    """Sin papelera: aqui se comprueba la via que borra de verdad."""
    mod_dir = tmp_path / "mod"
    malo = _mod_instalado(mod_dir, nombre="Malo", uid="uid-1")
    bueno = _mod_instalado(mod_dir, nombre="Bueno", uid="uid-2")

    real = Path.unlink

    def unlink_selectivo(self, *args, **kwargs):
        if self.name == "uid-1.mod":
            raise OSError("en uso por otro proceso")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink_selectivo)

    planes = [plan_uninstall(m, [], mod_dir=mod_dir) for m in (malo, bueno)]
    hechos, errores = execute_uninstall(planes, quarantine=False)

    assert hechos == 1
    assert len(errores) == 1 and "Malo" in errores[0]
    assert not bueno.folder.exists()


def test_el_registro_no_se_quita_si_el_disco_fallo(tmp_path, monkeypatch):
    """Sin contenido pero con fila, `cleanup` lo repara. Al reves, no.

    Tambien sin papelera: con ella el contenido se mueve y no se borra, asi que
    un `unlink` roto no es el fallo que se quiere provocar.
    """
    mod_dir = tmp_path / "mod"
    mod = _mod_instalado(mod_dir)
    monkeypatch.setattr(
        Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("bloqueado"))
    )

    quitados: list[str] = []
    plan = plan_uninstall(mod, [], mod_dir=mod_dir)
    hechos, errores = execute_uninstall(
        [plan], unregister=quitados.append, quarantine=False
    )

    assert hechos == 0
    assert errores
    assert quitados == []


def test_un_mod_sin_nada_en_disco_sigue_saliendo_del_registro(tmp_path):
    """El caso del mod ya medio borrado a mano: queda la fila y poco mas."""
    mod = Mod(uid="uid-1", name="Resto", in_registry=True, on_disk=False)

    quitados: list[str] = []
    plan = plan_uninstall(mod, [], mod_dir=tmp_path)
    assert plan.paths == []
    assert plan.size == 0

    hechos, errores = execute_uninstall([plan], unregister=quitados.append)
    assert (hechos, errores) == (1, [])
    assert quitados == ["uid-1"]


@pytest.mark.parametrize("sin_mod_dir", [True, False])
def test_sin_mod_dir_nada_se_considera_de_fuera(tmp_path, sin_mod_dir):
    """Sin carpeta de referencia no se puede decidir que es de Steam."""
    mod_dir = tmp_path / "mod"
    mod = _mod_instalado(mod_dir)
    plan = plan_uninstall(mod, [], mod_dir=None if sin_mod_dir else mod_dir)
    assert plan.outside_paths == []
