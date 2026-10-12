# -*- mode: python ; coding: utf-8 -*-
"""Receta de empaquetado de Loadstone para PyInstaller.

Produce una sola carpeta con dos ejecutables que comparten el runtime:

    Loadstone.exe      la ventana, sin consola detras
    loadstone-cli.exe  la linea de comandos

Compartir la carpeta importa: Qt pesa unos 60 MB y meterlo dos veces seria
absurdo. Por eso hay dos analisis pero un unico COLLECT.

    pyinstaller packaging/loadstone.spec --noconfirm
"""

from pathlib import Path

RAIZ = Path(SPECPATH).parent
SRC = str(RAIZ / "src")
ASSETS = RAIZ / "src" / "loadstone" / "gui" / "assets"

# El icono del ejecutable. Si falta, Windows pone el generico de PyInstaller
# y el programa parece un script suelto en vez de una aplicacion.
ICONO = str(ASSETS / "loadstone.ico")

# Lo que ninguna de las dos aplicaciones usa. Recortar de mas rompe Qt, asi
# que aqui solo entra lo que se sabe seguro.
EXCLUIDOS = [
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "pytest",
    "ruff",
    "setuptools",
    "pip",
]

# La linea de comandos no toca Qt: excluirlo entero deja su ejecutable minimo.
EXCLUIDOS_CLI = [*EXCLUIDOS, "PySide6", "shiboken6"]


# El navegador del Workshop se importa dentro de una funcion, para no pagar
# Chromium en cada arranque. PyInstaller sigue los imports perezosos, pero
# declararlos aqui deja constancia de que el paquete tiene que traerlos: si
# alguien los quita, lo que se rompe es una ventana concreta y no el arranque,
# asi que el fallo no aparece hasta que un usuario le da al menu.
WEBENGINE = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
]

analisis_gui = Analysis(
    [str(RAIZ / "packaging" / "loadstone_gui.py")],
    pathex=[SRC],
    binaries=[],
    # Van dentro del paquete para que `importlib.resources` los encuentre
    # igual congelado que en desarrollo.
    datas=[(str(ASSETS), "loadstone/gui/assets")],
    hiddenimports=WEBENGINE,
    excludes=EXCLUIDOS,
    noarchive=False,
    optimize=0,
)
# Chromium trae su interfaz traducida a 53 idiomas, 44 MB, y la aplicacion
# esta en espanol. Se dejan esos dos mas el ingles, que es al que Chromium
# recurre cuando no encuentra el pedido; quitarlos todos daria una ventana con
# los menus del navegador en blanco.
IDIOMAS = ("es-419.pak", "es.pak", "en-US.pak", "en-GB.pak")

analisis_gui.datas = [
    entrada
    for entrada in analisis_gui.datas
    if "qtwebengine_locales" not in entrada[0].replace("\\", "/")
    or entrada[0].endswith(IDIOMAS)
]

pyz_gui = PYZ(analisis_gui.pure)
exe_gui = EXE(
    pyz_gui,
    analisis_gui.scripts,
    [],
    exclude_binaries=True,
    name="Loadstone",
    debug=False,
    strip=False,
    upx=False,
    # Sin consola: es una aplicacion de ventana.
    console=False,
    icon=ICONO,
)

analisis_cli = Analysis(
    [str(RAIZ / "packaging" / "loadstone_cli.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=[],
    excludes=EXCLUIDOS_CLI,
    noarchive=False,
    optimize=0,
)
pyz_cli = PYZ(analisis_cli.pure)
exe_cli = EXE(
    pyz_cli,
    analisis_cli.scripts,
    [],
    exclude_binaries=True,
    name="loadstone-cli",
    debug=False,
    strip=False,
    upx=False,
    # Con consola: aqui la salida de texto es el producto.
    console=True,
)

COLLECT(
    exe_gui,
    analisis_gui.binaries,
    analisis_gui.datas,
    exe_cli,
    analisis_cli.binaries,
    analisis_cli.datas,
    strip=False,
    upx=False,
    name="Loadstone",
)
