"""Lo que el usuario dispara: las herramientas y el menu contextual.

Se separa de `main_window` por donde se partia solo. Todo lo de aqui responde a
la misma forma —alguien pulsa algo, se abre una ventana o se lanza una accion
sobre unos mods— y nada de ello participa en montar ni refrescar la ventana
principal, que es lo que hace el resto del modulo. Con cada funcion nueva
aterrizando en el mismo archivo, ese archivo habia pasado de 700 lineas a 1300.

Es un mixin y no un modulo de funciones sueltas porque todas necesitan lo mismo
—el juego actual, el backend, los mods, el playset— y pasarselo por parametro a
una docena de metodos seria el mismo acoplamiento escrito mas largo. Lo que si
cambia es que ahora se ve de un vistazo que depende de que: todo lo de aqui usa
`self` como ventana, y nada de aqui lo usa como estado propio.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMenu, QMessageBox

from ..core.launch import open_in_file_manager
from ..core.models import Mod
from ..core.repair import plan_repair
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
from .widgets import ModListWidget

__all__ = ["ToolActionsMixin"]


class ToolActionsMixin:
    """Las acciones de las barras de menu y del clic derecho.

    Pensado para `MainWindow` y solo para ella: da por hecho `self.mods`,
    `self.playsets`, `self.backend`, `self.playset` y los metodos de recarga.
    """

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
        ConflictsDialog(
            self,
            orden,
            self._current_game(),
            lambda: self._on_game_changed(self.game_box.currentIndex()),
        ).exec()

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
