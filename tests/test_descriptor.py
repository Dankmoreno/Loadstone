from loadstone.core.descriptor import scan_mod_dir


def write_mod(mod_dir, stem, body):
    (mod_dir / f"{stem}.mod").write_text(body, encoding="utf-8")


def test_distingue_presente_colgado_y_sin_enlazar(tmp_path):
    data = tmp_path / "Stellaris"
    mod_dir = data / "mod"
    mod_dir.mkdir(parents=True)

    presente = mod_dir / "1234"
    presente.mkdir()
    (presente / "descriptor.mod").write_text('name="Presente"', encoding="utf-8")
    write_mod(
        mod_dir,
        "1234",
        f'name="Presente"\npath="{presente.as_posix()}"\nsupported_version="v4.5.*"\n',
    )

    write_mod(
        mod_dir,
        "9999",
        'name="Colgado"\npath="' + (mod_dir / "borrado").as_posix() + '"\n',
    )

    suelto = mod_dir / "a_mano"
    suelto.mkdir()
    (suelto / "descriptor.mod").write_text('name="A mano"\nversion="1.0"', encoding="utf-8")

    mods = {mod.name: mod for mod in scan_mod_dir(mod_dir, data)}
    assert mods["Presente"].on_disk and mods["Presente"].registry_id == "mod/1234.mod"
    assert mods["Colgado"].on_disk is False
    assert mods["A mano"].registry_id is None
    assert mods["A mano"].on_disk is True


def test_ruta_relativa_al_directorio_de_datos(tmp_path):
    data = tmp_path / "CK3"
    mod_dir = data / "mod"
    (mod_dir / "mi_mod").mkdir(parents=True)
    write_mod(mod_dir, "mi_mod", 'name="Relativo"\npath="mod/mi_mod"\n')

    mod = scan_mod_dir(mod_dir, data)[0]
    assert mod.folder == mod_dir / "mi_mod"
    assert mod.on_disk


def test_archivo_comprimido(tmp_path):
    data = tmp_path / "HOI4"
    mod_dir = data / "mod"
    mod_dir.mkdir(parents=True)
    (mod_dir / "paquete.zip").write_bytes(b"PK\x03\x04")
    write_mod(mod_dir, "paquete", 'name="Comprimido"\narchive="mod/paquete.zip"\n')

    mod = scan_mod_dir(mod_dir, data)[0]
    assert mod.is_archived and mod.on_disk


def test_descriptor_roto_no_corta_el_escaneo(tmp_path):
    data = tmp_path / "Stellaris"
    mod_dir = data / "mod"
    mod_dir.mkdir(parents=True)
    write_mod(mod_dir, "roto", 'name="sin cerrar\n')
    (mod_dir / "bueno").mkdir()
    write_mod(mod_dir, "bueno", 'name="Bueno"\npath="mod/bueno"\n')

    mods = {mod.name: mod for mod in scan_mod_dir(mod_dir, data)}
    assert mods["roto"].parse_error is not None
    assert mods["Bueno"].parse_error is None


def test_carpeta_sin_descriptor_no_es_un_mod(tmp_path):
    data = tmp_path / "Stellaris"
    mod_dir = data / "mod"
    (mod_dir / "basura").mkdir(parents=True)
    assert scan_mod_dir(mod_dir, data) == []
