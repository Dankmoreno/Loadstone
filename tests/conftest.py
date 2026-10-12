"""Configuracion comun de las pruebas.

Dos garantias que importan mas de lo que parece:

- ninguna prueba lee ni escribe la configuracion real de quien las ejecuta,
- ninguna prueba sale a internet.

La segunda es facil de romper sin darse cuenta: `check_updates` consulta a
Steam si no se le pasan los datos, y una prueba que lo olvide pasaria en una
maquina con red y fallaria en la integracion continua.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Sin esto, cualquier prueba que cree un widget abre una ventana de verdad en
# la pantalla de quien ejecuta las pruebas, y en la integracion continua no
# hay pantalla ninguna.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from loadstone.core.paths import HOME_ENV


@pytest.fixture(autouse=True)
def entorno_aislado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Manda la configuracion, el historial y los registros a un temporal."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "loadstone-home"))
    yield


@pytest.fixture(autouse=True)
def sin_red(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Corta el acceso a la red salvo que la prueba lo pida explicitamente.

    Una prueba marcada con `@pytest.mark.network` queda exenta.
    """
    if request.node.get_closest_marker("network"):
        return

    import urllib.request

    def prohibido(*args: object, **kwargs: object):
        raise AssertionError(
            f"la prueba {request.node.name} ha intentado salir a la red; "
            "pasale los datos en vez de consultarlos"
        )

    monkeypatch.setattr(urllib.request, "urlopen", prohibido)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "network: la prueba necesita internet")
