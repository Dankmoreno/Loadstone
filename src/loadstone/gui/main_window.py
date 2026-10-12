"""Ventana principal de Loadstone.

El reparto en tres columnas responde a las tres preguntas que trae el usuario:
que mod es este (detalle), que tengo instalado y que estoy usando (las dos
listas), y que esta mal (el diagnostico de abajo). Nada se escribe en el juego
hasta pulsar Guardar o Aplicar.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QImage,
    QPainter,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.analysis import IssueKind, Severity, analyze
from ..core.backends import Backend, BackendError, get_backend
from ..core.config import Config
from ..core.conflicts import mod_folder_size
from ..core.games import detect_games
from ..core.history import History
from ..core.launch import GameLaunchError, launch_game, open_in_file_manager, read_launch_target
from ..core.models import GameProfile, LoadOrderMode, Mod, Playset, PlaysetMod
from ..core.notes import Notes
from ..core.playsets import export_playset, import_playset, read_playset_file
from ..core.repair import RepairPlan, plan_repair
from ..core.sorting import CycleError, minimal_moves, sort_alphabetical, sort_by_dependencies
from .assets import svg_path
from .dialogs import (
    CleanupDialog,
    ConflictsDialog,
    DlcDialog,
    DownloadDialog,
    HistoryDialog,
    QuarantineDialog,
    RepairDialog,
    SearchDialog,
    UninstallDialog,
    UpdatesDialog,
)
from .theme import current_palette
from .widgets import UID_ROLE, DetailPanel, ModListWidget


def _severity_color(severity: Severity) -> QColor:
    paleta = current_palette()
    return QColor(
        {
            Severity.ERROR: paleta.error,
            Severity.WARNING: paleta.aviso,
            Severity.INFO: paleta.texto_apagado,
        }[severity]
    )
_SEVERITY_LABEL = {Severity.ERROR: "ERROR", Severity.WARNING: "AVISO", Severity.INFO: "info"}

_ABRIR_HASTA = 6
"""Hasta cuantos problemas de un tipo se ensenan desplegados de entrada."""

# En plural y describiendo el problema, no su nombre interno: la cabecera del
# grupo es lo unico que mucha gente va a leer.
_ISSUE_KIND_LABEL = {
    IssueKind.DANGLING: "mods sin contenido en disco",
    IssueKind.ORPHAN: "mods que el launcher no conoce",
    IssueKind.UNLINKED: "carpetas que el juego no ve",
    IssueKind.PARSE_ERROR: "descriptores con errores",
    IssueKind.VERSION_MISMATCH: "mods hechos para otra version del juego",
    IssueKind.MISSING_DEPENDENCY: "dependencias que no estan instaladas",
    IssueKind.DISABLED_DEPENDENCY: "dependencias desactivadas",
    IssueKind.DEPENDENCY_ORDER: "dependencias que cargan demasiado tarde",
    IssueKind.DUPLICATE: "mods duplicados",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Loadstone")
        self.resize(1480, 880)

        self.games: dict[str, GameProfile] = {}
        self.backend: Backend | None = None
        self.mods: dict[str, Mod] = {}
        self.playsets: list[Playset] = []
        self.playset: Playset | None = None
        self.notes: Notes | None = None
        self.dirty = False
        self._saved_state: list[tuple[str, bool, int]] = []
        self._repair_plan = RepairPlan()

        self._build_ui()
        # Cargar despues de mostrar: escanear la carpeta de mods tarda y
        # arrancar con la ventana en blanco parece un cuelgue.
        QTimer.singleShot(0, self.reload_games)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        layout.addLayout(self._build_top_bar())

        vertical = QSplitter(Qt.Orientation.Vertical)

        columnas = QSplitter(Qt.Orientation.Horizontal)
        self.detail = DetailPanel()
        self.detail.note_changed.connect(self._on_note_changed)
        columnas.addWidget(self.detail)

        columnas.addWidget(self._build_list_pane(activos=False))
        columnas.addWidget(self._build_list_pane(activos=True))
        columnas.setStretchFactor(0, 2)
        columnas.setStretchFactor(1, 3)
        columnas.setStretchFactor(2, 3)
        vertical.addWidget(columnas)

        panel_diagnostico = self._build_issues_pane()
        # Sin un minimo, el reparto deja el diagnostico en dos filas y los
        # errores, que es lo que hay que ver, quedan fuera de la vista.
        panel_diagnostico.setMinimumHeight(170)
        vertical.addWidget(panel_diagnostico)
        vertical.setStretchFactor(0, 4)
        vertical.setStretchFactor(1, 1)
        layout.addWidget(vertical, 1)

        layout.addLayout(self._build_bottom_bar())
        self.setCentralWidget(central)
        self.statusBar().showMessage("Buscando juegos...")
        self._build_menu()

    def _build_brand(self) -> QWidget:
        """La marca en la barra superior: el logo y el nombre.

        Se dibuja desde el SVG y no desde el `.ico` porque aqui el tamano
        depende de la escala de la pantalla, y rasterizar el vector a la altura
        exacta del texto evita el borde sucio de reescalar un mapa de bits.
        """
        marca = QWidget()
        caja = QHBoxLayout(marca)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(8)

        lado = max(22, self.fontMetrics().height() + 8)
        ruta = svg_path()
        if ruta is not None:
            imagen = QImage(lado, lado, QImage.Format.Format_ARGB32)
            imagen.fill(Qt.GlobalColor.transparent)
            pintor = QPainter(imagen)
            pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            QSvgRenderer(str(ruta)).render(pintor)
            pintor.end()
            logo = QLabel()
            logo.setPixmap(QPixmap.fromImage(imagen))
            caja.addWidget(logo)

        nombre = QLabel("Loadstone")
        fuente = QFont()
        fuente.setBold(True)
        fuente.setPointSizeF(fuente.pointSizeF() + 0.5)
        nombre.setFont(fuente)
        nombre.setStyleSheet(f"color: {current_palette().acento}")
        caja.addWidget(nombre)
        return marca

    def _build_top_bar(self) -> QHBoxLayout:
        fila = QHBoxLayout()
        fila.setSpacing(8)
        fila.addWidget(self._build_brand())
        fila.addSpacing(6)
        fila.addWidget(QLabel("Juego:"))
        self.game_box = QComboBox()
        self.game_box.setMinimumWidth(200)
        self.game_box.currentIndexChanged.connect(self._on_game_changed)
        fila.addWidget(self.game_box)

        fila.addWidget(QLabel("Playset:"))
        self.playset_box = QComboBox()
        self.playset_box.setMinimumWidth(220)
        self.playset_box.currentIndexChanged.connect(self._on_playset_changed)
        fila.addWidget(self.playset_box)

        self.version_label = QLabel()
        self.version_label.setStyleSheet(f"color: {current_palette().texto_apagado}")
        fila.addWidget(self.version_label)
        fila.addStretch(1)

        fila.addWidget(QLabel("Filtrar por:"))
        self.filter_field = QComboBox()
        for etiqueta, clave in (
            ("nombre", "name"),
            ("id de Workshop", "steam"),
            ("etiqueta", "tag"),
        ):
            self.filter_field.addItem(etiqueta, clave)
        self.filter_field.currentIndexChanged.connect(lambda _i: self._apply_filter())
        fila.addWidget(self.filter_field)

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("escribe para filtrar...")
        self.filter_box.setClearButtonEnabled(True)
        self.filter_box.setMaximumWidth(260)
        self.filter_box.textChanged.connect(lambda _t: self._apply_filter())
        fila.addWidget(self.filter_box)
        return fila

    def _build_list_pane(self, *, activos: bool) -> QWidget:
        panel = QWidget()
        caja = QVBoxLayout(panel)
        caja.setContentsMargins(0, 0, 0, 0)

        titulo = QLabel()
        fuente = QFont()
        fuente.setBold(True)
        titulo.setFont(fuente)
        caja.addWidget(titulo)

        lista = ModListWidget(with_checkboxes=activos, numbered=activos)
        if activos:
            lista.set_empty_text(
                "Este playset esta vacio.\n\n"
                "Arrastra mods desde la izquierda, o seleccionalos y pulsa\n"
                "'Anadir al playset'.",
                "Ningun mod del playset casa con el filtro.",
            )
        else:
            lista.set_empty_text(
                "Todo lo que tienes instalado esta ya en este playset.",
                "Ningun mod instalado casa con el filtro.",
            )
        lista.itemSelectionChanged.connect(lambda: self._on_selection(lista))
        lista.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lista.customContextMenuRequested.connect(
            lambda punto, w=lista: self._mod_context_menu(w, punto)
        )
        lista.itemDoubleClicked.connect(
            lambda item, _c: self._move_uids([item.data(0, UID_ROLE)], to_active=not activos)
        )
        lista.mods_dropped.connect(
            lambda uids: self._move_uids(uids, to_active=activos)
        )
        caja.addWidget(lista)

        boton = QPushButton("Quitar del playset  →" if activos else "←  Anadir al playset")
        boton.clicked.connect(
            lambda: self._move_uids(lista.selected_uids(), to_active=not activos)
        )
        caja.addWidget(boton)

        if activos:
            self.active_list, self.active_title = lista, titulo
            lista.order_changed.connect(self._on_order_changed)
            lista.enabled_changed.connect(self._on_enabled_changed)
        else:
            self.inactive_list, self.inactive_title = lista, titulo
        return panel

    def _build_issues_pane(self) -> QWidget:
        panel = QWidget()
        caja = QVBoxLayout(panel)
        caja.setContentsMargins(0, 0, 0, 0)
        self.issues_title = QLabel("Diagnostico")
        fuente = QFont()
        fuente.setBold(True)
        self.issues_title.setFont(fuente)
        caja.addWidget(self.issues_title)

        # Barra de reparacion: aparece solo cuando hay algo roto que el
        # programa sabe arreglar. Un diagnostico que describe un problema
        # resoluble sin ofrecer la solucion deja el trabajo a medias.
        self.repair_bar = QWidget()
        self.repair_bar.setVisible(False)
        barra = QHBoxLayout(self.repair_bar)
        barra.setContentsMargins(10, 7, 10, 7)
        self.repair_label = QLabel()
        self.repair_label.setWordWrap(True)
        barra.addWidget(self.repair_label, 1)
        self.repair_button = QPushButton("Recuperar...")
        self.repair_button.clicked.connect(self.open_repair)
        barra.addWidget(self.repair_button)
        caja.addWidget(self.repair_bar)

        self.issue_tree = QTreeWidget()
        self.issue_tree.setHeaderLabels(["Nivel", "Problema"])
        # Con decoracion: ahora los problemas van agrupados y hace falta ver
        # que un grupo se puede desplegar.
        self.issue_tree.setRootIsDecorated(True)
        self.issue_tree.setColumnWidth(0, 60)
        self.issue_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.issue_tree.itemDoubleClicked.connect(self._on_issue_activated)
        caja.addWidget(self.issue_tree)
        return panel

    def _build_bottom_bar(self) -> QHBoxLayout:
        fila = QHBoxLayout()
        for texto, accion, tooltip in (
            ("Recargar", self.reload_current, "Volver a leer mods y playsets del disco"),
            ("Vaciar", self.clear_playset, "Quitar todos los mods del playset"),
            ("Revertir", self.revert_playset, "Deshacer los cambios sin guardar"),
        ):
            boton = QPushButton(texto)
            boton.setToolTip(tooltip)
            boton.clicked.connect(accion)
            fila.addWidget(boton)

        fila.addSpacing(16)
        self.deps_button = QPushButton("Ordenar por dependencias")
        self.deps_button.clicked.connect(self.sort_by_deps)
        fila.addWidget(self.deps_button)
        self.alpha_button = QPushButton("Alfabetico")
        self.alpha_button.clicked.connect(self.sort_alpha)
        fila.addWidget(self.alpha_button)

        fila.addStretch(1)
        self.save_button = QPushButton("Guardar")
        self.save_button.clicked.connect(self.save)
        fila.addWidget(self.save_button)
        self.apply_button = QPushButton("Aplicar al juego")
        self.apply_button.clicked.connect(self.apply_to_game)
        fila.addWidget(self.apply_button)
        self.play_button = QPushButton("Jugar")
        self.play_button.setDefault(True)
        self.play_button.clicked.connect(self.play)
        fila.addWidget(self.play_button)
        return fila

    def _build_menu(self) -> None:
        herramientas = self.menuBar().addMenu("&Herramientas")
        for texto, atajo, accion in (
            ("&Buscar en los archivos de los mods...", "Ctrl+F", self.open_search),
            ("Ver &conflictos entre mods...", "Ctrl+K", self.open_conflicts),
            ("Comprobar &actualizaciones...", None, self.open_updates),
            ("&Explorar el Workshop...", "Ctrl+B", self.open_workshop),
            ("&Descargar del Workshop por enlace...", "Ctrl+D", self.open_download),
        ):
            accion_qt = QAction(texto, self)
            if atajo:
                accion_qt.setShortcut(atajo)
            accion_qt.triggered.connect(accion)
            herramientas.addAction(accion_qt)

        herramientas.addSeparator()
        for texto, atajo, accion in (
            ("&Historial de listas...", "Ctrl+H", self.open_history),
            ("&Papelera de mods...", None, self.open_quarantine),
            ("&Limpiar restos...", None, self.open_cleanup),
        ):
            accion_qt = QAction(texto, self)
            if atajo:
                accion_qt.setShortcut(atajo)
            accion_qt.triggered.connect(accion)
            herramientas.addAction(accion_qt)

        menu_playset = self.menuBar().addMenu("&Playset")
        for texto, accion in (
            ("&Nuevo...", self.new_playset),
            ("&Duplicar...", self.duplicate_playset),
            ("&Renombrar...", self.rename_playset),
            ("&Borrar...", self.delete_playset),
        ):
            accion_qt = QAction(texto, self)
            accion_qt.triggered.connect(accion)
            menu_playset.addAction(accion_qt)
        menu_playset.addSeparator()
        for texto, accion in (
            ("&Exportar a un archivo...", self.export_playset),
            ("&Importar de un archivo...", self.import_playset),
        ):
            accion_qt = QAction(texto, self)
            accion_qt.triggered.connect(accion)
            menu_playset.addAction(accion_qt)

        menu_juego = self.menuBar().addMenu("&Juego")
        jugar = QAction("&Jugar", self)
        jugar.setShortcut("F9")
        jugar.triggered.connect(self.play)
        menu_juego.addAction(jugar)
        dlc = QAction("Gestionar &DLC...", self)
        dlc.triggered.connect(self.open_dlc)
        menu_juego.addAction(dlc)
        menu_juego.addSeparator()
        for texto, obtener in (
            ("Abrir la carpeta de &mods", lambda g: g.mod_dir),
            ("Abrir la carpeta de &datos", lambda g: g.data_path),
            ("Abrir la carpeta de &instalacion", lambda g: g.install_path),
        ):
            accion_qt = QAction(texto, self)
            accion_qt.triggered.connect(
                lambda _checked=False, f=obtener: self._open_folder(f)
            )
            menu_juego.addAction(accion_qt)

        recargar = QAction("Recargar", self)
        recargar.setShortcut("F5")
        recargar.triggered.connect(self.reload_current)
        self.addAction(recargar)

    # -------------------------------------------------------------- carga

    def reload_games(self) -> None:
        config = Config.load()
        self.games = {
            key: game
            for key, game in detect_games(config.extra_roots).items()
            if game.has_data_dir
        }
        self.game_box.blockSignals(True)
        self.game_box.clear()
        for key, game in self.games.items():
            etiqueta = game.display_name
            if not game.is_installed:
                etiqueta += "  (sin instalacion detectada)"
            self.game_box.addItem(etiqueta, key)
        self.game_box.blockSignals(False)

        if not self.games:
            self.statusBar().showMessage(
                "No hay ninguna carpeta de datos de Paradox en Documentos"
            )
            return
        self._on_game_changed(self.game_box.currentIndex())

    def reload_current(self) -> None:
        if self._confirm_discard():
            self._on_game_changed(self.game_box.currentIndex())

    def _current_game(self) -> GameProfile | None:
        key = self.game_box.currentData()
        return self.games.get(key) if key else None

    def _on_game_changed(self, _index: int) -> None:
        game = self._current_game()
        if game is None or not self._confirm_discard():
            return
        self.version_label.setText(f"{game.raw_version or 'version ?'} · {game.backend}")

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.backend = get_backend(game)
            self.mods = {mod.uid: mod for mod in self.backend.read_mods()}
            self.playsets = self.backend.read_playsets()
            self.notes = Notes(game.key)
        except BackendError as error:
            self.backend = None
            self.mods, self.playsets = {}, []
            self.statusBar().showMessage(str(error))
            self._clear_views()
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.play_button.setEnabled(read_launch_target(game) is not None)
        self._refresh_playset_box()

    def _refresh_playset_box(self, seleccionar: str | None = None) -> None:
        self.playset_box.blockSignals(True)
        self.playset_box.clear()
        for playset in self.playsets:
            sufijo = "  (activo)" if playset.is_active else ""
            self.playset_box.addItem(f"{playset.name}{sufijo}", playset.id)
        self.playset_box.blockSignals(False)

        indice = 0
        if seleccionar:
            encontrado = self.playset_box.findData(seleccionar)
            indice = max(encontrado, 0)
        else:
            indice = next((i for i, p in enumerate(self.playsets) if p.is_active), 0)
        self.playset_box.setCurrentIndex(indice)
        self._on_playset_changed(indice)

    def _on_playset_changed(self, index: int) -> None:
        if not self._confirm_discard():
            return
        self.playset = self.playsets[index] if 0 <= index < len(self.playsets) else None
        self._remember_saved_state()
        self._set_dirty(False)
        self.populate()

    def _remember_saved_state(self) -> None:
        """Guarda el estado con el que se podra comparar al revertir."""
        self._saved_state = (
            [(e.uid, e.enabled, e.position) for e in self.playset.mods]
            if self.playset
            else []
        )

    def _clear_views(self) -> None:
        self.active_list.clear()
        self.inactive_list.clear()
        self.issue_tree.clear()
        self.playset_box.clear()
        self.detail.show_mod(None)

    # --------------------------------------------------------------- vista

    def populate(self) -> None:
        for lista in (self.active_list, self.inactive_list):
            lista.blockSignals(True)
            lista.clear()

        en_playset: set[str] = set()
        if self.playset is not None:
            for posicion, entrada in enumerate(
                sorted(self.playset.mods, key=lambda e: e.position)
            ):
                en_playset.add(entrada.uid)
                self.active_list.add_mod(
                    self.mods.get(entrada.uid),
                    entrada.uid,
                    enabled=entrada.enabled,
                    position=posicion,
                )

        fuera = sorted(
            (mod for uid, mod in self.mods.items() if uid not in en_playset),
            key=lambda m: m.name.lower(),
        )
        for mod in fuera:
            self.inactive_list.add_mod(mod, mod.uid, enabled=False, position=0)

        for lista in (self.active_list, self.inactive_list):
            lista.blockSignals(False)

        self._apply_filter()
        self.refresh_issues()
        self._update_status()

    def _apply_filter(self) -> None:
        texto = self.filter_box.text().strip().lower()
        campo = self.filter_field.currentData()
        if campo != "name" and texto:
            # Filtrar por id o etiqueta necesita mirar el mod, no la fila.
            for lista in (self.active_list, self.inactive_list):
                for indice in range(lista.topLevelItemCount()):
                    item = lista.topLevelItem(indice)
                    mod = self.mods.get(item.data(0, UID_ROLE))
                    item.setHidden(not self._matches(mod, campo, texto))
        else:
            for lista in (self.active_list, self.inactive_list):
                lista.apply_filter(texto)
        self._update_titles()

    @staticmethod
    def _matches(mod: Mod | None, campo: str, texto: str) -> bool:
        if mod is None:
            return False
        if campo == "steam":
            return texto in (mod.steam_id or "").lower()
        return any(texto in tag.lower() for tag in mod.tags)

    def _update_titles(self) -> None:
        def visibles(lista: ModListWidget) -> int:
            return sum(
                not lista.topLevelItem(i).isHidden()
                for i in range(lista.topLevelItemCount())
            )

        total_activos = self.active_list.topLevelItemCount()
        total_fuera = self.inactive_list.topLevelItemCount()
        filtrando = bool(self.filter_box.text().strip())
        self.active_title.setText(
            f"En el playset [{visibles(self.active_list)} de {total_activos}]"
            if filtrando
            else f"En el playset [{total_activos}]"
        )
        self.inactive_title.setText(
            f"Instalados, fuera del playset [{visibles(self.inactive_list)} de {total_fuera}]"
            if filtrando
            else f"Instalados, fuera del playset [{total_fuera}]"
        )

    def refresh_issues(self) -> None:
        self.issue_tree.clear()
        game = self._current_game()
        if game is None:
            return
        issues = analyze(game, list(self.mods.values()), self.playset)
        orden = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

        # Agrupado por tipo de problema. Una instalacion rota de verdad produce
        # doscientas lineas con la misma frase, y eso no es un diagnostico sino
        # un muro: lo que importa —cuantas clases de problema hay y cuales— se
        # pierde entre repeticiones.
        grupos: dict[IssueKind, list] = {}
        for issue in issues:
            grupos.setdefault(issue.kind, []).append(issue)

        def peor(lista: list) -> Severity:
            return min((i.severity for i in lista), key=lambda s: orden[s])

        for kind, lista in sorted(
            grupos.items(), key=lambda par: (orden[peor(par[1])], -len(par[1]))
        ):
            severidad = peor(lista)
            color = QBrush(_severity_color(severidad))
            etiqueta = _ISSUE_KIND_LABEL.get(kind, kind.value)
            padre = QTreeWidgetItem([_SEVERITY_LABEL[severidad], f"{len(lista)} {etiqueta}"])
            padre.setForeground(0, color)
            fuente = padre.font(1)
            fuente.setBold(True)
            padre.setFont(1, fuente)
            self.issue_tree.addTopLevelItem(padre)

            for issue in lista:
                hijo = QTreeWidgetItem(["", issue.message])
                hijo.setData(0, UID_ROLE, issue.mod_uid)
                padre.addChild(hijo)

            # Los grupos pequenos se abren solos; los de doscientos, no: para
            # eso se ha agrupado.
            padre.setExpanded(len(lista) <= _ABRIR_HASTA)

        errores = sum(1 for i in issues if i.severity is Severity.ERROR)
        avisos = sum(1 for i in issues if i.severity is Severity.WARNING)
        self.issues_title.setText(
            f"Diagnostico: {errores} errores, {avisos} avisos, {len(issues)} en total"
        )
        self._refresh_repair_bar()

    def _refresh_repair_bar(self) -> None:
        """Ensena la barra solo si hay mods que falten y se puedan recuperar."""
        self._repair_plan = plan_repair(list(self.mods.values()))
        plan = self._repair_plan
        if not plan.hay_algo_que_hacer:
            self.repair_bar.setVisible(False)
            return

        paleta = current_palette()
        self.repair_bar.setStyleSheet(
            f"background: {paleta.superficie_alta};"
            f"border: 1px solid {paleta.aviso};"
            "border-radius: 8px;"
        )
        perdidos = (
            f" Otros {len(plan.perdidos)} se instalaron a mano y no se pueden recuperar."
            if plan.perdidos
            else ""
        )
        self.repair_label.setText(
            f"Faltan {plan.total} mods en disco: el launcher los lista pero el juego "
            f"no los encontrara. {len(plan.recuperables)} tienen id del Workshop y se "
            f"pueden volver a descargar.{perdidos}"
        )
        self.repair_button.setText(f"Recuperar {len(plan.recuperables)}...")
        self.repair_bar.setVisible(True)

    def open_repair(self) -> None:
        if not self._require_game():
            return
        game = self._current_game()
        assert game is not None and self.backend is not None
        plan = plan_repair(list(self.mods.values()))
        if not plan.hay_algo_que_hacer:
            QMessageBox.information(
                self, "Nada que recuperar", "No falta ningun mod recuperable."
            )
            return
        RepairDialog(
            self,
            game,
            self.backend,
            plan,
            lambda: self._on_game_changed(self.game_box.currentIndex()),
        ).exec()

    def _update_status(self) -> None:
        if self.playset is None:
            self.statusBar().showMessage("Sin playset")
            return
        activos = len(self.playset.enabled_uids())
        marca = "  ·  sin guardar" if self.dirty else ""
        self.statusBar().showMessage(
            f"{len(self.playset.mods)} mods en el playset, {activos} activados, "
            f"{len(self.mods)} instalados, orden {self.playset.load_order}{marca}"
        )

    def _set_dirty(self, value: bool) -> None:
        self.dirty = value
        self.setWindowTitle("Loadstone *" if value else "Loadstone")
        self._update_status()

    # ------------------------------------------------------------ eventos

    def _on_selection(self, lista: ModListWidget) -> None:
        uid = lista.current_uid()
        mod = self.mods.get(uid) if uid else None
        nota = self.notes.get(mod.registry_id) if (self.notes and mod) else ""
        self.detail.show_mod(mod, nota=nota, size=mod_folder_size(mod) if mod else None)

    def _on_note_changed(self, registry_id: str, texto: str) -> None:
        if self.notes and self.notes.set(registry_id, texto):
            self.statusBar().showMessage("Nota guardada")

    def _on_enabled_changed(self, uid: str, enabled: bool) -> None:
        if self.playset is None:
            return
        for entrada in self.playset.mods:
            if entrada.uid == uid and entrada.enabled != enabled:
                entrada.enabled = enabled
                self._set_dirty(True)
                self.refresh_issues()
                break

    def _on_order_changed(self) -> None:
        if self.playset is None:
            return
        posiciones = {uid: i for i, uid in enumerate(self.active_list.uids())}
        for entrada in self.playset.mods:
            if entrada.uid in posiciones:
                entrada.position = posiciones[entrada.uid]
        self.active_list.renumber()
        self._set_dirty(True)
        self.refresh_issues()

    def _move_uids(self, uids: list[str], *, to_active: bool) -> None:
        """Mete o saca mods del playset."""
        if self.playset is None or not uids:
            return
        objetivo = [u for u in uids if u]
        if to_active:
            presentes = {e.uid for e in self.playset.mods}
            siguiente = max((e.position for e in self.playset.mods), default=-1) + 1
            for uid in objetivo:
                if uid in presentes:
                    continue
                self.playset.mods.append(
                    PlaysetMod(uid=uid, enabled=True, position=siguiente)
                )
                siguiente += 1
        else:
            fuera = set(objetivo)
            self.playset.mods = [e for e in self.playset.mods if e.uid not in fuera]
            self.playset.renumber()

        self._set_dirty(True)
        self.populate()

    def _on_issue_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        uid = item.data(0, UID_ROLE)
        if not uid:
            return
        for lista in (self.active_list, self.inactive_list):
            for indice in range(lista.topLevelItemCount()):
                candidato = lista.topLevelItem(indice)
                if candidato.data(0, UID_ROLE) == uid:
                    lista.setCurrentItem(candidato)
                    lista.scrollToItem(candidato)
                    return

    # ----------------------------------------------------------- acciones

    def clear_playset(self) -> None:
        if self.playset is None or not self.playset.mods:
            return
        if QMessageBox.question(
            self,
            "Vaciar el playset",
            f"Se quitaran los {len(self.playset.mods)} mods de "
            f"'{self.playset.name}'.\n\nLos mods siguen instalados.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Ok:
            return
        self.playset.mods = []
        self._set_dirty(True)
        self.populate()

    def revert_playset(self) -> None:
        if self.playset is None or not self.dirty:
            return
        self.playset.mods = [
            PlaysetMod(uid=uid, enabled=enabled, position=posicion)
            for uid, enabled, posicion in self._saved_state
        ]
        self._set_dirty(False)
        self.populate()
        self.statusBar().showMessage("Cambios descartados")

    def sort_by_deps(self) -> None:
        if self.playset is None:
            return
        try:
            movidos = sort_by_dependencies(self.playset, self.mods)
        except CycleError as error:
            QMessageBox.warning(self, "Dependencias circulares", str(error))
            return
        self.playset.load_order = LoadOrderMode.CUSTOM
        self.populate()
        if movidos:
            self._set_dirty(True)
        self.statusBar().showMessage(
            f"{len(movidos)} mods reubicados" if movidos else "Ya cumplia las dependencias"
        )

    def sort_alpha(self) -> None:
        if self.playset is None:
            return
        antes = [e.uid for e in sorted(self.playset.mods, key=lambda e: e.position)]
        sort_alphabetical(self.playset, self.mods)
        self.playset.load_order = LoadOrderMode.ALPHABETICAL
        despues = [e.uid for e in sorted(self.playset.mods, key=lambda e: e.position)]
        self.populate()
        self._set_dirty(True)
        self.statusBar().showMessage(f"{len(minimal_moves(antes, despues))} mods reubicados")

    def save(self) -> bool:
        if self.backend is None or self.playset is None:
            return False
        try:
            self.backend.save_playset(self.playset)
        except BackendError as error:
            QMessageBox.critical(self, "No se pudo guardar", str(error))
            return False
        self._remember_saved_state()
        self._set_dirty(False)
        self.statusBar().showMessage("Guardado en el registro del launcher")
        return True

    def apply_to_game(self) -> bool:
        if self.backend is None or self.playset is None:
            return False
        activos = len(self.playset.enabled_uids())
        if QMessageBox.question(
            self,
            "Aplicar al juego",
            f"Se escribiran {activos} mods en el orden actual para "
            f"'{self.playset.name}'.\n\n"
            "Cierra el launcher de Paradox antes de continuar: si esta abierto "
            "puede sobrescribir el cambio.\n\n"
            "Se guarda una copia de los archivos afectados.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Ok:
            return False
        if self.dirty and not self.save():
            return False
        try:
            escrito: Path | None = self.backend.apply_to_game(self.playset)
        except BackendError as error:
            QMessageBox.critical(self, "No se pudo aplicar", str(error))
            return False

        game = self._current_game()
        instantanea = ""
        if game is not None:
            try:
                snapshot = History(game.key).save(self.playset, self.mods)
                instantanea = f"  ·  instantanea {snapshot.id}"
            except OSError as error:
                instantanea = f"  ·  sin instantanea ({error})"
        self.statusBar().showMessage(f"Aplicado: {escrito}{instantanea}")
        return True

    def play(self) -> None:
        game = self._current_game()
        if game is None:
            return
        if self.dirty:
            respuesta = QMessageBox.question(
                self,
                "Hay cambios sin aplicar",
                "El playset tiene cambios que el juego todavia no vera.\n\n"
                "Aplicarlos antes de jugar?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if respuesta == QMessageBox.StandardButton.Cancel:
                return
            if respuesta == QMessageBox.StandardButton.Yes and not self.apply_to_game():
                return
        try:
            objetivo = launch_game(game)
        except GameLaunchError as error:
            QMessageBox.critical(self, "No se pudo arrancar", str(error))
            return
        self.statusBar().showMessage(f"Arrancando {objetivo.executable.name}")

    def _open_folder(self, obtener) -> None:
        game = self._current_game()
        carpeta = obtener(game) if game else None
        if carpeta is None:
            QMessageBox.information(self, "Sin carpeta", "Esa carpeta no esta disponible.")
            return
        try:
            open_in_file_manager(carpeta)
        except GameLaunchError as error:
            QMessageBox.warning(self, "No se pudo abrir", str(error))

    # -------------------------------------------------- gestion de playsets

    def new_playset(self) -> None:
        if self.backend is None:
            return
        nombre, aceptado = QInputDialog.getText(self, "Nuevo playset", "Nombre:")
        if not aceptado or not nombre.strip():
            return
        try:
            nuevo = self.backend.create_playset(nombre.strip())
        except BackendError as error:
            QMessageBox.warning(self, "No se pudo crear", str(error))
            return
        self.playsets = self.backend.read_playsets()
        self._refresh_playset_box(nuevo)

    def duplicate_playset(self) -> None:
        if self.backend is None or self.playset is None:
            return
        nombre, aceptado = QInputDialog.getText(
            self, "Duplicar playset", "Nombre del nuevo:", text=f"{self.playset.name} (copia)"
        )
        if not aceptado or not nombre.strip():
            return
        try:
            nuevo = self.backend.create_playset(nombre.strip())
            copia = next(p for p in self.backend.read_playsets() if p.id == nuevo)
            copia.mods = [
                PlaysetMod(uid=e.uid, enabled=e.enabled, position=e.position)
                for e in self.playset.mods
            ]
            self.backend.save_playset(copia)
        except (BackendError, StopIteration) as error:
            QMessageBox.warning(self, "No se pudo duplicar", str(error))
            return
        self.playsets = self.backend.read_playsets()
        self._refresh_playset_box(nuevo)

    def rename_playset(self) -> None:
        if self.backend is None or self.playset is None:
            return
        nombre, aceptado = QInputDialog.getText(
            self, "Renombrar playset", "Nombre:", text=self.playset.name
        )
        if not aceptado or not nombre.strip():
            return
        try:
            self.backend.rename_playset(self.playset.id, nombre.strip())
        except BackendError as error:
            QMessageBox.warning(self, "No se pudo renombrar", str(error))
            return
        actual = self.playset.id
        self.playsets = self.backend.read_playsets()
        self._refresh_playset_box(actual)

    def delete_playset(self) -> None:
        if self.backend is None or self.playset is None:
            return
        if QMessageBox.question(
            self,
            "Borrar playset",
            f"Se borrara el playset '{self.playset.name}'.\n\n"
            "Los mods siguen instalados; solo se pierde esta lista.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Ok:
            return
        try:
            self.backend.delete_playset(self.playset.id)
        except BackendError as error:
            QMessageBox.warning(self, "No se pudo borrar", str(error))
            return
        self.playsets = self.backend.read_playsets()
        self._set_dirty(False)
        self._refresh_playset_box()

    def export_playset(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        game = self._current_game()
        if game is None or self.playset is None:
            return
        destino, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar playset",
            f"{self.playset.name}.loadstone.json",
            "Playsets de Loadstone (*.json)",
        )
        if not destino:
            return
        try:
            archivo = export_playset(self.playset, self.mods, game.key, Path(destino))
        except OSError as error:
            QMessageBox.warning(self, "No se pudo exportar", str(error))
            return
        QMessageBox.information(
            self,
            "Playset exportado",
            f"'{archivo.name}' con {len(archivo.mods)} mods.\n\n{destino}",
        )

    def import_playset(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        if self.backend is None or self.playset is None:
            return
        origen, _ = QFileDialog.getOpenFileName(
            self, "Importar playset", "", "Playsets de Loadstone (*.json)"
        )
        if not origen:
            return
        try:
            archivo = read_playset_file(Path(origen))
        except ValueError as error:
            QMessageBox.warning(self, "No se pudo importar", str(error))
            return

        colocados, faltantes = import_playset(archivo, self.playset, list(self.mods.values()))
        aviso = (
            f"'{archivo.name}': {colocados} mods colocados en "
            f"'{self.playset.name}'."
        )
        if faltantes:
            aviso += f"\n\n{len(faltantes)} no estan instalados:\n  " + "\n  ".join(
                faltantes[:8]
            )
        aviso += "\n\nNada se guarda hasta que pulses Guardar."
        QMessageBox.information(self, "Playset importado", aviso)
        self._set_dirty(True)
        self.populate()

    # --------------------------------------------------------- herramientas

    def _require_game(self) -> bool:
        if self.backend is None or self._current_game() is None:
            QMessageBox.information(
                self, "Sin juego", "Primero selecciona un juego con datos."
            )
            return False
        return True

    def open_search(self) -> None:
        if self._require_game():
            SearchDialog(self, list(self.mods.values()), self.playset).exec()

    def open_updates(self) -> None:
        if self._require_game():
            UpdatesDialog(
                self,
                list(self.mods.values()),
                self._current_game(),
                self.backend,
                lambda: self._on_game_changed(self.game_box.currentIndex()),
            ).exec()

    def open_conflicts(self) -> None:
        if not self._require_game() or self.playset is None:
            return
        orden = [
            self.mods[uid] for uid in self.playset.enabled_uids() if uid in self.mods
        ]
        ConflictsDialog(self, orden).exec()

    def open_dlc(self) -> None:
        if not self._require_game() or self.playset is None:
            return
        game = self._current_game()
        assert game is not None and self.backend is not None
        DlcDialog(self, game, self.playset, self.backend).exec()

    def open_download(self) -> None:
        if not self._require_game():
            return
        game = self._current_game()
        assert game is not None and self.backend is not None
        DownloadDialog(
            self, game, self.backend, lambda: self._on_game_changed(self.game_box.currentIndex())
        ).exec()

    def open_workshop(self) -> None:
        if not self._require_game():
            return
        game = self._current_game()
        assert game is not None and self.backend is not None
        if game.steam_appid is None:
            QMessageBox.information(
                self,
                "Sin Workshop",
                f"De {game.display_name} no se conoce el appid de Steam, "
                "asi que no hay Workshop que explorar.",
            )
            return
        # Importado aqui y no arriba a proposito: arrastra QtWebEngine, que son
        # 130 MB y un par de segundos. Quien no abra el navegador no los paga.
        try:
            from .workshop import WorkshopBrowserDialog
        except ImportError as error:
            QMessageBox.warning(
                self,
                "Falta el navegador",
                "Esta instalacion no trae QtWebEngine, asi que el navegador "
                "empotrado no esta disponible.\n\nPuedes seguir anadiendo mods "
                "con 'Descargar del Workshop por enlace...' (Ctrl+D).\n\n"
                f"Detalle: {error}",
            )
            return
        WorkshopBrowserDialog(
            self, game, self.backend, lambda: self._on_game_changed(self.game_box.currentIndex())
        ).exec()

    def open_history(self) -> None:
        if not self._require_game():
            return
        game = self._current_game()
        assert game is not None

        def restaurada() -> None:
            self.populate()
            self._set_dirty(True)

        HistoryDialog(self, game, self.playset, list(self.mods.values()), restaurada).exec()

    # ---------------------------------------------------- menu contextual

    def _mod_context_menu(self, lista: ModListWidget, punto) -> None:
        """Lo que se puede hacer con un mod concreto, donde se busca: encima.

        Las acciones que solo tienen sentido con un mod se desactivan en vez de
        esconderse cuando hay varios seleccionados: un menu que cambia de
        tamano segun lo que haya marcado obliga a volver a leerlo cada vez.
        """
        uids = lista.selected_uids()
        if not uids:
            uid = lista.current_uid()
            if uid is None:
                return
            uids = [uid]

        mods = [self.mods[uid] for uid in uids if uid in self.mods]
        if not mods:
            return
        uno = mods[0] if len(mods) == 1 else None

        menu = QMenu(self)

        abrir = menu.addAction("Abrir la carpeta del mod")
        abrir.setEnabled(uno is not None and uno.folder is not None)
        abrir.triggered.connect(lambda: self._open_mod_folder(mods[0]))

        workshop = menu.addAction("Ver en el Workshop")
        workshop.setEnabled(uno is not None and bool(uno.steam_id))
        workshop.triggered.connect(lambda: self._open_workshop_page(mods[0]))

        menu.addSeparator()
        etiqueta = (
            f"Desinstalar '{mods[0].name}'..."
            if uno is not None
            else f"Desinstalar {len(mods)} mods..."
        )
        desinstalar = menu.addAction(etiqueta)
        desinstalar.triggered.connect(lambda: self.uninstall_mods(mods))

        menu.exec(lista.viewport().mapToGlobal(punto))

    def _open_mod_folder(self, mod: Mod) -> None:
        if mod.folder is None:
            return
        try:
            open_in_file_manager(mod.folder)
        except OSError as error:
            QMessageBox.warning(self, "No se pudo abrir", str(error))

    def _open_workshop_page(self, mod: Mod) -> None:
        if not mod.steam_id:
            return
        QDesktopServices.openUrl(
            QUrl(f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod.steam_id}")
        )

    def uninstall_mods(self, mods: list[Mod]) -> None:
        """Borra mods del disco, del registro y de todos los playsets."""
        if not self._require_game() or not mods:
            return
        game = self._current_game()
        assert game is not None and self.backend is not None
        backend = self.backend

        # Desinstalar escribe los playsets en el juego, y los escribe tal y
        # como estan en memoria. Con cambios a medias se colarian ademas esas
        # ediciones, que nadie ha pedido guardar todavia. Antes de tocar nada
        # se exige decidir sobre ellas.
        if self.dirty:
            QMessageBox.information(
                self,
                "Hay cambios sin guardar",
                "Desinstalar reescribe los playsets en el juego, asi que "
                "arrastraria tambien los cambios que tienes a medias.\n\n"
                "Pulsa Guardar o Revertir y vuelve a intentarlo.",
            )
            return

        def terminado() -> None:
            # Los playsets ya se han escrito en el juego, asi que lo que haya
            # en pantalla esta obsoleto: se recarga todo en vez de parchearlo.
            self._set_dirty(False)
            self._on_game_changed(self.game_box.currentIndex())

        UninstallDialog(
            self,
            game,
            mods,
            self.playsets,
            backend.save_playset,
            backend.unregister_mod,
            terminado,
        ).exec()

    def open_quarantine(self) -> None:
        QuarantineDialog(
            self, lambda: self._on_game_changed(self.game_box.currentIndex())
        ).exec()

    def open_cleanup(self) -> None:
        if not self._require_game():
            return
        game = self._current_game()
        assert game is not None and self.backend is not None
        CleanupDialog(
            self,
            game,
            list(self.mods.values()),
            self.playsets,
            self.backend.unregister_mod,
            lambda: self._on_game_changed(self.game_box.currentIndex()),
        ).exec()

    # ------------------------------------------------------------- cierre

    def _confirm_discard(self) -> bool:
        """Pregunta antes de perder cambios. `True` si se puede continuar."""
        if not self.dirty:
            return True
        respuesta = QMessageBox.question(
            self,
            "Cambios sin guardar",
            "Hay cambios en el playset que no se han guardado. Descartarlos?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if respuesta == QMessageBox.StandardButton.Discard:
            self._set_dirty(False)
            return True
        return False

    def closeEvent(self, event) -> None:
        self.detail.commit_note()
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
