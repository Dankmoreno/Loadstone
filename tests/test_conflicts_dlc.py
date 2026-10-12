"""Conflictos entre mods, DLC, lanzamiento del juego, notas y playsets."""

from __future__ import annotations

import json

import pytest

from loadstone.core.conflicts import find_conflicts, index_mod_files
from loadstone.core.dlc import scan_dlc
from loadstone.core.launch import read_launch_target
from loadstone.core.models import BackendKind, GameProfile, Mod, Playset, PlaysetMod
from loadstone.core.notes import Notes
from loadstone.core.playsets import export_playset, import_playset, read_playset_file


def hacer_mod(raiz, nombre, archivos, **extra) -> Mod:
    carpeta = raiz / nombre.replace(" ", "_")
    for relativa, contenido in archivos.items():
        destino = carpeta / relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")
    return Mod(
        uid=nombre,
        name=nombre,
        registry_id=f"mod/{nombre}.mod",
        folder=carpeta,
        on_disk=True,
        **extra,
    )


# ------------------------------------------------------------- conflictos


def test_detecta_el_archivo_compartido_y_quien_gana(tmp_path):
    primero = hacer_mod(tmp_path, "Primero", {"common/governments/00_gob.txt": "a"})
    segundo = hacer_mod(tmp_path, "Segundo", {"common/governments/00_gob.txt": "b"})

    informe = find_conflicts([primero, segundo])
    assert len(informe.conflicts) == 1
    conflicto = informe.conflicts[0]
    assert conflicto.path == "common/governments/00_gob.txt"
    # El ultimo de la lista es el que carga despues, y gana.
    assert conflicto.winner.name == "Segundo"
    assert [m.name for m in conflicto.losers] == ["Primero"]


def test_el_orden_decide_el_ganador(tmp_path):
    primero = hacer_mod(tmp_path, "Primero", {"common/x.txt": "a"})
    segundo = hacer_mod(tmp_path, "Segundo", {"common/x.txt": "b"})
    assert find_conflicts([segundo, primero]).conflicts[0].winner.name == "Primero"


def test_archivos_distintos_no_son_conflicto(tmp_path):
    uno = hacer_mod(tmp_path, "Uno", {"common/a.txt": "a"})
    dos = hacer_mod(tmp_path, "Dos", {"common/b.txt": "b"})
    assert find_conflicts([uno, dos]).conflicts == []


def test_los_descriptores_y_miniaturas_no_cuentan(tmp_path):
    uno = hacer_mod(tmp_path, "Uno", {"common/a.txt": "a", "descriptor.mod": "x"})
    dos = hacer_mod(tmp_path, "Dos", {"common/b.txt": "b", "descriptor.mod": "y"})
    assert find_conflicts([uno, dos]).conflicts == []


def test_solo_se_indexan_las_carpetas_del_juego(tmp_path):
    mod = hacer_mod(
        tmp_path,
        "Uno",
        {"common/a.txt": "a", "docs/manual.txt": "b", ".git/config": "c"},
    )
    assert index_mod_files(mod) == {"common/a.txt"}


def test_replace_path_se_marca(tmp_path):
    primero = hacer_mod(tmp_path, "Primero", {"common/governments/x.txt": "a"})
    segundo = hacer_mod(
        tmp_path,
        "Segundo",
        {"common/governments/x.txt": "b"},
        replace_paths=["common/governments"],
    )
    conflicto = find_conflicts([primero, segundo]).conflicts[0]
    assert conflicto.replaced


def test_resumen_por_parejas(tmp_path):
    primero = hacer_mod(tmp_path, "Primero", {"common/a.txt": "1", "common/b.txt": "1"})
    segundo = hacer_mod(tmp_path, "Segundo", {"common/a.txt": "2", "common/b.txt": "2"})
    assert find_conflicts([primero, segundo]).by_pair() == {("Primero", "Segundo"): 2}


# -------------------------------------------------------------------- DLC


def _instalacion_con_dlc(tmp_path, *, moderno: bool = False):
    install = tmp_path / "juego"
    carpeta = install / "dlc" / "dlc014_utopia"
    carpeta.mkdir(parents=True)
    if moderno:
        (carpeta / "dlc014_utopia.dlc.json").write_text(
            json.dumps(
                {"name": "utopia", "path": "dlc/dlc014_utopia", "pops_id": "utopia"}
            ),
            encoding="utf-8",
        )
    else:
        (carpeta / "dlc014.dlc").write_text(
            'name = "Utopia"\n'
            'archive = "dlc/dlc014_utopia/dlc014.zip"\n'
            'pops_id = "utopia"\n'
            'category = "expansion"\n',
            encoding="utf-8",
        )
    return install


def test_lee_un_dlc_clasico(tmp_path):
    dlc = scan_dlc(_instalacion_con_dlc(tmp_path))[0]
    assert dlc.id == "utopia"
    assert dlc.name == "Utopia"
    assert dlc.folder == "dlc/dlc014_utopia"
    assert dlc.is_expansion


def test_lee_el_formato_json_de_eu5(tmp_path):
    dlc = scan_dlc(_instalacion_con_dlc(tmp_path, moderno=True))[0]
    assert dlc.id == "utopia"
    assert dlc.folder == "dlc/dlc014_utopia"


def test_los_dos_formatos_juntos_no_duplican(tmp_path):
    install = _instalacion_con_dlc(tmp_path)
    carpeta = install / "dlc" / "dlc014_utopia"
    (carpeta / "dlc014_utopia.dlc.json").write_text(
        json.dumps({"name": "utopia", "path": "dlc/dlc014_utopia", "pops_id": "utopia"}),
        encoding="utf-8",
    )
    # Victoria 3 trae los dos en la misma carpeta y antes se contaba dos veces.
    assert len(scan_dlc(install)) == 1


def test_sin_instalacion_no_hay_dlc(tmp_path):
    assert scan_dlc(None) == []
    assert scan_dlc(tmp_path / "no_existe") == []


# ---------------------------------------------------------------- arrancar


def test_lee_el_ejecutable_de_launcher_settings(tmp_path):
    install = tmp_path / "juego"
    install.mkdir()
    (install / "stellaris.exe").write_bytes(b"MZ")
    (install / "launcher-settings.json").write_text(
        json.dumps({"exePath": "./stellaris.exe", "exeArgs": ["-gdpr-compliant"]}),
        encoding="utf-8",
    )
    juego = GameProfile(
        key="stellaris",
        display_name="Stellaris",
        game_id="stellaris",
        data_dir_name="Stellaris",
        steam_appid=281990,
        backend=BackendKind.LAUNCHER_V2,
        install_path=install,
    )
    objetivo = read_launch_target(juego)
    assert objetivo is not None
    assert objetivo.executable.name == "stellaris.exe"
    assert objetivo.arguments == ["-gdpr-compliant"]


def test_sin_launcher_settings_se_adivina(tmp_path):
    # Es el caso de EU5, que ya no trae launcher externo.
    install = tmp_path / "juego"
    install.mkdir()
    (install / "eu5.exe").write_bytes(b"MZ")
    (install / "unins000.exe").write_bytes(b"MZ")
    juego = GameProfile(
        key="eu5",
        display_name="Europa Universalis V",
        game_id="eu5",
        data_dir_name="Europa Universalis V",
        steam_appid=None,
        backend=BackendKind.PLAYSETS_JSON,
        install_path=install,
    )
    objetivo = read_launch_target(juego)
    assert objetivo is not None and objetivo.executable.name == "eu5.exe"


def test_sin_instalacion_no_hay_nada_que_arrancar():
    juego = GameProfile(
        key="x",
        display_name="X",
        game_id="x",
        data_dir_name="X",
        steam_appid=None,
        backend=BackendKind.LAUNCHER_V2,
    )
    assert read_launch_target(juego) is None


# ------------------------------------------------------------------ notas


def test_las_notas_se_guardan_y_se_releen():
    notas = Notes("stellaris")
    assert notas.set("mod/a.mod", "rompe los gobiernos")
    assert Notes("stellaris").get("mod/a.mod") == "rompe los gobiernos"


def test_una_nota_vacia_se_borra():
    notas = Notes("stellaris")
    notas.set("mod/a.mod", "algo")
    assert notas.set("mod/a.mod", "   ")
    assert Notes("stellaris").get("mod/a.mod") == ""
    assert len(Notes("stellaris")) == 0


def test_guardar_lo_mismo_no_cambia_nada():
    notas = Notes("stellaris")
    notas.set("mod/a.mod", "igual")
    assert not notas.set("mod/a.mod", "igual")


def test_las_notas_no_se_mezclan_entre_juegos():
    Notes("stellaris").set("mod/a.mod", "de stellaris")
    assert Notes("ck3").get("mod/a.mod") == ""


# --------------------------------------------------------------- playsets


def test_exportar_e_importar_conserva_orden_y_activaciones(tmp_path):
    mods = [
        Mod(uid="a", name="Alfa", registry_id="mod/a.mod"),
        Mod(uid="b", name="Beta", registry_id="mod/b.mod"),
    ]
    origen = Playset(
        id="p",
        name="Mi partida",
        mods=[
            PlaysetMod(uid="b", enabled=True, position=0),
            PlaysetMod(uid="a", enabled=False, position=1),
        ],
    )
    destino = tmp_path / "exportado.json"
    export_playset(origen, {m.uid: m for m in mods}, "stellaris", destino)

    archivo = read_playset_file(destino)
    assert archivo.name == "Mi partida"
    assert archivo.enabled_count == 1

    # En otra maquina los uid serian distintos: se casa por registry_id.
    otros = [
        Mod(uid="x1", name="Alfa", registry_id="mod/a.mod"),
        Mod(uid="x2", name="Beta", registry_id="mod/b.mod"),
    ]
    nuevo = Playset(id="q", name="Vacio")
    colocados, faltantes = import_playset(archivo, nuevo, otros)

    assert colocados == 2 and faltantes == []
    assert [(e.uid, e.enabled) for e in nuevo.mods] == [("x2", True), ("x1", False)]


def test_importar_avisa_de_lo_que_falta(tmp_path):
    mods = [Mod(uid="a", name="Alfa", registry_id="mod/a.mod")]
    origen = Playset(id="p", name="P", mods=[PlaysetMod(uid="a", position=0)])
    destino = tmp_path / "x.json"
    export_playset(origen, {m.uid: m for m in mods}, "stellaris", destino)

    nuevo = Playset(id="q", name="Q")
    colocados, faltantes = import_playset(read_playset_file(destino), nuevo, [])
    assert colocados == 0 and faltantes == ["Alfa"]


def test_un_json_cualquiera_no_es_un_playset(tmp_path):
    archivo = tmp_path / "otro.json"
    archivo.write_text('{"algo": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="no es un playset"):
        read_playset_file(archivo)
