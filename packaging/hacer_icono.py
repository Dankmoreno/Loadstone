"""Convierte la marca SVG en el `.ico` que usan la ventana y el ejecutable.

Se genera en vez de guardarse ya hecho porque el `.ico` es un derivado: si se
versionaran los dos, tarde o temprano alguien tocaria el SVG y el icono del
ejecutable seguiria siendo el viejo durante meses sin que nadie lo notara.

Usa QtSvg y el escritor de imagenes de Qt, que ya vienen con la aplicacion. No
hace falta Pillow, ni ImageMagick, ni nada que instalar aparte.

    .venv\\Scripts\\python.exe packaging\\hacer_icono.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

RAIZ = Path(__file__).resolve().parent.parent
ASSETS = RAIZ / "src" / "loadstone" / "gui" / "assets"
SVG = ASSETS / "loadstone.svg"

# Los tamanos que Windows pide de verdad: 16 para la barra de titulo y las
# listas, 32 para la barra de tareas, 48 y 256 para el explorador.
TAMANOS = (16, 20, 24, 32, 48, 64, 128, 256)


def _render(renderer: QSvgRenderer, lado: int) -> QImage:
    imagen = QImage(lado, lado, QImage.Format.Format_ARGB32)
    imagen.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(imagen)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(pintor)
    pintor.end()
    return imagen


def _png(imagen: QImage) -> bytes:
    # Sin argumento: QBuffer usa su propio almacen. Pasarle un QByteArray
    # recien creado lo dejaria apuntando a un temporal que Python se lleva en
    # cuanto vuelve la llamada, y el proceso cae por violacion de acceso.
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    imagen.save(buffer, "PNG")
    buffer.close()
    return bytes(buffer.data())


def _ico(imagenes: list[QImage]) -> bytes:
    """Arma el contenedor ICO a mano, con cada tamano como un PNG dentro.

    Qt sabe escribir `.ico`, pero solo guarda una imagen: un icono de un unico
    tamano se ve emborronado en todas las demas escalas. El formato admite
    PNG desde Windows Vista y la cabecera son veintidos bytes, asi que sale
    mas barato montarlo que arrastrar una dependencia para esto.
    """
    cuerpos = [_png(imagen) for imagen in imagenes]
    cabecera = bytearray()
    cabecera += (0).to_bytes(2, "little")  # reservado
    cabecera += (1).to_bytes(2, "little")  # 1 = icono
    cabecera += len(cuerpos).to_bytes(2, "little")

    desplazamiento = 6 + 16 * len(cuerpos)
    entradas = bytearray()
    for imagen, cuerpo in zip(imagenes, cuerpos, strict=True):
        lado = imagen.width()
        entradas += bytes([0 if lado >= 256 else lado])  # ancho (0 = 256)
        entradas += bytes([0 if lado >= 256 else lado])  # alto
        entradas += bytes([0])  # colores de la paleta: ninguna
        entradas += bytes([0])  # reservado
        entradas += (1).to_bytes(2, "little")  # planos
        entradas += (32).to_bytes(2, "little")  # bits por pixel
        entradas += len(cuerpo).to_bytes(4, "little")
        entradas += desplazamiento.to_bytes(4, "little")
        desplazamiento += len(cuerpo)

    return bytes(cabecera + entradas + b"".join(cuerpos))


def main() -> int:
    if not SVG.is_file():
        print(f"no encuentro {SVG}", file=sys.stderr)
        return 1

    # Hace falta una aplicacion de Qt viva para rasterizar, pero no una ventana.
    # La referencia se guarda: sin ella el recolector se la lleva en cuanto
    # termina la linea y el primer QPainter revienta el proceso.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication.instance() or QGuiApplication([])

    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print(f"el SVG no es valido: {SVG}", file=sys.stderr)
        return 1

    imagenes = [_render(renderer, lado) for lado in TAMANOS]
    assert app is not None

    destino_ico = ASSETS / "loadstone.ico"
    destino_ico.write_bytes(_ico(imagenes))
    print(f"{destino_ico.relative_to(RAIZ)}  ({destino_ico.stat().st_size:,} bytes)")

    # Un PNG grande suelto para el README y para los escritorios que no leen
    # `.ico`, que son todos menos Windows.
    destino_png = ASSETS / "loadstone-256.png"
    imagenes[-1].save(str(destino_png), "PNG")
    print(f"{destino_png.relative_to(RAIZ)}  ({destino_png.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
