import json
from pathlib import Path

import pytest

from loadstone.core import config
from loadstone.core.config import Config
from loadstone.core.paths import HOME_ENV


@pytest.fixture(autouse=True)
def entorno_aislado(tmp_path, monkeypatch):
    """Aisla config y rutas heredadas del equipo que ejecuta las pruebas."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "actual"))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "hogar"))


def escribir(raiz: Path, nombre: str, carpeta: str) -> None:
    """Escribe una configuracion de un nombre anterior del proyecto."""
    ruta = raiz / nombre / "config.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"extra_roots": [carpeta]}), encoding="utf-8")


def escribir_actual(tmp_path: Path, carpeta: str) -> None:
    ruta = config.config_path()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"extra_roots": [carpeta]}), encoding="utf-8")


@pytest.mark.parametrize("nombre_anterior", ["loadstone", "stellaris-sort", "parasort"])
def test_adopta_la_configuracion_de_un_nombre_anterior(tmp_path, nombre_anterior):
    escribir(tmp_path, nombre_anterior, "D:/Games")

    assert Config.load().extra_roots == [Path("D:/Games")]


def test_la_configuracion_actual_tiene_prioridad(tmp_path):
    escribir(tmp_path, "parasort", "D:/Viejo")
    escribir(tmp_path, "stellaris-sort", "D:/Intermedio")
    escribir_actual(tmp_path, "D:/Actual")

    assert Config.load().extra_roots == [Path("D:/Actual")]


def test_entre_dos_anteriores_gana_la_mas_reciente(tmp_path):
    escribir(tmp_path, "parasort", "D:/Viejo")
    escribir(tmp_path, "stellaris-sort", "D:/Intermedio")

    assert Config.load().extra_roots == [Path("D:/Intermedio")]


def test_guarda_siempre_en_la_ruta_actual(tmp_path):
    escribir(tmp_path, "parasort", "D:/Games")

    configuracion = Config.load()
    destino = configuracion.save()

    assert destino == config.config_path()
    assert destino.is_file()
    assert Config.load().extra_roots == [Path("D:/Games")]


def test_sin_configuracion_de_ningun_nombre(tmp_path):
    assert Config.load().extra_roots == []


def test_la_variable_de_entorno_manda(tmp_path):
    # Una instalacion portatil guarda su estado donde se le diga.
    assert config.config_path() == tmp_path / "actual" / "config.json"
