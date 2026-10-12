"""Paleta y hoja de estilo de la aplicacion.

Antes los colores vivian sueltos: un `"color: gray"` aqui, un `#c0392b` alla,
y tres sitios distintos decidiendo que aspecto tiene un aviso. Eso no se nota
mientras hay cinco, y es imposible de cambiar cuando hay cincuenta.

Aqui estan todos, una vez, con nombre. Lo que el resto del programa pide no es
"ese azul" sino `accento`, y si manana el azul cambia, cambia en un sitio.

**Dos esquemas, no uno.** Es tentador fijar el tema oscuro y acabar antes: los
juegos de Paradox son oscuros y la aplicacion se ve bien. Pero quien tenga
Windows en claro se encontraria una ventana negra entre todas las suyas
blancas, que es exactamente la clase de detalle que hace que un programa
parezca ajeno al sistema. Se lee lo que pide el sistema y se obedece.

El acento sale del propio logo, el azul de la aguja imantada. Los colores de
diagnostico —error, aviso, correcto— se mantienen aparte y no se parecen al
acento a proposito: si una advertencia se confundiera con un boton, el
diagnostico dejaria de cumplir su unica funcion.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication

__all__ = ["Paleta", "apply_theme", "current_palette", "stylesheet"]


@dataclass(frozen=True, slots=True)
class Paleta:
    """Los colores de un esquema, con nombres de lo que son, no de lo que valen."""

    fondo: str
    """El lienzo de la ventana, lo que queda detras de todo."""

    superficie: str
    """Paneles y listas: lo que se levanta un escalon sobre el fondo."""

    superficie_alta: str
    """Cabeceras de tabla, filas alternas, campos de texto."""

    borde: str
    texto: str
    texto_apagado: str
    """Lo secundario: unidades, rutas, notas al pie. Nunca informacion unica."""

    acento: str
    acento_vivo: str
    acento_texto: str
    """Lo que se escribe *encima* del acento. Va aparte porque en claro y en
    oscuro no es el mismo, y adivinarlo es como nacen los textos ilegibles."""

    error: str
    aviso: str
    correcto: str
    seleccion: str
    seleccion_texto: str


OSCURO = Paleta(
    fondo="#14181f",
    superficie="#1b212b",
    superficie_alta="#222935",
    borde="#2d3747",
    texto="#dde3ec",
    texto_apagado="#8d99ab",
    acento="#3fa9e0",
    acento_vivo="#5fc2f2",
    acento_texto="#06131c",
    error="#e06a6a",
    aviso="#d79a3c",
    correcto="#4caf7d",
    seleccion="#2a4f6a",
    seleccion_texto="#f2f7fc",
)

CLARO = Paleta(
    fondo="#eef1f5",
    superficie="#ffffff",
    superficie_alta="#f4f7fa",
    borde="#d3dae3",
    texto="#1a2029",
    texto_apagado="#5d6978",
    acento="#1872ad",
    acento_vivo="#135c88",
    acento_texto="#ffffff",
    error="#c0392b",
    aviso="#9a6b12",
    correcto="#2e7d55",
    seleccion="#cfe4f5",
    seleccion_texto="#10161d",
)


def _es_oscuro() -> bool:
    """Lo que el sistema dice preferir. Ante la duda, oscuro.

    `Unknown` lo devuelven los escritorios que no publican la preferencia. Se
    elige oscuro porque es donde se usa esto: al lado de un juego a pantalla
    completa, de noche.
    """
    hints = QGuiApplication.styleHints()
    if hints is None:
        return True
    return hints.colorScheme() != Qt.ColorScheme.Light


def current_palette() -> Paleta:
    return OSCURO if _es_oscuro() else CLARO


def _aclarar(color: str, cantidad: int) -> str:
    return QColor(color).lighter(cantidad).name()


def stylesheet(paleta: Paleta | None = None) -> str:
    """La hoja de estilo completa para un esquema.

    No se tocan los `::indicator` de casillas ni los `::branch` de los arboles:
    en cuanto se les pone un estilo propio, Qt deja de dibujar el suyo y hay
    que aportar imagenes para cada estado. Una casilla invisible a cambio de
    una esquina redondeada es un mal negocio.
    """
    p = paleta or current_palette()
    return f"""
QWidget {{
    background: {p.fondo};
    color: {p.texto};
    selection-background-color: {p.seleccion};
    selection-color: {p.seleccion_texto};
}}

QMainWindow, QDialog {{ background: {p.fondo}; }}

QMenuBar {{
    background: {p.fondo};
    border-bottom: 1px solid {p.borde};
    padding: 2px 4px;
}}
QMenuBar::item {{
    padding: 6px 12px;
    border-radius: 6px;
    background: transparent;
}}
QMenuBar::item:selected {{ background: {p.superficie_alta}; }}
QMenuBar::item:pressed {{ background: {p.acento}; color: {p.acento_texto}; }}

QMenu {{
    background: {p.superficie};
    border: 1px solid {p.borde};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p.acento}; color: {p.acento_texto}; }}
QMenu::item:disabled {{ color: {p.texto_apagado}; }}
QMenu::separator {{
    height: 1px;
    background: {p.borde};
    margin: 6px 10px;
}}

QLabel {{ background: transparent; }}

QPushButton {{
    background: {p.superficie_alta};
    border: 1px solid {p.borde};
    border-radius: 7px;
    padding: 7px 16px;
    min-height: 18px;
}}
QPushButton:hover {{ background: {_aclarar(p.superficie_alta, 118)}; }}
QPushButton:pressed {{ background: {p.superficie}; }}
QPushButton:disabled {{ color: {p.texto_apagado}; background: {p.superficie}; }}
/* El boton por defecto de cada ventana: Jugar en la principal, la accion que
   la cierra en los dialogos. Solo uno por pantalla, o deja de significar. */
QPushButton:default {{
    background: {p.acento};
    border-color: {p.acento};
    color: {p.acento_texto};
    font-weight: 600;
}}
QPushButton:default:hover {{
    background: {p.acento_vivo};
    border-color: {p.acento_vivo};
}}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {{
    background: {p.superficie_alta};
    border: 1px solid {p.borde};
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: {p.acento};
    selection-color: {p.acento_texto};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {p.acento};
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{ color: {p.texto_apagado}; }}

QComboBox {{
    background: {p.superficie_alta};
    border: 1px solid {p.borde};
    border-radius: 7px;
    padding: 6px 10px;
    min-height: 18px;
}}
QComboBox:hover {{ border-color: {p.acento}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {p.superficie};
    border: 1px solid {p.borde};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}

QTreeWidget, QTreeView, QListView, QTableView {{
    background: {p.superficie};
    alternate-background-color: {p.superficie_alta};
    border: 1px solid {p.borde};
    border-radius: 9px;
    outline: none;
}}
QTreeView::item, QListView::item {{
    padding: 4px 2px;
    border: none;
}}
QTreeView::item:hover, QListView::item:hover {{ background: {p.superficie_alta}; }}
QTreeView::item:selected, QListView::item:selected {{
    background: {p.seleccion};
    color: {p.seleccion_texto};
}}

QHeaderView::section {{
    background: {p.superficie_alta};
    color: {p.texto_apagado};
    border: none;
    border-bottom: 1px solid {p.borde};
    border-right: 1px solid {p.borde};
    padding: 7px 8px;
    font-weight: 600;
}}
QHeaderView::section:last {{ border-right: none; }}

QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.borde};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.texto_apagado}; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p.borde};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p.texto_apagado}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QSplitter::handle:hover {{ background: {p.borde}; }}

QProgressBar {{
    background: {p.superficie_alta};
    border: 1px solid {p.borde};
    border-radius: 7px;
    text-align: center;
    padding: 1px;
    min-height: 16px;
}}
QProgressBar::chunk {{ background: {p.acento}; border-radius: 6px; }}

QStatusBar {{
    background: {p.fondo};
    border-top: 1px solid {p.borde};
    color: {p.texto_apagado};
}}
QStatusBar::item {{ border: none; }}

QToolTip {{
    background: {p.superficie_alta};
    color: {p.texto};
    border: 1px solid {p.borde};
    border-radius: 6px;
    padding: 5px 8px;
}}

QDialogButtonBox QPushButton {{ min-width: 92px; }}
"""


def apply_theme(app: QGuiApplication) -> None:
    """Pinta la aplicacion y se queda atento a si el sistema cambia de tema.

    Windows permite cambiar de claro a oscuro con la aplicacion abierta. Sin
    volver a aplicar la hoja, la ventana se queda con los colores del esquema
    anterior y el resultado es ilegible.
    """
    app.setStyleSheet(stylesheet())
    hints = app.styleHints()
    if hints is not None:
        hints.colorSchemeChanged.connect(lambda _e: app.setStyleSheet(stylesheet()))
