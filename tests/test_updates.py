from datetime import UTC, datetime, timedelta

import pytest

from loadstone.core.models import Mod
from loadstone.core.updates import UpdateState, check_updates
from loadstone.core.workshop_api import WorkshopItem, parse_workshop_id

AHORA = datetime(2026, 10, 12, tzinfo=UTC)


def hacer_mod(tmp_path, nombre="Mod", steam_id="123456789", contenido="x" * 100):
    carpeta = tmp_path / nombre.replace(" ", "_")
    carpeta.mkdir()
    (carpeta / "descriptor.mod").write_text(contenido, encoding="utf-8")
    return Mod(uid=nombre, name=nombre, steam_id=steam_id, folder=carpeta, on_disk=True)


def test_mismo_tamano_es_estar_al_dia(tmp_path):
    mod = hacer_mod(tmp_path)
    remoto = {mod.steam_id: WorkshopItem(mod.steam_id, "Mod", AHORA, file_size=100)}
    estado = check_updates([mod], details=remoto)[0]
    assert estado.state is UpdateState.UP_TO_DATE


def test_tamano_distinto_es_desactualizado(tmp_path):
    mod = hacer_mod(tmp_path)
    remoto = {mod.steam_id: WorkshopItem(mod.steam_id, "Mod", AHORA, file_size=5000)}
    estado = check_updates([mod], details=remoto)[0]
    assert estado.state is UpdateState.OUTDATED
    assert "4.900 bytes mas" in estado.reason


def test_fecha_mas_nueva_es_desactualizado(tmp_path):
    mod = hacer_mod(tmp_path)
    futuro = datetime.now(tz=UTC) + timedelta(days=30)
    remoto = {mod.steam_id: WorkshopItem(mod.steam_id, "Mod", futuro, file_size=100)}
    estado = check_updates([mod], details=remoto)[0]
    assert estado.state is UpdateState.OUTDATED
    assert "Workshop el" in estado.reason


def test_un_margen_evita_los_falsos_positivos(tmp_path):
    # Publicado un par de horas despues de instalarlo: no es una version nueva.
    mod = hacer_mod(tmp_path)
    poco_despues = datetime.now(tz=UTC) + timedelta(hours=2)
    remoto = {mod.steam_id: WorkshopItem(mod.steam_id, "Mod", poco_despues, file_size=100)}
    assert check_updates([mod], details=remoto)[0].state is UpdateState.UP_TO_DATE


def test_mod_retirado_del_workshop(tmp_path):
    mod = hacer_mod(tmp_path)
    remoto = {mod.steam_id: WorkshopItem(mod.steam_id, available=False)}
    estado = check_updates([mod], details=remoto)[0]
    assert estado.state is UpdateState.REMOVED


def test_mod_local_no_se_consulta(tmp_path):
    mod = hacer_mod(tmp_path, steam_id=None)
    estado = check_updates([mod], details={})[0]
    assert estado.state is UpdateState.UNKNOWN
    assert "no viene del Workshop" in estado.reason


def test_steam_sin_respuesta_no_se_da_por_bueno(tmp_path):
    mod = hacer_mod(tmp_path)
    estado = check_updates([mod], details={})[0]
    assert estado.state is UpdateState.UNKNOWN


def test_cambio_de_titulo_se_conserva(tmp_path):
    mod = hacer_mod(tmp_path, nombre="Giga (4.3)")
    remoto = {mod.steam_id: WorkshopItem(mod.steam_id, "Giga (4.5)", AHORA, file_size=9999)}
    estado = check_updates([mod], details=remoto)[0]
    assert estado.remote_title == "Giga (4.5)"


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("1087781345", "1087781345"),
        ("https://steamcommunity.com/sharedfiles/filedetails/?id=1087781345", "1087781345"),
        ("https://steamcommunity.com/workshop/filedetails/?id=1087781345&tab=info", "1087781345"),
        ("no hay id aqui", None),
        ("123", None),
    ],
)
def test_extraer_id_del_workshop(entrada, esperado):
    assert parse_workshop_id(entrada) == esperado
