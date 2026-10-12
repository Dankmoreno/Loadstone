"""Pruebas del navegador del Workshop.

No abren Chromium ni tocan la red: lo que importa aqui es la cola y lo que la
ventana decide con lo que Steam contesta, no que una pagina pinte bien. Si
QtWebEngine no esta instalado el modulo entero se salta, porque es opcional
por diseno y el resto de la aplicacion tiene que seguir funcionando sin el.
"""

from __future__ import annotations

import pytest

from loadstone.core.models import BackendKind, GameProfile, Mod
from loadstone.core.workshop_api import WorkshopItem

pytest.importorskip("PySide6.QtWebEngineWidgets", reason="QtWebEngine no instalado")

from loadstone.gui.workshop import WorkshopBrowserDialog


class _BackendFalso:
    def __init__(self, mods: list[Mod]) -> None:
        self._mods = mods

    def read_mods(self) -> list[Mod]:
        return list(self._mods)


@pytest.fixture
def juego(tmp_path) -> GameProfile:
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
    )


@pytest.fixture
def navegador(qtbot, juego, tmp_path, monkeypatch):
    # El perfil persistente no debe escribir en la carpeta real del usuario.
    monkeypatch.setattr(
        "loadstone.gui.workshop.browser_profile_dir", lambda: tmp_path / "browser"
    )
    instalado = Mod(uid="a", name="Ya lo tengo", steam_id="111", on_disk=True)
    dialogo = WorkshopBrowserDialog(
        None, juego, _BackendFalso([instalado]), lambda: None
    )
    qtbot.addWidget(dialogo)
    return dialogo


def test_la_cola_empieza_vacia_y_el_boton_apagado(navegador):
    assert navegador._cola == {}
    assert not navegador.descargar_btn.isEnabled()
    assert not navegador.anadir_btn.isEnabled()


def test_encolar_un_mod_pone_su_nombre_real(navegador):
    navegador._anadidos(
        (["222"], {"222": WorkshopItem(item_id="222", title="Mod Nuevo")})
    )
    assert navegador._cola == {"222": "Mod Nuevo"}
    assert navegador.descargar_btn.isEnabled()
    assert navegador.descargar_btn.text() == "Descargar e instalar (1)"
    assert navegador.tabla.topLevelItem(0).text(1) == "Mod Nuevo"


def test_un_item_retirado_no_se_encola(navegador):
    """Si Steam dice que ya no esta, SteamCMD no lo va a poder bajar."""
    navegador._anadidos(
        (["999"], {"999": WorkshopItem(item_id="999", title="Borrado", available=False)})
    )
    assert navegador._cola == {}
    assert not navegador.descargar_btn.isEnabled()
    assert "ya no esta en el Workshop" in navegador.viendo.text()


def test_una_coleccion_entra_entera_y_avisa_de_los_caidos(navegador):
    navegador._anadidos(
        (
            ["1", "2", "3"],
            {
                "1": WorkshopItem(item_id="1", title="Uno"),
                "2": WorkshopItem(item_id="2", title="Dos"),
                "3": WorkshopItem(item_id="3", title="Tres", available=False),
            },
        )
    )
    assert list(navegador._cola) == ["1", "2"]
    assert "2 mods anadidos" in navegador.viendo.text()
    assert "1 ya no estan" in navegador.viendo.text()


def test_no_se_duplica_lo_que_ya_estaba_en_la_cola(navegador):
    detalle = {"222": WorkshopItem(item_id="222", title="Mod Nuevo")}
    navegador._anadidos((["222"], detalle))
    navegador._anadidos((["222"], detalle))
    assert len(navegador._cola) == 1
    assert navegador.tabla.topLevelItemCount() == 1


def test_lo_ya_instalado_se_encola_pero_marcado(navegador):
    navegador._anadidos(
        (["111"], {"111": WorkshopItem(item_id="111", title="Ya lo tengo")})
    )
    assert navegador._cola == {"111": "Ya lo tengo"}
    assert "reinstalara" in navegador.tabla.topLevelItem(0).toolTip(1)


def test_vaciar_deja_la_cola_como_al_principio(navegador):
    navegador._anadidos(
        (["1", "2"], {"1": WorkshopItem(item_id="1"), "2": WorkshopItem(item_id="2")})
    )
    assert len(navegador._cola) == 2
    navegador._vaciar()
    assert navegador._cola == {}
    assert navegador.tabla.topLevelItemCount() == 0
    assert not navegador.descargar_btn.isEnabled()


def test_solo_las_paginas_de_item_ofrecen_anadir(navegador):
    from PySide6.QtCore import QUrl

    navegador._on_url(QUrl("https://steamcommunity.com/app/281990/workshop/"))
    assert navegador._actual is None
    assert not navegador.anadir_btn.isEnabled()

    navegador._on_url(
        QUrl("https://steamcommunity.com/sharedfiles/filedetails/?id=1595876588")
    )
    assert navegador._actual == "1595876588"
    assert navegador.anadir_btn.isEnabled()


def test_el_prefijo_de_steam_no_ensucia_la_linea(navegador, monkeypatch):
    from PySide6.QtCore import QUrl

    monkeypatch.setattr(
        type(navegador.vista), "title", lambda self: "Steam Workshop::Mod Bonito"
    )
    navegador._on_url(
        QUrl("https://steamcommunity.com/sharedfiles/filedetails/?id=1087781345")
    )
    assert navegador.viendo.text().startswith("Mod Bonito (1087781345)")
