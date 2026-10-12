"""Navegador del Workshop empotrado, al estilo de RimSort.

Vive en su propio modulo por una razon concreta: es lo unico de Loadstone que
necesita QtWebEngine, que son 130 MB de Chromium y un par de segundos de
arranque. Importandolo solo aqui, y solo cuando alguien abre la ventana, el
resto de la aplicacion no paga nada por existir esta.

La sesion se guarda en disco, asi que se entra en Steam una vez y las
siguientes ya se navega identificado: es la diferencia entre poder ver tus
suscripciones y tus colecciones privadas, o no.

Lo que el navegador **no** hace es suscribirse ni descargar por su cuenta. Lo
unico que saca de la pagina es el id del mod que se esta mirando; bajarlo sigue
siendo cosa de SteamCMD, igual que en la descarga por enlace. Asi solo hay un
camino por el que entran mods, y es el que ya estaba probado.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.backends import Backend
from ..core.models import GameProfile
from ..core.paths import browser_profile_dir
from ..core.workshop_api import parse_workshop_id
from .dialogs import _BaseDialog, download_and_install, resolve_workshop_input
from .theme import current_palette

__all__ = ["WorkshopBrowserDialog"]

_INICIO = "https://steamcommunity.com/app/{appid}/workshop/"

_perfil: QWebEngineProfile | None = None


def _profile() -> QWebEngineProfile:
    """Perfil persistente, uno solo para todo el proceso.

    Qt exige que el perfil sobreviva a las paginas que lo usan; si se creara
    por ventana, cerrar el navegador destruiria el perfil mientras su pagina
    todavia se esta desmontando, y eso tira el proceso entero.
    """
    global _perfil
    if _perfil is None:
        carpeta = browser_profile_dir()
        carpeta.mkdir(parents=True, exist_ok=True)
        _perfil = QWebEngineProfile("loadstone")
        _perfil.setPersistentStoragePath(str(carpeta))
        _perfil.setCachePath(str(carpeta / "cache"))
        _perfil.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
    return _perfil


class WorkshopBrowserDialog(_BaseDialog):
    """El Workshop de Steam dentro de la aplicacion, con cola de descarga."""

    def __init__(
        self,
        parent: Any,
        game: GameProfile,
        backend: Backend,
        on_installed: Callable[[], None],
    ) -> None:
        super().__init__(parent, f"Workshop de {game.display_name}", 1280, 820)
        self._game = game
        self._backend = backend
        self._on_installed = on_installed
        self._cola: dict[str, str] = {}
        """Id -> nombre, en el orden en que se fueron anadiendo."""

        self._actual: str | None = None
        """Id del item que se esta mirando, si la pagina es la de un item."""

        self._instalados = {mod.steam_id for mod in backend.read_mods() if mod.steam_id}

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_barra())

        divisor = QSplitter(Qt.Orientation.Horizontal)
        self.vista = QWebEngineView()
        self.vista.setPage(QWebEnginePage(_profile(), self.vista))
        self.vista.urlChanged.connect(self._on_url)
        self.vista.loadFinished.connect(lambda _ok: self._on_url(self.vista.url()))
        divisor.addWidget(self.vista)
        divisor.addWidget(self._build_cola())
        divisor.setStretchFactor(0, 1)
        divisor.setSizes([900, 360])
        layout.addWidget(divisor, 1)

        layout.addLayout(self._build_pie())
        layout.addWidget(self.progress)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self._ir_a_inicio()

    # ------------------------------------------------------------- montaje

    def _build_barra(self) -> QHBoxLayout:
        fila = QHBoxLayout()
        for texto, ancho, accion in (
            ("←", 32, lambda: self.vista.back()),
            ("→", 32, lambda: self.vista.forward()),
            ("⟳", 32, lambda: self.vista.reload()),
            ("Inicio", 64, self._ir_a_inicio),
        ):
            boton = QPushButton(texto)
            boton.setMaximumWidth(ancho)
            boton.clicked.connect(accion)
            fila.addWidget(boton)

        self.barra_url = QLineEdit()
        self.barra_url.returnPressed.connect(self._navegar)
        fila.addWidget(self.barra_url, 1)
        return fila

    def _build_cola(self) -> QWidget:
        panel = QWidget()
        caja = QVBoxLayout(panel)
        caja.setContentsMargins(6, 0, 0, 0)
        caja.addWidget(QLabel("Cola de descarga"))

        self.tabla = QTreeWidget()
        self.tabla.setHeaderLabels(["Id", "Mod"])
        self.tabla.setRootIsDecorated(False)
        self.tabla.setColumnWidth(0, 96)
        self.tabla.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        caja.addWidget(self.tabla, 1)

        fila = QHBoxLayout()
        quitar = QPushButton("Quitar")
        quitar.clicked.connect(self._quitar)
        fila.addWidget(quitar)
        vaciar = QPushButton("Vaciar")
        vaciar.clicked.connect(self._vaciar)
        fila.addWidget(vaciar)
        caja.addLayout(fila)

        self.descargar_btn = QPushButton("Descargar e instalar")
        self.descargar_btn.setEnabled(False)
        self.descargar_btn.clicked.connect(self._descargar)
        caja.addWidget(self.descargar_btn)

        nota = QLabel(
            "De los juegos soportados solo Stellaris permite la descarga anonima. "
            "En los demas SteamCMD pedira por consola una cuenta que tenga el juego."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {current_palette().texto_apagado}")
        caja.addWidget(nota)
        return panel

    def _build_pie(self) -> QHBoxLayout:
        fila = QHBoxLayout()
        self.viendo = QLabel("Navega hasta un mod o una coleccion.")
        self.viendo.setWordWrap(True)
        fila.addWidget(self.viendo, 1)
        self.anadir_btn = QPushButton("Anadir a la cola")
        self.anadir_btn.setEnabled(False)
        self.anadir_btn.clicked.connect(self._anadir_actual)
        fila.addWidget(self.anadir_btn)
        return fila

    # ---------------------------------------------------------- navegacion

    def _ir_a_inicio(self) -> None:
        if self._game.steam_appid is None:
            self.vista.setHtml(
                "<body style='font-family:sans-serif;padding:2em'>"
                "<h2>Sin Workshop</h2><p>De este juego no se conoce el appid de "
                "Steam, asi que no hay Workshop al que ir.</p></body>"
            )
            return
        self.vista.setUrl(QUrl(_INICIO.format(appid=self._game.steam_appid)))

    def _navegar(self) -> None:
        texto = self.barra_url.text().strip()
        if not texto:
            return
        if "://" not in texto:
            texto = f"https://{texto}"
        self.vista.setUrl(QUrl(texto))

    def _on_url(self, url: QUrl) -> None:
        texto = url.toString()
        if not self.barra_url.hasFocus():
            self.barra_url.setText(texto)

        # Solo las paginas de un item llevan id; el resto del Workshop (listas,
        # busquedas, perfiles) no tiene nada que anadir.
        self._actual = (
            parse_workshop_id(texto) if "filedetails" in texto.lower() else None
        )
        if self._actual is None:
            self.viendo.setText("Navega hasta un mod o una coleccion.")
            self.anadir_btn.setEnabled(False)
            return

        # Steam titula sus paginas "Steam Workshop::<nombre del mod>", y ese
        # prefijo repetido en cada linea no aporta nada.
        titulo = self.vista.title() or "este item"
        _, separador, resto = titulo.partition("::")
        if separador:
            titulo = resto.strip() or titulo
        if self._actual in self._cola:
            self.viendo.setText(f"{titulo} ({self._actual}) — ya esta en la cola")
            self.anadir_btn.setEnabled(False)
        elif self._actual in self._instalados:
            self.viendo.setText(f"{titulo} ({self._actual}) — ya lo tienes instalado")
            self.anadir_btn.setEnabled(True)
        else:
            self.viendo.setText(f"{titulo} ({self._actual})")
            self.anadir_btn.setEnabled(True)

    # ---------------------------------------------------------------- cola

    def _anadir_actual(self) -> None:
        identificador = self._actual
        if identificador is None:
            return
        self.anadir_btn.setEnabled(False)
        # Puede ser una coleccion: resolverlo dice de cuantos mods se trata de
        # verdad y como se llaman, que es lo que la cola tiene que mostrar.
        self.run_task(
            lambda: resolve_workshop_input([identificador]),
            self._anadidos,
            busy_text="consultando a Steam...",
        )

    def _anadidos(self, resultado: tuple[list[str], dict]) -> None:
        ids, detalles = resultado
        nuevos = 0
        retirados = 0
        for identificador in ids:
            if identificador in self._cola:
                continue
            detalle = detalles.get(identificador)
            # Borrado, oculto o baneado: SteamCMD no lo puede bajar, asi que
            # encolarlo solo serviria para que fallara mas tarde.
            if detalle is not None and not detalle.available:
                retirados += 1
                continue
            nombre = detalle.title if detalle and detalle.title else "(sin nombre)"
            self._cola[identificador] = nombre
            fila = QTreeWidgetItem([identificador, nombre])
            if identificador in self._instalados:
                fila.setForeground(1, QBrush(current_palette().aviso))
                fila.setToolTip(1, "Ya lo tienes: se reinstalara encima")
            self.tabla.addTopLevelItem(fila)
            nuevos += 1

        self._refrescar_cola()
        if retirados and not nuevos:
            self.viendo.setText(
                "Esto ya no esta en el Workshop: borrado, oculto o retirado. "
                "No hay nada que descargar."
            )
        elif nuevos > 1:
            aviso = f", {retirados} ya no estan" if retirados else ""
            self.viendo.setText(
                f"Era una coleccion: {nuevos} mods anadidos a la cola{aviso}."
            )

    def _quitar(self) -> None:
        for item in self.tabla.selectedItems():
            self._cola.pop(item.text(0), None)
            self.tabla.takeTopLevelItem(self.tabla.indexOfTopLevelItem(item))
        self._refrescar_cola()

    def _vaciar(self) -> None:
        self._cola.clear()
        self.tabla.clear()
        self._refrescar_cola()

    def _refrescar_cola(self) -> None:
        self.descargar_btn.setEnabled(bool(self._cola))
        self.descargar_btn.setText(f"Descargar e instalar ({len(self._cola)})")
        self._on_url(self.vista.url())

    # ------------------------------------------------------------ descarga

    def _descargar(self) -> None:
        if not self._cola:
            return
        ids = list(self._cola)
        juego, backend = self._game, self._backend
        self.descargar_btn.setEnabled(False)
        self.run_task(
            lambda: download_and_install(juego, backend, ids),
            self._descargado,
            busy_text="descargando con SteamCMD...",
        )

    def _descargado(self, informe: list[tuple[str, str]]) -> None:
        correctos = sum(1 for _i, estado in informe if estado.startswith("instalado"))
        detalle = "\n".join(f"{i}: {estado}" for i, estado in informe[:12])
        QMessageBox.information(
            self,
            "Descarga terminada",
            f"{correctos} de {len(informe)} instalados.\n\n{detalle}",
        )
        self._on_installed()
        # Se queda abierto a proposito: lo normal es seguir mirando mods.
        self._instalados = {
            mod.steam_id for mod in self._backend.read_mods() if mod.steam_id
        }
        self._vaciar()
