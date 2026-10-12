import json
import os
import stat
import sys

import pytest

from loadstone.core.atomic import atomic_write_json, atomic_write_text, replace_with_retry


def test_escribe_texto_y_no_deja_temporales(tmp_path):
    destino = tmp_path / "salida.txt"
    atomic_write_text(destino, "contenido")

    assert destino.read_text(encoding="utf-8") == "contenido"
    assert list(tmp_path.glob("*.loadstone-tmp")) == []


def test_crea_la_carpeta_si_falta(tmp_path):
    destino = tmp_path / "sin" / "crear" / "x.json"
    atomic_write_json(destino, {"a": 1})
    assert json.loads(destino.read_text(encoding="utf-8")) == {"a": 1}


def test_sobrescribe_dejando_el_contenido_entero(tmp_path):
    destino = tmp_path / "x.txt"
    destino.write_text("viejo", encoding="utf-8")
    atomic_write_text(destino, "nuevo")
    assert destino.read_text(encoding="utf-8") == "nuevo"


def test_si_falla_la_escritura_no_queda_el_temporal(tmp_path, monkeypatch):
    destino = tmp_path / "x.txt"
    destino.write_text("intacto", encoding="utf-8")

    def explota(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr("loadstone.core.atomic.replace_with_retry", explota)
    with pytest.raises(OSError, match="disco lleno"):
        atomic_write_text(destino, "nuevo")

    assert destino.read_text(encoding="utf-8") == "intacto"
    assert list(tmp_path.glob("*.loadstone-tmp")) == []


def test_reintenta_mientras_el_destino_esta_bloqueado(tmp_path, monkeypatch):
    origen = tmp_path / "origen"
    origen.write_text("nuevo", encoding="utf-8")
    destino = tmp_path / "destino"
    destino.write_text("viejo", encoding="utf-8")

    intentos = {"n": 0}
    real = os.replace

    def bloqueado_al_principio(src, dst):
        intentos["n"] += 1
        # Dos fallos seguidos, como un antivirus que abre el archivo recien
        # escrito, y a la tercera funciona.
        if intentos["n"] < 3:
            raise PermissionError("en uso por otro proceso")
        real(src, dst)

    monkeypatch.setattr(os, "replace", bloqueado_al_principio)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    replace_with_retry(origen, destino)
    assert intentos["n"] == 3
    assert destino.read_text(encoding="utf-8") == "nuevo"


def test_se_rinde_y_propaga_si_no_se_libera(tmp_path, monkeypatch):
    origen = tmp_path / "origen"
    origen.write_text("nuevo", encoding="utf-8")
    destino = tmp_path / "destino"
    destino.write_text("viejo", encoding="utf-8")

    def siempre_bloqueado(src, dst):
        raise PermissionError("en uso por otro proceso")

    monkeypatch.setattr(os, "replace", siempre_bloqueado)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    with pytest.raises(PermissionError):
        replace_with_retry(origen, destino)
    assert destino.read_text(encoding="utf-8") == "viejo"


@pytest.mark.skipif(sys.platform != "win32", reason="el atributo es de Windows")
def test_sobrescribe_un_destino_de_solo_lectura(tmp_path):
    # Es lo que deja una restauracion desde ciertas copias de seguridad, y
    # ningun numero de reintentos lo arregla: hay que quitar el atributo.
    destino = tmp_path / "x.txt"
    destino.write_text("viejo", encoding="utf-8")
    destino.chmod(destino.stat().st_mode & ~stat.S_IWRITE)

    atomic_write_text(destino, "nuevo")
    assert destino.read_text(encoding="utf-8") == "nuevo"
