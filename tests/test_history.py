from loadstone.core.history import History, diff_snapshots, restore_into
from loadstone.core.models import Mod, Playset, PlaysetMod


def mods_de(*nombres):
    return {
        nombre: Mod(uid=nombre, name=nombre.upper(), registry_id=f"mod/{nombre}.mod")
        for nombre in nombres
    }


def playset_de(*entradas):
    return Playset(
        id="p",
        name="Prueba",
        mods=[
            PlaysetMod(uid=uid, enabled=enabled, position=indice)
            for indice, (uid, enabled) in enumerate(entradas)
        ],
    )


def test_guarda_y_relee(tmp_path):
    historial = History("stellaris", tmp_path)
    snapshot = historial.save(playset_de(("a", True), ("b", False)), mods_de("a", "b"))

    assert snapshot.playset == "Prueba"
    assert snapshot.enabled_ids == ["mod/a.mod"]
    assert [s.id for s in historial.list()] == [snapshot.id]


def test_no_guarda_mods_sin_descriptor(tmp_path):
    # Sin registry_id no hay forma de restaurarlo despues.
    mods = mods_de("a")
    mods["b"] = Mod(uid="b", name="B", registry_id=None)
    snapshot = History("s", tmp_path).save(playset_de(("a", True), ("b", True)), mods)
    assert len(snapshot.entries) == 1


def test_dos_instantaneas_el_mismo_segundo_no_se_pisan(tmp_path):
    historial = History("s", tmp_path)
    primera = historial.save(playset_de(("a", True)), mods_de("a"))
    segunda = historial.save(playset_de(("a", True)), mods_de("a"))
    assert primera.id != segunda.id
    assert len(historial.list()) == 2


def test_poda_las_viejas(tmp_path):
    historial = History("s", tmp_path)
    for _ in range(5):
        historial.save(playset_de(("a", True)), mods_de("a"), keep=3)
    assert len(historial.list()) == 3


def test_notas(tmp_path):
    historial = History("s", tmp_path)
    snapshot = historial.save(playset_de(("a", True)), mods_de("a"))
    assert historial.set_note(snapshot.id, "antes de la partida larga")
    assert historial.get(snapshot.id).note == "antes de la partida larga"
    assert not historial.set_note("no-existe", "x")


def test_diff_detecta_altas_bajas_y_movimientos(tmp_path):
    historial = History("s", tmp_path)
    mods = mods_de("a", "b", "c", "d")
    antigua = historial.save(playset_de(("a", True), ("b", True), ("c", True)), mods)
    nueva = historial.save(playset_de(("b", True), ("c", True), ("a", True), ("d", True)), mods)

    cambios = diff_snapshots(antigua, nueva)
    assert cambios.added == ["D"]
    assert cambios.removed == []
    # Mover A al final desplaza a B y C, pero el movido es solo A.
    assert cambios.moved == ["A"]
    assert "1 anadidos" in cambios.summary()


def test_diff_cuenta_como_baja_lo_desactivado(tmp_path):
    historial = History("s", tmp_path)
    mods = mods_de("a", "b")
    antigua = historial.save(playset_de(("a", True), ("b", True)), mods)
    nueva = historial.save(playset_de(("a", True), ("b", False)), mods)
    assert diff_snapshots(antigua, nueva).removed == ["B"]


def test_sin_cambios(tmp_path):
    historial = History("s", tmp_path)
    mods = mods_de("a")
    una = historial.save(playset_de(("a", True)), mods)
    otra = historial.save(playset_de(("a", True)), mods)
    assert diff_snapshots(una, otra).is_empty
    assert diff_snapshots(una, otra).summary() == "sin cambios"


def test_restaurar_recoloca_y_avisa_de_lo_que_falta(tmp_path):
    historial = History("s", tmp_path)
    mods = mods_de("a", "b", "c")
    snapshot = historial.save(
        playset_de(("c", True), ("a", False), ("b", True)), mods
    )

    # "c" ya no esta instalado cuando se restaura.
    instalados = [mods["a"], mods["b"]]
    playset = playset_de(("a", True))
    colocados, faltantes = restore_into(snapshot, playset, instalados)

    assert colocados == 2
    assert faltantes == ["C"]
    assert [(e.uid, e.enabled, e.position) for e in playset.mods] == [
        ("a", False, 0),
        ("b", True, 1),
    ]


def test_historial_vacio(tmp_path):
    assert History("s", tmp_path).list() == []
    assert History("s", tmp_path).get("lo-que-sea") is None
