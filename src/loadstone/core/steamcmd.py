"""Descarga de mods del Workshop de Steam con SteamCMD.

Comprobado el 2026-10-12: `+login anonymous +workshop_download_item 281990 <id>`
descarga mods de Stellaris sin necesidad de poseer el juego en la cuenta. Valve
permite el acceso anonimo al contenido de usuario de ese appid, asi que esto
funciona tambien en instalaciones que no vienen de Steam.

No esta verificado para los demas juegos: el permiso depende de la
configuracion de cada aplicacion. Por eso aqui no se asume nada, se intenta la
descarga y se lee el resultado.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .logs import get_logger
from .paths import steamcmd_dir

__all__ = ["DownloadResult", "SteamCmd", "SteamCmdError"]

_STEAMCMD_ZIP_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

# La salida trae barras de progreso con retornos de carro; se normaliza antes.
_SUCCESS_RE = re.compile(
    r'Success\. Downloaded item (\d+) to "(.+?)" \((\d+) bytes\)', re.IGNORECASE
)
_FAILURE_RE = re.compile(r"ERROR! Download item (\d+) failed \((.+?)\)", re.IGNORECASE)


_logger = get_logger("steamcmd")


class SteamCmdError(RuntimeError):
    """SteamCMD no se pudo preparar o ejecutar."""


@dataclass(slots=True)
class DownloadResult:
    item_id: str
    ok: bool
    path: Path | None = None
    size: int | None = None
    error: str | None = None


class SteamCmd:
    """Envoltorio del ejecutable de SteamCMD."""

    def __init__(self, executable: Path) -> None:
        self.executable = executable

    # ------------------------------------------------------------ arranque

    @staticmethod
    def default_dir() -> Path:
        # En cache y no en datos: son cientos de MB que siempre se pueden
        # volver a descargar.
        return steamcmd_dir()

    @classmethod
    def find(cls, explicit: Path | None = None) -> SteamCmd | None:
        """Busca SteamCMD sin descargar nada."""
        if explicit:
            return cls(explicit) if explicit.is_file() else None
        local = cls.default_dir() / ("steamcmd.exe" if os.name == "nt" else "steamcmd.sh")
        if local.is_file():
            return cls(local)
        found = shutil.which("steamcmd") or shutil.which("steamcmd.exe")
        return cls(Path(found)) if found else None

    @classmethod
    def bootstrap(cls, target_dir: Path | None = None) -> SteamCmd:
        """Descarga el SteamCMD oficial de Valve si no esta ya disponible.

        Solo automatiza el caso de Windows, que es donde Valve publica un zip
        autocontenido. En Linux y macOS se espera que lo instale el gestor de
        paquetes, porque ahi SteamCMD depende de bibliotecas del sistema.
        """
        existing = cls.find()
        if existing is not None:
            return existing
        if platform.system() != "Windows":
            raise SteamCmdError(
                "SteamCMD no esta instalado. Instalalo con el gestor de paquetes "
                "de tu sistema y vuelve a intentarlo."
            )

        directory = target_dir or cls.default_dir()
        directory.mkdir(parents=True, exist_ok=True)
        archive = directory / "steamcmd.zip"
        try:
            with urllib.request.urlopen(_STEAMCMD_ZIP_URL, timeout=120) as response:
                archive.write_bytes(response.read())
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(directory)
        except (OSError, zipfile.BadZipFile) as exc:
            raise SteamCmdError(f"no se pudo descargar SteamCMD: {exc}") from exc
        finally:
            archive.unlink(missing_ok=True)

        executable = directory / "steamcmd.exe"
        if not executable.is_file():
            raise SteamCmdError("el paquete de SteamCMD no contenia steamcmd.exe")
        return cls(executable)

    # ------------------------------------------------------------ descarga

    def download(
        self,
        appid: int,
        item_ids: list[str],
        *,
        timeout: int = 3600,
        login: str = "anonymous",
    ) -> list[DownloadResult]:
        """Descarga uno o varios items del Workshop en una sola sesion.

        Agrupar las descargas importa: cada arranque de SteamCMD comprueba
        actualizaciones y tarda varios segundos, asi que pedirlas de una vez es
        mucho mas rapido que llamar al ejecutable por cada mod.
        """
        if not item_ids:
            return []
        command = [str(self.executable), "+login", login]
        for item_id in item_ids:
            command += ["+workshop_download_item", str(appid), str(item_id)]
        command.append("+quit")

        # Con una cuenta real, SteamCMD pide la clave y el codigo de Steam
        # Guard por consola. Capturar su salida lo dejaria colgado esperando una
        # entrada que nadie ve, asi que en ese caso hereda la terminal y el
        # resultado se deduce de lo que haya quedado en disco.
        interactive = login != "anonymous"
        try:
            completed = subprocess.run(
                command,
                # SteamCMD devuelve 0 incluso cuando una descarga falla, asi
                # que el codigo de salida no sirve: manda lo que diga la salida.
                check=False,
                capture_output=not interactive,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=self.executable.parent,
            )
        except subprocess.TimeoutExpired as exc:
            raise SteamCmdError(f"SteamCMD no termino en {timeout}s") from exc
        except OSError as exc:
            raise SteamCmdError(f"no se pudo ejecutar SteamCMD: {exc}") from exc

        if interactive:
            return [self.result_from_disk(appid, item_id) for item_id in item_ids]
        resultados = self._parse(completed.stdout or "", item_ids)
        _logger.info(
            "steamcmd: %d de %d descargados",
            sum(1 for r in resultados if r.ok),
            len(resultados),
        )
        return resultados

    def content_dir(self, appid: int) -> Path:
        """Carpeta donde SteamCMD deja el contenido descargado."""
        return self.executable.parent / "steamapps" / "workshop" / "content" / str(appid)

    def result_from_disk(self, appid: int, item_id: str) -> DownloadResult:
        """Deduce el resultado mirando la carpeta de destino.

        Es el recurso cuando no se pudo leer la salida del proceso.
        """
        path = self.content_dir(appid) / str(item_id)
        if not path.is_dir():
            return DownloadResult(
                item_id=str(item_id), ok=False, error="no se descargo nada en el destino"
            )
        size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        if size == 0:
            return DownloadResult(
                item_id=str(item_id), ok=False, error="la carpeta descargada esta vacia"
            )
        return DownloadResult(item_id=str(item_id), ok=True, path=path, size=size)

    @staticmethod
    def _parse(output: str, item_ids: list[str]) -> list[DownloadResult]:
        text = output.replace("\r", "\n")
        results: dict[str, DownloadResult] = {}
        for match in _SUCCESS_RE.finditer(text):
            item_id, path, size = match.groups()
            results[item_id] = DownloadResult(
                item_id=item_id, ok=True, path=Path(path), size=int(size)
            )
        for match in _FAILURE_RE.finditer(text):
            item_id, reason = match.groups()
            if item_id not in results:
                results[item_id] = DownloadResult(item_id=item_id, ok=False, error=reason)

        ordered: list[DownloadResult] = []
        for item_id in item_ids:
            key = str(item_id)
            ordered.append(
                results.get(
                    key,
                    DownloadResult(
                        item_id=key,
                        ok=False,
                        error="SteamCMD no informo de este item (revisa el id)",
                    ),
                )
            )
        return ordered
