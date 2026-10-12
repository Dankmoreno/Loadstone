"""Punto de entrada de la ventana para PyInstaller.

PyInstaller ejecuta el script como `__main__`, y los modulos del paquete usan
imports relativos, que ahi no funcionan. Este envoltorio importa el paquete de
forma normal y delega.
"""

from loadstone.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
