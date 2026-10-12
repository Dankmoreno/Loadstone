"""Mods que el launcher lista pero cuyo contenido ya no esta en disco.

Es el estado en que queda una instalacion cuando alguien vacia la carpeta
`mod/` por su cuenta, cuando una sincronizacion sale mal, o cuando un gestor
externo decide limpiar. El launcher sigue teniendo sus 213 filas y el juego no
encuentra ni una: al arrancar, los mods simplemente no estan.

El diagnostico ya sabia detectarlo y escribia una linea de error por cada mod.
Doscientas lineas identicas no son un diagnostico, son un muro; y sobre todo,
decir el problema doscientas veces sin ofrecer la solucion cuando el programa
ya sabe ejecutarla es trabajo a medias.

Este modulo solo decide **que se puede recuperar**. Bajarlo no es cosa suya:
un mod publicado en el Workshop tiene su id ahi mismo, en la fila que dejo el
launcher, y con el id SteamCMD hace el resto. Uno instalado a mano desde un zip
no deja rastro de donde vino, y ese no vuelve solo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .logs import get_logger
from .models import Mod

__all__ = ["RepairPlan", "plan_repair"]


_logger = get_logger("repair")


@dataclass(slots=True)
class RepairPlan:
    """Lo que falta, separado por si tiene arreglo automatico o no."""

    recuperables: list[Mod] = field(default_factory=list)
    """Registrados, sin contenido, y con id del Workshop: se pueden volver a bajar."""

    perdidos: list[Mod] = field(default_factory=list)
    """Registrados y sin contenido, pero sin id: nadie sabe de donde salieron."""

    @property
    def total(self) -> int:
        return len(self.recuperables) + len(self.perdidos)

    @property
    def hay_algo_que_hacer(self) -> bool:
        return bool(self.recuperables)

    @property
    def ids(self) -> list[str]:
        """Los ids del Workshop que habria que descargar, sin repetir."""
        return list(dict.fromkeys(m.steam_id for m in self.recuperables if m.steam_id))


def plan_repair(mods: list[Mod]) -> RepairPlan:
    """Separa los mods rotos de los sanos. No descarga ni toca nada.

    Un mod cuenta como roto cuando el launcher lo lista y su contenido no esta.
    El caso contrario —contenido en disco que el launcher no conoce— no es
    cosa de aqui: eso lo recoge `cleanup`, y no se arregla descargando nada.
    """
    plan = RepairPlan()
    for mod in mods:
        if not mod.is_dangling:
            continue
        if mod.steam_id:
            plan.recuperables.append(mod)
        else:
            plan.perdidos.append(mod)

    if plan.total:
        _logger.info(
            "faltan %s mods en disco (%s recuperables del Workshop)",
            plan.total,
            len(plan.recuperables),
        )
    return plan
