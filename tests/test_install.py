import zipfile

import pytest

from loadstone.core.clausewitz import parse
from loadstone.core.descriptor import (
    Descriptor,
    dump_descriptor,
    load_descriptor,
    scan_mod_dir,
)
from loadstone.core.install import InstallError, install_mod
from loadstone.core.models import BackendKind, GameProfile

_DESCRIPTOR = (
    'name="Mi Mod"\n'
    'version="1.2"\n'
    'picture="thumbnail.jpg"\n'
    'remote_file_id="1087781345"\n'
    'tags={\n\t"Gameplay"\n\t"Balance"\n}\n'
    'supported_version="v4.5.*"\n'
)


@pytest.fixture
def game(tmp_path) -> GameProfile:
    data = tmp_path / "Stellaris"
    (data / "mod").mkdir(parents=True)
    return GameProfile(
        key="stellaris",
        display_name="Stellaris",
        game_id="stellaris",
        data_dir_name="Stellaris",
        steam_appid=281990,
        backend=BackendKind.LAUNCHER_V2,
        data_path=data,
        raw_version="v4.5.1",
        mods_compat_version="4.5",
    )


@pytest.fixture
def descargado(tmp_path):
    """Imita lo que deja SteamCMD en steamapps/workshop/content/<appid>/<id>."""
    source = tmp_path / "workshop" / "1087781345"
    (source / "common").mkdir(parents=True)
    (source / "descriptor.mod").write_text(_DESCRIPTOR, encoding="utf-8")
    (source / "common" / "x.txt").write_text("contenido", encoding="utf-8")
    (source / "thumbnail.jpg").write_bytes(b"\xff\xd8\xff")
    return source


def test_instala_desde_carpeta_y_lo_hace_visible(game, descargado):
    mod = install_mod(game, descargado, mod_id="1087781345", remote_file_id="1087781345")

    assert mod.registry_id == "mod/1087781345.mod"
    assert (game.mod_dir / "1087781345" / "common" / "x.txt").is_file()

    # El punto de todo esto: que el juego lo encuentre al escanear.
    encontrados = {found.name: found for found in scan_mod_dir(game.mod_dir, game.data_path)}
    assert encontrados["Mi Mod"].on_disk
    assert encontrados["Mi Mod"].registry_id == "mod/1087781345.mod"


def test_el_descriptor_generado_apunta_al_contenido(game, descargado):
    install_mod(game, descargado, mod_id="1087781345")
    escrito = load_descriptor(game.mod_dir / "1087781345.mod")

    assert escrito.path == (game.mod_dir / "1087781345").as_posix()
    assert escrito.name == "Mi Mod"
    assert escrito.tags == ["Gameplay", "Balance"]
    assert escrito.supported_version == "v4.5.*"
    assert escrito.remote_file_id == "1087781345"


def test_id_por_defecto_sale_del_workshop(game, descargado):
    mod = install_mod(game, descargado)
    assert mod.registry_id == "mod/1087781345.mod"


def test_sin_id_de_workshop_usa_el_nombre(game, tmp_path):
    source = tmp_path / "suelto"
    source.mkdir()
    (source / "descriptor.mod").write_text('name="Mod Sin Steam"\n', encoding="utf-8")
    mod = install_mod(game, source)
    assert mod.registry_id == "mod/mod_sin_steam.mod"


def test_instala_desde_zip_con_carpeta_contenedora(game, tmp_path, descargado):
    archivo = tmp_path / "mimod.zip"
    with zipfile.ZipFile(archivo, "w") as bundle:
        for item in descargado.rglob("*"):
            if item.is_file():
                bundle.write(item, f"MiMod/{item.relative_to(descargado).as_posix()}")

    mod = install_mod(game, archivo)
    assert (game.mod_dir / "1087781345" / "common" / "x.txt").is_file()
    assert mod.on_disk


def test_zip_con_ruta_insegura_se_rechaza(game, tmp_path):
    archivo = tmp_path / "malicioso.zip"
    with zipfile.ZipFile(archivo, "w") as bundle:
        bundle.writestr("../fuera.txt", "no deberia escribirse")
    with pytest.raises(InstallError, match="insegura"):
        install_mod(game, archivo)
    assert not (game.data_path.parent / "fuera.txt").exists()


def test_no_sobrescribe_sin_permiso(game, descargado):
    install_mod(game, descargado)
    with pytest.raises(InstallError, match="ya existe"):
        install_mod(game, descargado)
    install_mod(game, descargado, overwrite=True)


def test_origen_sin_descriptor(game, tmp_path):
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    with pytest.raises(InstallError, match="descriptor"):
        install_mod(game, vacio)


def test_dump_y_parse_son_simetricos():
    original = Descriptor(
        name='Con "comillas"',
        path="C:/mods/x",
        version="1.0",
        tags=["A", "B"],
        dependencies=["Otro"],
        replace_paths=["common/a", "common/b"],
        supported_version="v4.5.*",
        remote_file_id="123",
    )
    vuelta = Descriptor.from_block(parse(dump_descriptor(original)))
    assert vuelta == original
