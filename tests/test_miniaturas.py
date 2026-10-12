"""Pruebas de las miniaturas de las listas.

Lo que importa no es que la imagen se vea bonita sino que no se cargue la que
nadie esta mirando: con una biblioteca de doscientos mods, hacerlo al poblar
cuesta segundos cada vez que se cambia de playset.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage

from loadstone.core.models import Mod
from loadstone.gui import widgets as w
from loadstone.gui.widgets import ModListWidget


@pytest.fixture(autouse=True)
def cache_limpia():
    """La cache es del modulo: sin vaciarla, una prueba contagia a la siguiente."""
    w._cache_miniaturas.clear()
    yield
    w._cache_miniaturas.clear()


def _mod_con_miniatura(raiz: Path, uid: str, formato: str = "png") -> Mod:
    carpeta = raiz / uid
    carpeta.mkdir(parents=True)
    imagen = QImage(256, 256, QImage.Format.Format_RGB32)
    imagen.fill(0x3366AA)
    imagen.save(str(carpeta / f"thumbnail.{formato}"))
    return Mod(uid=uid, name=f"Mod {uid}", folder=carpeta, on_disk=True)


def _mod_sin_miniatura(raiz: Path, uid: str) -> Mod:
    carpeta = raiz / uid
    carpeta.mkdir(parents=True)
    (carpeta / "descriptor.mod").write_text('name="x"', encoding="utf-8")
    return Mod(uid=uid, name=f"Mod {uid}", folder=carpeta, on_disk=True)


def test_la_miniatura_se_lee_y_se_escala(tmp_path, qtbot):
    mod = _mod_con_miniatura(tmp_path, "a")
    icono = w._thumbnail_icon(mod.folder)

    assert icono is not None
    tamanos = icono.availableSizes()
    assert tamanos and tamanos[0].height() <= w._LADO_MINIATURA


def test_un_mod_sin_miniatura_se_recuerda_como_tal(tmp_path, qtbot):
    """Volver a mirar en disco en cada repoblado seria el coste que se evita."""
    mod = _mod_sin_miniatura(tmp_path, "b")

    assert w._thumbnail_icon(mod.folder) is None
    assert str(mod.folder) in w._cache_miniaturas
    assert w._cache_miniaturas[str(mod.folder)] is None


def test_la_cache_evita_releer(tmp_path, qtbot):
    mod = _mod_con_miniatura(tmp_path, "c")
    primero = w._thumbnail_icon(mod.folder)

    # Si volviera a leer de disco, sin el archivo daria None.
    (mod.folder / "thumbnail.png").unlink()
    assert w._thumbnail_icon(mod.folder) is primero


def test_solo_se_cargan_las_filas_visibles(tmp_path, qtbot):
    """El punto de todo esto: cien mods fuera de pantalla no se tocan."""
    lista = ModListWidget(with_checkboxes=False, numbered=False)
    qtbot.addWidget(lista)
    lista.resize(400, 120)  # caben pocas filas
    lista.show()
    qtbot.waitExposed(lista)

    for i in range(60):
        mod = _mod_con_miniatura(tmp_path, f"m{i:02d}")
        lista.add_mod(mod, mod.uid, enabled=True, position=i)
    lista._load_visible_icons()

    leidas = len(w._cache_miniaturas)
    assert leidas > 0, "no ha cargado ninguna"
    assert leidas < 60, f"ha cargado las 60, deberia cargar solo las visibles ({leidas})"


def test_al_vaciar_la_lista_se_olvida_de_que_carpeta_era_cada_fila(tmp_path, qtbot):
    """Si sobreviviera, al cambiar de juego apuntaria a los mods del anterior."""
    lista = ModListWidget(with_checkboxes=False, numbered=False)
    qtbot.addWidget(lista)
    mod = _mod_con_miniatura(tmp_path, "d")
    lista.add_mod(mod, mod.uid, enabled=True, position=0)

    assert lista._iconos_por_uid
    lista.clear()
    assert lista._iconos_por_uid == {}


def test_un_mod_sin_contenido_no_entra_en_el_indice(tmp_path, qtbot):
    """No hay carpeta donde mirar, y pedirlo seria un acceso a disco de balde."""
    lista = ModListWidget(with_checkboxes=False, numbered=False)
    qtbot.addWidget(lista)
    roto = Mod(uid="x", name="Sin contenido", in_registry=True, on_disk=False)
    lista.add_mod(roto, roto.uid, enabled=True, position=0)

    assert lista._iconos_por_uid == {}


def test_una_imagen_ilegible_no_rompe_nada(tmp_path, qtbot):
    carpeta = tmp_path / "rota"
    carpeta.mkdir()
    (carpeta / "thumbnail.png").write_bytes(b"esto no es un png")

    assert w._thumbnail_icon(carpeta) is None
    assert QSize is not None and Qt is not None
