"""Pruebas del mod-parche que resuelve conflictos a mano."""

from __future__ import annotations

from pathlib import Path

import pytest

from loadstone.core.descriptor import load_descriptor
from loadstone.core.install import InstallError
from loadstone.core.merge import PatchSelection, build_patch_mod
from loadstone.core.models import BackendKind, GameProfile


@pytest.fixture
def juego(tmp_path: Path) -> GameProfile:
    datos = tmp_path / "Stellaris"
    (datos / "mod").mkdir(parents=True)
    return GameProfile(
        key="stellaris",
        display_name="Stellaris",
        game_id="stellaris",
        data_dir_name="Stellaris",
        steam_appid=281990,
        backend=BackendKind.LAUNCHER_V2,
        data_path=datos,
        raw_version="v4.5.1",
        mods_compat_version="4.5",
    )


def _archivo(raiz: Path, relativa: str, contenido: str) -> Path:
    ruta = raiz / relativa
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def test_el_parche_lleva_los_archivos_elegidos_en_su_ruta(juego, tmp_path):
    origen = _archivo(tmp_path / "mod-a", "common/governments/00_gob.txt", "elegido\n")
    seleccion = PatchSelection(
        path="common/governments/00_gob.txt", source=origen, mod_name="Mod A"
    )

    mod = build_patch_mod(juego, "Parche de prueba", [seleccion])

    destino = mod.folder / "common" / "governments" / "00_gob.txt"
    assert destino.is_file()
    assert destino.read_text(encoding="utf-8") == "elegido\n"


def test_el_descriptor_declara_la_version_del_juego(juego, tmp_path):
    """Sin esto, el launcher lo marca incompatible nada mas crearlo."""
    origen = _archivo(tmp_path / "a", "common/x.txt", "x\n")
    mod = build_patch_mod(
        juego, "Parche", [PatchSelection("common/x.txt", origen, "Mod A")]
    )

    descriptor = load_descriptor(mod.descriptor_path)
    assert descriptor.name == "Parche"
    assert descriptor.supported_version == "4.5"
    assert descriptor.path  # apunta al contenido ya instalado


def test_se_pueden_coger_archivos_de_mods_distintos(juego, tmp_path):
    """El caso que motiva todo esto: una version de aqui y otra de alla."""
    de_a = _archivo(tmp_path / "a", "common/uno.txt", "de A\n")
    de_b = _archivo(tmp_path / "b", "common/dos.txt", "de B\n")

    mod = build_patch_mod(
        juego,
        "Mezcla",
        [
            PatchSelection("common/uno.txt", de_a, "Mod A"),
            PatchSelection("common/dos.txt", de_b, "Mod B"),
        ],
    )

    assert (mod.folder / "common" / "uno.txt").read_text(encoding="utf-8") == "de A\n"
    assert (mod.folder / "common" / "dos.txt").read_text(encoding="utf-8") == "de B\n"


def test_sin_archivos_elegidos_no_se_crea_nada(juego):
    with pytest.raises(InstallError, match="ningun archivo elegido"):
        build_patch_mod(juego, "Vacio", [])


def test_un_archivo_que_desaparecio_se_salta_sin_tumbar_el_parche(juego, tmp_path):
    bueno = _archivo(tmp_path / "a", "common/bueno.txt", "sigue aqui\n")
    perdido = tmp_path / "a" / "common" / "ya-no-esta.txt"

    mod = build_patch_mod(
        juego,
        "Parche",
        [
            PatchSelection("common/bueno.txt", bueno, "Mod A"),
            PatchSelection("common/ya-no-esta.txt", perdido, "Mod B"),
        ],
    )

    assert (mod.folder / "common" / "bueno.txt").is_file()
    assert not (mod.folder / "common" / "ya-no-esta.txt").exists()


def test_si_no_queda_ningun_archivo_se_avisa(juego, tmp_path):
    perdido = tmp_path / "nada" / "x.txt"
    with pytest.raises(InstallError, match="sigue en disco"):
        build_patch_mod(juego, "Parche", [PatchSelection("x.txt", perdido, "Mod")])


def test_rehacer_el_parche_lo_sustituye(juego, tmp_path):
    primero = _archivo(tmp_path / "a", "common/x.txt", "primera\n")
    build_patch_mod(juego, "Parche", [PatchSelection("common/x.txt", primero, "A")])

    segundo = _archivo(tmp_path / "b", "common/x.txt", "segunda\n")
    mod = build_patch_mod(juego, "Parche", [PatchSelection("common/x.txt", segundo, "B")])

    assert (mod.folder / "common" / "x.txt").read_text(encoding="utf-8") == "segunda\n"


def test_el_nombre_se_convierte_en_un_id_de_carpeta_valido(juego, tmp_path):
    origen = _archivo(tmp_path / "a", "common/x.txt", "x\n")
    mod = build_patch_mod(
        juego, "Parche: UI + Gobiernos (v2)", [PatchSelection("common/x.txt", origen, "A")]
    )
    assert mod.folder.name.startswith("loadstone-")
    assert " " not in mod.folder.name
    assert ":" not in mod.folder.name
