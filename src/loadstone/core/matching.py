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

__all__ = ["dependency_index", "normalize", "suggest_similar"]

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
