"""Papelera propia para los mods desinstalados.

Hasta ahora desinstalar era `rmtree` y se acabo. Funciona, es honesto —el
dialogo avisa de que no tiene vuelta atras— y aun asi es la operacion que mas
cara sale cuando alguien se equivoca de fila, porque un mod del Workshop se
vuelve a bajar pero uno traducido a mano o con parches propios no vuelve.

Asi que no se borra: se aparta. El contenido se mueve a la cache, con un
manifiesto que recuerda de donde salio cada cosa, y de ahi puede volver a su
sitio exacto. Lo que pasa de `DIAS_EN_CUARENTENA` se purga solo, porque una
papelera que no se vacia nunca es una segunda copia de la biblioteca de mods
ocupando disco para siempre.

Va a la cache y no a los datos a proposito: si alguien borra la carpeta de
cache, lo que pierde es la posibilidad de deshacer, no nada que no hubiera
decidido ya tirar.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .logs import get_logger
from .models import Mod
from .paths import cache_dir

__all__ = [
    "DIAS_EN_CUARENTENA",
    "QuarantineEntry",
    "list_entries",
    "purge",
    "quarantine_dir",
    "restore",
    "store",
    "total_size",
]


_logger = get_logger("quarantine")

DIAS_EN_CUARENTENA = 14
"""Cuanto se guarda lo apartado antes de purgarlo.

Dos semanas: lo bastante para que alguien note que le falta un mod la proxima
vez que juegue, y lo bastante poco para que la cache no crezca sin limite.
"""

_MANIFIESTO = "entrada.json"


def quarantine_dir() -> Path:
    return cache_dir() / "cuarentena"


@dataclass(slots=True)
class QuarantineEntry:
    """Un mod apartado, con lo que hace falta para devolverlo a su sitio."""

    carpeta: Path
    """Donde esta guardado ahora, dentro de la cuarentena."""

    uid: str
    nombre: str
    cuando: datetime
    archivos: list[tuple[Path, str]]
    """Pares (ruta original, nombre dentro de la carpeta de cuarentena)."""

    @property
    def dias(self) -> int:
        return max(0, (datetime.now(UTC) - self.cuando).days)

    @property
    def size(self) -> int:
        total = 0
        for elemento in self.carpeta.rglob("*"):
            try:
                if elemento.is_file():
                    total += elemento.stat().st_size
            except OSError:
                continue
        return total


def _leer(carpeta: Path) -> QuarantineEntry | None:
    manifiesto = carpeta / _MANIFIESTO
    try:
        datos = json.loads(manifiesto.read_text(encoding="utf-8"))
        return QuarantineEntry(
            carpeta=carpeta,
            uid=datos["uid"],
            nombre=datos["nombre"],
            cuando=datetime.fromisoformat(datos["cuando"]),
            archivos=[(Path(o), g) for o, g in datos["archivos"]],
        )
    except (OSError, ValueError, KeyError):
        # Una entrada ilegible no puede impedir ver las demas.
        _logger.warning("entrada de cuarentena ilegible: %s", carpeta.name)
        return None


def store(mod: Mod, rutas: list[Path]) -> QuarantineEntry | None:
    """Aparta el contenido de un mod. Devuelve la entrada, o `None` si no habia nada.

    Mueve en vez de copiar: duplicar para luego borrar el original dejaria la
    biblioteca entera repetida en disco durante la operacion, que con
    doscientos mods no es un detalle.
    """
    existentes = [r for r in rutas if r.exists()]
    if not existentes:
        return None

    sello = time.strftime("%Y%m%d-%H%M%S")
    # El uid puede traer caracteres que no valen en un nombre de carpeta.
    seguro = "".join(c if c.isalnum() or c in "-_" else "_" for c in mod.uid)[:40]
    destino = quarantine_dir() / f"{sello}-{seguro}"
    sufijo = 1
    while destino.exists():
        sufijo += 1
        destino = quarantine_dir() / f"{sello}-{seguro}-{sufijo}"
    destino.mkdir(parents=True)

    archivos: list[tuple[Path, str]] = []
    try:
        for indice, ruta in enumerate(existentes):
            # Se numera porque dos rutas distintas pueden acabar en el mismo nombre.
            guardado = f"{indice:02d}-{ruta.name}"
            shutil.move(str(ruta), str(destino / guardado))
            archivos.append((ruta, guardado))
    except OSError:
        # A medio mover no se puede dejar: el manifiesto se escribe al final,
        # asi que una entrada incompleta seria invisible al listarla y sus
        # archivos quedarian secuestrados en la cache para siempre. Se deshace
        # lo hecho y se devuelve el fallo a quien llamo, que decidira.
        for original, guardado in reversed(archivos):
            try:
                shutil.move(str(destino / guardado), str(original))
            except OSError:
                _logger.exception("no se pudo devolver %s a su sitio", original)
        shutil.rmtree(destino, ignore_errors=True)
        raise

    entrada = QuarantineEntry(
        carpeta=destino,
        uid=mod.uid,
        nombre=mod.name,
        cuando=datetime.now(UTC),
        archivos=archivos,
    )
    (destino / _MANIFIESTO).write_text(
        json.dumps(
            {
                "uid": entrada.uid,
                "nombre": entrada.nombre,
                "cuando": entrada.cuando.isoformat(),
                "archivos": [[str(o), g] for o, g in archivos],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _logger.info("apartado %s en %s", mod.name, destino.name)
    return entrada


def list_entries() -> list[QuarantineEntry]:
    """Lo apartado, de lo mas reciente a lo mas viejo."""
    raiz = quarantine_dir()
    if not raiz.is_dir():
        return []
    entradas = [e for c in raiz.iterdir() if c.is_dir() and (e := _leer(c)) is not None]
    return sorted(entradas, key=lambda e: e.cuando, reverse=True)


def restore(entrada: QuarantineEntry) -> list[str]:
    """Devuelve el contenido a su sitio. Lista de errores, vacia si fue bien.

    No se restaura encima de algo: si en la ruta original ya hay contenido, es
    que el mod se volvio a instalar y pisarlo seria perder lo nuevo.
    """
    errores: list[str] = []
    movidos: list[Path] = []
    for original, guardado in entrada.archivos:
        origen = entrada.carpeta / guardado
        if not origen.exists():
            errores.append(f"{entrada.nombre}: falta {guardado} en la cuarentena")
            continue
        if original.exists():
            errores.append(f"{entrada.nombre}: {original.name} ya existe en su sitio")
            continue
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origen), str(original))
            movidos.append(original)
        except OSError as exc:
            errores.append(f"{entrada.nombre}: no se pudo devolver {original.name} ({exc})")

    if not errores:
        shutil.rmtree(entrada.carpeta, ignore_errors=True)
        _logger.info("restaurado %s", entrada.nombre)
    return errores


def purge(dias: int = DIAS_EN_CUARENTENA) -> int:
    """Tira lo que lleve mas de `dias` apartado. Devuelve cuantas entradas cayeron.

    Con `dias=0` vacia la cuarentena entera, que es lo que hace el boton de
    vaciar: alli el usuario ya ha dicho explicitamente que no lo quiere.
    """
    limite = datetime.now(UTC) - timedelta(days=dias)
    caidas = 0
    for entrada in list_entries():
        if entrada.cuando > limite:
            continue
        shutil.rmtree(entrada.carpeta, ignore_errors=True)
        caidas += 1
    if caidas:
        _logger.info("purgadas %s entradas de la cuarentena", caidas)
    return caidas


def total_size() -> int:
    return sum(entrada.size for entrada in list_entries())
