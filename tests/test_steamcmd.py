"""Parseo de la salida de SteamCMD.

Las cadenas de ejemplo son las de una sesion real del 2026-10-12 contra el
appid 281990 (Stellaris) con `+login anonymous`.
"""

from pathlib import Path

from loadstone.core.steamcmd import SteamCmd

_SALIDA_OK = (
    "Steam Console Client (c) Valve Corporation - version 1788292693\r\n"
    "Connecting anonymously to Steam Public...OK\r\n"
    "Waiting for client config...OK\r\n"
    "Downloading item 1087781345 ...\r\n"
    'Success. Downloaded item 1087781345 to "C:\\steamcmd\\steamapps\\workshop'
    '\\content\\281990\\1087781345" (372760 bytes)\r\n'
)


def test_lee_una_descarga_correcta():
    resultado = SteamCmd._parse(_SALIDA_OK, ["1087781345"])[0]
    assert resultado.ok
    assert resultado.size == 372760
    assert resultado.path == Path(r"C:\steamcmd\steamapps\workshop\content\281990\1087781345")


def test_lee_un_fallo_con_su_motivo():
    salida = "Downloading item 999 ...\r\nERROR! Download item 999 failed (Failure).\r\n"
    resultado = SteamCmd._parse(salida, ["999"])[0]
    assert not resultado.ok
    assert resultado.error and "Failure" in resultado.error


def test_conserva_el_orden_pedido():
    salida = _SALIDA_OK + "ERROR! Download item 222 failed (Timeout).\r\n"
    resultados = SteamCmd._parse(salida, ["222", "1087781345"])
    assert [r.item_id for r in resultados] == ["222", "1087781345"]
    assert [r.ok for r in resultados] == [False, True]


def test_item_del_que_no_se_informa_nada():
    # Un id inexistente puede no aparecer en la salida: no se da por bueno.
    resultado = SteamCmd._parse(_SALIDA_OK, ["404"])[0]
    assert not resultado.ok
    assert resultado.error and "revisa el id" in resultado.error


def test_resultado_deducido_del_disco(tmp_path):
    # Con cuenta real no se puede leer la salida, asi que manda el disco.
    exe = tmp_path / "steamcmd.exe"
    exe.write_bytes(b"")
    steamcmd = SteamCmd(exe)

    destino = steamcmd.content_dir(281990) / "777"
    destino.mkdir(parents=True)
    (destino / "descriptor.mod").write_text('name="X"', encoding="utf-8")

    bueno = steamcmd.result_from_disk(281990, "777")
    assert bueno.ok and bueno.size == 8 and bueno.path == destino

    assert not steamcmd.result_from_disk(281990, "888").ok

    vacio = steamcmd.content_dir(281990) / "999"
    vacio.mkdir(parents=True)
    resultado = steamcmd.result_from_disk(281990, "999")
    assert not resultado.ok and "vacia" in resultado.error
