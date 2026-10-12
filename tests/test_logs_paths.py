import logging
from pathlib import Path

from loadstone.core import logs, paths
from loadstone.core.paths import HOME_ENV


def test_todo_cuelga_de_la_variable_de_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "portatil"))
    raiz = tmp_path / "portatil"

    assert paths.config_file() == raiz / "config.json"
    assert paths.history_dir() == raiz / "history"
    assert paths.log_dir() == raiz / "logs"
    assert paths.steamcmd_dir() == raiz / "cache" / "steamcmd"


def test_sin_variable_usa_la_convencion_del_sistema(monkeypatch):
    monkeypatch.delenv(HOME_ENV, raising=False)
    # No se comprueba la ruta exacta, que cambia por sistema, sino que es
    # absoluta y lleva el nombre de la aplicacion.
    destino = paths.config_file()
    assert destino.is_absolute()
    assert paths.APP_NAME in str(destino).lower()


def test_una_variable_vacia_no_cuenta(monkeypatch):
    monkeypatch.setenv(HOME_ENV, "   ")
    assert paths.APP_NAME in str(paths.config_file()).lower()


def test_rutas_heredadas_no_incluyen_la_actual(monkeypatch, tmp_path):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    assert paths.config_file() not in paths.legacy_config_files()
    nombres = {ruta.parent.name for ruta in paths.legacy_config_files()}
    assert {"stellaris-sort", "parasort"} <= nombres


def test_el_registro_escribe_en_su_sitio(tmp_path, monkeypatch):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    monkeypatch.setattr(logs, "_configurado", False)
    # Dejar limpio el logger entre pruebas: es global al proceso.
    raiz = logging.getLogger("loadstone")
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)

    destino = logs.setup_logging(to_stderr=False)
    assert destino == tmp_path / "logs" / "loadstone.log"

    logs.get_logger("prueba").info("hola %s", "mundo")
    for handler in logging.getLogger("loadstone").handlers:
        handler.flush()

    contenido = destino.read_text(encoding="utf-8")
    assert "hola mundo" in contenido
    assert "loadstone.prueba" in contenido


def test_si_no_se_puede_escribir_el_registro_la_app_sigue(tmp_path, monkeypatch):
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    monkeypatch.setattr(logs, "_configurado", False)
    for handler in list(logging.getLogger("loadstone").handlers):
        logging.getLogger("loadstone").removeHandler(handler)

    def sin_permiso(*args, **kwargs):
        raise OSError("sin permiso")

    monkeypatch.setattr(Path, "mkdir", sin_permiso)
    assert logs.setup_logging(to_stderr=False) is None


def test_el_excepthook_registra_y_avisa(monkeypatch):
    avisos: list[tuple[str, str]] = []
    monkeypatch.setattr("sys.excepthook", lambda *a: None)
    logs.install_excepthook(lambda resumen, detalle: avisos.append((resumen, detalle)))

    import sys

    try:
        raise ValueError("algo se rompio")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    assert avisos and avisos[0][0] == "ValueError: algo se rompio"
    assert "Traceback" in avisos[0][1]


def test_ctrl_c_no_se_trata_como_fallo(monkeypatch):
    avisos: list[str] = []
    monkeypatch.setattr("sys.excepthook", lambda *a: None)
    logs.install_excepthook(lambda resumen, detalle: avisos.append(resumen))

    import sys

    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        sys.excepthook(*sys.exc_info())

    assert avisos == []
