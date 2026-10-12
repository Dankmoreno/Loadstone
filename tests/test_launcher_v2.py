"""Pruebas del backend launcher v2 contra una base sintetica.

El esquema reproduce las columnas que Loadstone consulta de la base real del
launcher (ver `docs/formatos.md`), de modo que estas pruebas no tocan nunca los
datos del juego instalado.
"""

import json
import sqlite3

import pytest

from loadstone.core.backends.base import BackendError
from loadstone.core.backends.launcher_v2 import LauncherV2Backend
from loadstone.core.models import BackendKind, GameProfile, LoadOrderMode

_SCHEMA = """
CREATE TABLE mods (
    id char(36) PRIMARY KEY, pdxId varchar(255), steamId varchar(255),
    remoteSteamId varchar(255),
    gameRegistryId text, name varchar(255), displayName varchar(255),
    version varchar(255), requiredVersion varchar(255), tags json DEFAULT '[]',
    dirPath text, archivePath text, status text, source text, size integer
);
CREATE TABLE mods_dependencies (
    modId char(36), modVersion varchar(255), dependencyType text,
    dependencyId char(36), dependencyVersion varchar(255), dependencyName varchar(255)
);
CREATE TABLE playsets (
    id char(36) PRIMARY KEY, name varchar(255) NOT NULL, isActive boolean,
    loadOrder varchar(255), createdOn datetime, updatedOn datetime,
    isRemoved boolean NOT NULL DEFAULT 0
);
CREATE TABLE playsets_mods (
    playsetId char(36), modId char(36), enabled boolean DEFAULT 1, position integer,
    FOREIGN KEY(playsetId) REFERENCES playsets(id) ON DELETE CASCADE,
    FOREIGN KEY(modId) REFERENCES mods(id) ON DELETE CASCADE
);
CREATE TABLE playsets_dlcs (
    playsetId char(36), dlcId text, enabled boolean NOT NULL DEFAULT 0,
    PRIMARY KEY (playsetId, dlcId)
);
"""


@pytest.fixture
def game(tmp_path) -> GameProfile:
    data = tmp_path / "Stellaris"
    mod_dir = data / "mod"
    mod_dir.mkdir(parents=True)

    for index, name in ((1, "Base"), (2, "Encima")):
        folder = mod_dir / f"mod{index}"
        folder.mkdir()
        (folder / "descriptor.mod").write_text(f'name="{name}"', encoding="utf-8")
        (mod_dir / f"mod{index}.mod").write_text(
            f'name="{name}"\npath="{folder.as_posix()}"\nsupported_version="v4.5.*"\n',
            encoding="utf-8",
        )

    connection = sqlite3.connect(data / "launcher-v2.sqlite")
    connection.executescript(_SCHEMA)
    connection.executemany(
        "INSERT INTO mods (id, gameRegistryId, displayName, requiredVersion, tags, "
        "dirPath, status, source) VALUES (?, ?, ?, ?, ?, ?, 'ready_to_play', 'local')",
        [
            ("uid-1", "mod/mod1.mod", "Base", "v4.5.*", '["Gameplay"]',
             str(mod_dir / "mod1")),
            ("uid-2", "mod/mod2.mod", "Encima", "v4.5.*", "[]", str(mod_dir / "mod2")),
        ],
    )
    connection.execute(
        "INSERT INTO mods_dependencies (modId, modVersion, dependencyType, dependencyId, "
        "dependencyName) VALUES ('uid-2', '1', 'required', 'uid-1', 'Base')"
    )
    connection.execute(
        "INSERT INTO playsets (id, name, isActive, loadOrder, createdOn) "
        "VALUES ('ps-1', 'Prueba', 1, 'custom', '2026-01-01 00:00:00')"
    )
    connection.executemany(
        "INSERT INTO playsets_mods (playsetId, modId, enabled, position) VALUES (?, ?, ?, ?)",
        [("ps-1", "uid-2", 1, 0), ("ps-1", "uid-1", 1, 1)],
    )
    connection.commit()
    connection.close()

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


def test_lee_mods_cruzando_registro_y_disco(game):
    mods = {mod.name: mod for mod in LauncherV2Backend(game).read_mods()}
    assert mods["Base"].in_registry and mods["Base"].on_disk
    assert mods["Base"].tags == ["Gameplay"]
    assert mods["Base"].registry_id == "mod/mod1.mod"
    assert mods["Encima"].dependencies == ["Base"]


def test_lee_playset_con_su_orden(game):
    playset = LauncherV2Backend(game).read_playsets()[0]
    assert playset.is_active and playset.load_order is LoadOrderMode.CUSTOM
    assert playset.enabled_uids() == ["uid-2", "uid-1"]


def test_guarda_el_orden_y_deja_copia(game):
    backend = LauncherV2Backend(game)
    playset = backend.read_playsets()[0]
    for entry in playset.mods:
        entry.position = 0 if entry.uid == "uid-1" else 1
    backend.save_playset(playset)

    assert backend.read_playsets()[0].enabled_uids() == ["uid-1", "uid-2"]
    assert list(game.data_path.glob("launcher-v2.sqlite.*.loadstone-backup"))


def test_apply_escribe_dlc_load_en_orden(game):
    backend = LauncherV2Backend(game)
    playset = backend.read_playsets()[0]
    written = backend.apply_to_game(playset)

    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["enabled_mods"] == ["mod/mod2.mod", "mod/mod1.mod"]
    assert payload["disabled_dlcs"] == []


def test_apply_conserva_los_dlc_desactivados(game):
    # Loadstone no gestiona DLC todavia: lo que haya en el archivo se respeta.
    dlc_load = game.data_path / "dlc_load.json"
    dlc_load.write_text(
        json.dumps({"disabled_dlcs": ["dlc/dlc001_x"], "enabled_mods": []}), encoding="utf-8"
    )
    backend = LauncherV2Backend(game)
    backend.apply_to_game(backend.read_playsets()[0])

    payload = json.loads(dlc_load.read_text(encoding="utf-8"))
    assert payload["disabled_dlcs"] == ["dlc/dlc001_x"]
    assert len(payload["enabled_mods"]) == 2


def test_mod_desactivado_no_llega_al_juego(game):
    backend = LauncherV2Backend(game)
    playset = backend.read_playsets()[0]
    for entry in playset.mods:
        entry.enabled = entry.uid == "uid-1"
    written = backend.apply_to_game(playset)

    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["enabled_mods"] == ["mod/mod1.mod"]


def test_no_guarda_mods_fuera_del_registro(game):
    backend = LauncherV2Backend(game)
    playset = backend.read_playsets()[0]
    playset.mods[0].uid = "fs:mod/inventado.mod"
    with pytest.raises(BackendError, match="registro"):
        backend.save_playset(playset)


def test_activar_un_playset_desactiva_el_resto(game):
    backend = LauncherV2Backend(game)
    second = backend.create_playset("Otro")
    backend.activate(second)
    activos = [p.name for p in backend.read_playsets() if p.is_active]
    assert activos == ["Otro"]


def test_base_ausente_da_mensaje_claro(game):
    (game.data_path / "launcher-v2.sqlite").unlink()
    with pytest.raises(BackendError, match="launcher"):
        LauncherV2Backend(game).read_mods()
