"""Interfaz de linea de comandos de Loadstone.

Existe por dos razones: permite usar el nucleo sin GUI (scripts, servidores de
multijugador, comprobar una instalacion por SSH) y es la forma mas rapida de
verificar contra datos reales lo que luego mostrara la ventana.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .core.analysis import Severity, analyze
from .core.backends import Backend, BackendError, get_backend
from .core.cleanup import execute_cleanup, plan_cleanup
from .core.config import Config
from .core.conflicts import find_conflicts
from .core.dlc import scan_dlc
from .core.games import detect_games
from .core.history import History, diff_snapshots, restore_into
from .core.install import InstallError, install_mod
from .core.launch import GameLaunchError, launch_game, read_launch_target
from .core.logs import get_logger, install_excepthook, setup_logging
from .core.models import GameProfile, LoadOrderMode, Mod, Playset, PlaysetMod
from .core.quarantine import DIAS_EN_CUARENTENA
from .core.quarantine import list_entries as list_quarantine
from .core.quarantine import purge as purge_quarantine
from .core.quarantine import restore as restore_quarantine
from .core.search import SearchOptions, SearchScope, search_mods, select_scope
from .core.sorting import CycleError, minimal_moves, sort_alphabetical, sort_by_dependencies
from .core.steamcmd import SteamCmd, SteamCmdError
from .core.uninstall import execute_uninstall, plan_uninstall
from .core.updates import UpdateState, check_updates
from .core.workshop_api import WorkshopApiError, collection_items, parse_workshop_id

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
_SEVERITY_LABEL = {Severity.ERROR: "ERROR", Severity.WARNING: "AVISO", Severity.INFO: "info"}


def _resolve_games(args: argparse.Namespace) -> dict[str, GameProfile]:
    config = Config.load()
    roots = list(config.extra_roots)
    for root in getattr(args, "root", None) or []:
        roots.append(Path(root))
    return detect_games(roots)


def _pick_game(args: argparse.Namespace) -> GameProfile:
    games = _resolve_games(args)
    game = games.get(args.game)
    if game is None:
        available = ", ".join(sorted(games))
        raise SystemExit(f"juego desconocido '{args.game}'. Opciones: {available}")
    if not game.has_data_dir:
        raise SystemExit(
            f"{game.display_name}: no hay carpeta de datos en "
            f"{game.data_path or 'Documents/Paradox Interactive'}"
        )
    return game


def _pick_playset(playsets: list[Playset], wanted: str | None) -> Playset:
    if not playsets:
        raise SystemExit("este juego no tiene ningun playset todavia")
    if wanted is None:
        for playset in playsets:
            if playset.is_active:
                return playset
        return playsets[0]
    lowered = wanted.strip().lower()
    for playset in playsets:
        if playset.id.lower() == lowered or playset.name.lower() == lowered:
            return playset
    names = ", ".join(f"'{p.name}'" for p in playsets)
    raise SystemExit(f"no encuentro el playset '{wanted}'. Hay: {names}")


def _mod_flags(mod: Mod) -> str:
    return "".join(
        (
            "R" if mod.in_registry else "-",
            "D" if mod.on_disk else "-",
            "Z" if mod.is_archived else "-",
            "!" if mod.parse_error else "-",
        )
    )


# ------------------------------------------------------------------ comandos


def cmd_games(args: argparse.Namespace) -> int:
    games = _resolve_games(args)
    if args.add_root:
        config = Config.load()
        added = config.add_root(Path(args.add_root))
        path = config.save()
        print(("anadida" if added else "ya estaba") + f" {args.add_root} -> {path}\n")
        games = _resolve_games(args)

    print(f"{'clave':11} {'juego':24} {'version':12} {'backend':14} instalacion")
    print("-" * 100)
    for key, game in games.items():
        install = str(game.install_path) if game.install_path else "(no encontrada)"
        data = "" if game.has_data_dir else "  [sin carpeta de datos]"
        print(
            f"{key:11} {game.display_name:24} {game.raw_version or '?':12} "
            f"{game.backend:14} {install}{data}"
        )
    return 0


def cmd_mods(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    mods = backend.read_mods()
    mods.sort(key=lambda mod: (mod.name or "").lower())

    registered = sum(1 for mod in mods if mod.in_registry)
    on_disk = sum(1 for mod in mods if mod.on_disk)
    print(
        f"{game.display_name} {game.raw_version or ''} - {len(mods)} mods "
        f"({registered} en el registro, {on_disk} con contenido en disco)\n"
    )
    print(f"{'flags':6} {'version':12} {'soporta':12} nombre")
    print("-" * 92)
    limit = args.limit if args.limit > 0 else len(mods)
    for mod in mods[:limit]:
        print(
            f"{_mod_flags(mod):6} {(mod.version or '-')[:12]:12} "
            f"{(mod.supported_version or '-')[:12]:12} {mod.name[:46]}"
        )
    if len(mods) > limit:
        print(f"... y {len(mods) - limit} mas (usa --limit 0 para verlos todos)")
    print("\nflags: R=registrado en el launcher  D=contenido en disco  "
          "Z=comprimido  !=descriptor con error")
    return 0


def cmd_playsets(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    playsets = backend.read_playsets()
    if not playsets:
        print(f"{game.display_name}: no hay playsets")
        return 0
    print(f"{game.display_name} - {len(playsets)} playsets\n")
    for playset in playsets:
        active = " (ACTIVO)" if playset.is_active else ""
        enabled = len(playset.enabled_uids())
        print(
            f"- {playset.name}{active}: {len(playset.mods)} mods, {enabled} activados, "
            f"orden {playset.load_order}"
        )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    mods = backend.read_mods()
    playsets = backend.read_playsets()
    playset = None
    if playsets:
        try:
            playset = _pick_playset(playsets, args.playset)
        except SystemExit:
            if args.playset:
                raise
    issues = analyze(game, mods, playset)
    issues.sort(key=lambda issue: _SEVERITY_ORDER[issue.severity])

    scope = f" / playset '{playset.name}'" if playset else ""
    print(f"{game.display_name} {game.raw_version or ''}{scope}: {len(mods)} mods revisados")
    if not issues:
        print("sin problemas detectados")
        return 0

    counts: dict[Severity, int] = {}
    by_kind: dict[str, int] = {}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
        by_kind[issue.kind] = by_kind.get(issue.kind, 0) + 1
    summary = ", ".join(
        f"{counts[s]} {_SEVERITY_LABEL[s].lower()}" for s in _SEVERITY_ORDER if s in counts
    )
    print(summary)
    # El desglose por tipo evita que 200 avisos de version tapen un error unico.
    for kind, total in sorted(by_kind.items(), key=lambda item: -item[1]):
        print(f"  {total:5}  {kind}")
    print()

    limit = args.limit if args.limit > 0 else len(issues)
    for issue in issues[:limit]:
        print(f"{_SEVERITY_LABEL[issue.severity]:6} {issue.kind:20} {issue.message}")
    if len(issues) > limit:
        print(f"... y {len(issues) - limit} mas (usa --limit 0 para verlos todos)")
    return 1 if counts.get(Severity.ERROR) else 0


def cmd_sort(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    mods = {mod.uid: mod for mod in backend.read_mods()}
    playset = _pick_playset(backend.read_playsets(), args.playset)

    before = [entry.uid for entry in sorted(playset.mods, key=lambda m: m.position)]
    if args.mode == "alpha":
        sort_alphabetical(playset, mods)
        playset.load_order = LoadOrderMode.ALPHABETICAL
        after = [entry.uid for entry in sorted(playset.mods, key=lambda m: m.position)]
        moved = [
            (mods[uid].name if uid in mods else uid) for uid in minimal_moves(before, after)
        ]
    else:
        try:
            moved = sort_by_dependencies(playset, mods)
        except CycleError as exc:
            print(f"no se puede ordenar: {exc}", file=sys.stderr)
            return 2
        playset.load_order = LoadOrderMode.CUSTOM

    print(f"playset '{playset.name}': {len(playset.mods)} mods, {len(moved)} cambian de posicion")
    for name in moved[:15]:
        print(f"  movido: {name}")
    if len(moved) > 15:
        print(f"  ... y {len(moved) - 15} mas")

    if not args.write:
        print("\n(simulacion: nada escrito. Anade --write para guardar)")
        return 0

    backend.save_playset(playset)
    print("\nguardado en el registro del launcher")
    if args.apply:
        written = backend.apply_to_game(playset)
        print(f"aplicado al juego: {written}")
    return 0


def _snapshot(game: GameProfile, backend: Backend, playset: Playset, note: str = "") -> None:
    """Guarda el estado antes de que el juego lo use, para poder volver."""
    try:
        mods = {mod.uid: mod for mod in backend.read_mods()}
        snapshot = History(game.key).save(playset, mods, note=note)
    except (BackendError, OSError) as error:
        # Fallar al guardar el historial no debe impedir jugar.
        print(f"aviso: no se pudo guardar la instantanea ({error})", file=sys.stderr)
        return
    print(f"instantanea guardada: {snapshot.id}")


def cmd_apply(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    playset = _pick_playset(backend.read_playsets(), args.playset)
    if args.activate:
        backend.activate(playset.id)
        print(f"playset '{playset.name}' marcado como activo")
    written = backend.apply_to_game(playset)
    enabled = len(playset.enabled_uids())
    print(f"escritos {enabled} mods en orden de carga -> {written}")
    _snapshot(game, backend, playset, note=getattr(args, "note", "") or "")
    return 0


def _add_to_playset(backend: Backend, playset_name: str | None, uid: str, name: str) -> None:
    """Mete un mod recien instalado al final de un playset y lo guarda."""
    playset = _pick_playset(backend.read_playsets(), playset_name)
    if any(entry.uid == uid for entry in playset.mods):
        print(f"  '{name}' ya estaba en el playset '{playset.name}'")
        return
    position = max((entry.position for entry in playset.mods), default=-1) + 1
    playset.mods.append(PlaysetMod(uid=uid, enabled=True, position=position))
    backend.save_playset(playset)
    print(f"  anadido al playset '{playset.name}' en la posicion {position + 1}")


def _install_and_register(
    args: argparse.Namespace,
    game: GameProfile,
    backend: Backend,
    source: Path,
    *,
    mod_id: str | None,
    remote_file_id: str | None,
) -> bool:
    try:
        mod = install_mod(
            game,
            source,
            mod_id=mod_id,
            remote_file_id=remote_file_id,
            overwrite=args.force,
        )
    except InstallError as error:
        print(f"  no instalado: {error}", file=sys.stderr)
        return False

    print(f"  instalado: {mod.name} -> {mod.registry_id}")
    try:
        uid = backend.register_mod(mod)
    except BackendError as error:
        print(f"  instalado pero no registrado en el launcher: {error}", file=sys.stderr)
        return False
    if args.playset:
        _add_to_playset(backend, args.playset, uid, mod.name)
    return True


def cmd_workshop(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    if game.steam_appid is None:
        raise SystemExit(
            f"{game.display_name}: no se conoce su appid de Steam, "
            "no se puede descargar del Workshop"
        )
    backend = get_backend(game)

    ids = list(args.ids)
    if args.collection:
        collection_id = parse_workshop_id(args.collection)
        if collection_id is None:
            raise SystemExit(f"no reconozco una coleccion en '{args.collection}'")
        try:
            del_coleccion = collection_items(collection_id)
        except WorkshopApiError as error:
            raise SystemExit(str(error)) from error
        print(f"la coleccion {collection_id} tiene {len(del_coleccion)} mods")
        if args.missing_only:
            instalados = {mod.steam_id for mod in backend.read_mods() if mod.steam_id}
            antes = len(del_coleccion)
            del_coleccion = [i for i in del_coleccion if i not in instalados]
            print(f"  {antes - len(del_coleccion)} ya instalados, quedan {len(del_coleccion)}")
        ids.extend(i for i in del_coleccion if i not in ids)

    if not ids:
        raise SystemExit("no hay nada que descargar")
    args.ids = ids

    steamcmd = SteamCmd.find(Path(args.steamcmd) if args.steamcmd else None)
    if steamcmd is None:
        print("SteamCMD no encontrado, descargando el oficial de Valve...")
        try:
            steamcmd = SteamCmd.bootstrap()
        except SteamCmdError as error:
            raise SystemExit(str(error)) from error
        print(f"SteamCMD listo en {steamcmd.executable}")

    print(f"Descargando {len(args.ids)} item(s) del Workshop de {game.display_name}...")
    try:
        results = steamcmd.download(
            game.steam_appid, args.ids, timeout=args.timeout, login=args.login
        )
    except SteamCmdError as error:
        raise SystemExit(str(error)) from error

    installed = 0
    for result in results:
        if not result.ok or result.path is None:
            print(f"- {result.item_id}: fallo ({result.error})", file=sys.stderr)
            continue
        print(f"- {result.item_id}: descargado ({result.size} bytes)")
        if args.download_only:
            print(f"  en {result.path}")
            installed += 1
            continue
        if _install_and_register(
            args, game, backend, result.path,
            mod_id=result.item_id, remote_file_id=result.item_id,
        ):
            installed += 1

    failed = len(results) - installed
    print(f"\n{installed} de {len(results)} completados")
    if failed and args.login == "anonymous":
        # Comprobado el 2026-10-12: solo Stellaris permite descarga anonima de
        # entre los juegos soportados. En los demas hay que usar una cuenta que
        # posea el juego, asi que conviene decirlo en vez de dejar un 'Failure'.
        print(
            "\nAviso: de los juegos soportados, solo Stellaris permite la descarga\n"
            "anonima del Workshop. Para los demas necesitas una cuenta de Steam que\n"
            "posea el juego:  loadstone workshop --game ck3 --login TU_USUARIO <id>",
            file=sys.stderr,
        )
    return 1 if failed else 0


def cmd_search(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    mods = backend.read_mods()
    playsets = backend.read_playsets()

    scope = SearchScope(args.scope)
    if scope is not SearchScope.ALL and playsets:
        playset = _pick_playset(playsets, args.playset)
        mods = select_scope(mods, set(playset.enabled_uids()), scope)

    options = SearchOptions(
        query=args.query,
        regex=args.regex,
        case_sensitive=args.case_sensitive,
        in_paths=args.paths,
        skip_translations=not args.include_translations,
        max_hits=args.limit if args.limit > 0 else 10**9,
    )
    if args.extensions:
        options.extensions = tuple(
            ext if ext.startswith(".") else f".{ext}" for ext in args.extensions
        )

    donde = "rutas de archivo" if args.paths else "contenido"
    print(f"Buscando en {donde} de {len(mods)} mods ({scope})...\n")
    try:
        hits = search_mods(mods, options)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    por_mod: dict[str, list] = {}
    for hit in hits:
        por_mod.setdefault(hit.mod.name, []).append(hit)

    for nombre, encontrados in por_mod.items():
        print(f"{nombre}  ({len(encontrados)})")
        for hit in encontrados[:5]:
            sitio = hit.path.as_posix()
            if hit.line_number:
                print(f"    {sitio}:{hit.line_number}  {hit.line[:90]}")
            else:
                print(f"    {sitio}")
        if len(encontrados) > 5:
            print(f"    ... y {len(encontrados) - 5} mas en este mod")

    print(f"\n{len(hits)} coincidencias en {len(por_mod)} mods")
    if len(hits) >= options.max_hits:
        print("(limite alcanzado; afina la busqueda o sube --limit)")
    return 0 if hits else 1


def cmd_outdated(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    mods = backend.read_mods()
    con_id = sum(1 for mod in mods if mod.steam_id)
    print(f"Consultando el Workshop por {con_id} de {len(mods)} mods...")

    try:
        estados = check_updates(mods, timeout=args.timeout)
    except WorkshopApiError as error:
        raise SystemExit(str(error)) from error

    por_estado: dict[UpdateState, list] = {}
    for estado in estados:
        por_estado.setdefault(estado.state, []).append(estado)

    for clave in (UpdateState.OUTDATED, UpdateState.REMOVED, UpdateState.UP_TO_DATE,
                  UpdateState.UNKNOWN):
        print(f"  {len(por_estado.get(clave, [])):4}  {clave}")

    desactualizados = por_estado.get(UpdateState.OUTDATED, [])
    retirados = por_estado.get(UpdateState.REMOVED, [])

    if retirados:
        print("\nYa no estan en el Workshop (no recibiran arreglos):")
        for estado in retirados:
            print(f"  {estado.mod.name[:55]:57} id {estado.mod.steam_id}")

    if desactualizados:
        print("\nCon version nueva:")
        limite = args.limit if args.limit > 0 else len(desactualizados)
        for estado in desactualizados[:limite]:
            print(f"  {estado.mod.name[:45]:47} {estado.reason}")
            titulo = estado.remote_title
            if titulo and titulo != estado.mod.name:
                print(f"  {'':47} ahora se llama: {titulo[:60]}")
        if len(desactualizados) > limite:
            print(f"  ... y {len(desactualizados) - limite} mas")

        ids = [e.mod.steam_id for e in desactualizados if e.mod.steam_id]
        if ids:
            print(
                f"\nPara actualizarlos:\n"
                f"  loadstone workshop --game {game.key} --force {' '.join(ids[:6])}"
                + (" ..." if len(ids) > 6 else "")
            )
    return 1 if desactualizados or retirados else 0


def cmd_history(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    historial = History(game.key)
    snapshots = historial.list()
    if not snapshots:
        print(f"{game.display_name}: aun no hay instantaneas. Se crean al aplicar un playset.")
        return 0

    if args.restore:
        return _restore_snapshot(args, game, historial)

    if args.note is not None:
        objetivo = args.snapshot or snapshots[0].id
        if historial.set_note(objetivo, args.note):
            print(f"nota guardada en {objetivo}")
            return 0
        raise SystemExit(f"no existe la instantanea '{objetivo}'")

    print(f"{game.display_name}: {len(snapshots)} instantaneas\n")
    for indice, snapshot in enumerate(snapshots):
        fecha = time.strftime("%Y-%m-%d %H:%M", time.localtime(snapshot.created))
        activos = len(snapshot.enabled_ids)
        linea = f"{snapshot.id}  {fecha}  '{snapshot.playset}'  {activos} mods activos"
        if snapshot.note:
            linea += f'  — "{snapshot.note}"'
        print(linea)
        # Comparar con la siguiente, que es la inmediatamente anterior.
        if indice + 1 < len(snapshots):
            cambios = diff_snapshots(snapshots[indice + 1], snapshot)
            print(f"      respecto a la anterior: {cambios.summary()}")
            for etiqueta, valores in (("+", cambios.added), ("-", cambios.removed),
                                      ("~", cambios.moved)):
                for nombre in valores[:4]:
                    print(f"        {etiqueta} {nombre}")
                if len(valores) > 4:
                    print(f"        {etiqueta} ... y {len(valores) - 4} mas")
    return 0


def _restore_snapshot(
    args: argparse.Namespace, game: GameProfile, historial: History
) -> int:
    snapshot = historial.get(args.restore)
    if snapshot is None:
        raise SystemExit(f"no existe la instantanea '{args.restore}'")

    backend = get_backend(game)
    mods = backend.read_mods()
    playset = _pick_playset(backend.read_playsets(), args.playset)
    colocados, faltantes = restore_into(snapshot, playset, mods)

    print(f"instantanea {snapshot.id} ('{snapshot.playset}'): {colocados} mods colocados")
    for nombre in faltantes[:10]:
        print(f"  no instalado, se omite: {nombre}")
    if len(faltantes) > 10:
        print(f"  ... y {len(faltantes) - 10} mas sin instalar")

    if not args.write:
        print("\n(simulacion: nada escrito. Anade --write para aplicarlo)")
        return 0
    backend.save_playset(playset)
    written = backend.apply_to_game(playset)
    print(f"restaurado y aplicado -> {written}")
    _snapshot(game, backend, playset, note=f"restaurada {snapshot.id}")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Quita mods del disco, del registro y de todos los playsets.

    Es lo contrario de `clean`: aquel borra basura y por eso se niega a tocar
    nada que algun playset mencione; este borra mods sanos que ya no se
    quieren, y por eso tiene que sacarlos de los playsets el primero.

    Sin `--write` solo cuenta lo que haria. Un borrado irreversible no debe
    ocurrir por escribir mal el nombre de un mod.
    """
    game = _pick_game(args)
    backend = get_backend(game)
    mods = backend.read_mods()
    playsets = backend.read_playsets()

    elegidos: list[Mod] = []
    for texto in args.mods:
        clave = texto.lower()
        # Un uid o un id del Workshop exacto manda sobre cualquier parecido de
        # nombre. Si no, el consejo de "usa el id para desambiguar" no serviria
        # de nada: un uid corto como 'a' aparece dentro de medio catalogo.
        exactos = [m for m in mods if m.uid == texto or (m.steam_id or "") == texto]
        coincidencias = exactos or [m for m in mods if clave in m.name.lower()]
        if not coincidencias:
            raise SystemExit(f"no encuentro ningun mod que case con '{texto}'")
        if len(coincidencias) > 1 and not args.all_matches:
            nombres = ", ".join(m.name for m in coincidencias[:5])
            raise SystemExit(
                f"'{texto}' casa con {len(coincidencias)} mods ({nombres}...). "
                "Afina el texto, usa el id, o pasa --all-matches para todos."
            )
        elegidos.extend(coincidencias)

    unicos = list({m.uid: m for m in elegidos}.values())
    planes = [plan_uninstall(m, playsets, mod_dir=game.mod_dir) for m in unicos]

    total = sum(plan.size for plan in planes)
    print(f"{game.display_name}: {len(planes)} mod(s) a desinstalar")
    for plan in planes:
        en_playsets = f", en {len(plan.playsets)} playset(s)" if plan.playsets else ""
        fuera = " [contenido de Steam, no se borra]" if plan.is_steam_managed else ""
        megas = plan.size / 1024 / 1024
        print(f"  {plan.mod.name[:48]:50} {megas:6.1f} MB{en_playsets}{fuera}")
    if total:
        print(f"liberaria {total / 1024 / 1024:.1f} MB")

    if not args.write:
        print("(simulacion: nada borrado. Anade --write para hacerlo)")
        return 0

    hechos, errores = execute_uninstall(
        planes,
        save_playset=backend.save_playset,
        unregister=backend.unregister_mod,
        include_outside=args.include_steam,
    )
    print(f"{hechos} mod(s) desinstalados")
    for error in errores[:10]:
        print(f"  {error}", file=sys.stderr)
    return 0 if not errores else 1


def cmd_quarantine(args: argparse.Namespace) -> int:
    """Lista, devuelve o vacia lo que `uninstall` aparto.

    No pide `--game`: la papelera es una sola para toda la maquina, porque lo
    apartado ya guarda su ruta original y esa dice a que juego vuelve.
    """
    entradas = list_quarantine()

    if args.empty:
        caidas = purge_quarantine(dias=0)
        print(f"{caidas} entrada(s) borradas definitivamente")
        return 0

    if args.restore:
        por_nombre = {e.nombre.lower(): e for e in entradas}
        elegidas = []
        for texto in args.restore:
            entrada = por_nombre.get(texto.lower()) or next(
                (e for e in entradas if texto.lower() in e.nombre.lower()), None
            )
            if entrada is None:
                raise SystemExit(f"no hay nada apartado que case con '{texto}'")
            elegidas.append(entrada)

        errores: list[str] = []
        for entrada in elegidas:
            errores.extend(restore_quarantine(entrada))
        if errores:
            for error in errores[:10]:
                print(f"  {error}", file=sys.stderr)
            return 1
        print(f"{len(elegidas)} mod(s) devueltos a su sitio")
        print("Tendras que volver a anadirlos al playset.")
        return 0

    if not entradas:
        print("la papelera esta vacia")
        return 0

    total = sum(e.size for e in entradas)
    print(f"{len(entradas)} mod(s) apartados, {total / 1024 / 1024:.1f} MB en total")
    print(f"se purgan solos a los {DIAS_EN_CUARENTENA} dias")
    print()
    print(f"{'hace':>8}  {'tamano':>9}  mod")
    print("-" * 70)
    for entrada in entradas:
        dias = "hoy" if entrada.dias == 0 else f"{entrada.dias}d"
        print(f"{dias:>8}  {entrada.size / 1024 / 1024:7.1f} MB  {entrada.nombre}")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    mods = backend.read_mods()
    plan = plan_cleanup(
        mods,
        backend.read_playsets(),
        include_unlinked=args.unlinked,
        mod_dir=game.mod_dir if args.orphans else None,
    )

    if not plan:
        print(f"{game.display_name}: nada que limpiar")
        return 0

    por_tipo: dict[str, list] = {}
    for item in plan:
        por_tipo.setdefault(item.kind, []).append(item)

    total = sum(item.size for item in plan)
    print(f"{game.display_name}: {len(plan)} elementos para limpiar")
    if total:
        print(f"liberaria {total / 1024 / 1024:.1f} MB")
    for tipo, items in por_tipo.items():
        print(f"\n{tipo}  ({len(items)})")
        for item in items[:12]:
            detalle = f" [{item.size / 1024 / 1024:.1f} MB]" if item.size else ""
            print(f"  {item.mod.name[:50]:52}{detalle}")
        if len(items) > 12:
            print(f"  ... y {len(items) - 12} mas")

    if not args.write:
        print("\n(simulacion: nada borrado. Anade --write para hacerlo)")
        if not args.unlinked:
            print("Usa --unlinked para incluir las carpetas con mod que el juego no ve.")
        if not args.orphans:
            print("Usa --orphans para buscar restos de contenido sin descriptor.")
        return 0

    borrados, errores = execute_cleanup(plan, unregister=backend.unregister_mod)
    print(f"\n{borrados} elementos borrados")
    for error in errores[:10]:
        print(f"  {error}", file=sys.stderr)
    return 1 if errores else 0


def cmd_import(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    source = Path(args.source)
    print(f"Importando {source.name} en {game.display_name}...")
    ok = _install_and_register(
        args, game, backend, source, mod_id=args.id, remote_file_id=None
    )
    return 0 if ok else 1


def cmd_conflicts(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    backend = get_backend(game)
    mods = {mod.uid: mod for mod in backend.read_mods()}
    playset = _pick_playset(backend.read_playsets(), args.playset)
    orden = [mods[uid] for uid in playset.enabled_uids() if uid in mods]

    print(f"Comparando {len(orden)} mods activos de '{playset.name}'...")
    informe = find_conflicts(orden)
    parejas = informe.by_pair()
    print(
        f"{len(informe.conflicts)} archivos en conflicto entre {informe.scanned} mods, "
        f"en {len(parejas)} parejas\n"
    )
    if not informe.conflicts:
        return 0

    limite = args.limit if args.limit > 0 else len(informe.conflicts)
    if args.files:
        for conflicto in informe.conflicts[:limite]:
            marca = " (reemplaza la carpeta)" if conflicto.replaced else ""
            print(f"  {conflicto.path[:62]:64} gana: {conflicto.winner.name[:30]}{marca}")
        restantes = len(informe.conflicts) - limite
    else:
        for (perdedor, ganador), cuantos in list(parejas.items())[:limite]:
            print(f"  {cuantos:5} archivos: '{ganador[:34]}' pisa a '{perdedor[:34]}'")
        restantes = len(parejas) - limite
    if restantes > 0:
        print(f"  ... y {restantes} mas")
    print("\nGana el que carga el ultimo. Esto compara rutas, no contenido.")
    return 0


def cmd_dlc(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    dlcs = scan_dlc(game.install_path)
    if not dlcs:
        raise SystemExit(
            f"{game.display_name}: no se encuentran los DLC. "
            "Hace falta localizar la instalacion del juego."
        )

    backend = get_backend(game)
    playset = _pick_playset(backend.read_playsets(), args.playset)
    estado = {dlc.id: playset.dlcs.get(dlc.id, True) for dlc in dlcs}

    if args.enable or args.disable:
        objetivo = {d.lower() for d in (args.enable or []) + (args.disable or [])}
        conocidos = {dlc.id.lower(): dlc.id for dlc in dlcs}
        desconocidos = objetivo - set(conocidos)
        if desconocidos:
            raise SystemExit(f"DLC desconocidos: {', '.join(sorted(desconocidos))}")
        for clave in args.enable or []:
            backend.set_dlc_enabled(playset, conocidos[clave.lower()], True)
        for clave in args.disable or []:
            backend.set_dlc_enabled(playset, conocidos[clave.lower()], False)
        print(
            f"actualizado el playset '{playset.name}'. "
            "Se aplicara al juego en el proximo 'apply'."
        )
        return 0

    activos = sum(1 for valor in estado.values() if valor)
    print(f"{game.display_name}: {len(dlcs)} DLC, {activos} activos en '{playset.name}'\n")
    for dlc in dlcs:
        marca = "x" if estado[dlc.id] else " "
        print(f"  [{marca}] {dlc.id[:34]:36} {dlc.name[:38]}")
    print("\nPara cambiarlos:  loadstone dlc --game "
          f"{game.key} --disable <id> --enable <id>")
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    game = _pick_game(args)
    objetivo = read_launch_target(game)
    if objetivo is None:
        raise SystemExit(
            f"{game.display_name}: no se encuentra el ejecutable en "
            f"{game.install_path or 'una instalacion sin detectar'}"
        )

    if args.apply:
        backend = get_backend(game)
        playset = _pick_playset(backend.read_playsets(), args.playset)
        escrito = backend.apply_to_game(playset)
        print(f"aplicado '{playset.name}' -> {escrito}")
        _snapshot(game, backend, playset, note="antes de jugar")

    try:
        launch_game(game)
    except GameLaunchError as error:
        raise SystemExit(str(error)) from error
    print(f"arrancando {objetivo.executable}")
    return 0


# -------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    # `--root` se declara en un parser padre para que valga tanto antes como
    # despues del subcomando; obligar a una sola posicion solo genera errores.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="registra todo el detalle en el archivo de registro",
    )
    common.add_argument(
        "--root",
        action="append",
        metavar="CARPETA",
        # Sin SUPPRESS, el default del subcomando pisaria el valor que ya haya
        # puesto el parser principal cuando `--root` va antes del subcomando.
        default=argparse.SUPPRESS,
        help="carpeta extra donde buscar instalaciones (repetible)",
    )

    parser = argparse.ArgumentParser(
        prog="loadstone",
        description="Gestor de mods y orden de carga para juegos de Paradox.",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    games = subparsers.add_parser("games", parents=[common], help="lista los juegos detectados")
    games.add_argument("--add-root", metavar="CARPETA", help="recuerda esta carpeta de busqueda")
    games.set_defaults(func=cmd_games)

    def with_game(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = subparsers.add_parser(name, parents=[common], help=help_text)
        sub.add_argument("--game", required=True, help="clave del juego, p.ej. stellaris")
        return sub

    mods = with_game("mods", "lista los mods de un juego")
    mods.add_argument("--limit", type=int, default=40, help="0 para no limitar")
    mods.set_defaults(func=cmd_mods)

    playsets = with_game("playsets", "lista los playsets de un juego")
    playsets.set_defaults(func=cmd_playsets)

    check = with_game("check", "busca problemas en los mods y el playset")
    check.add_argument("--playset", help="nombre o id; por defecto el activo")
    check.add_argument("--limit", type=int, default=30, help="0 para no limitar")
    check.set_defaults(func=cmd_check)

    sort_cmd = with_game("sort", "reordena un playset")
    sort_cmd.add_argument("--playset", help="nombre o id; por defecto el activo")
    sort_cmd.add_argument(
        "--mode",
        choices=("deps", "alpha"),
        default="deps",
        help="deps: respeta dependencias conservando el orden actual; alpha: alfabetico",
    )
    sort_cmd.add_argument("--write", action="store_true", help="guarda el resultado")
    sort_cmd.add_argument("--apply", action="store_true", help="y lo escribe para el juego")
    sort_cmd.set_defaults(func=cmd_sort)

    apply_cmd = with_game("apply", "escribe el playset en lo que el juego lee al arrancar")
    apply_cmd.add_argument("--playset", help="nombre o id; por defecto el activo")
    apply_cmd.add_argument(
        "--activate", action="store_true", help="marcalo tambien como activo"
    )
    apply_cmd.add_argument("--note", help="nota para la instantanea del historial")
    apply_cmd.set_defaults(func=cmd_apply)

    workshop = with_game("workshop", "descarga mods del Workshop de Steam con SteamCMD")
    workshop.add_argument(
        "ids", nargs="*", metavar="ID", help="ids de items del Workshop"
    )
    workshop.add_argument(
        "--collection", metavar="URL_O_ID", help="anadir los mods de una coleccion"
    )
    workshop.add_argument(
        "--missing-only",
        action="store_true",
        help="de la coleccion, solo los que no tengas ya",
    )
    workshop.add_argument("--playset", help="anadirlos a este playset al terminar")
    workshop.add_argument(
        "--download-only", action="store_true", help="no instalar ni registrar"
    )
    workshop.add_argument("--force", action="store_true", help="sobrescribir si ya existe")
    workshop.add_argument("--steamcmd", metavar="RUTA", help="ejecutable de SteamCMD a usar")
    workshop.add_argument(
        "--login",
        default="anonymous",
        metavar="USUARIO",
        help="cuenta de Steam; necesaria salvo en Stellaris (pide la clave SteamCMD)",
    )
    workshop.add_argument(
        "--timeout", type=int, default=3600, help="segundos maximos de descarga"
    )
    workshop.set_defaults(func=cmd_workshop)

    import_cmd = with_game("import", "instala un mod desde una carpeta o un .zip")
    import_cmd.add_argument("source", metavar="ORIGEN", help="carpeta o archivo .zip")
    import_cmd.add_argument("--id", help="nombre de la carpeta y del .mod a crear")
    import_cmd.add_argument("--playset", help="anadirlo a este playset al terminar")
    import_cmd.add_argument("--force", action="store_true", help="sobrescribir si ya existe")
    import_cmd.set_defaults(func=cmd_import)

    search = with_game("search", "busca texto dentro de los archivos de los mods")
    search.add_argument("query", metavar="TEXTO", help="lo que se busca")
    search.add_argument(
        "--scope",
        choices=[s.value for s in SearchScope],
        default=SearchScope.ALL.value,
        help="en que mods buscar",
    )
    search.add_argument("--playset", help="playset que define cuales estan activos")
    search.add_argument("--regex", action="store_true", help="tratar el texto como patron")
    search.add_argument(
        "--case-sensitive", action="store_true", help="distinguir mayusculas"
    )
    search.add_argument(
        "--paths", action="store_true", help="buscar en las rutas, no en el contenido"
    )
    search.add_argument(
        "--extensions", nargs="+", metavar="EXT", help="limitar a estas extensiones"
    )
    search.add_argument(
        "--include-translations",
        action="store_true",
        help="no saltarse las carpetas de localizacion",
    )
    search.add_argument("--limit", type=int, default=500, help="maximo de coincidencias")
    search.set_defaults(func=cmd_search)

    outdated = with_game("outdated", "compara tus mods con el Workshop de Steam")
    outdated.add_argument("--limit", type=int, default=25, help="0 para no limitar")
    outdated.add_argument("--timeout", type=int, default=30, help="segundos de espera")
    outdated.set_defaults(func=cmd_outdated)

    history = with_game("history", "instantaneas de la lista de mods")
    history.add_argument("--restore", metavar="ID", help="restaurar esta instantanea")
    history.add_argument("--playset", help="playset sobre el que restaurar")
    history.add_argument("--write", action="store_true", help="aplicar la restauracion")
    history.add_argument("--note", help="anotar la instantanea indicada o la ultima")
    history.add_argument("--snapshot", metavar="ID", help="a cual poner la nota")
    history.set_defaults(func=cmd_history)

    uninstall = with_game(
        "uninstall", "borra mods del disco, del registro y de las listas"
    )
    uninstall.add_argument(
        "mods", nargs="+", metavar="MOD", help="uid, id del Workshop o parte del nombre"
    )
    uninstall.add_argument(
        "--all-matches",
        action="store_true",
        help="si un texto casa con varios mods, desinstalarlos todos",
    )
    uninstall.add_argument(
        "--include-steam",
        action="store_true",
        help="borrar tambien el contenido que vive fuera de la carpeta del juego",
    )
    uninstall.add_argument("--write", action="store_true", help="borrar de verdad")
    uninstall.set_defaults(func=cmd_uninstall)

    cuarentena = subparsers.add_parser(
        "quarantine",
        parents=[common],
        help="lo que `uninstall` aparto, y como devolverlo",
    )
    cuarentena.add_argument(
        "--restore",
        nargs="+",
        metavar="MOD",
        help="devuelve a su sitio los mods cuyo nombre case",
    )
    cuarentena.add_argument(
        "--empty", action="store_true", help="borra definitivamente todo lo apartado"
    )
    cuarentena.set_defaults(func=cmd_quarantine)

    clean = with_game("clean", "limpia descriptores colgados y restos en mod/")
    clean.add_argument(
        "--unlinked",
        action="store_true",
        help="incluir carpetas sin .mod, que el juego no ve",
    )
    clean.add_argument(
        "--orphans",
        action="store_true",
        help="incluir carpetas de contenido sin descriptor (restos de borrados)",
    )
    clean.add_argument("--write", action="store_true", help="borrar de verdad")
    clean.set_defaults(func=cmd_clean)

    conflicts = with_game("conflicts", "archivos que varios mods del playset definen")
    conflicts.add_argument("--playset", help="nombre o id; por defecto el activo")
    conflicts.add_argument(
        "--files", action="store_true", help="listar por archivo en vez de por parejas"
    )
    conflicts.add_argument("--limit", type=int, default=20, help="0 para no limitar")
    conflicts.set_defaults(func=cmd_conflicts)

    dlc = with_game("dlc", "lista y cambia los DLC de un playset")
    dlc.add_argument("--playset", help="nombre o id; por defecto el activo")
    dlc.add_argument("--enable", nargs="+", metavar="ID", help="activar estos DLC")
    dlc.add_argument("--disable", nargs="+", metavar="ID", help="desactivar estos DLC")
    dlc.set_defaults(func=cmd_dlc)

    play = with_game("play", "arranca el juego")
    play.add_argument("--playset", help="playset a aplicar antes de jugar")
    play.add_argument(
        "--apply", action="store_true", help="aplicar el playset antes de arrancar"
    )
    play.set_defaults(func=cmd_play)

    return parser


def main(argv: list[str] | None = None) -> int:
    # La consola de Windows usa la pagina de codigos del sistema, y los mods y
    # playsets vienen con tildes, cirilico y CJK. Sin esto, imprimirlos falla.
    for stream in (sys.stdout, sys.stderr):
        if (stream.encoding or "").lower().replace("-", "") != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass

    args = build_parser().parse_args(argv)
    archivo = setup_logging(debug=getattr(args, "debug", False))
    install_excepthook()
    logger = get_logger("cli")
    logger.info("comando: %s", args.command)

    try:
        codigo = args.func(args)
    except BackendError as exc:
        logger.error("%s: %s", args.command, exc)
        print(f"error: {exc}", file=sys.stderr)
        if archivo:
            print(f"(detalle en {archivo})", file=sys.stderr)
        return 2
    logger.info("comando %s terminado con codigo %s", args.command, codigo)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
