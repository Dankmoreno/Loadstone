"""Pruebas del comando `loadstone uninstall`.

Lo que importa aqui no es el formato de la salida sino las dos garantias que
hacen seguro un borrado irreversible desde una consola: que sin `--write` no
se toque nada, y que un texto ambiguo pare el comando en vez de llevarse por
delante nueve mods que nadie nombro.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from loadstone.cli import main
from loadstone.core.models import (
    BackendKind,
    GameProfile,
    Mod,
    Playset,
    PlaysetMod,
)


class _BackendFalso:
    def __init__(self, mods: list[Mod], playsets: list[Playset]) -> None:
        self._mods, self._playsets = mods, playsets
        self.guardados: list[Playset] = []
        self.quitados: list[str] = []

    def read_mods(self) -> list[Mod]:
        return list(self._mods)

    def read_playsets(self) -> list[Playset]:
        return list(self._playsets)

    def save_playset(self, playset: Playset) -> None:
        self.guardados.append(playset)

    def unregister_mod(self, uid: str) -> bool:
        self.quitados.append(uid)
        return True


@pytest.fixture
def entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    datos = tmp_path / "Stellaris"
    mod_dir = datos / "mod"
    mod_dir.mkdir(parents=True)

    mods = []
    for uid, nombre in (("a", "Alpha Mod"), ("b", "Beta Mod"), ("c", "Beta Mod Extra")):
        carpeta = mod_dir / uid
        carpeta.mkdir()
        (carpeta / "datos.txt").write_text("x" * 1024, encoding="utf-8")
        descriptor = mod_dir / f"{uid}.mod"
        descriptor.write_text(f'name="{nombre}"', encoding="utf-8")
        mods.append(
            Mod(
                uid=uid,
                name=nombre,
                descriptor_path=descriptor,
                folder=carpeta,
                in_registry=True,
                on_disk=True,
            )
        )

    playset = Playset(
        id="p1",
        name="Lista",
        mods=[PlaysetMod(uid="a", position=0), PlaysetMod(uid="b", position=1)],
    )
    juego = GameProfile(
        key="stellaris",
        display_name="Stellaris",
        game_id="stellaris",
        data_dir_name="Stellaris",
        steam_appid=281990,
        backend=BackendKind.LAUNCHER_V2,
        data_path=datos,
    )
    backend = _BackendFalso(mods, [playset])

    monkeypatch.setattr("loadstone.cli._pick_game", lambda args: juego)
    monkeypatch.setattr("loadstone.cli.get_backend", lambda g: backend)
    return juego, backend, mods, playset


def test_sin_write_no_se_borra_nada(entorno, capsys):
    _juego, backend, mods, playset = entorno

    codigo = main(["uninstall", "--game", "stellaris", "Alpha"])

    assert codigo == 0
    assert mods[0].folder.exists(), "la simulacion ha borrado contenido"
    assert backend.quitados == []
    assert len(playset.mods) == 2
    salida = capsys.readouterr().out
    assert "1 mod(s) a desinstalar" in salida
    assert "simulacion" in salida


def test_un_texto_ambiguo_para_el_comando(entorno):
    """'Beta' casa con dos mods; borrar el que no era no tiene vuelta atras."""
    with pytest.raises(SystemExit) as fallo:
        main(["uninstall", "--game", "stellaris", "Beta"])
    assert "casa con 2 mods" in str(fallo.value)


def test_all_matches_acepta_la_ambiguedad_a_proposito(entorno, capsys):
    codigo = main(["uninstall", "--game", "stellaris", "Beta", "--all-matches"])
    assert codigo == 0
    assert "2 mod(s) a desinstalar" in capsys.readouterr().out


def test_un_texto_que_no_casa_con_nada_falla(entorno):
    with pytest.raises(SystemExit) as fallo:
        main(["uninstall", "--game", "stellaris", "no existe este mod"])
    assert "no encuentro" in str(fallo.value)


def test_con_write_borra_y_limpia_los_playsets(entorno, capsys):
    _juego, backend, mods, playset = entorno

    codigo = main(["uninstall", "--game", "stellaris", "Alpha", "--write"])

    assert codigo == 0
    assert not mods[0].folder.exists()
    assert not mods[0].descriptor_path.exists()
    assert backend.quitados == ["a"]
    # Sale del playset, y el que queda se renumera.
    assert [(e.uid, e.position) for e in playset.mods] == [("b", 0)]
    assert len(backend.guardados) == 1
    assert "1 mod(s) desinstalados" in capsys.readouterr().out
    # Los vecinos no se tocan.
    assert mods[1].folder.exists()


def test_se_puede_nombrar_por_uid_exacto(entorno, capsys):
    main(["uninstall", "--game", "stellaris", "b"])
    # 'b' como uid es exacto y no se confunde con los dos 'Beta Mod'.
    assert "1 mod(s) a desinstalar" in capsys.readouterr().out


def test_el_mismo_mod_nombrado_dos_veces_cuenta_una(entorno, capsys):
    main(["uninstall", "--game", "stellaris", "a", "Alpha"])
    assert "1 mod(s) a desinstalar" in capsys.readouterr().out


def test_el_ciclo_completo_desinstalar_listar_y_devolver(entorno, capsys, tmp_path):
    """Lo que de verdad importa: que se pueda deshacer desde la consola."""
    _juego, _backend, mods, _playset = entorno

    main(["uninstall", "--game", "stellaris", "Alpha", "--write"])
    assert not mods[0].folder.exists()
    capsys.readouterr()

    main(["quarantine"])
    listado = capsys.readouterr().out
    assert "1 mod(s) apartados" in listado
    assert "Alpha Mod" in listado

    main(["quarantine", "--restore", "Alpha"])
    devuelto = capsys.readouterr().out
    assert "1 mod(s) devueltos" in devuelto
    assert (mods[0].folder / "datos.txt").exists()

    main(["quarantine"])
    assert "la papelera esta vacia" in capsys.readouterr().out


def test_devolver_algo_que_no_esta_apartado_falla(entorno):
    with pytest.raises(SystemExit) as fallo:
        main(["quarantine", "--restore", "no existe"])
    assert "no hay nada apartado" in str(fallo.value)


def test_vaciar_la_papelera_es_definitivo(entorno, capsys):
    _juego, _backend, mods, _playset = entorno
    main(["uninstall", "--game", "stellaris", "Alpha", "--write"])
    capsys.readouterr()

    main(["quarantine", "--empty"])
    assert "1 entrada(s) borradas" in capsys.readouterr().out

    main(["quarantine"])
    assert "la papelera esta vacia" in capsys.readouterr().out
    assert not mods[0].folder.exists()
