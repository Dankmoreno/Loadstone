"""Carpetas de la aplicacion.

Antes esto estaba resuelto a mano en tres modulos distintos, leyendo `APPDATA`
con un `~/.config` de consuelo: correcto en Windows, flojo en Linux (ignoraba
`XDG_CONFIG_HOME`) y equivocado en macOS. `platformdirs` conoce la convencion
de cada sistema, asi que aqui solo queda decidir que va en cada sitio.

El reparto importa porque los sistemas lo tratan distinto: lo que el usuario no
querria perder va en datos, y lo que se puede regenerar va en cache.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import PlatformDirs

__all__ = [
    "HOME_ENV",
    "browser_profile_dir",
    "cache_dir",
    "config_file",
    "history_dir",
    "legacy_config_files",
    "legacy_history_dirs",
    "log_dir",
    "steamcmd_dir",
]

APP_NAME = "loadstone"

HOME_ENV = "LOADSTONE_HOME"
"""Variable que concentra todas las carpetas bajo una sola ruta.

Sirve para dos cosas: una instalacion portatil que guarda su estado junto al
ejecutable, en un USB por ejemplo, y unas pruebas que no tocan la configuracion
real de quien las ejecuta. En Windows `platformdirs` resuelve las carpetas
consultando al sistema y no la variable `APPDATA`, asi que redirigirlas desde
fuera necesita una via propia.
"""


def _home_override() -> Path | None:
    valor = os.environ.get(HOME_ENV, "").strip()
    return Path(valor) if valor else None


def _dirs() -> PlatformDirs:
    """Se construye en cada llamada, no al importar.

    En Windows `platformdirs` lee `APPDATA` y `LOCALAPPDATA` del entorno. Si se
    resolviera una sola vez al importar el modulo, las pruebas no podrian
    apuntarlo a un directorio temporal y acabarian leyendo y escribiendo en la
    configuracion real del usuario.
    """
    return PlatformDirs(appname=APP_NAME, appauthor=False, roaming=True)


def config_file() -> Path:
    """Las preferencias del usuario: pocas, pequenas y suyas."""
    raiz = _home_override()
    if raiz is not None:
        return raiz / "config.json"
    return Path(_dirs().user_config_dir) / "config.json"


def history_dir() -> Path:
    """Las instantaneas de listas de mods, que no se pueden reconstruir."""
    raiz = _home_override()
    if raiz is not None:
        return raiz / "history"
    return Path(_dirs().user_data_dir) / "history"


def log_dir() -> Path:
    raiz = _home_override()
    return raiz / "logs" if raiz is not None else Path(_dirs().user_log_dir)


def cache_dir() -> Path:
    raiz = _home_override()
    return raiz / "cache" if raiz is not None else Path(_dirs().user_cache_dir)


def steamcmd_dir() -> Path:
    """SteamCMD y lo que descarga: pesado y siempre recuperable."""
    return cache_dir() / "steamcmd"


def browser_profile_dir() -> Path:
    """Sesion del navegador del Workshop: cookies, para no reiniciar sesion.

    Va en datos y no en cache porque perderla obliga a volver a entrar en
    Steam a mano, que es justo la molestia que el navegador empotrado evita.
    """
    raiz = _home_override()
    if raiz is not None:
        return raiz / "browser"
    return Path(_dirs().user_data_dir) / "browser"


def legacy_config_files() -> list[Path]:
    """Rutas donde vivio la configuracion antes, de la mas reciente a la mas vieja.

    El proyecto cambio de nombre dos veces y de convencion de carpetas una, y
    cada cambio podia dejar al usuario sin sus rutas de busqueda sin que nada
    se lo explicara.
    """
    candidatas: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        raiz = Path(appdata)
        candidatas += [
            raiz / "loadstone" / "config.json",
            raiz / "stellaris-sort" / "config.json",
            raiz / "parasort" / "config.json",
        ]
    hogar = Path.home() / ".config"
    candidatas += [
        hogar / "loadstone" / "config.json",
        hogar / "stellaris-sort" / "config.json",
        hogar / "parasort" / "config.json",
    ]
    actual = config_file()
    return [ruta for ruta in candidatas if ruta != actual]


def legacy_history_dirs() -> list[Path]:
    """Historiales guardados antes del cambio a `platformdirs`."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    antigua = Path(appdata) / "loadstone" / "history"
    return [antigua] if antigua != history_dir() else []
