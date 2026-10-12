"""Pruebas de la paleta, la hoja de estilo y los recursos de la marca."""

from __future__ import annotations

import re

import pytest

from loadstone.gui.assets import icon_path, svg_path
from loadstone.gui.theme import CLARO, OSCURO, Paleta, stylesheet

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@pytest.mark.parametrize("paleta", [OSCURO, CLARO], ids=["oscuro", "claro"])
def test_todos_los_colores_son_hex_validos(paleta: Paleta):
    """Un color mal escrito no falla: Qt lo ignora y deja el hueco en negro."""
    for campo in paleta.__slots__:
        valor = getattr(paleta, campo)
        assert _HEX.match(valor), f"{campo} no es un color valido: {valor!r}"


@pytest.mark.parametrize("paleta", [OSCURO, CLARO], ids=["oscuro", "claro"])
def test_la_hoja_no_deja_marcadores_sin_sustituir(paleta: Paleta):
    hoja = stylesheet(paleta)
    assert "{" in hoja and "}" in hoja
    # Si una llave de formato se escapara mal, quedaria el nombre del atributo.
    for campo in paleta.__slots__:
        assert f"{{{campo}}}" not in hoja
    assert "None" not in hoja


@pytest.mark.parametrize("paleta", [OSCURO, CLARO], ids=["oscuro", "claro"])
def test_los_colores_de_diagnostico_no_se_confunden_con_el_acento(paleta: Paleta):
    """Si un aviso pareciera un boton, el diagnostico dejaria de avisar."""
    assert paleta.error != paleta.acento
    assert paleta.aviso != paleta.acento
    assert paleta.error != paleta.aviso


def test_los_dos_esquemas_son_de_verdad_distintos():
    assert OSCURO.fondo != CLARO.fondo
    assert OSCURO.texto != CLARO.texto
    # El texto de un esquema no puede valer de fondo en el otro.
    assert OSCURO.fondo != CLARO.texto


@pytest.mark.parametrize("paleta", [OSCURO, CLARO], ids=["oscuro", "claro"])
def test_el_texto_contrasta_con_el_fondo(paleta: Paleta):
    """Una paleta nueva mal elegida se nota aqui y no en una captura."""

    def luminancia(color: str) -> float:
        canales = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lineal = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
        return 0.2126 * lineal[0] + 0.7152 * lineal[1] + 0.0722 * lineal[2]

    def contraste(a: str, b: str) -> float:
        la, lb = sorted((luminancia(a), luminancia(b)))
        return (lb + 0.05) / (la + 0.05)

    # 4.5:1 es el minimo de la norma para texto normal.
    assert contraste(paleta.texto, paleta.fondo) >= 4.5
    assert contraste(paleta.texto, paleta.superficie) >= 4.5
    # Lo apagado es texto de apoyo: se le exige el 3:1 de texto grande.
    assert contraste(paleta.texto_apagado, paleta.superficie) >= 3.0
    # Y lo que se escribe encima del acento tiene que leerse.
    assert contraste(paleta.acento_texto, paleta.acento) >= 4.5


def test_los_recursos_de_la_marca_existen_y_son_lo_que_dicen():
    svg = svg_path()
    assert svg is not None and svg.is_file()
    assert svg.read_text(encoding="utf-8").lstrip().startswith("<?xml")

    ico = icon_path()
    assert ico is not None and ico.is_file()
    cabecera = ico.read_bytes()[:6]
    # Reservado=0, tipo=1 (icono), y al menos un tamano dentro.
    assert cabecera[0:2] == b"\x00\x00"
    assert cabecera[2:4] == b"\x01\x00"
    assert int.from_bytes(cabecera[4:6], "little") >= 4


def test_el_icono_trae_los_tamanos_pequenos():
    """Sin un 16 de verdad, Windows reescala el 256 y sale emborronado."""
    datos = icon_path().read_bytes()
    cuantos = int.from_bytes(datos[4:6], "little")
    lados = {datos[6 + 16 * i] or 256 for i in range(cuantos)}
    assert {16, 32, 48, 256} <= lados, f"faltan tamanos: {sorted(lados)}"
