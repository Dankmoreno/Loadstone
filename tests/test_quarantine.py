"""Pruebas de la papelera de mods desinstalados.

El `entorno_aislado` de conftest manda la cache a un temporal, asi que nada de
esto toca la cuarentena real de quien ejecuta las pruebas.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from loadstone.core.models import Mod, Playset, PlaysetMod
from loadstone.core.quarantine import (
    list_entries,
    purge,
    quarantine_dir,
    restore,
    store,
    total_size,
)
from loadstone.core.uninstall import execute_uninstall, plan_uninstall


def _mod_con_contenido(mod_dir: Path, uid: str = "uid-1", nombre: str = "Mod") -> Mod:
    carpeta = mod_dir / uid
    carpeta.mkdir(parents=True)
    (carpeta / "datos.txt").write_text("contenido", encoding="utf-8")
    descriptor = mod_dir / f"{uid}.mod"
    descriptor.write_text(f'name="{nombre}"', encoding="utf-8")
    return Mod(
        uid=uid,
        name=nombre,
        descriptor_path=descriptor,
        folder=carpeta,
        in_registry=True,
        on_disk=True,
    )


def test_apartar_mueve_y_deja_rastro_de_donde_estaba(tmp_path):
    mod = _mod_con_contenido(tmp_path / "mod")
    rutas = [mod.folder, mod.descriptor_path]

    entrada = store(mod, rutas)

    assert entrada is not None
    assert not mod.folder.exists(), "deberia mover, no copiar"
    assert not mod.descriptor_path.exists()
    assert entrada.nombre == "Mod"
    assert {o for o, _g in entrada.archivos} == set(rutas)
    assert entrada.size > 0


def test_restaurar_lo_devuelve_a_su_ruta_exacta(tmp_path):
    mod = _mod_con_contenido(tmp_path / "mod")
    entrada = store(mod, [mod.folder, mod.descriptor_path])

    assert restore(entrada) == []
    assert mod.folder.is_dir()
    assert (mod.folder / "datos.txt").read_text(encoding="utf-8") == "contenido"
    assert mod.descriptor_path.is_file()
    # La entrada desaparece de la papelera al restaurarse.
    assert list_entries() == []


def test_no_se_restaura_encima_de_algo_que_ya_esta(tmp_path):
    """Si el mod se reinstalo, pisarlo seria perder lo nuevo."""
    mod = _mod_con_contenido(tmp_path / "mod")
    entrada = store(mod, [mod.folder, mod.descriptor_path])

    mod.folder.mkdir(parents=True)
    (mod.folder / "datos.txt").write_text("version nueva", encoding="utf-8")

    errores = restore(entrada)
    assert errores and "ya existe" in errores[0]
    assert (mod.folder / "datos.txt").read_text(encoding="utf-8") == "version nueva"
    # Y lo apartado sigue ahi, no se ha perdido por el camino.
    assert len(list_entries()) == 1


def test_apartar_un_mod_sin_nada_en_disco_no_crea_entrada(tmp_path):
    vacio = Mod(uid="x", name="Fantasma", in_registry=True, on_disk=False)
    assert store(vacio, []) is None
    assert list_entries() == []


def test_dos_mods_con_el_mismo_nombre_de_archivo_no_se_pisan(tmp_path):
    uno = _mod_con_contenido(tmp_path / "a", uid="m", nombre="Uno")
    dos = _mod_con_contenido(tmp_path / "b", uid="m", nombre="Dos")

    e1 = store(uno, [uno.folder, uno.descriptor_path])
    e2 = store(dos, [dos.folder, dos.descriptor_path])

    assert e1 is not None and e2 is not None
    assert e1.carpeta != e2.carpeta
    assert len(list_entries()) == 2


def test_la_purga_respeta_lo_reciente_y_tira_lo_viejo(tmp_path, monkeypatch):
    mod = _mod_con_contenido(tmp_path / "mod")
    entrada = store(mod, [mod.folder, mod.descriptor_path])
    assert entrada is not None

    # Nada que purgar: acaba de entrar.
    assert purge(dias=14) == 0
    assert len(list_entries()) == 1

    # Se envejece el manifiesto a mano, que es mas honesto que esperar.
    manifiesto = entrada.carpeta / "entrada.json"
    datos = manifiesto.read_text(encoding="utf-8")
    viejo = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    manifiesto.write_text(
        datos.replace(entrada.cuando.isoformat(), viejo), encoding="utf-8"
    )

    assert purge(dias=14) == 1
    assert list_entries() == []


def test_purgar_con_cero_dias_vacia_la_papelera_entera(tmp_path):
    mod = _mod_con_contenido(tmp_path / "mod")
    store(mod, [mod.folder, mod.descriptor_path])
    assert total_size() > 0

    assert purge(dias=0) == 1
    assert list_entries() == []
    assert total_size() == 0


def test_una_entrada_ilegible_no_tumba_el_listado(tmp_path):
    mod = _mod_con_contenido(tmp_path / "mod")
    store(mod, [mod.folder, mod.descriptor_path])

    rota = quarantine_dir() / "20200101-000000-rota"
    rota.mkdir(parents=True)
    (rota / "entrada.json").write_text("{esto no es json", encoding="utf-8")

    assert len(list_entries()) == 1


def test_desinstalar_aparta_en_vez_de_borrar(tmp_path):
    """El caso completo: se desinstala y se puede deshacer."""
    mod = _mod_con_contenido(tmp_path / "mod")
    playset = Playset(id="p", name="P", mods=[PlaysetMod(uid="uid-1")])
    plan = plan_uninstall(mod, [playset], mod_dir=tmp_path / "mod")

    hechos, errores = execute_uninstall([plan], save_playset=lambda p: None)

    assert (hechos, errores) == (1, [])
    assert not mod.folder.exists()
    entradas = list_entries()
    assert len(entradas) == 1
    assert entradas[0].nombre == "Mod"

    assert restore(entradas[0]) == []
    assert (mod.folder / "datos.txt").read_text(encoding="utf-8") == "contenido"


def test_se_puede_desinstalar_sin_papelera(tmp_path):
    """Para quien prefiera que el espacio se libere en el acto."""
    mod = _mod_con_contenido(tmp_path / "mod")
    plan = plan_uninstall(mod, [], mod_dir=tmp_path / "mod")

    hechos, errores = execute_uninstall([plan], quarantine=False)

    assert (hechos, errores) == (1, [])
    assert not mod.folder.exists()
    assert list_entries() == []


def test_si_apartar_falla_no_se_borra_ni_se_desregistra(tmp_path, monkeypatch):
    """Apartar es ahora el primer paso: si falla, no sigue nada mas."""
    mod = _mod_con_contenido(tmp_path / "mod")
    monkeypatch.setattr(
        "loadstone.core.quarantine.shutil.move",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno")),
    )

    quitados: list[str] = []
    plan = plan_uninstall(mod, [], mod_dir=tmp_path / "mod")
    hechos, errores = execute_uninstall([plan], unregister=quitados.append)

    assert hechos == 0
    assert errores and "no se pudo apartar" in errores[0]
    assert mod.folder.exists(), "el contenido sigue donde estaba"
    assert quitados == [], "no se desregistra lo que no se ha podido quitar"


def test_un_fallo_a_medio_apartar_no_secuestra_archivos(tmp_path, monkeypatch):
    """El manifiesto se escribe al final: media entrada seria invisible."""
    mod = _mod_con_contenido(tmp_path / "mod")
    rutas = [mod.folder, mod.descriptor_path]

    real = __import__("shutil").move
    llamadas = {"n": 0}

    def move_que_falla_a_la_segunda(origen, destino):
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise OSError("se acabo el sitio")
        return real(origen, destino)

    monkeypatch.setattr(
        "loadstone.core.quarantine.shutil.move", move_que_falla_a_la_segunda
    )

    try:
        store(mod, rutas)
    except OSError:
        pass

    # Lo que se llego a mover vuelve a su sitio y no queda entrada a medias.
    assert mod.folder.exists()
    assert list_entries() == []
    assert not any(quarantine_dir().iterdir()) if quarantine_dir().is_dir() else True
