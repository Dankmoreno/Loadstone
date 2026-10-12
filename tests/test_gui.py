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


def test_lo_que_falta_se_marca_con_simbolo_y_no_solo_con_color(qtbot, mods):
    """Un 8% de los hombres no distingue ese rojo; el simbolo no depende de eso."""
    from loadstone.gui.widgets import AVISO, ModListWidget

    lista = ModListWidget(with_checkboxes=False, numbered=False)
    qtbot.addWidget(lista)

    sano = mods[0]
    roto = Mod(uid="x", name="Sin contenido", in_registry=True, on_disk=False)
    lista.add_mod(sano, sano.uid, enabled=True, position=0)
    lista.add_mod(roto, roto.uid, enabled=True, position=1)

    assert lista.topLevelItem(0).text(0) == "Mod Uno"
    assert lista.topLevelItem(1).text(0) == f"{AVISO} Sin contenido"
    assert "no esta en disco" in lista.topLevelItem(1).toolTip(0)


def test_un_mod_desconocido_tambien_se_marca(qtbot):
    """Un uid del playset que no casa con ningun mod instalado."""
    from loadstone.gui.widgets import AVISO, ModListWidget

    lista = ModListWidget(with_checkboxes=True, numbered=True)
    qtbot.addWidget(lista)
    lista.add_mod(None, "fantasma", enabled=True, position=0)

    assert lista.topLevelItem(0).text(2).startswith(AVISO)


def test_el_simbolo_no_estorba_al_filtrar(qtbot):
    """El prefijo va delante del nombre: buscar por el nombre tiene que seguir yendo."""
    from loadstone.gui.widgets import ModListWidget

    lista = ModListWidget(with_checkboxes=False, numbered=False)
    qtbot.addWidget(lista)
    roto = Mod(uid="x", name="Planetary Diversity", in_registry=True, on_disk=False)
    lista.add_mod(roto, roto.uid, enabled=True, position=0)

    assert lista.apply_filter("planetary") == 1
    assert lista.apply_filter("diversity") == 1
    assert lista.apply_filter("otra cosa") == 0


def test_el_diagnostico_se_agrupa_por_tipo_de_problema(ventana):
    """Doscientas lineas con la misma frase no son un diagnostico."""
    # Se rompen los dos mods de la misma manera.
    for mod in ventana.mods.values():
        mod.on_disk = False
        mod.in_registry = True
    ventana.refresh_issues()

    arbol = ventana.issue_tree
    assert arbol.topLevelItemCount() >= 1
    grupo = arbol.topLevelItem(0)
    assert grupo.text(0) == "ERROR"
    assert grupo.text(1) == "2 mods sin contenido en disco"
    assert grupo.childCount() == 2
    # Los uids viajan en los hijos, que es lo que lleva al mod al pulsarlos.
    from loadstone.gui.widgets import UID_ROLE

    assert {grupo.child(i).data(0, UID_ROLE) for i in range(2)} == {"a", "b"}


def test_un_grupo_pequeno_se_abre_solo(ventana):
    for mod in ventana.mods.values():
        mod.on_disk = False
    ventana.refresh_issues()
    assert ventana.issue_tree.topLevelItem(0).isExpanded()


def test_un_grupo_grande_llega_plegado(ventana):
    """Para eso se ha agrupado: si se abriera, volveria el muro."""
    from loadstone.core.models import Mod as _Mod

    ventana.mods = {
        f"u{i}": _Mod(uid=f"u{i}", name=f"Mod {i}", in_registry=True, on_disk=False)
        for i in range(30)
    }
    ventana.refresh_issues()

    grupo = ventana.issue_tree.topLevelItem(0)
    assert grupo.childCount() == 30
    assert not grupo.isExpanded()
    assert "30 mods sin contenido en disco" == grupo.text(1)


def test_los_grupos_se_ordenan_por_gravedad(ventana):
    """Primero lo que impide jugar, despues lo que solo avisa."""
    ventana.refresh_issues()
    niveles = [
        ventana.issue_tree.topLevelItem(i).text(0)
        for i in range(ventana.issue_tree.topLevelItemCount())
    ]
    orden = {"ERROR": 0, "AVISO": 1, "info": 2}
    assert niveles == sorted(niveles, key=lambda n: orden[n])


def test_una_lista_vacia_explica_que_hacer(qtbot):
    """Un rectangulo en blanco no distingue 'no hay nada' de 'no ha cargado'."""
    from loadstone.gui.widgets import ModListWidget

    lista = ModListWidget(with_checkboxes=True, numbered=True)
    qtbot.addWidget(lista)
    lista.set_empty_text("Esto esta vacio", "Nada casa con el filtro")
    lista.resize(400, 300)

    # Vacia de verdad: el mensaje que explica que hacer.
    assert lista.topLevelItemCount() == 0
    lista.render(lista.viewport().grab())  # fuerza el paintEvent sin pantalla

    # Con contenido no se dibuja nada.
    mod = Mod(uid="a", name="Uno", on_disk=True)
    lista.add_mod(mod, "a", enabled=True, position=0)
    assert lista.topLevelItemCount() == 1


def test_los_dos_mensajes_son_distintos(ventana):
    """Vacia de verdad y vaciada por el filtro no son la misma situacion."""
    assert ventana.active_list._texto_vacia != ventana.active_list._texto_sin_resultados
    assert "filtro" in ventana.active_list._texto_sin_resultados
    assert "filtro" not in ventana.active_list._texto_vacia
    # Y las dos listas dicen cosas distintas, porque hacen cosas distintas.
    assert ventana.active_list._texto_vacia != ventana.inactive_list._texto_vacia


def test_al_anadir_un_mod_se_ofrecen_sus_dependencias(ventana, monkeypatch):
    """El diagnostico ya lo sabia; decirlo al final es llegar tarde."""
    import loadstone.gui.main_window as mw

    # 'Mod Dos' pasa a necesitar 'Mod Uno', que esta instalado.
    ventana.mods["b"].dependencies = ["Mod Uno"]
    ventana._move_uids(["a"], to_active=False)  # deja el playset vacio
    assert ventana.playset.mods == []

    preguntas = []

    class _CajaQueDiceSi(mw.QMessageBox):
        @staticmethod
        def question(*a, **k):
            preguntas.append(a[2])
            return mw.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(mw, "QMessageBox", _CajaQueDiceSi)
    ventana._move_uids(["b"], to_active=True)

    assert preguntas and "Mod Uno" in preguntas[0]
    # La dependencia entra antes que quien la necesita.
    assert [e.uid for e in ventana.playset.mods] == ["a", "b"]


def test_si_se_dice_que_no_solo_entra_lo_pedido(ventana, monkeypatch):
    import loadstone.gui.main_window as mw

    ventana.mods["b"].dependencies = ["Mod Uno"]
    ventana._move_uids(["a"], to_active=False)

    class _CajaQueDiceNo(mw.QMessageBox):
        @staticmethod
        def question(*a, **k):
            return mw.QMessageBox.StandardButton.No

    monkeypatch.setattr(mw, "QMessageBox", _CajaQueDiceNo)
    ventana._move_uids(["b"], to_active=True)

    assert [e.uid for e in ventana.playset.mods] == ["b"]


def test_sin_dependencias_que_falten_no_se_pregunta_nada(ventana, monkeypatch):
    import loadstone.gui.main_window as mw

    ventana._move_uids(["a"], to_active=False)
    preguntas = []

    class _CajaEspia(mw.QMessageBox):
        @staticmethod
        def question(*a, **k):
            preguntas.append(a)
            return mw.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(mw, "QMessageBox", _CajaEspia)
    ventana._move_uids(["b"], to_active=True)

    assert preguntas == [], "no debe molestar cuando no hay nada que resolver"


def _mod_con_archivo(raiz, uid, contenido, ruta="common/x.txt"):
    carpeta = raiz / uid
    archivo = carpeta / ruta
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(contenido, encoding="utf-8")
    return Mod(uid=uid, name=f"Mod {uid}", folder=carpeta, on_disk=True)


def test_los_conflictos_separan_las_copias_identicas(qtbot, tmp_path):
    """Lo que mas ruido mete en una instalacion grande."""
    from loadstone.gui.dialogs import ConflictsDialog

    iguales = [
        _mod_con_archivo(tmp_path, "a", "mismo\n"),
        _mod_con_archivo(tmp_path, "b", "mismo\n"),
    ]
    distintos = [
        _mod_con_archivo(tmp_path, "c", "uno\n", "common/y.txt"),
        _mod_con_archivo(tmp_path, "d", "otro\n", "common/y.txt"),
    ]
    dialogo = ConflictsDialog(None, iguales + distintos)
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo._informe is not None)

    dialogo.solo_reales.setChecked(True)
    esperar(qtbot, lambda: dialogo._reales is not None)

    assert [c.path for c in dialogo._identicos] == ["common/x.txt"]
    assert [c.path for c in dialogo._reales] == ["common/y.txt"]
    assert "1 cambian algo" in dialogo.resumen.text()
    assert "1 son copias identicas" in dialogo.resumen.text()


def test_el_diff_se_ensena_al_elegir_un_archivo(qtbot, tmp_path):
    from loadstone.gui.dialogs import ConflictsDialog

    mods = [
        _mod_con_archivo(tmp_path, "a", "comun\nvalor = viejo\n"),
        _mod_con_archivo(tmp_path, "b", "comun\nvalor = nuevo\n"),
    ]
    dialogo = ConflictsDialog(None, mods)
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo._informe is not None)

    dialogo.vista.setCurrentIndex(1)  # por archivo
    assert dialogo.tabla.topLevelItemCount() == 1
    dialogo.tabla.setCurrentItem(dialogo.tabla.topLevelItem(0))

    texto = dialogo.diff.toPlainText()
    assert "-valor = viejo" in texto
    assert "+valor = nuevo" in texto


def test_un_archivo_identico_lo_dice_en_vez_de_ensenar_un_diff_vacio(qtbot, tmp_path):
    from loadstone.gui.dialogs import ConflictsDialog

    mods = [
        _mod_con_archivo(tmp_path, "a", "igual\n"),
        _mod_con_archivo(tmp_path, "b", "igual\n"),
    ]
    dialogo = ConflictsDialog(None, mods)
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo._informe is not None)

    dialogo.vista.setCurrentIndex(1)
    dialogo.tabla.setCurrentItem(dialogo.tabla.topLevelItem(0))

    assert "identico byte a byte" in dialogo.diff.toPlainText()


def test_elegir_otra_version_prepara_el_parche(qtbot, tmp_path, juego):
    """El caso que motiva el parche: quiero la del que pierde."""
    from loadstone.gui.dialogs import ConflictsDialog

    mods = [
        _mod_con_archivo(tmp_path, "a", "quiero esta\n"),
        _mod_con_archivo(tmp_path, "b", "esta gana ahora\n"),
    ]
    dialogo = ConflictsDialog(None, mods, juego)
    qtbot.addWidget(dialogo)
    esperar(qtbot, lambda: dialogo._informe is not None)

    dialogo.vista.setCurrentIndex(1)
    dialogo.tabla.setCurrentItem(dialogo.tabla.topLevelItem(0))

    # El desplegable llega con el ganador actual marcado, y eso no es elegir.
    assert dialogo.version_box.count() == 2
    assert "(la que gana ahora)" in dialogo.version_box.currentText()
    assert dialogo._elegidos == {}
    assert not dialogo.parche_btn.isEnabled()

    # Elegir al que pierde si cuenta.
    dialogo.version_box.setCurrentIndex(0)
    assert list(dialogo._elegidos) == ["common/x.txt"]
    assert dialogo._elegidos["common/x.txt"].mod_name == "Mod a"
    assert dialogo.parche_btn.isEnabled()
    assert "(1)" in dialogo.parche_btn.text()

    # Y volver al ganador lo retira: un parche con lo que ya pasa no sirve.
    dialogo.version_box.setCurrentIndex(1)
    assert dialogo._elegidos == {}
    assert not dialogo.parche_btn.isEnabled()
