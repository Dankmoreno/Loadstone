"""Cliente de la API publica del Workshop de Steam.

Dos endpoints bastan para lo que Loadstone necesita, y ninguno pide clave de
API ni cuenta: se consultan con una peticion POST con formulario.

- `GetPublishedFileDetails`: titulo, tamano y fecha de la ultima actualizacion
  de cada mod. Es lo que permite saber que hay version nueva sin descargar
  nada.
- `GetCollectionDetails`: los mods que componen una coleccion.

Comprobado el 2026-10-12 contra el appid 281990.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime

__all__ = [
    "WorkshopApiError",
    "WorkshopItem",
    "collection_items",
    "parse_workshop_id",
    "published_file_details",
]

_BASE = "https://api.steampowered.com/ISteamRemoteStorage"
# Steam acepta lotes grandes, pero trocear evita peticiones enormes y permite
# que un fallo puntual no tire la consulta entera.
_LOTE = 100
_ID_RE = re.compile(r"(?:^|[?&]id=|/)(\d{6,})")


class WorkshopApiError(RuntimeError):
    """No se pudo consultar la API publica de Steam."""


@dataclass(slots=True)
class WorkshopItem:
    """Lo que el Workshop sabe de un mod."""

    item_id: str
    title: str | None = None
    time_updated: datetime | None = None
    file_size: int | None = None
    app_id: int | None = None
    available: bool = True
    """`False` si el mod fue borrado, ocultado o baneado."""


def parse_workshop_id(text: str) -> str | None:
    """Saca el id de un enlace del Workshop, o lo devuelve si ya es un id.

    Acepta las formas con las que la gente copia y pega: la URL completa, la
    URL con parametros de mas, o el numero a secas.
    """
    candidato = text.strip()
    # Se exige la misma longitud minima en las dos ramas: los ids del Workshop
    # son largos, y aceptar un numero de tres cifras solo sirve para que el
    # error aparezca mas tarde, en forma de descarga fallida.
    if candidato.isdigit():
        return candidato if len(candidato) >= 6 else None
    match = _ID_RE.search(candidato)
    return match.group(1) if match else None


def _post(endpoint: str, campos: dict[str, str], timeout: int) -> dict:
    datos = urllib.parse.urlencode(campos).encode("utf-8")
    peticion = urllib.request.Request(
        f"{_BASE}/{endpoint}/v1/",
        data=datos,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            cuerpo = json.loads(respuesta.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WorkshopApiError(f"no se pudo consultar Steam: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise WorkshopApiError(f"Steam devolvio una respuesta ilegible: {exc}") from exc

    respuesta_api = cuerpo.get("response")
    if not isinstance(respuesta_api, dict):
        raise WorkshopApiError("Steam devolvio una respuesta con forma inesperada")
    return respuesta_api


def _fecha(valor: object) -> datetime | None:
    if not isinstance(valor, int) or valor <= 0:
        return None
    return datetime.fromtimestamp(valor, tz=UTC)


def published_file_details(
    item_ids: list[str], *, timeout: int = 30
) -> dict[str, WorkshopItem]:
    """Consulta varios mods del Workshop a la vez.

    Devuelve un mapa por id. Los mods borrados o privados aparecen con
    `available=False` en vez de desaparecer del resultado, porque "este mod ya
    no existe" es justo lo que interesa saber.
    """
    unicos = [str(i) for i in dict.fromkeys(item_ids) if str(i).strip()]
    resultado: dict[str, WorkshopItem] = {}

    for inicio in range(0, len(unicos), _LOTE):
        lote = unicos[inicio : inicio + _LOTE]
        campos = {"itemcount": str(len(lote))}
        for indice, item_id in enumerate(lote):
            campos[f"publishedfileids[{indice}]"] = item_id

        respuesta = _post("GetPublishedFileDetails", campos, timeout)
        for detalle in respuesta.get("publishedfiledetails") or []:
            if not isinstance(detalle, dict):
                continue
            item_id = str(detalle.get("publishedfileid") or "")
            if not item_id:
                continue
            # `result` 1 es correcto; cualquier otro valor significa que el mod
            # no esta accesible, normalmente porque lo borraron.
            disponible = detalle.get("result") == 1
            resultado[item_id] = WorkshopItem(
                item_id=item_id,
                title=detalle.get("title") or None,
                time_updated=_fecha(detalle.get("time_updated")),
                file_size=_entero(detalle.get("file_size")),
                app_id=_entero(detalle.get("consumer_app_id")),
                available=disponible,
            )
    return resultado


def _entero(valor: object) -> int | None:
    # Steam devuelve los tamanos unas veces como numero y otras como cadena.
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and valor.isdigit():
        return int(valor)
    return None


def collection_items(collection_id: str, *, timeout: int = 30) -> list[str]:
    """Ids de los mods que componen una coleccion, en el orden que define.

    Se filtran los elementos que no son mods: una coleccion puede contener
    otras colecciones, y esas tienen `filetype` distinto de 0.
    """
    respuesta = _post(
        "GetCollectionDetails",
        {"collectioncount": "1", "publishedfileids[0]": str(collection_id)},
        timeout,
    )
    detalles = respuesta.get("collectiondetails") or []
    if not detalles or not isinstance(detalles[0], dict):
        raise WorkshopApiError(f"la coleccion {collection_id} no existe o es privada")

    detalle = detalles[0]
    if detalle.get("result") != 1:
        raise WorkshopApiError(
            f"la coleccion {collection_id} no esta accesible (codigo {detalle.get('result')})"
        )

    hijos = [h for h in detalle.get("children") or [] if isinstance(h, dict)]
    hijos.sort(key=lambda h: _entero(h.get("sortorder")) or 0)
    return [
        str(h["publishedfileid"])
        for h in hijos
        if h.get("publishedfileid") and _entero(h.get("filetype")) in (0, None)
    ]
