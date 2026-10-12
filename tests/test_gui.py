"""Pruebas de la interfaz con pytest-qt.

Antes esto se comprobaba con scripts sueltos en una carpeta temporal, que se
perdian en cuanto terminaba la sesion. Aqui los widgets se construyen con datos
sinteticos, sin depender de que haya juegos de Paradox instalados en la maquina
que ejecuta las pruebas.
"""

from __future__ import annotations

import pytest

from loadstone.core.models import BackendKind, GameProfile, Mod, Playset, PlaysetMod
from loadstone.core.search import SearchScope
from loadstone.core.updates import UpdateState, UpdateStatus
from loadstone.core.workshop_api import WorkshopItem
from loadstone.gui.dialogs import (
    CleanupDialog,
    HistoryDialog,
    SearchDialog,
    UninstallDialog,
    UpdatesDialog,
)


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
        raw_version="v4.5.1",
        mods_compat_version="4.5",
    )


def _crear(carpeta):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "descriptor.mod").write_text('name="x"', encoding="utf-8")
    return carpeta


@pytest.fixture
def mods(juego) -> list[Mod]:
    carpeta = juego.mod_dir / "uno"
    (carpeta / "common" / "governments").mkdir(parents=True)
    (carpeta / "common" / "governments" / "00_gob.txt").write_text(
        "democratic_government = { always = yes }\n", encoding="utf-8"
    )
    return [
        Mod(
            uid="a",
            name="Mod Uno",
            registry_id="mod/uno.mod",
            folder=carpeta,
            steam_id="123456789",
            in_registry=True,
            on_disk=True,
        ),
        Mod(
            uid="b",
            name="Mod Dos",
            registry_id="mod/dos.mod",
            folder=_crear(juego.mod_dir / "dos"),
            in_registry=True,
            on_disk=True,
        ),
    ]


@pytest.fixture
def playset() -> Playset:
    return Playset(
        id="p",
        name="Prueba",
        mods=[PlaysetMod(uid="a", enabled=True, position=0)],
    )


def esperar(qtbot, condicion) -> None:
    qtbot.waitUntil(condicion, timeout=8000)


def test_busqueda_encuentra_y_agrupa_por_mod(qtbot, mods, playset):
    dialogo = SearchDialog(None, mods, playset)
    qtbot.addWidget(dialogo)

    dialogo.query.setText("democratic_government")
    dialogo.buscar()
    esperar(qtbot, lambda: dialogo.resultados.topLevelItemCount() == 1)

    padre = dialogo.resultados.topLevelItem(0)
    assert padre.text(0).startswith("Mod Uno")
    assert padre.childCount() == 1
    assert "00_gob.txt" in padre.child(0).text(0)
    assert "1 coincidencias en 1 mods" in dialogo.estado.text()


def test_busqueda_por_rutas(qtbot, mods, playset):
    dialogo = SearchDialog(None, mods, playset)
    qtbot.addWidget(dialogo)

    dialogo.query.setText("common/governments")
    dialogo.en_rutas.setChecked(True)
    dialogo.buscar()
    esperar(qtbot, lambda: dialogo.resultados.topLevelItemCount() == 1)
    assert dialogo.resultados.topLevelItem(0).childCount() == 1


def test_busqueda_vacia_no_hace_nada(qtbot, mods, playset):
    dialogo = SearchDialog(None, mods, playset)
    qtbot.addWidget(dialogo)
    dialogo.query.setText("   ")
    dialogo.buscar()
    assert dialogo.resultados.topLevelItemCount() == 0


def test_ambito_restringe_a_los_activos(qtbot, mods, playset):
    dialogo = SearchDialog(None, mods, playset)
    qtbot.addWidget(dialogo)
    indice = dialogo.scope.findData(SearchScope.INACTIVE)
    dialogo.scope.setCurrentIndex(indice)
    dialogo.query.setText("democratic_government")
    dialogo.buscar()
    # "Mod Uno" esta activo, asi que buscando en inactivos no debe salir.
    qtbot.wait(400)
    assert dialogo.resultados.topLevelItemCount() == 0


def test_actualizaciones_muestra_lo_que_no_esta_al_dia(qtbot, mods, monkeypatch):
    estados = [
        UpdateStatus(
            mods[0],
            UpdateState.OUTDATED,
            "el Workshop pesa 100 bytes mas",
            WorkshopItem("123456789", "Mod Uno (4.5)"),
        ),
        UpdateStatus(mods[1], UpdateState.UP_TO_DATE, "mismo tamano"),
    ]
    monkeypatch.setattr("loadstone.gui.dialogs.check_updates", lambda *a, **k: estados)

    dialogo = UpdatesDialog(None, mods)
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo.tabla.topLevelItemCount() == 1)

    fila = dialogo.tabla.topLevelItem(0)
    assert fila.text(0) == "Mod Uno"
    assert "ahora se llama" in fila.text(2)
    # Los que estan al dia no ensucian la lista.
    assert "1 desactualizado" in dialogo.resumen.text()
    assert dialogo.comando.text().endswith("123456789")


def test_limpieza_lista_los_restos(qtbot, juego, mods):
    resto = juego.mod_dir / "resto"
    resto.mkdir()
    (resto / "basura.txt").write_text("x" * 2048, encoding="utf-8")

    dialogo = CleanupDialog(None, juego, mods, [], lambda uid: True, lambda: None)
    qtbot.addWidget(dialogo)
    dialogo.incluir_contenido.setChecked(True)
    esperar(qtbot, lambda: dialogo.tabla.topLevelItemCount() > 0)

    nombres = [
        dialogo.tabla.topLevelItem(i).text(0)
        for i in range(dialogo.tabla.topLevelItemCount())
    ]
    assert "resto" in nombres
    assert dialogo.borrar.isEnabled()


def test_limpieza_no_propone_nada_cuando_esta_limpio(qtbot, juego, mods):
    dialogo = CleanupDialog(None, juego, mods, [], lambda uid: True, lambda: None)
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: "Nada que limpiar" in dialogo.resumen.text())
    assert not dialogo.borrar.isEnabled()


def test_historial_vacio_desactiva_restaurar(qtbot, juego, mods, playset):
    dialogo = HistoryDialog(None, juego, playset, mods, lambda: None)
    qtbot.addWidget(dialogo)
    assert not dialogo.restaurar.isEnabled()
    assert dialogo.lista.topLevelItemCount() == 1
    assert "sin instantaneas" in dialogo.lista.topLevelItem(0).text(0)


def test_historial_lista_las_instantaneas(qtbot, juego, mods, playset):
    from loadstone.core.history import History

    History(juego.key).save(playset, {m.uid: m for m in mods}, note="antes de jugar")

    dialogo = HistoryDialog(None, juego, playset, mods, lambda: None)
    qtbot.addWidget(dialogo)
    assert dialogo.lista.topLevelItemCount() == 1
    fila = dialogo.lista.topLevelItem(0)
    assert fila.text(1) == "Prueba"
    assert "antes de jugar" in fila.text(3)
    assert dialogo.restaurar.isEnabled()


def test_desinstalar_resume_lo_que_se_pierde(qtbot, juego, mods, playset):
    dialogo = UninstallDialog(
        None, juego, [mods[0]], [playset], lambda p: None, lambda uid: True, lambda: None
    )
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo.desinstalar_btn.isEnabled())

    assert dialogo.tabla.topLevelItemCount() == 1
    assert dialogo.tabla.topLevelItem(0).text(0) == "Mod Uno"
    # Esta en el playset, y el resumen tiene que decirlo antes de borrar nada.
    assert dialogo.tabla.topLevelItem(0).text(2) == "1"
    assert "1 playset(s)" in dialogo.resumen.text()
    # Nada de Steam por medio: la casilla de riesgo no aparece.
    # `isVisibleTo` y no `isVisible` porque el dialogo nunca llega a
    # mostrarse en las pruebas, y entonces todo hijo se declara oculto.
    assert not dialogo.incluir_steam.isVisibleTo(dialogo)


def test_desinstalar_avisa_del_contenido_de_steam(qtbot, juego, tmp_path, playset):
    steam = tmp_path / "workshop" / "content" / "281990" / "999"
    steam.mkdir(parents=True)
    (steam / "datos.txt").write_text("x" * 128, encoding="utf-8")
    descriptor = juego.mod_dir / "999.mod"
    descriptor.write_text('name="Suscrito"', encoding="utf-8")
    suscrito = Mod(
        uid="s",
        name="Suscrito",
        descriptor_path=descriptor,
        folder=steam,
        steam_id="999",
        in_registry=True,
        on_disk=True,
    )

    dialogo = UninstallDialog(
        None, juego, [suscrito], [], lambda p: None, lambda uid: True, lambda: None
    )
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo.desinstalar_btn.isEnabled())

    assert dialogo.incluir_steam.isVisibleTo(dialogo)
    assert not dialogo.incluir_steam.isChecked()
    assert "fuera de la carpeta del juego" in dialogo.aviso.text()


def test_desinstalar_varios_cuenta_el_total(qtbot, juego, mods, playset):
    dialogo = UninstallDialog(
        None, juego, mods, [playset], lambda p: None, lambda uid: True, lambda: None
    )
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo.desinstalar_btn.isEnabled())

    assert dialogo.tabla.topLevelItemCount() == 2
    assert dialogo.desinstalar_btn.text() == "Desinstalar (2)"


class _BackendDeMentira:
    """Lo minimo que la ventana le pide a un backend."""

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

    def activate(self, playset_id: str) -> None:
        pass

    def apply_to_game(self, playset: Playset):
        return None


@pytest.fixture
def ventana(qtbot, juego, mods, playset, monkeypatch):
    from loadstone.gui import main_window as mw

    backend = _BackendDeMentira(mods, [playset])
    monkeypatch.setattr(mw, "detect_games", lambda *a, **k: {"stellaris": juego})
    monkeypatch.setattr(mw, "get_backend", lambda g: backend)

    # Una ventana con cambios a medias pregunta al cerrarse si se descartan, y
    # pytest-qt cierra los widgets sin que nadie conteste: la sesion se queda
    # colgada esperando una respuesta que no llega nunca. El aviso es correcto
    # y tiene sus propias pruebas; aqui solo estorba.
    monkeypatch.setattr(mw.MainWindow, "_confirm_discard", lambda self: True)

    v = mw.MainWindow()
    qtbot.addWidget(v)
    v.reload_games()
    v.backend_falso = backend
    return v


def test_el_menu_contextual_ofrece_las_tres_acciones(ventana, qtbot):
    from PySide6.QtCore import QPoint

    menus = []

    import loadstone.gui.main_window as mw

    class _MenuEspia(mw.QMenu):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            menus.append(self)

        def exec(self, *a, **k):
            return None

    mw.QMenu = _MenuEspia
    try:
        ventana.inactive_list.setCurrentItem(ventana.inactive_list.topLevelItem(0))
        ventana._mod_context_menu(ventana.inactive_list, QPoint(5, 5))
    finally:
        mw.QMenu = _MenuEspia.__bases__[0]

    assert menus, "no se construyo ningun menu"
    textos = [a.text() for a in menus[0].actions() if a.text()]
    assert textos[0] == "Abrir la carpeta del mod"
    assert textos[1] == "Ver en el Workshop"
    assert textos[2].startswith("Desinstalar")


def test_ver_en_el_workshop_solo_si_el_mod_viene_de_steam(ventana):
    from PySide6.QtCore import QPoint

    import loadstone.gui.main_window as mw

    menus = []

    class _MenuEspia(mw.QMenu):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            menus.append(self)

        def exec(self, *a, **k):
            return None

    mw.QMenu = _MenuEspia
    try:
        # "Mod Dos" no tiene steam_id.
        lista = ventana.inactive_list
        for i in range(lista.topLevelItemCount()):
            if lista.topLevelItem(i).text(0) == "Mod Dos":
                lista.setCurrentItem(lista.topLevelItem(i))
                break
        ventana._mod_context_menu(lista, QPoint(5, 5))
    finally:
        mw.QMenu = _MenuEspia.__bases__[0]

    acciones = {a.text(): a for a in menus[0].actions() if a.text()}
    assert not acciones["Ver en el Workshop"].isEnabled()


def test_desinstalar_se_niega_con_cambios_sin_guardar(ventana, mods, monkeypatch):
    """Escribiria en el juego ediciones que nadie ha pedido guardar."""
    import loadstone.gui.main_window as mw

    avisos = []

    class _CajaFalsa(mw.QMessageBox):
        """Sustituye el nombre en el modulo, no el metodo en la clase de Qt.

        Parchear `QMessageBox.information` sobre el tipo de PySide6 deja a Qt
        en un estado del que no se recupera al deshacer el parche, y la sesion
        de pruebas se queda colgada al terminar. Hereda para conservar
        `StandardButton`, y responde al aviso de cierre para que el desmontaje
        no se quede esperando a nadie.
        """

        @staticmethod
        def information(*a, **k):
            avisos.append(a[1:])

        @staticmethod
        def question(*a, **k):
            return mw.QMessageBox.StandardButton.Discard

    monkeypatch.setattr(mw, "QMessageBox", _CajaFalsa)
    abiertos = []
    monkeypatch.setattr(
        mw, "UninstallDialog", lambda *a, **k: abiertos.append(a) or _NuncaSeAbre()
    )

    ventana._set_dirty(True)
    ventana.uninstall_mods([mods[0]])

    assert abiertos == [], "no debe llegar a abrir el dialogo"
    assert avisos and "sin guardar" in avisos[0][0]


class _NuncaSeAbre:
    def exec(self):
        raise AssertionError("no deberia haberse abierto")


def _espiar_menu(mw, menus):
    """Devuelve un QMenu que se registra y no se abre de verdad."""

    class _MenuEspia(mw.QMenu):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            menus.append(self)

        def exec(self, *a, **k):
            return None

    return _MenuEspia


def test_con_varios_seleccionados_el_menu_los_desinstala_todos(ventana, monkeypatch):
    from PySide6.QtCore import QPoint

    import loadstone.gui.main_window as mw

    recibidos = []
    monkeypatch.setattr(ventana, "uninstall_mods", recibidos.append)

    # El fixture deja 'Mod Uno' dentro del playset; se saca para tener los
    # dos en la misma lista y poder marcarlos a la vez.
    ventana._move_uids(["a"], to_active=False)
    lista = ventana.inactive_list
    lista.selectAll()
    assert len(lista.selected_uids()) == 2

    # `QMenu` se devuelve a su sitio en cuanto el menu esta construido: si se
    # dejara sustituido hasta el final de la prueba, Qt no termina de cerrar
    # la ventana y la sesion se queda colgada al salir.
    menus = []
    espia = _espiar_menu(mw, menus)
    real, mw.QMenu = mw.QMenu, espia
    try:
        ventana._mod_context_menu(lista, QPoint(5, 5))
    finally:
        mw.QMenu = real

    acciones = {a.text(): a for a in menus[0].actions() if a.text()}
    assert "Desinstalar 2 mods..." in acciones
    # Las acciones de un solo mod se apagan, no desaparecen.
    assert not acciones["Abrir la carpeta del mod"].isEnabled()
    assert not acciones["Ver en el Workshop"].isEnabled()

    acciones["Desinstalar 2 mods..."].trigger()
    assert len(recibidos) == 1
    assert {m.name for m in recibidos[0]} == {"Mod Uno", "Mod Dos"}


def test_el_clic_derecho_conserva_la_seleccion_multiple(ventana, qtbot):
    """Si Qt la deshiciera al pulsar, borrar varios de una vez seria imposible.

    No es codigo propio sino comportamiento de `QAbstractItemView`, y de el
    depende toda la desinstalacion multiple: conviene tenerlo sujeto por si
    cambia en una version futura de Qt.

    Lo que este clic sintetico no provoca es el evento de menu contextual, que
    en Windows lo genera el sistema al soltar el boton; el contenido del menu
    se comprueba llamando al manejador directamente en la prueba de arriba.
    """
    from PySide6.QtCore import Qt as QtNS

    ventana._move_uids(["a"], to_active=False)
    lista = ventana.inactive_list
    lista.selectAll()
    assert len(lista.selected_uids()) == 2

    qtbot.mouseClick(
        lista.viewport(),
        QtNS.MouseButton.RightButton,
        pos=lista.visualItemRect(lista.topLevelItem(1)).center(),
    )
    assert len(lista.selected_uids()) == 2, "el clic derecho perdio la seleccion"

    # Y sobre una fila no marcada, se queda solo esa: lo que cualquiera espera.
    lista.clearSelection()
    lista.topLevelItem(0).setSelected(True)
    qtbot.mouseClick(
        lista.viewport(),
        QtNS.MouseButton.RightButton,
        pos=lista.visualItemRect(lista.topLevelItem(1)).center(),
    )
    assert len(lista.selected_uids()) == 1


def test_la_barra_de_reparacion_aparece_cuando_faltan_mods(ventana, mods):
    """Un diagnostico que puede arreglarse tiene que ofrecer el arreglo."""
    assert not ventana.repair_bar.isVisibleTo(ventana)

    # El caso real: el launcher los lista y su contenido ya no esta.
    for mod in ventana.mods.values():
        mod.on_disk = False
        mod.in_registry = True
    ventana.refresh_issues()

    assert ventana.repair_bar.isVisibleTo(ventana)
    assert "Faltan 2 mods" in ventana.repair_label.text()
    # Solo 'Mod Uno' tiene steam_id en el fixture.
    assert ventana.repair_button.text() == "Recuperar 1..."
    assert "no se pueden recuperar" in ventana.repair_label.text()


def test_la_barra_se_esconde_cuando_no_hay_nada_roto(ventana):
    ventana.refresh_issues()
    assert not ventana.repair_bar.isVisibleTo(ventana)


def test_actualizaciones_ofrece_actualizar_cuando_hay_juego(qtbot, mods, juego, monkeypatch):
    """Detectar lo desactualizado sin poder arreglarlo deja el trabajo a medias."""
    from loadstone.core.updates import UpdateStatus

    estados = [
        UpdateStatus(mod=mods[0], state=UpdateState.OUTDATED, reason="hay version nueva"),
        UpdateStatus(mod=mods[1], state=UpdateState.UP_TO_DATE, reason="al dia"),
    ]
    monkeypatch.setattr("loadstone.gui.dialogs.check_updates", lambda _m: estados)

    backend = _BackendDeMentira(mods, [])
    dialogo = UpdatesDialog(None, mods, juego, backend, lambda: None)
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo.tabla.topLevelItemCount() > 0)

    # 'Mod Uno' tiene steam_id; 'Mod Dos' esta al dia y no entra.
    assert dialogo._ids == ["123456789"]
    assert dialogo.actualizar_btn.isEnabled()
    assert dialogo.actualizar_btn.text() == "Actualizar los 1"
    # Y sigue ensenando el equivalente en consola, para guionizarlo.
    assert "loadstone workshop --force 123456789" in dialogo.comando.text()


def test_sin_backend_solo_se_puede_mirar(qtbot, mods, monkeypatch):
    from loadstone.core.updates import UpdateStatus

    monkeypatch.setattr(
        "loadstone.gui.dialogs.check_updates",
        lambda _m: [UpdateStatus(mod=mods[0], state=UpdateState.OUTDATED, reason="vieja")],
    )
    dialogo = UpdatesDialog(None, mods)
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo.tabla.topLevelItemCount() > 0)

    assert dialogo._ids == ["123456789"]
    assert not dialogo.actualizar_btn.isEnabled()
