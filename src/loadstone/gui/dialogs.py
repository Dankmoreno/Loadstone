"""Dialogos de las herramientas: busqueda, actualizaciones, historial y limpieza.

Todos siguen la misma forma: el trabajo lento se lanza con `Task`, la ventana
sigue respondiendo, y nada se borra ni se escribe sin que el usuario lo pida
explicitamente.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..core.backends import Backend, BackendError
from ..core.cleanup import CleanupKind, execute_cleanup, plan_cleanup
from ..core.conflicts import find_conflicts
from ..core.dlc import scan_dlc
from ..core.history import History, diff_snapshots, restore_into
from ..core.install import InstallError, install_mod
from ..core.models import GameProfile, Mod, Playset
from ..core.quarantine import (
    DIAS_EN_CUARENTENA,
    QuarantineEntry,
    list_entries,
    purge,
    restore,
)
from ..core.repair import RepairPlan
from ..core.search import SearchOptions, SearchScope, search_mods, select_scope
from ..core.steamcmd import SteamCmd
from ..core.uninstall import UninstallPlan, execute_uninstall, plan_uninstall
from ..core.updates import UpdateState, check_updates
from ..core.workshop_api import (
    WorkshopApiError,
    collection_items,
    parse_workshop_id,
    published_file_details,
)
from .tasks import Task
from .theme import current_palette

__all__ = [
    "CleanupDialog",
    "ConflictsDialog",
    "DlcDialog",
    "DownloadDialog",
    "HistoryDialog",
    "QuarantineDialog",
    "RepairDialog",
    "SearchDialog",
    "UninstallDialog",
    "UpdatesDialog",
    "download_and_install",
    "resolve_workshop_input",
]

def _rojo() -> QColor:
    return QColor(current_palette().error)


def _ambar() -> QColor:
    return QColor(current_palette().aviso)


def _apagado() -> str:
    """Para los textos de apoyo: notas al pie, unidades, advertencias suaves."""
    return f"color: {current_palette().texto_apagado}"


def resolve_workshop_input(textos: list[str]) -> tuple[list[str], dict]:
    """Convierte lo que alguien pego en ids reales, con sus datos de Steam.

    Acepta ids, enlaces de mod y enlaces de coleccion mezclados; las
    colecciones se expanden en los mods que contienen. Es trabajo de red, asi
    que se llama siempre desde un hilo.
    """
    ids: list[str] = []
    for texto in textos:
        identificador = parse_workshop_id(texto)
        if identificador is None:
            continue
        # Si es una coleccion devuelve sus mods; si no, falla y se trata como
        # un mod suelto.
        try:
            hijos = collection_items(identificador)
        except WorkshopApiError:
            hijos = []
        ids.extend(hijos or [identificador])
    unicos = list(dict.fromkeys(ids))
    return unicos, published_file_details(unicos)


def download_and_install(
    game: GameProfile, backend: Backend, ids: list[str]
) -> list[tuple[str, str]]:
    """Baja los ids con SteamCMD y los deja instalados y dados de alta.

    Devuelve un parte por item, `(id, estado)`, en vez de lanzar: con veinte
    mods en marcha, que uno falle no puede tirar los diecinueve restantes.
    Vive aqui, fuera de cualquier dialogo, porque tanto la descarga por enlace
    como el navegador del Workshop terminan en exactamente este paso.
    """
    if game.steam_appid is None:
        raise BackendError(f"{game.display_name}: no tiene appid de Steam conocido")

    steamcmd = SteamCmd.find() or SteamCmd.bootstrap()
    informe: list[tuple[str, str]] = []
    for resultado in steamcmd.download(game.steam_appid, ids):
        if not resultado.ok or resultado.path is None:
            informe.append((resultado.item_id, f"fallo: {resultado.error}"))
            continue
        try:
            mod = install_mod(
                game,
                resultado.path,
                mod_id=resultado.item_id,
                remote_file_id=resultado.item_id,
                overwrite=True,
            )
            backend.register_mod(mod)
            informe.append((resultado.item_id, f"instalado: {mod.name}"))
        except (InstallError, BackendError) as error:
            informe.append((resultado.item_id, f"descargado, sin instalar: {error}"))
    return informe


class _BaseDialog(QDialog):
    """Lo comun: una barra de progreso y una tarea en segundo plano."""

    def __init__(self, parent: Any, titulo: str, ancho: int = 900, alto: int = 560) -> None:
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(ancho, alto)
        self._task: Task | None = None
        self._pending: tuple[Callable[[], Any], Callable[[Any], None], str] | None = None
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)

    def run_task(
        self,
        work: Callable[[], Any],
        on_done: Callable[[Any], None],
        *,
        busy_text: str = "",
    ) -> None:
        if self._task is not None and self._task.isRunning():
            # Descartarla dejaria la interfaz mostrando un resultado que no
            # corresponde a lo que el usuario acaba de pedir: se encola y se
            # lanza en cuanto termine la actual.
            self._pending = (work, on_done, busy_text)
            return
        self.progress.setFormat(busy_text)
        self.progress.setVisible(True)
        self._task = Task(work, self)
        self._task.finished_ok.connect(lambda r: self._finish(on_done, r))
        self._task.failed.connect(self._error)
        self._task.start()

    def _finish(self, on_done: Callable[[Any], None], resultado: Any) -> None:
        self.progress.setVisible(False)
        # La senal se emite desde dentro de `run()`, asi que el hilo todavia
        # figura como activo: sin soltarlo aqui, la tarea encolada se volveria
        # a encolar a si misma y no se ejecutaria nunca. El objeto no se
        # destruye porque el dialogo sigue siendo su padre.
        self._task = None
        if self._pending is not None:
            pendiente, self._pending = self._pending, None
            self.run_task(pendiente[0], pendiente[1], busy_text=pendiente[2])
            return
        on_done(resultado)

    def _error(self, mensaje: str) -> None:
        self.progress.setVisible(False)
        QMessageBox.warning(self, "No se pudo completar", mensaje)


class SearchDialog(_BaseDialog):
    """Busca texto o rutas dentro de los archivos de los mods."""

    def __init__(self, parent: Any, mods: list[Mod], playset: Playset | None) -> None:
        super().__init__(parent, "Buscar en los archivos de los mods", 980, 600)
        self._mods = mods
        self._playset = playset

        layout = QVBoxLayout(self)

        fila = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("texto a buscar, o parte de una ruta")
        self.query.returnPressed.connect(self.buscar)
        fila.addWidget(self.query, 1)
        self.boton = QPushButton("Buscar")
        self.boton.clicked.connect(self.buscar)
        fila.addWidget(self.boton)
        layout.addLayout(fila)

        opciones = QHBoxLayout()
        opciones.addWidget(QLabel("En:"))
        self.scope = QComboBox()
        for scope in SearchScope:
            self.scope.addItem(f"mods {scope.value}", scope)
        opciones.addWidget(self.scope)
        self.en_rutas = QCheckBox("Buscar en rutas de archivo")
        self.en_rutas.setToolTip(
            "Para saber que mods tocan un mismo archivo, que es el origen de\n"
            "casi todos los conflictos en los juegos de Paradox."
        )
        opciones.addWidget(self.en_rutas)
        self.mayusculas = QCheckBox("Distinguir mayusculas")
        opciones.addWidget(self.mayusculas)
        self.regex = QCheckBox("Expresion regular")
        opciones.addWidget(self.regex)
        self.traducciones = QCheckBox("Incluir traducciones")
        opciones.addWidget(self.traducciones)
        opciones.addStretch(1)
        layout.addLayout(opciones)

        self.resultados = QTreeWidget()
        self.resultados.setHeaderLabels(["Mod / archivo", "Linea", "Contenido"])
        self.resultados.setColumnWidth(0, 330)
        self.resultados.setColumnWidth(1, 60)
        self.resultados.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.resultados, 1)

        layout.addWidget(self.progress)
        self.estado = QLabel("Escribe algo y pulsa Buscar.")
        layout.addWidget(self.estado)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

    def buscar(self) -> None:
        texto = self.query.text().strip()
        if not texto:
            return
        # Qt devuelve el dato del combo como cadena, no como miembro del enum.
        scope = SearchScope(self.scope.currentData())
        objetivo = self._mods
        if scope is not SearchScope.ALL and self._playset is not None:
            objetivo = select_scope(self._mods, set(self._playset.enabled_uids()), scope)

        opciones = SearchOptions(
            query=texto,
            regex=self.regex.isChecked(),
            case_sensitive=self.mayusculas.isChecked(),
            in_paths=self.en_rutas.isChecked(),
            skip_translations=not self.traducciones.isChecked(),
        )
        self.resultados.clear()
        self.estado.setText(f"Buscando en {len(objetivo)} mods...")
        self.boton.setEnabled(False)
        self.run_task(
            lambda: search_mods(objetivo, opciones),
            self._mostrar,
            busy_text="buscando...",
        )

    def _mostrar(self, hits: list) -> None:
        self.boton.setEnabled(True)
        por_mod: dict[str, list] = {}
        for hit in hits:
            por_mod.setdefault(hit.mod.name, []).append(hit)

        for nombre, encontrados in por_mod.items():
            padre = QTreeWidgetItem([f"{nombre}  ({len(encontrados)})", "", ""])
            for hit in encontrados:
                padre.addChild(
                    QTreeWidgetItem(
                        [
                            hit.path.as_posix(),
                            str(hit.line_number) if hit.line_number else "",
                            hit.line[:200],
                        ]
                    )
                )
            self.resultados.addTopLevelItem(padre)
        if len(por_mod) <= 8:
            self.resultados.expandAll()
        self.estado.setText(f"{len(hits)} coincidencias en {len(por_mod)} mods")


class UpdatesDialog(_BaseDialog):
    """Compara los mods instalados con el Workshop."""

    def __init__(self, parent: Any, mods: list[Mod]) -> None:
        super().__init__(parent, "Actualizaciones disponibles", 940, 560)
        self._mods = mods

        layout = QVBoxLayout(self)
        self.resumen = QLabel("Consultando a Steam...")
        layout.addWidget(self.resumen)

        self.tabla = QTreeWidget()
        self.tabla.setHeaderLabels(["Mod", "Estado", "Detalle"])
        self.tabla.setRootIsDecorated(False)
        self.tabla.setColumnWidth(0, 300)
        self.tabla.setColumnWidth(1, 120)
        self.tabla.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tabla, 1)
        layout.addWidget(self.progress)

        self.comando = QLineEdit()
        self.comando.setReadOnly(True)
        self.comando.setPlaceholderText("aqui aparecera el comando para actualizarlos")
        layout.addWidget(self.comando)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self.run_task(
            lambda: check_updates(self._mods), self._mostrar, busy_text="consultando a Steam..."
        )

    def _mostrar(self, estados: list) -> None:
        conteo: dict[UpdateState, int] = {}
        for estado in estados:
            conteo[estado.state] = conteo.get(estado.state, 0) + 1
        self.resumen.setText(
            "  ".join(f"{conteo.get(e, 0)} {e.value}" for e in UpdateState)
        )

        orden = {
            UpdateState.REMOVED: 0,
            UpdateState.OUTDATED: 1,
            UpdateState.UNKNOWN: 2,
            UpdateState.UP_TO_DATE: 3,
        }
        ids: list[str] = []
        for estado in sorted(estados, key=lambda e: orden[e.state]):
            if estado.state is UpdateState.UP_TO_DATE:
                continue
            detalle = estado.reason
            titulo = estado.remote_title
            if titulo and titulo != estado.mod.name:
                detalle += f"  ·  ahora se llama: {titulo}"
            item = QTreeWidgetItem([estado.mod.name, estado.state.value, detalle])
            if estado.state is UpdateState.REMOVED:
                item.setForeground(1, QBrush(_rojo()))
            elif estado.state is UpdateState.OUTDATED:
                item.setForeground(1, QBrush(_ambar()))
                if estado.mod.steam_id:
                    ids.append(estado.mod.steam_id)
            self.tabla.addTopLevelItem(item)

        if ids:
            self.comando.setText("loadstone workshop --force " + " ".join(ids))


class HistoryDialog(_BaseDialog):
    """Instantaneas de la lista de mods, con comparacion y restauracion."""

    def __init__(
        self,
        parent: Any,
        game: GameProfile,
        playset: Playset | None,
        mods: list[Mod],
        on_restored: Callable[[], None],
    ) -> None:
        super().__init__(parent, "Historial de listas de mods", 820, 520)
        self._history = History(game.key)
        self._playset = playset
        self._mods = mods
        self._on_restored = on_restored

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Se guarda una instantanea cada vez que aplicas un playset al juego.")
        )

        self.lista = QTreeWidget()
        self.lista.setHeaderLabels(["Fecha", "Playset", "Mods", "Cambios respecto a la anterior"])
        self.lista.setRootIsDecorated(False)
        self.lista.setColumnWidth(0, 140)
        self.lista.setColumnWidth(1, 160)
        self.lista.setColumnWidth(2, 60)
        self.lista.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.lista, 1)

        fila = QHBoxLayout()
        self.restaurar = QPushButton("Restaurar la seleccionada")
        self.restaurar.clicked.connect(self._restaurar)
        fila.addWidget(self.restaurar)
        fila.addStretch(1)
        layout.addLayout(fila)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self._cargar()

    def _cargar(self) -> None:
        self.lista.clear()
        self._snapshots = self._history.list()
        for indice, snapshot in enumerate(self._snapshots):
            cambios = (
                diff_snapshots(self._snapshots[indice + 1], snapshot).summary()
                if indice + 1 < len(self._snapshots)
                else "la mas antigua"
            )
            item = QTreeWidgetItem(
                [
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(snapshot.created)),
                    snapshot.playset,
                    str(len(snapshot.enabled_ids)),
                    cambios + (f"  — {snapshot.note}" if snapshot.note else ""),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, snapshot.id)
            self.lista.addTopLevelItem(item)
        if not self._snapshots:
            self.lista.addTopLevelItem(QTreeWidgetItem(["(sin instantaneas todavia)", "", "", ""]))
        self.restaurar.setEnabled(bool(self._snapshots) and self._playset is not None)

    def _restaurar(self) -> None:
        item = self.lista.currentItem()
        if item is None or self._playset is None:
            return
        snapshot = self._history.get(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if snapshot is None:
            return

        colocados, faltantes = restore_into(snapshot, self._playset, self._mods)
        aviso = f"Se colocaran {colocados} mods en el playset '{self._playset.name}'."
        if faltantes:
            aviso += (
                f"\n\n{len(faltantes)} mods de la instantanea ya no estan instalados "
                f"y se omiten:\n  " + "\n  ".join(faltantes[:6])
            )
        aviso += "\n\nEl cambio no se guarda hasta que pulses Guardar en la ventana principal."
        QMessageBox.information(self, "Instantanea restaurada", aviso)
        self._on_restored()
        self.accept()


class CleanupDialog(_BaseDialog):
    """Restos en la carpeta de mods, y su borrado."""

    def __init__(
        self,
        parent: Any,
        game: GameProfile,
        mods: list[Mod],
        playsets: list[Playset],
        unregister: Callable[[str], bool],
        on_cleaned: Callable[[], None],
    ) -> None:
        super().__init__(parent, "Limpiar restos", 820, 520)
        self._game = game
        self._mods = mods
        self._playsets = playsets
        self._unregister = unregister
        self._on_cleaned = on_cleaned
        self._plan: list = []

        layout = QVBoxLayout(self)
        self.resumen = QLabel("Analizando la carpeta de mods...")
        layout.addWidget(self.resumen)

        self.incluir_contenido = QCheckBox(
            "Incluir carpetas con contenido (no solo descriptores sueltos)"
        )
        self.incluir_contenido.setToolTip(
            "Carpetas que el juego no ve. Pueden ser restos de un mod borrado a\n"
            "medias, pero tambien un mod que alguien descomprimio a mano."
        )
        self.incluir_contenido.toggled.connect(self._analizar)
        layout.addWidget(self.incluir_contenido)

        self.tabla = QTreeWidget()
        self.tabla.setHeaderLabels(["Elemento", "Tipo", "Tamano", "Motivo"])
        self.tabla.setRootIsDecorated(False)
        self.tabla.setColumnWidth(0, 240)
        self.tabla.setColumnWidth(1, 150)
        self.tabla.setColumnWidth(2, 90)
        self.tabla.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tabla, 1)
        layout.addWidget(self.progress)

        fila = QHBoxLayout()
        self.borrar = QPushButton("Borrar todo lo listado")
        self.borrar.setEnabled(False)
        self.borrar.clicked.connect(self._borrar)
        fila.addWidget(self.borrar)
        fila.addStretch(1)
        layout.addLayout(fila)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self._analizar()

    def _analizar(self) -> None:
        incluir = self.incluir_contenido.isChecked()
        self.tabla.clear()
        self.borrar.setEnabled(False)
        self.run_task(
            lambda: plan_cleanup(
                self._mods,
                self._playsets,
                include_unlinked=incluir,
                mod_dir=self._game.mod_dir if incluir else None,
            ),
            self._mostrar,
            busy_text="analizando...",
        )

    def _mostrar(self, plan: list) -> None:
        self._plan = plan
        total = sum(item.size for item in plan)
        if not plan:
            self.resumen.setText("Nada que limpiar.")
        else:
            liberado = f", liberaria {total / 1024 / 1024:.1f} MB" if total else ""
            self.resumen.setText(f"{len(plan)} elementos para limpiar{liberado}")
        for item in plan:
            fila = QTreeWidgetItem(
                [
                    item.mod.name,
                    item.kind.value,
                    f"{item.size / 1024 / 1024:.1f} MB" if item.size else "",
                    item.reason,
                ]
            )
            if not item.is_safe:
                fila.setForeground(1, QBrush(_ambar()))
            self.tabla.addTopLevelItem(fila)
        self.borrar.setEnabled(bool(plan))

    def _borrar(self) -> None:
        if not self._plan:
            return
        con_contenido = [i for i in self._plan if i.kind is not CleanupKind.DANGLING]
        aviso = f"Se borraran {len(self._plan)} elementos. Esto no se puede deshacer."
        if con_contenido:
            aviso += (
                f"\n\n{len(con_contenido)} de ellos contienen archivos. "
                "Comprueba la lista antes de continuar."
            )
        if QMessageBox.question(
            self,
            "Confirmar borrado",
            aviso,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Ok:
            return

        borrados, errores = execute_cleanup(self._plan, unregister=self._unregister)
        mensaje = f"{borrados} elementos borrados."
        if errores:
            mensaje += "\n\nNo se pudieron borrar:\n  " + "\n  ".join(errores[:6])
        QMessageBox.information(self, "Limpieza terminada", mensaje)
        self._on_cleaned()
        self.accept()


class ConflictsDialog(_BaseDialog):
    """Archivos que varios mods del playset definen a la vez.

    Se ensena en dos vistas porque responden a preguntas distintas: por
    parejas, para ver de un vistazo quien pisa a quien, y por archivo, para
    mirar un caso concreto.
    """

    def __init__(self, parent: Any, mods_en_orden: list[Mod]) -> None:
        super().__init__(parent, "Conflictos entre mods", 1000, 620)
        layout = QVBoxLayout(self)

        self.resumen = QLabel(f"Analizando {len(mods_en_orden)} mods activos...")
        layout.addWidget(self.resumen)
        aviso = QLabel(
            "Gana el que carga el ultimo. Esto compara rutas de archivo, no su "
            "contenido: dos mods en el mismo archivo pueden estar tocando cosas "
            "distintas."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet(_apagado())
        layout.addWidget(aviso)

        self.vista = QComboBox()
        self.vista.addItem("Por parejas de mods", "parejas")
        self.vista.addItem("Por archivo", "archivos")
        self.vista.currentIndexChanged.connect(lambda _i: self._pintar())
        layout.addWidget(self.vista)

        self.tabla = QTreeWidget()
        self.tabla.setRootIsDecorated(False)
        self.tabla.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tabla, 1)
        layout.addWidget(self.progress)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self._informe: Any = None
        self.run_task(
            lambda: find_conflicts(mods_en_orden),
            self._listo,
            busy_text="comparando archivos...",
        )

    def _listo(self, informe: Any) -> None:
        self._informe = informe
        parejas = informe.by_pair()
        self.resumen.setText(
            f"{len(informe.conflicts)} archivos en conflicto entre "
            f"{informe.scanned} mods, en {len(parejas)} parejas"
        )
        self._pintar()

    def _pintar(self) -> None:
        self.tabla.clear()
        if self._informe is None:
            return

        if self.vista.currentData() == "parejas":
            self.tabla.setHeaderLabels(["Mod que pierde", "Lo pisa", "Archivos"])
            # Las dos columnas de nombres se reparten el ancho: truncar el
            # nombre del que gana deja la tabla sin su informacion principal.
            cabecera = self.tabla.header()
            cabecera.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            cabecera.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            cabecera.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            self.tabla.setColumnWidth(2, 80)
            for (perdedor, ganador), cuantos in self._informe.by_pair().items():
                item = QTreeWidgetItem([perdedor, ganador, str(cuantos)])
                if cuantos >= 50:
                    item.setForeground(2, QBrush(_ambar()))
                self.tabla.addTopLevelItem(item)
            return

        self.tabla.setHeaderLabels(["Archivo", "Gana", "Mods"])
        cabecera = self.tabla.header()
        cabecera.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cabecera.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        cabecera.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tabla.setColumnWidth(2, 60)
        for conflicto in self._informe.conflicts:
            nombre = conflicto.winner.name
            if conflicto.replaced:
                nombre += "  (reemplaza la carpeta entera)"
            self.tabla.addTopLevelItem(
                QTreeWidgetItem([conflicto.path, nombre, str(len(conflicto.mods))])
            )


class DlcDialog(_BaseDialog):
    """Activar y desactivar los DLC del playset."""

    def __init__(
        self, parent: Any, game: GameProfile, playset: Playset, backend: Backend
    ) -> None:
        super().__init__(parent, f"DLC de {game.display_name}", 760, 560)
        self._playset = playset
        self._backend = backend

        layout = QVBoxLayout(self)
        self.resumen = QLabel("Leyendo los DLC instalados...")
        layout.addWidget(self.resumen)

        self.tabla = QTreeWidget()
        self.tabla.setHeaderLabels(["DLC", "Tipo", "Carpeta"])
        self.tabla.setRootIsDecorated(False)
        self.tabla.setColumnWidth(0, 300)
        self.tabla.setColumnWidth(1, 110)
        self.tabla.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tabla.itemChanged.connect(self._cambiado)
        layout.addWidget(self.tabla, 1)
        layout.addWidget(self.progress)

        nota = QLabel(
            "El cambio se guarda al momento en el playset, y llega al juego la "
            "proxima vez que pulses Aplicar."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_apagado())
        layout.addWidget(nota)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self.run_task(
            lambda: scan_dlc(game.install_path), self._listo, busy_text="leyendo..."
        )

    def _listo(self, dlcs: list) -> None:
        if not dlcs:
            self.resumen.setText(
                "No se han encontrado DLC. Hace falta localizar la instalacion del juego."
            )
            return
        activos = sum(1 for d in dlcs if self._playset.dlcs.get(d.id, True))
        self.resumen.setText(
            f"{len(dlcs)} DLC instalados, {activos} activos en este playset"
        )

        self.tabla.blockSignals(True)
        for dlc in dlcs:
            item = QTreeWidgetItem([dlc.name, dlc.category or "-", dlc.folder])
            item.setData(0, Qt.ItemDataRole.UserRole, dlc.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                Qt.CheckState.Checked
                if self._playset.dlcs.get(dlc.id, True)
                else Qt.CheckState.Unchecked,
            )
            self.tabla.addTopLevelItem(item)
        self.tabla.blockSignals(False)

    def _cambiado(self, item: QTreeWidgetItem, columna: int) -> None:
        if columna != 0:
            return
        dlc_id = item.data(0, Qt.ItemDataRole.UserRole)
        activo = item.checkState(0) == Qt.CheckState.Checked
        try:
            self._backend.set_dlc_enabled(self._playset, dlc_id, activo)
        except Exception as error:  # noqa: BLE001 - el backend decide su error
            QMessageBox.warning(self, "No se pudo guardar", str(error))


class DownloadDialog(_BaseDialog):
    """Descargar mods del Workshop por id, enlace o coleccion.

    Hace lo que el navegador incrustado de otros gestores sin incrustar un
    navegador: se pegan enlaces, se consulta a la API publica de Steam que son
    antes de bajar nada, y SteamCMD hace el resto.
    """

    def __init__(
        self,
        parent: Any,
        game: GameProfile,
        backend: Backend,
        on_installed: Callable[[], None],
    ) -> None:
        super().__init__(parent, "Descargar del Workshop", 880, 620)
        self._game = game
        self._backend = backend
        self._on_installed = on_installed
        self._ids: list[str] = []

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Pega ids, enlaces de mods o el enlace de una coleccion, uno por linea.")
        )
        self.entrada = QPlainTextEdit()
        self.entrada.setMaximumHeight(90)
        self.entrada.setPlaceholderText(
            "1121692237\n"
            "https://steamcommunity.com/sharedfiles/filedetails/?id=1087781345"
        )
        layout.addWidget(self.entrada)

        fila = QHBoxLayout()
        self.resolver_btn = QPushButton("Comprobar que son")
        self.resolver_btn.clicked.connect(self._resolver)
        fila.addWidget(self.resolver_btn)
        self.saltar_instalados = QCheckBox("Saltar los que ya tengo")
        self.saltar_instalados.setChecked(True)
        fila.addWidget(self.saltar_instalados)
        fila.addStretch(1)
        layout.addLayout(fila)

        self.tabla = QTreeWidget()
        self.tabla.setHeaderLabels(["Id", "Nombre", "Tamano", "Estado"])
        self.tabla.setRootIsDecorated(False)
        self.tabla.setColumnWidth(0, 110)
        self.tabla.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tabla, 1)
        layout.addWidget(self.progress)

        nota = QLabel(
            "De los juegos soportados, solo Stellaris permite la descarga anonima. "
            "En los demas hace falta una cuenta de Steam que posea el juego, y "
            "SteamCMD la pedira por consola."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_apagado())
        layout.addWidget(nota)

        self.descargar_btn = QPushButton("Descargar e instalar")
        self.descargar_btn.setEnabled(False)
        self.descargar_btn.clicked.connect(self._descargar)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.addButton(self.descargar_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

    def _resolver(self) -> None:
        textos = [
            linea.strip()
            for linea in self.entrada.toPlainText().splitlines()
            if linea.strip()
        ]
        if not textos:
            return
        instalados = {mod.steam_id for mod in self._backend.read_mods() if mod.steam_id}
        saltar = self.saltar_instalados.isChecked()

        def trabajo() -> tuple[list[str], dict]:
            return resolve_workshop_input(textos)

        self.resolver_btn.setEnabled(False)
        self.run_task(
            trabajo,
            lambda r: self._resueltos(r, instalados, saltar),
            busy_text="consultando a Steam...",
        )

    def _resueltos(self, resultado: tuple, instalados: set, saltar: bool) -> None:
        self.resolver_btn.setEnabled(True)
        ids, detalles = resultado
        self.tabla.clear()
        self._ids = []

        for identificador in ids:
            detalle = detalles.get(identificador)
            nombre = detalle.title if detalle and detalle.title else "(desconocido)"
            tamano = (
                f"{detalle.file_size / 1024 / 1024:.1f} MB"
                if detalle and detalle.file_size
                else "-"
            )
            if detalle is not None and not detalle.available:
                estado = "ya no esta en el Workshop"
            elif identificador in instalados:
                estado = "ya instalado"
            else:
                estado = "se descargara"

            item = QTreeWidgetItem([identificador, nombre, tamano, estado])
            if estado != "se descargara":
                item.setForeground(3, QBrush(_ambar()))
            self.tabla.addTopLevelItem(item)

            if estado == "se descargara" or (estado == "ya instalado" and not saltar):
                self._ids.append(identificador)

        self.descargar_btn.setEnabled(bool(self._ids))
        self.descargar_btn.setText(f"Descargar e instalar ({len(self._ids)})")

    def _descargar(self) -> None:
        if not self._ids or self._game.steam_appid is None:
            QMessageBox.information(
                self, "No se puede", "Este juego no tiene appid de Steam conocido."
            )
            return

        ids = list(self._ids)
        juego = self._game
        backend = self._backend

        def trabajo() -> list[tuple[str, str]]:
            return download_and_install(juego, backend, ids)

        self.descargar_btn.setEnabled(False)
        self.run_task(trabajo, self._descargado, busy_text="descargando con SteamCMD...")

    def _descargado(self, informe: list[tuple[str, str]]) -> None:
        correctos = sum(1 for _i, estado in informe if estado.startswith("instalado"))
        detalle = "\n".join(f"{i}: {estado}" for i, estado in informe[:12])
        QMessageBox.information(
            self,
            "Descarga terminada",
            f"{correctos} de {len(informe)} instalados.\n\n{detalle}",
        )
        self._on_installed()
        if correctos:
            self.accept()
        else:
            self.descargar_btn.setEnabled(True)


class UninstallDialog(_BaseDialog):
    """Confirmacion de desinstalar mods: que se borra y de donde desaparece.

    Es una ventana y no un `QMessageBox` porque hay tres cosas que decir y
    ninguna cabe en una linea: cuanto espacio se libera, de que playsets va a
    salir el mod, y si su contenido lo gestiona Steam y volvera a aparecer.
    """

    def __init__(
        self,
        parent: Any,
        game: GameProfile,
        mods: list[Mod],
        playsets: list[Playset],
        save_playset: Callable[[Playset], None],
        unregister: Callable[[str], bool],
        on_done: Callable[[], None],
    ) -> None:
        super().__init__(parent, "Desinstalar mods", 760, 480)
        self._game = game
        self._mods = mods
        self._playsets = playsets
        self._save_playset = save_playset
        self._unregister = unregister
        self._on_done = on_done
        self._plans: list[UninstallPlan] = []

        layout = QVBoxLayout(self)
        self.resumen = QLabel("Calculando...")
        self.resumen.setWordWrap(True)
        layout.addWidget(self.resumen)

        self.tabla = QTreeWidget()
        self.tabla.setHeaderLabels(["Mod", "Tamano", "En playsets", "Que se borra"])
        self.tabla.setRootIsDecorated(False)
        self.tabla.setColumnWidth(0, 240)
        self.tabla.setColumnWidth(1, 80)
        self.tabla.setColumnWidth(2, 90)
        self.tabla.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tabla, 1)

        self.incluir_steam = QCheckBox(
            "Borrar tambien el contenido que gestiona Steam"
        )
        self.incluir_steam.setToolTip(
            "Ese contenido vive fuera de la carpeta del juego. Si sigues\n"
            "suscrito en el Workshop, Steam lo volvera a descargar."
        )
        self.incluir_steam.setVisible(False)
        layout.addWidget(self.incluir_steam)

        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        self.aviso.setStyleSheet(f"color: {current_palette().aviso}")
        self.aviso.setVisible(False)
        layout.addWidget(self.aviso)
        layout.addWidget(self.progress)

        self.desinstalar_btn = QPushButton("Desinstalar")
        self.desinstalar_btn.setEnabled(False)
        self.desinstalar_btn.clicked.connect(self._desinstalar)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        botones.addButton(self.desinstalar_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self._analizar()

    def _analizar(self) -> None:
        mods, playsets, mod_dir = self._mods, self._playsets, self._game.mod_dir
        self.run_task(
            lambda: [plan_uninstall(m, playsets, mod_dir=mod_dir) for m in mods],
            self._mostrar,
            busy_text="midiendo lo que ocupan...",
        )

    def _mostrar(self, plans: list[UninstallPlan]) -> None:
        self._plans = plans
        total = sum(plan.size for plan in plans)
        afectados = {p.id for plan in plans for p in plan.playsets}
        self.resumen.setText(
            f"Se van a desinstalar {len(plans)} mod(s), liberando "
            f"{total / 1024 / 1024:.1f} MB. "
            + (
                f"Saldran de {len(afectados)} playset(s)."
                if afectados
                else "No estan en ningun playset."
            )
        )

        for plan in plans:
            nombres = ", ".join(p.name for p in plan.playsets) or "-"
            rutas = ", ".join(r.name for r in plan.paths) or "(nada en disco)"
            fila = QTreeWidgetItem(
                [
                    plan.mod.name,
                    f"{plan.size / 1024 / 1024:.1f} MB" if plan.size else "-",
                    str(len(plan.playsets)),
                    rutas,
                ]
            )
            fila.setToolTip(2, nombres)
            if plan.is_steam_managed:
                fila.setForeground(3, QBrush(_ambar()))
            self.tabla.addTopLevelItem(fila)

        de_steam = [plan for plan in plans if plan.is_steam_managed]
        if de_steam:
            self.incluir_steam.setVisible(True)
            self.aviso.setVisible(True)
            self.aviso.setText(
                f"{len(de_steam)} mod(s) tienen su contenido fuera de la carpeta del "
                "juego, donde lo pone Steam. Por defecto solo se quita el descriptor, "
                "que es lo que hace que el juego deje de verlos; para que no vuelvan, "
                "cancela la suscripcion en el Workshop."
            )
        self.desinstalar_btn.setEnabled(bool(plans))
        self.desinstalar_btn.setText(f"Desinstalar ({len(plans)})")

    def _desinstalar(self) -> None:
        if not self._plans:
            return
        confirmar = QMessageBox.question(
            self,
            "Confirmar",
            f"Se borraran {len(self._plans)} mod(s) del disco. Esto no se puede "
            "deshacer.\n\nLos playsets se guardan en el juego al instante, no "
            "hace falta pulsar Guardar despues.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmar != QMessageBox.StandardButton.Yes:
            return

        plans = self._plans
        incluir = self.incluir_steam.isChecked()
        guardar, quitar = self._save_playset, self._unregister
        self.desinstalar_btn.setEnabled(False)
        self.run_task(
            lambda: execute_uninstall(
                plans,
                save_playset=guardar,
                unregister=quitar,
                include_outside=incluir,
            ),
            self._terminado,
            busy_text="desinstalando...",
        )

    def _terminado(self, resultado: tuple[int, list[str]]) -> None:
        hechos, errores = resultado
        if errores:
            QMessageBox.warning(
                self,
                "Desinstalacion incompleta",
                f"{hechos} de {len(self._plans)} desinstalados.\n\n"
                + "\n".join(errores[:10]),
            )
        else:
            QMessageBox.information(
                self, "Hecho", f"{hechos} mod(s) desinstalados."
            )
        self._on_done()
        self.accept()


class RepairDialog(_BaseDialog):
    """Vuelve a descargar los mods que el launcher lista y no estan en disco.

    No pregunta que descargar: lo que falta ya lo dijo el diagnostico, y los
    ids estaban en la propia base del launcher. Lo unico que hay que decidir
    aqui es si se hace, y eso cabe en un boton.
    """

    def __init__(
        self,
        parent: Any,
        game: GameProfile,
        backend: Backend,
        plan: RepairPlan,
        on_repaired: Callable[[], None],
    ) -> None:
        super().__init__(parent, "Recuperar los mods que faltan", 720, 460)
        self._game = game
        self._backend = backend
        self._plan = plan
        self._on_repaired = on_repaired

        layout = QVBoxLayout(self)
        resumen = QLabel(
            f"El launcher lista {plan.total} mod(s) cuyo contenido no esta en disco. "
            f"{len(plan.recuperables)} tienen id del Workshop y se pueden volver a "
            "descargar."
        )
        resumen.setWordWrap(True)
        layout.addWidget(resumen)

        self.tabla = QTreeWidget()
        self.tabla.setHeaderLabels(["Mod", "Workshop", "Estado"])
        self.tabla.setRootIsDecorated(False)
        self.tabla.setColumnWidth(0, 320)
        self.tabla.setColumnWidth(1, 110)
        self.tabla.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for mod in plan.recuperables:
            self.tabla.addTopLevelItem(
                QTreeWidgetItem([mod.name, mod.steam_id or "-", "se descargara"])
            )
        for mod in plan.perdidos:
            fila = QTreeWidgetItem([mod.name, "-", "sin id: no se puede recuperar"])
            fila.setForeground(2, QBrush(_ambar()))
            self.tabla.addTopLevelItem(fila)
        layout.addWidget(self.tabla, 1)

        if plan.perdidos:
            nota = QLabel(
                f"Los {len(plan.perdidos)} sin id se instalaron a mano y no dejaron "
                "rastro de su origen. Habra que volver a ponerlos desde donde "
                "salieran, o quitarlos del registro con 'Limpiar restos'."
            )
            nota.setWordWrap(True)
            nota.setStyleSheet(_apagado())
            layout.addWidget(nota)

        aviso = QLabel(
            "De los juegos soportados solo Stellaris permite la descarga anonima. "
            "En los demas SteamCMD pedira por consola una cuenta que tenga el juego."
        )
        aviso.setWordWrap(True)
        aviso.setStyleSheet(_apagado())
        layout.addWidget(aviso)
        layout.addWidget(self.progress)

        self.descargar_btn = QPushButton(f"Descargar los {len(plan.recuperables)}")
        self.descargar_btn.setEnabled(plan.hay_algo_que_hacer)
        self.descargar_btn.clicked.connect(self._descargar)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.addButton(self.descargar_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

    def _descargar(self) -> None:
        ids = self._plan.ids
        if not ids:
            return
        juego, backend = self._game, self._backend
        self.descargar_btn.setEnabled(False)
        self.run_task(
            lambda: download_and_install(juego, backend, ids),
            self._descargado,
            busy_text=f"descargando {len(ids)} mods con SteamCMD...",
        )

    def _descargado(self, informe: list[tuple[str, str]]) -> None:
        correctos = sum(1 for _i, estado in informe if estado.startswith("instalado"))
        fallos = [f"{i}: {estado}" for i, estado in informe if not estado.startswith("instalado")]
        texto = f"{correctos} de {len(informe)} recuperados."
        if fallos:
            texto += "\n\nNo se pudieron bajar:\n" + "\n".join(fallos[:10])
        QMessageBox.information(self, "Recuperacion terminada", texto)
        self._on_repaired()
        if correctos:
            self.accept()
        else:
            self.descargar_btn.setEnabled(True)


class QuarantineDialog(_BaseDialog):
    """La papelera: lo desinstalado que todavia se puede devolver a su sitio."""

    def __init__(self, parent: Any, on_restored: Callable[[], None]) -> None:
        super().__init__(parent, "Papelera de mods", 760, 480)
        self._on_restored = on_restored
        self._entradas: list[QuarantineEntry] = []

        layout = QVBoxLayout(self)
        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        layout.addWidget(self.resumen)

        self.tabla = QTreeWidget()
        self.tabla.setHeaderLabels(["Mod", "Desinstalado hace", "Tamano"])
        self.tabla.setRootIsDecorated(False)
        self.tabla.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tabla.setColumnWidth(0, 360)
        self.tabla.setColumnWidth(1, 140)
        self.tabla.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tabla, 1)

        nota = QLabel(
            f"Lo que lleve mas de {DIAS_EN_CUARENTENA} dias aqui se borra solo. "
            "Un mod del Workshop siempre se puede volver a bajar; uno traducido a "
            "mano o con parches propios, no."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(_apagado())
        layout.addWidget(nota)
        layout.addWidget(self.progress)

        fila = QHBoxLayout()
        self.restaurar_btn = QPushButton("Devolver a su sitio")
        self.restaurar_btn.setEnabled(False)
        self.restaurar_btn.clicked.connect(self._restaurar)
        fila.addWidget(self.restaurar_btn)
        self.vaciar_btn = QPushButton("Vaciar la papelera")
        self.vaciar_btn.clicked.connect(self._vaciar)
        fila.addWidget(self.vaciar_btn)
        fila.addStretch(1)
        layout.addLayout(fila)

        self.tabla.itemSelectionChanged.connect(
            lambda: self.restaurar_btn.setEnabled(bool(self.tabla.selectedItems()))
        )

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self._cargar()

    def _cargar(self) -> None:
        self.tabla.clear()
        self.run_task(list_entries, self._mostrar, busy_text="midiendo la papelera...")

    def _mostrar(self, entradas: list[QuarantineEntry]) -> None:
        self._entradas = entradas
        if not entradas:
            self.resumen.setText("La papelera esta vacia.")
            self.vaciar_btn.setEnabled(False)
            return

        total = sum(e.size for e in entradas)
        self.resumen.setText(
            f"{len(entradas)} mod(s) apartados, {total / 1024 / 1024:.1f} MB en total."
        )
        self.vaciar_btn.setEnabled(True)
        for indice, entrada in enumerate(entradas):
            cuando = "hoy" if entrada.dias == 0 else f"{entrada.dias} dia(s)"
            fila = QTreeWidgetItem(
                [entrada.nombre, cuando, f"{entrada.size / 1024 / 1024:.1f} MB"]
            )
            fila.setData(0, Qt.ItemDataRole.UserRole, indice)
            if entrada.dias >= DIAS_EN_CUARENTENA - 3:
                fila.setForeground(1, QBrush(_ambar()))
                fila.setToolTip(1, "A punto de purgarse")
            self.tabla.addTopLevelItem(fila)

    def _seleccionadas(self) -> list[QuarantineEntry]:
        return [
            self._entradas[item.data(0, Qt.ItemDataRole.UserRole)]
            for item in self.tabla.selectedItems()
        ]

    def _restaurar(self) -> None:
        elegidas = self._seleccionadas()
        if not elegidas:
            return
        self.restaurar_btn.setEnabled(False)

        def trabajo() -> list[str]:
            errores: list[str] = []
            for entrada in elegidas:
                errores.extend(restore(entrada))
            return errores

        self.run_task(trabajo, self._restaurado, busy_text="devolviendo a su sitio...")

    def _restaurado(self, errores: list[str]) -> None:
        if errores:
            QMessageBox.warning(
                self, "No se pudo devolver todo", "\n".join(errores[:10])
            )
        else:
            QMessageBox.information(
                self,
                "Hecho",
                "Devueltos a su sitio. Tendras que volver a anadirlos al playset.",
            )
        self._on_restored()
        self._cargar()

    def _vaciar(self) -> None:
        if QMessageBox.question(
            self,
            "Vaciar la papelera",
            f"Se borraran los {len(self._entradas)} mods apartados. "
            "Esto si es definitivo.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.run_task(lambda: purge(dias=0), lambda _n: self._cargar(), busy_text="vaciando...")
