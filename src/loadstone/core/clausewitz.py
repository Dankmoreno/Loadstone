"""Parser del subconjunto de Clausewitz que usan los descriptores de mods.

Un `.mod` o `descriptor.mod` es una esquina minuscula del lenguaje: sentencias
`clave = valor`, cadenas entre comillas, bloques con llaves que contienen o una
lista de valores o mas sentencias, y comentarios con `#`.

Las claves pueden repetirse legalmente (`replace_path` aparece una vez por
carpeta), asi que el arbol conserva el orden de insercion en lugar de colapsar
en un dict.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["Block", "ClausewitzError", "parse", "read_text"]


class ClausewitzError(ValueError):
    """Script mal formado. Lleva la linea para poder mostrarla al usuario."""

    def __init__(self, message: str, line: int) -> None:
        super().__init__(f"linea {line}: {message}")
        self.line = line


_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<comment>\#[^\n]*)
    | (?P<string>"(?:[^"\\\n]|\\.)*")
    | (?P<unterminated>"(?:[^"\\\n]|\\.)*)
    | (?P<open>\{)
    | (?P<close>\})
    | (?P<eq>=)
    | (?P<bare>[^\s"{}=\#]+)
    """,
    re.VERBOSE,
)

_ESCAPES = {'\\"': '"', "\\\\": "\\", "\\n": "\n", "\\t": "\t"}
_ESCAPE_RE = re.compile(r"\\.")


@dataclass(slots=True)
class _Token:
    kind: str
    value: str
    line: int


def _tokenize(text: str) -> Iterator[_Token]:
    line = 1
    pos = 0
    end = len(text)
    while pos < end:
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise ClausewitzError(f"caracter inesperado {text[pos]!r}", line)
        kind = match.lastgroup
        raw = match.group()
        pos = match.end()
        if kind == "unterminated":
            raise ClausewitzError("cadena sin cerrar", line)
        newlines = raw.count("\n")
        if kind in ("ws", "comment"):
            line += newlines
            continue
        yield _Token(kind, raw, line)
        line += newlines


def _unquote(raw: str) -> str:
    inner = raw[1:-1]
    if "\\" not in inner:
        return inner
    return _ESCAPE_RE.sub(lambda m: _ESCAPES.get(m.group(), m.group()[1:]), inner)


@dataclass(slots=True)
class Block:
    """Un bloque de script: secuencia ordenada de `(clave | None, valor)`.

    Los elementos de una lista (`tags = { "A" "B" }`) se guardan con clave
    `None`, asi que el mismo tipo representa bloques-mapa y bloques-lista.
    """

    entries: list[tuple[str | None, Any]] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        """Primer valor asociado a `key`. El primero gana, como el launcher."""
        for name, value in self.entries:
            if name == key:
                return value
        return default

    def get_str(self, key: str, default: str | None = None) -> str | None:
        value = self.get(key)
        return value if isinstance(value, str) else default

    def get_all(self, key: str) -> list[Any]:
        """Todos los valores de una clave repetida, en orden."""
        return [value for name, value in self.entries if name == key]

    def get_list(self, key: str) -> list[str]:
        """Valores escalares del bloque en `key`, ignorando sub-bloques.

        Tolera las dos formas que aparecen en la practica:
        `tags = { "A" "B" }` y `tags = { "A" }` repetido.
        """
        out: list[str] = []
        for value in self.get_all(key):
            if isinstance(value, Block):
                out.extend(v for _, v in value.entries if isinstance(v, str))
            elif isinstance(value, str):
                out.append(value)
        return out

    def keys(self) -> list[str]:
        return [name for name, _ in self.entries if name is not None]

    def __contains__(self, key: str) -> bool:
        return any(name == key for name, _ in self.entries)


# Un descriptor legitimo no pasa de dos niveles; el limite existe para que un
# archivo corrupto no reviente la pila de Python.
_MAX_DEPTH = 64


def parse(text: str) -> Block:
    """Parsea un script completo y devuelve el bloque raiz."""
    tokens = list(_tokenize(text))
    index = 0
    depth = 0

    def guard_depth(line: int) -> None:
        if depth > _MAX_DEPTH:
            raise ClausewitzError("anidamiento excesivo", line)

    def parse_block(is_root: bool) -> Block:
        nonlocal index, depth
        block = Block()
        while index < len(tokens):
            token = tokens[index]
            if token.kind == "close":
                if is_root:
                    raise ClausewitzError("llave de cierre sin bloque abierto", token.line)
                index += 1
                return block
            key_token = token
            index += 1
            if key_token.kind == "open":
                # Bloque anonimo dentro de una lista.
                depth += 1
                guard_depth(key_token.line)
                block.entries.append((None, parse_block(False)))
                depth -= 1
                continue
            if key_token.kind == "eq":
                raise ClausewitzError("'=' sin clave a la izquierda", key_token.line)
            name = _unquote(key_token.value) if key_token.kind == "string" else key_token.value
            if index < len(tokens) and tokens[index].kind == "eq":
                index += 1
                if index >= len(tokens):
                    raise ClausewitzError(f"falta el valor de '{name}'", key_token.line)
                value_token = tokens[index]
                index += 1
                if value_token.kind == "open":
                    depth += 1
                    guard_depth(value_token.line)
                    block.entries.append((name, parse_block(False)))
                    depth -= 1
                elif value_token.kind == "string":
                    block.entries.append((name, _unquote(value_token.value)))
                elif value_token.kind == "bare":
                    block.entries.append((name, value_token.value))
                else:
                    raise ClausewitzError(
                        f"valor inesperado {value_token.value!r} para '{name}'", value_token.line
                    )
            else:
                # Elemento suelto: item de lista.
                block.entries.append((None, name))
        if not is_root:
            raise ClausewitzError("bloque sin cerrar al final del archivo", tokens[-1].line)
        return block

    return parse_block(True)


def read_text(path: Path) -> str:
    """Lee un script del disco aguantando las codificaciones de Paradox.

    Los descriptores vienen en UTF-8, a veces con BOM, y los mods viejos o
    editados a mano aparecen en cp1252. Se prueba en ese orden y el ultimo
    intento no puede fallar.
    """
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace")
