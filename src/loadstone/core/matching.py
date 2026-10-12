"""Resolucion de dependencias declaradas por nombre.

Paradox no da identificadores a las dependencias: un descriptor escribe
`dependencies={ "UI Overhaul Dynamic" }` y el launcher busca un mod que se
llame asi. Como el autor copia ese texto a mano, en la practica aparece el
nombre visible, el id del Workshop o el nombre de la carpeta.

Esta tabla acepta las tres formas, con prioridad para el nombre visible, que es
la unica que el launcher reconoce oficialmente. Cuando ninguna encaja, queda la
comparacion difusa: decir "no esta instalado" a secas es cierto pero inutil, y
casi siempre la diferencia es una version en el titulo, un prefijo de adorno o
una errata del autor.
"""

from __future__ import annotations

from rapidfuzz import fuzz, process

from .models import Mod

__all__ = ["dependency_index", "normalize", "required_mods", "suggest_similar"]

# Calibrado contra una instalacion de 213 mods. Por debajo de 70 empareja
# cosas que solo comparten vocabulario generico ("expanded", "events"). Por
# encima de 80 no encuentra nada util: el caso real que importa, un mod que
# pide "UI Overhaul 1080p Plus" teniendo "UI Overhaul Dynamic", puntua 73.
#
# Como a esa altura la coincidencia no es certeza, quien llama no debe
# presentarla como "es este", sino como "esto es lo mas parecido que tienes".
_UMBRAL = 70.0


def normalize(text: str) -> str:
    return text.strip().lower()


def dependency_index(mods: list[Mod]) -> dict[str, Mod]:
    """Mapa de alias a mod. El primer mod que reclama un alias se lo queda."""
    index: dict[str, Mod] = {}

    def claim(alias: str | None, mod: Mod) -> None:
        if alias:
            index.setdefault(normalize(alias), mod)

    for mod in mods:
        claim(mod.name, mod)
    # Los alias secundarios se registran despues para que nunca le quiten el
    # sitio al nombre real de otro mod.
    for mod in mods:
        claim(mod.steam_id, mod)
        claim(mod.folder.name if mod.folder else None, mod)
        if mod.registry_id:
            claim(mod.registry_id.rsplit("/", 1)[-1].removesuffix(".mod"), mod)
    return index


def required_mods(
    semillas: list[Mod], instalados: list[Mod], ya_presentes: set[str]
) -> list[Mod]:
    """Dependencias instaladas que hacen falta y todavia no estan en la lista.

    Se sigue la cadena entera, no un solo nivel: anadir un mod que necesita un
    parche que a su vez necesita una biblioteca y quedarse a medias deja el
    mismo error de antes con un nombre distinto.

    Solo devuelve lo que ya esta instalado. Una dependencia que no se tiene no
    se puede resolver desde aqui: el descriptor solo da un nombre, y buscar ese
    nombre en el Workshop necesita una clave de API que esta aplicacion no
    pide. Para esas queda el diagnostico, que ademas sugiere el mod instalado
    mas parecido.

    El orden de salida es el de descubrimiento, de la dependencia mas cercana a
    la mas lejana; quien lo use para escribir un playset debe reordenar
    despues, que para eso esta `sorting`.
    """
    indice = dependency_index(instalados)
    pendientes = list(semillas)
    vistos = {mod.uid for mod in semillas}
    encontrados: list[Mod] = []

    while pendientes:
        actual = pendientes.pop(0)
        for nombre in actual.dependencies:
            objetivo = indice.get(normalize(nombre))
            if objetivo is None or objetivo.uid in vistos:
                continue
            vistos.add(objetivo.uid)
            # Se sigue la cadena aunque ya este en la lista: sus propias
            # dependencias pueden faltar igualmente.
            pendientes.append(objetivo)
            if objetivo.uid not in ya_presentes:
                encontrados.append(objetivo)
    return encontrados


def suggest_similar(
    nombre: str, candidatos: list[Mod], *, limite: int = 2
) -> list[tuple[Mod, float]]:
    """Mods instalados cuyo nombre se parece al que se buscaba.

    Se usa `token_set_ratio` en vez de una comparacion literal porque las
    diferencias tipicas son de palabras sueltas: "Plentiful Traditions 4.2.x"
    frente a "Plentiful Traditions", o un "[4.3]" delante. Ese algoritmo
    compara los conjuntos de palabras, asi que el ruido del titulo deja de
    pesar.
    """
    buscado = normalize(nombre)
    if not buscado or not candidatos:
        return []

    por_nombre = {normalize(mod.name): mod for mod in candidatos if mod.name}
    coincidencias = process.extract(
        buscado,
        list(por_nombre),
        scorer=fuzz.token_set_ratio,
        limit=limite,
        score_cutoff=_UMBRAL,
    )
    return [(por_nombre[texto], puntuacion) for texto, puntuacion, _ in coincidencias]
