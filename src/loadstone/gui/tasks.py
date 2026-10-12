"""Ejecucion de trabajo lento fuera del hilo de la interfaz.

Comprobar actualizaciones tarda unos quince segundos entre la consulta a Steam
y el recuento de tamanos en disco, y una busqueda recorre miles de archivos.
Hacerlo en el hilo de la ventana la deja congelada y Windows la pinta como "no
responde", asi que va aparte.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

__all__ = ["Task"]


class Task(QThread):
    """Ejecuta una funcion en segundo plano y avisa con el resultado."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, work: Callable[[], Any], parent: Any = None) -> None:
        super().__init__(parent)
        self._work = work

    def run(self) -> None:
        try:
            resultado = self._work()
        except Exception as exc:  # noqa: BLE001 - cualquier fallo debe llegar a la UI
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.finished_ok.emit(resultado)
