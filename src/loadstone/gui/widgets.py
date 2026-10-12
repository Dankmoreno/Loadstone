"""Piezas de interfaz propias: las listas de mods y el panel de detalle.

La ventana tiene dos listas, como el gestor que sirvio de referencia: a la
izquierda lo instalado que no esta en el playset, a la derecha lo que si, en su
orden de carga. Arrastrar entre ellas es la forma natural de componer un
playset, y arrastrar dentro de la derecha es como se ordena.

Se mantiene la distincion que Paradox hace y que RimWorld no tiene: un mod
puede estar **en** el playset y a la vez **desactivado**. Por eso la lista
derecha tiene casillas y la izquierda no.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Mod
from .theme import current_palette

__all__ = ["AVISO", "UID_ROLE", "DetailPanel", "ModListWidget"]

AVISO = "⚠"
"""Marca de que falta el contenido de un mod.

Un simbolo y no una letra: sobrevive al truncado del nombre y no depende
del idioma. Va delante porque el final de la columna se corta.
"""

UID_ROLE = Qt.ItemDataRole.UserRole

def _rojo() -> QColor:
    """El mod que no esta donde deberia. Se consulta al pintar, no al importar:
    el esquema del sistema puede cambiar con la ventana ya abierta."""
    return QColor(current_palette().error)


def _gris() -> QColor:
    """El que esta en la lista pero desactivado."""
    return QColor(current_palette().texto_apagado)


class ModListWidget(QTreeWidget):
    """Lista de mods que acepta arrastres desde su pareja."""

    mods_dropped = Signal(list)
    """Uids que se han soltado aqui viniendo de la otra lista."""

    order_changed = Signal()
    enabled_changed = Signal(str, bool)

    def __init__(self, *, with_checkboxes: bool, numbered: bool) -> None:
        super().__init__()
        self._with_checkboxes = with_checkboxes
        self._numbered = numbered

        columnas = ["", "#", "Mod", "Version"] if numbered else ["Mod", "Version"]
        self.setHeaderLabels(columnas)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)

        encabezado = self.header()
        if numbered:
            self.setColumnWidth(0, 28)
            self.setColumnWidth(1, 42)
            encabezado.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            self.setColumnWidth(3, 90)
        else:
            encabezado.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            self.setColumnWidth(1, 90)

        self.itemChanged.connect(self._on_item_changed)
        self.model().rowsMoved.connect(self.order_changed)

    # ------------------------------------------------------------ contenido

    def add_mod(self, mod: Mod | None, uid: str, *, enabled: bool, position: int) -> None:
        nombre = mod.name if mod else f"(desconocido: {uid})"
        version = (mod.version or mod.supported_version or "-") if mod else "-"
        # El contenido que falta llevaba el aviso solo en el color. Alrededor de
        # un 8% de los hombres no distingue ese rojo del texto normal, y con 213
        # filas identicas la informacion desaparecia por completo para ellos.
        # El simbolo dice lo mismo sin depender de la vista de nadie.
        falta = mod is None or not mod.on_disk
        if falta:
            nombre = f"{AVISO} {nombre}"
        textos = (
            ["", str(position + 1), nombre, version] if self._numbered else [nombre, version]
        )
        item = QTreeWidgetItem(textos)
        item.setData(0, UID_ROLE, uid)
        banderas = item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled
        if self._with_checkboxes:
            item.setFlags(banderas | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0, Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
            )
        else:
            item.setFlags(banderas)

        columna_nombre = 2 if self._numbered else 0
        if falta:
            item.setForeground(columna_nombre, QBrush(_rojo()))
            item.setToolTip(
                columna_nombre,
                "El launcher lo lista pero su contenido no esta en disco: "
                "el juego no lo cargara.",
            )
        elif self._with_checkboxes and not enabled:
            # Aqui el color es el refuerzo y no el mensaje: la casilla sin
            # marcar ya dice que esta desactivado, y eso no es un color.
            item.setForeground(columna_nombre, QBrush(_gris()))
        self.addTopLevelItem(item)

    def uids(self) -> list[str]:
        return [
            self.topLevelItem(i).data(0, UID_ROLE) for i in range(self.topLevelItemCount())
        ]

    def selected_uids(self) -> list[str]:
        return [item.data(0, UID_ROLE) for item in self.selectedItems()]

    def current_uid(self) -> str | None:
        item = self.currentItem()
        return item.data(0, UID_ROLE) if item else None

    def renumber(self) -> None:
        if not self._numbered:
            return
        for indice in range(self.topLevelItemCount()):
            self.topLevelItem(indice).setText(1, str(indice + 1))

    def apply_filter(self, texto: str) -> int:
        """Oculta lo que no casa y devuelve cuantos quedan visibles."""
        aguja = texto.strip().lower()
        columna = 2 if self._numbered else 0
        visibles = 0
        for indice in range(self.topLevelItemCount()):
            item = self.topLevelItem(indice)
            oculto = bool(aguja) and aguja not in item.text(columna).lower()
            item.setHidden(oculto)
            visibles += not oculto
        return visibles

    # -------------------------------------------------------------- eventos

    def _on_item_changed(self, item: QTreeWidgetItem, columna: int) -> None:
        if columna == 0 and self._with_checkboxes:
            uid = item.data(0, UID_ROLE)
            if uid:
                self.enabled_changed.emit(
                    uid, item.checkState(0) == Qt.CheckState.Checked
                )

    def dropEvent(self, event) -> None:
        """Separa el reordenado interno del traspaso entre listas."""
        origen = event.source()
        if origen is self:
            super().dropEvent(event)
            self.renumber()
            self.order_changed.emit()
            return

        if isinstance(origen, ModListWidget):
            uids = [u for u in origen.selected_uids() if u]
            if uids:
                event.setDropAction(Qt.DropAction.IgnoreAction)
                event.accept()
                # El movimiento real lo decide la ventana, que es quien sabe
                # que significa aqui "activar" o "desactivar" un mod.
                self.mods_dropped.emit(uids)
                return
        event.ignore()


class DetailPanel(QWidget):
    """Ficha del mod seleccionado."""

    note_changed = Signal(str, str)
    """`(registry_id, texto)` cuando el usuario termina de escribir."""

    def __init__(self) -> None:
        super().__init__()
        self._registry_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.thumbnail = QLabel()
        self.thumbnail.setMinimumHeight(150)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setStyleSheet("border: 1px solid palette(mid);")
        layout.addWidget(self.thumbnail)

        self.titulo = QLabel("Ningun mod seleccionado")
        fuente = QFont()
        fuente.setBold(True)
        self.titulo.setFont(fuente)
        self.titulo.setWordWrap(True)
        layout.addWidget(self.titulo)

        self.formulario = QFormLayout()
        self.formulario.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.campos: dict[str, QLabel] = {}
        for clave, etiqueta in (
            ("version", "Version:"),
            ("supported", "Soporta:"),
            ("tags", "Etiquetas:"),
            ("steam", "Workshop:"),
            ("size", "Tamano:"),
            ("state", "Estado:"),
            ("path", "Ruta:"),
        ):
            valor = QLabel("-")
            valor.setWordWrap(True)
            valor.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            valor.setOpenExternalLinks(True)
            self.campos[clave] = valor
            self.formulario.addRow(etiqueta, valor)
        layout.addLayout(self.formulario)

        layout.addWidget(QLabel("Notas:"))
        self.notas = QPlainTextEdit()
        self.notas.setPlaceholderText(
            "Para que te acuerdes de por que este mod esta donde esta."
        )
        self.notas.setMaximumHeight(110)
        self.notas.setEnabled(False)
        layout.addWidget(self.notas)
        layout.addStretch(1)

    def focusOutEvent(self, event) -> None:
        self.commit_note()
        super().focusOutEvent(event)

    def commit_note(self) -> None:
        if self._registry_id:
            self.note_changed.emit(self._registry_id, self.notas.toPlainText())

    def show_mod(self, mod: Mod | None, *, nota: str = "", size: int | None = None) -> None:
        self.commit_note()
        if mod is None:
            self._registry_id = None
            self.titulo.setText("Ningun mod seleccionado")
            self.thumbnail.clear()
            for valor in self.campos.values():
                valor.setText("-")
            self.notas.clear()
            self.notas.setEnabled(False)
            return

        self._registry_id = mod.registry_id
        self.titulo.setText(mod.name)
        self.campos["version"].setText(mod.version or "-")
        self.campos["supported"].setText(mod.supported_version or "-")
        self.campos["tags"].setText(", ".join(mod.tags) if mod.tags else "-")
        if mod.steam_id:
            url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod.steam_id}"
            self.campos["steam"].setText(f'<a href="{url}">{mod.steam_id}</a>')
        else:
            self.campos["steam"].setText("no viene del Workshop")
        self.campos["size"].setText(
            f"{size / 1024 / 1024:.1f} MB" if size else "-"
        )
        self.campos["state"].setText(self._state_text(mod))
        destino = mod.folder or mod.archive
        if destino:
            self.campos["path"].setText(
                f'<a href="file:///{destino.as_posix()}">{destino}</a>'
            )
        else:
            self.campos["path"].setText("-")

        self._set_thumbnail(mod)
        self.notas.setEnabled(bool(mod.registry_id))
        self.notas.setPlainText(nota)

    @staticmethod
    def _state_text(mod: Mod) -> str:
        if mod.parse_error:
            return "descriptor con error"
        if mod.is_dangling:
            return "sin contenido en disco"
        if mod.registry_id is None:
            return "el juego no lo ve"
        if mod.is_archived:
            return "comprimido"
        return "correcto"

    def _set_thumbnail(self, mod: Mod) -> None:
        self.thumbnail.clear()
        carpeta: Path | None = mod.folder
        if carpeta is None or not carpeta.is_dir():
            self.thumbnail.setText("(sin imagen)")
            return
        for nombre in ("thumbnail.png", "thumbnail.jpg", "thumbnail.jpeg"):
            archivo = carpeta / nombre
            if not archivo.is_file():
                continue
            imagen = QPixmap(str(archivo))
            if imagen.isNull():
                continue
            self.thumbnail.setPixmap(
                imagen.scaled(
                    QSize(self.thumbnail.width() or 260, 150),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            return
        # Las miniaturas en .dds son habituales y Qt no las lee sin plugin.
        self.thumbnail.setText("(sin imagen)")
