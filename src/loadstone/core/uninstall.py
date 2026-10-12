"""Desinstalar un mod: sacarlo de los playsets, del disco y del registro.

Esto es lo contrario de `cleanup`. Aquel modulo existe para la basura
—descriptores colgados, registros fantasma, carpetas que el juego ni ve— y
por eso se niega a tocar nada que algun playset mencione. Aqui el mod esta
sano y completo, y quien manda ha decidido que no lo quiere mas.

El orden de las tres operaciones no es casual:

1. **Los playsets primero.** Si el contenido desapareciera antes, entre una
   cosa y la otra el launcher veria listas que apuntan a un mod inexistente,
   que es exactamente el estado roto que `cleanup` tiene luego que reparar.
2. **El disco despues**, que es lo unico irreversible.
3. **El registro al final**, porque mientras exista su fila el mod sigue
   teniendo nombre en los mensajes de error.

Un mod descargado del Workshop por Steam vive fuera de la carpeta de datos del
juego. Borrar eso seria meterse en lo que Steam gestiona, y ademas Steam lo
volveria a bajar, asi que esas rutas se separan en `outside_paths` y no se
borran salvo que quien llama lo pida expresamente.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .logs import get_logger
from .models import Mod, Playset
from .quarantine import purge as quarantine_purge
from .quarantine import store as quarantine_store

__all__ = ["UninstallPlan", "execute_uninstall", "plan_uninstall"]


_logger = get_logger("uninstall")


def _is_within(path: Path, parent: Path) -> bool:
    """Si `path` cuelga de `parent`, sin resolver enlaces que no existen."""
    try:
        path.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def _directory_size(carpeta: Path) -> int:
    total = 0
    for elemento in carpeta.rglob("*"):
        try:
            if elemento.is_file():
                total += elemento.stat().st_size
        except OSError:
            # Un archivo ilegible no invalida el total: solo lo deja corto.
            continue
    return total


@dataclass(slots=True)
class UninstallPlan:
    """Lo que supondria desinstalar un mod, sin haber tocado nada todavia."""

    mod: Mod

    paths: list[Path] = field(default_factory=list)
    """Lo que se borrara: contenido y descriptor, dentro de la carpeta del juego."""

    outside_paths: list[Path] = field(default_factory=list)
    """Contenido que vive fuera de la carpeta del juego, normalmente de Steam.

    Solo se borra si `execute_uninstall` recibe `include_outside=True`.
    """

    playsets: list[Playset] = field(default_factory=list)
    """Playsets de los que habra que sacarlo."""

    size: int = 0
    """Bytes que se liberan contando solo `paths`."""

    unregister: bool = False
    """Si ademas hay que quitar su fila del registro del launcher."""

    @property
    def is_steam_managed(self) -> bool:
        """Si su contenido lo gestiona Steam y volveria a aparecer solo."""
        return bool(self.outside_paths)


def plan_uninstall(
    mod: Mod,
    playsets: list[Playset],
    *,
    mod_dir: Path | None = None,
) -> UninstallPlan:
    """Describe que se borraria al desinstalar `mod`. No toca nada.

    `mod_dir` es la carpeta de mods del juego; lo que caiga fuera se aparta en
    `outside_paths` porque no es de Loadstone borrarlo a la ligera.
    """
    dentro: list[Path] = []
    fuera: list[Path] = []
    for ruta in (mod.folder, mod.archive, mod.descriptor_path):
        if ruta is None or not ruta.exists():
            continue
        if mod_dir is not None and not _is_within(ruta, mod_dir):
            fuera.append(ruta)
        else:
            dentro.append(ruta)

    tamano = 0
    for ruta in dentro:
        try:
            tamano += _directory_size(ruta) if ruta.is_dir() else ruta.stat().st_size
        except OSError:
            continue

    afectados = [
        playset for playset in playsets if any(e.uid == mod.uid for e in playset.mods)
    ]

    return UninstallPlan(
        mod=mod,
        paths=dentro,
        outside_paths=fuera,
        playsets=afectados,
        size=tamano,
        unregister=mod.in_registry,
    )


def execute_uninstall(
    plans: list[UninstallPlan],
    *,
    save_playset: Callable[[Playset], None] | None = None,
    unregister: Callable[[str], bool] | None = None,
    include_outside: bool = False,
    quarantine: bool = True,
) -> tuple[int, list[str]]:
    """Ejecuta los planes y devuelve `(mods desinstalados, errores)`.

    Las dos operaciones que dependen del juego llegan como invocables para que
    este modulo no dependa de ningun backend, igual que en `cleanup`.

    Con `quarantine` el contenido se aparta a la papelera de la cache en vez
    de borrarse, y se puede devolver a su sitio durante dos semanas.

    Un mod solo cuenta como desinstalado si las tres fases salieron bien. Si
    algo falla a mitad se sigue con el resto de la lista en vez de abortar: con
    diez mods seleccionados, que uno tenga un archivo bloqueado no es razon
    para dejar los otros nueve a medias.
    """
    hechos = 0
    errores: list[str] = []

    if quarantine:
        # La papelera se mantiene sola: nadie se acuerda de vaciarla, y
        # una que crece sin limite es una copia entera de la biblioteca.
        quarantine_purge()

    # Un mismo playset puede aparecer en varios planes; se reescribe una sola
    # vez, ya sin ninguno de los mods que se van.
    por_guardar: dict[str, Playset] = {}
    for plan in plans:
        for playset in plan.playsets:
            playset.mods = [e for e in playset.mods if e.uid != plan.mod.uid]
            playset.renumber()
            por_guardar[playset.id] = playset

    if save_playset is not None:
        for playset in por_guardar.values():
            try:
                save_playset(playset)
            except Exception as exc:  # noqa: BLE001 - el backend decide su error
                errores.append(f"playset '{playset.name}': no se pudo actualizar ({exc})")
                # Sin playsets limpios no se borra nada: dejar el contenido
                # fuera y la referencia dentro es el peor de los dos estados.
                return 0, errores

    for plan in plans:
        fallo = False
        rutas = [*plan.paths, *(plan.outside_paths if include_outside else [])]

        if quarantine:
            # Apartar en vez de borrar. Un mod del Workshop se vuelve a bajar,
            # pero uno traducido a mano o con parches propios no vuelve nunca,
            # y equivocarse de fila cuesta lo mismo en los dos casos.
            try:
                quarantine_store(plan.mod, rutas)
            except OSError as exc:
                # Ni se borra ni se desregistra. Si no se ha podido apartar,
                # borrar igualmente convertiria el fallo de la red de seguridad
                # en la perdida que la red existia para evitar.
                errores.append(f"{plan.mod.name}: no se pudo apartar ({exc})")
                continue
            # Apartar mueve: lo que quede aqui es lo que no llego a moverse.
            rutas = [r for r in rutas if r.exists()]

        for ruta in rutas:
            try:
                if ruta.is_dir():
                    shutil.rmtree(ruta)
                elif ruta.exists():
                    ruta.unlink()
            except OSError as exc:
                errores.append(f"{plan.mod.name}: no se pudo borrar {ruta.name} ({exc})")
                fallo = True

        if plan.unregister and unregister is not None and not fallo:
            try:
                unregister(plan.mod.uid)
            except Exception as exc:  # noqa: BLE001 - el backend decide su error
                errores.append(f"{plan.mod.name}: no se pudo quitar del registro ({exc})")
                fallo = True

        if not fallo:
            hechos += 1
            _logger.info("desinstalado %s (%s bytes)", plan.mod.name, plan.size)

    return hechos, errores
