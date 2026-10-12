"""Arranque de la interfaz grafica."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTimer, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from ..core.logs import get_logger, install_excepthook, log_file, setup_logging
from .assets import icon_path
from .main_window import MainWindow
from .theme import apply_theme

_SELFTEST = "--selftest"
_DEBUG = "--debug"


def _load_qt_translations(app: QApplication) -> QTranslator | None:
    """Traduce los botones que pone Qt (Aceptar, Cancelar, Cerrar).

    Sin esto, los dialogos mezclan el texto propio en espanol con los botones
    estandar en ingles. Las traducciones vienen dentro de PySide6, asi que no
    hay nada que descargar; el traductor se devuelve porque Qt no conserva la
    referencia y seria recogido por el recolector de basura.
    """
    traductor = QTranslator(app)
    ruta = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if traductor.load(QLocale.system(), "qtbase", "_", ruta):
        app.installTranslator(traductor)
        return traductor
    return None


def _show_crash(resumen: str, detalle: str) -> None:
    """Ensena un fallo no previsto en lugar de desaparecer sin mas."""
    caja = QMessageBox()
    caja.setIcon(QMessageBox.Icon.Critical)
    caja.setWindowTitle("Loadstone ha fallado")
    caja.setText(
        "Ha ocurrido un error inesperado.\n\n"
        f"{resumen}\n\n"
        "Nada de lo que estuvieras editando se ha escrito en el juego."
    )
    caja.setInformativeText(f"El detalle completo esta en:\n{log_file()}")
    caja.setDetailedText(detalle)
    caja.exec()


def _set_app_icon(app: QApplication) -> None:
    """Pone la marca en la ventana, la barra de tareas y el conmutador.

    En Windows hace falta ademas declarar un AppUserModelID propio: sin el, el
    sistema agrupa la ventana bajo el icono de `python.exe` y ensena el de
    Python en la barra de tareas por mucho que la ventana lleve el suyo.
    """
    ruta = icon_path()
    if ruta is not None:
        app.setWindowIcon(QIcon(str(ruta)))

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Loadstone.ModManager"
            )
        except Exception:  # noqa: BLE001,S110 - cosmetico, nunca motivo de fallo
            # Sin registro a proposito: esto corre antes de que el logger
            # exista, y lo unico que se pierde es el icono de la barra.
            pass


def _selftest_webengine(logger) -> bool:
    """Comprueba que Chromium arranca dentro del paquete.

    El navegador del Workshop son 300 MB de archivos sueltos —el proceso
    auxiliar, los `.pak` de recursos, los locales— que PyInstaller tiene que
    colocar en su sitio. Si falta cualquiera de ellos nada se rompe al
    arrancar: se rompe el dia que alguien abre el menu, que es tarde. Por eso
    la autocomprobacion lo monta aqui, donde el codigo de salida lo cuenta.
    """
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        logger.exception("el paquete no trae QtWebEngine")
        return False
    try:
        vista = QWebEngineView()
        vista.deleteLater()
    except Exception:
        logger.exception("QtWebEngine no arranca en este paquete")
        return False
    logger.info("QtWebEngine disponible")
    return True


def main(argv: list[str] | None = None) -> int:
    """Abre la ventana principal.

    Con `--selftest` monta la ventana sin mostrarla, la cierra sola y sale.
    Existe porque un ejecutable empaquetado no tiene consola donde contar lo
    que le pasa: si falta un plugin de Qt o un modulo, lo unico que se ve es
    que no abre. Asi el codigo de salida responde si el paquete arranca.
    """
    arguments = list(sys.argv if argv is None else argv)
    selftest = _SELFTEST in arguments
    if selftest:
        arguments.remove(_SELFTEST)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    debug = _DEBUG in arguments
    if debug:
        arguments.remove(_DEBUG)

    setup_logging(debug=debug)
    logger = get_logger("gui")
    logger.info("arrancando Loadstone (selftest=%s, debug=%s)", selftest, debug)

    # QtWebEngine, que es lo que mueve el navegador del Workshop, exige
    # compartir el contexto de OpenGL y exige decidirlo antes de que exista la
    # QApplication. Se pone siempre, aunque nadie abra el navegador: el
    # atributo es gratis, pero importar QtWebEngine aqui para averiguar si hace
    # falta costaria 130 MB de Chromium en cada arranque.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    app = QApplication(arguments)
    app.setApplicationName("Loadstone")
    app.setApplicationDisplayName("Loadstone")
    _set_app_icon(app)
    apply_theme(app)
    _load_qt_translations(app)
    # Durante la autocomprobacion no hay nadie mirando: un dialogo modal
    # dejaria el proceso colgado para siempre en lugar de fallar.
    install_excepthook(None if selftest else _show_crash)

    window = MainWindow()
    if selftest:
        if not _selftest_webengine(logger):
            return 1
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        # Tiempo para que termine la carga de juegos y mods, que es asincrona.
        QTimer.singleShot(3000, app.quit)
        return app.exec()

    window.show()
    codigo = app.exec()
    logger.info("cerrando Loadstone (codigo %s)", codigo)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
