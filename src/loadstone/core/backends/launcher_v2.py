"""Backend del launcher v2: `launcher-v2.sqlite` + `dlc_load.json`.

Cubre Stellaris, CK3, Victoria 3, HOI4 y EU4. Conviene tener claro el reparto
de papeles, porque es lo que hace que un gestor externo pueda funcionar:

- `launcher-v2.sqlite` es el estado del launcher: mods registrados, playsets y
  el orden (`playsets_mods.position`).
- `dlc_load.json` es lo unico que el ejecutable del juego lee al arrancar: una
  lista plana de descriptores en orden de carga.

Escribir solo la base no cambia nada en la partida; escribir solo el JSON hace
que el launcher muestre algo distinto de lo que se va a jugar. Loadstone escribe
los dos, y siempre con copia previa.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from ..atomic import atomic_write_json
from ..descriptor import scan_mod_dir, steam_id_from_filename
from ..dlc import scan_dlc
from ..logs import get_logger
from ..models import BackendKind, GameProfile, LoadOrderMode, Mod, ModSource, Playset, PlaysetMod
from .base import Backend, BackendError, backup_file

__all__ = ["LauncherV2Backend"]

_logger = get_logger("launcher_v2")

_SOURCE_MAP = {
    "local": ModSource.LOCAL,
    "steam": ModSource.STEAM,
    "pdx": ModSource.PARADOX,
    "paradox": ModSource.PARADOX,
}


def _normalize_registry_id(raw: str | None) -> str | None:
    """Clave de cruce entre la base y el disco.

    `gameRegistryId` y el nombre del `.mod` describen lo mismo pero no siempre
    con la misma forma: barras de Windows en una, normales en la otra, y
    mayusculas inconsistentes en los mods hechos a mano.
    """
    if not raw:
        return None
    return raw.replace("\\", "/").strip().lower()


class LauncherV2Backend(Backend):
    kind = BackendKind.LAUNCHER_V2

    def __init__(self, game: GameProfile) -> None:
        super().__init__(game)
        assert game.data_path is not None  # garantizado por Backend
        self.db_path = game.data_path / "launcher-v2.sqlite"
        self.dlc_load_path = game.data_path / "dlc_load.json"

    # ---------------------------------------------------------------- lectura

    def _connect_ro(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise BackendError(
                f"{self.game.display_name}: falta {self.db_path.name}. "
                "Abre el launcher una vez para que lo cree."
            )
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5)
        except sqlite3.Error as exc:
            raise BackendError(f"no se puede leer {self.db_path.name}: {exc}") from exc
        connection.row_factory = sqlite3.Row
        return connection

    def _connect_rw(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self.db_path, timeout=5)
        except sqlite3.Error as exc:
            raise BackendError(f"no se puede abrir {self.db_path.name}: {exc}") from exc
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def read_mods(self) -> list[Mod]:
        """Mods del registro cruzados con lo que hay realmente en `mod/`.

        El resultado incluye las tres situaciones utiles: registrados y
        presentes, registrados pero sin contenido, y presentes sin registrar.
        """
        mod_dir = self.game.mod_dir
        on_disk = scan_mod_dir(mod_dir, self.game.data_path) if mod_dir else []
        by_registry = {
            key: mod
            for mod in on_disk
            if (key := _normalize_registry_id(mod.registry_id)) is not None
        }

        merged: list[Mod] = []
        matched: set[str] = set()
        with self._connect_ro() as connection:
            dependencies = self._read_dependencies(connection)
            for row in connection.execute(
                """
                SELECT id, pdxId, steamId, remoteSteamId, gameRegistryId, name,
                       displayName, version, requiredVersion, tags, dirPath,
                       archivePath, status, source, size
                  FROM mods
                """
            ):
                key = _normalize_registry_id(row["gameRegistryId"])
                disk = by_registry.get(key) if key else None
                if key and disk is not None:
                    matched.add(key)
                merged.append(self._mod_from_row(row, disk, dependencies))

        merged.extend(
            mod
            for mod in on_disk
            if _normalize_registry_id(mod.registry_id) not in matched
        )
        return merged

    def _read_dependencies(self, connection: sqlite3.Connection) -> dict[str, list[str]]:
        """Dependencias declaradas, por id de mod.

        La base las guarda en dos sitios segun de donde venga el metadato:
        `mods_dependencies` para lo que trae el descriptor y
        `metadata_relationships` para lo que viene de Paradox Mods.
        """
        result: dict[str, list[str]] = {}
        for table, id_column, name_column in (
            ("mods_dependencies", "modId", "dependencyName"),
            ("metadata_relationships", "modMetadataId", "displayName"),
        ):
            try:
                rows = connection.execute(
                    f"SELECT {id_column} AS mod_id, {name_column} AS dep FROM {table}"
                ).fetchall()
            except sqlite3.Error:
                # Una base de una version anterior puede no tener la tabla.
                continue
            for row in rows:
                if row["dep"]:
                    result.setdefault(row["mod_id"], []).append(row["dep"])
        return result

    def _mod_from_row(
        self,
        row: sqlite3.Row,
        disk: Mod | None,
        dependencies: dict[str, list[str]],
    ) -> Mod:
        tags: list[str] = []
        if row["tags"]:
            try:
                parsed = json.loads(row["tags"])
                tags = [str(tag) for tag in parsed] if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                tags = []

        folder = Path(row["dirPath"]) if row["dirPath"] else None
        archive = Path(row["archivePath"]) if row["archivePath"] else None
        declared = dependencies.get(row["id"], [])

        return Mod(
            uid=row["id"],
            name=row["displayName"] or row["name"] or (disk.name if disk else row["id"]),
            registry_id=row["gameRegistryId"] or (disk.registry_id if disk else None),
            descriptor_path=disk.descriptor_path if disk else None,
            folder=folder if folder and folder.is_dir() else (disk.folder if disk else None),
            archive=archive if archive and archive.is_file() else (disk.archive if disk else None),
            version=row["version"] or (disk.version if disk else None),
            supported_version=row["requiredVersion"] or (disk.supported_version if disk else None),
            tags=tags or (disk.tags if disk else []),
            dependencies=declared or (disk.dependencies if disk else []),
            replace_paths=disk.replace_paths if disk else [],
            # El id del Workshop aparece en cuatro sitios y la base lo deja
            # vacio a menudo: en esta instalacion, en 102 de 213 filas. Se
            # recorren todos antes de darlo por perdido.
            steam_id=(
                row["steamId"]
                or row["remoteSteamId"]
                or (disk.steam_id if disk else None)
                or steam_id_from_filename(row["gameRegistryId"] or "")
            ),
            pdx_id=row["pdxId"],
            source=_SOURCE_MAP.get((row["source"] or "").lower(), ModSource.UNKNOWN),
            size=row["size"],
            in_registry=True,
            on_disk=disk.on_disk if disk else bool(folder and folder.is_dir()),
            parse_error=disk.parse_error if disk else None,
        )

    def read_playsets(self) -> list[Playset]:
        playsets: list[Playset] = []
        with self._connect_ro() as connection:
            rows = connection.execute(
                """
                SELECT id, name, isActive, loadOrder
                  FROM playsets
                 WHERE COALESCE(isRemoved, 0) = 0
                 ORDER BY COALESCE(updatedOn, createdOn) DESC
                """
            ).fetchall()
            for row in rows:
                mods = [
                    PlaysetMod(
                        uid=entry["modId"],
                        enabled=bool(entry["enabled"]),
                        position=entry["position"] if entry["position"] is not None else index,
                    )
                    for index, entry in enumerate(
                        connection.execute(
                            """
                            SELECT modId, enabled, position
                              FROM playsets_mods
                             WHERE playsetId = ?
                             ORDER BY position
                            """,
                            (row["id"],),
                        )
                    )
                ]
                dlcs = {
                    entry["dlcId"]: bool(entry["enabled"])
                    for entry in connection.execute(
                        "SELECT dlcId, enabled FROM playsets_dlcs WHERE playsetId = ?",
                        (row["id"],),
                    )
                }
                load_order = (
                    LoadOrderMode.ALPHABETICAL
                    if (row["loadOrder"] or "").lower() == "alphabetical"
                    else LoadOrderMode.CUSTOM
                )
                playsets.append(
                    Playset(
                        id=row["id"],
                        name=row["name"],
                        is_active=bool(row["isActive"]),
                        load_order=load_order,
                        mods=mods,
                        dlcs=dlcs,
                    )
                )
        return playsets

    # --------------------------------------------------------------- escritura

    def save_playset(self, playset: Playset) -> None:
        """Reescribe la pertenencia y el orden del playset en la base.

        Solo se tocan `playsets_mods` y las dos columnas del playset que
        dependen del orden; el resto de metadatos del launcher se deja intacto.
        """
        playset.renumber()
        registered = {mod.uid for mod in self.read_mods() if mod.in_registry}
        unknown = [entry.uid for entry in playset.mods if entry.uid not in registered]
        if unknown:
            raise BackendError(
                f"{len(unknown)} mod(s) no estan en el registro del launcher y no se "
                f"pueden guardar en la base: {', '.join(unknown[:3])}"
                + ("..." if len(unknown) > 3 else "")
            )

        backup_file(self.db_path)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._connect_rw() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise BackendError(
                    "la base del launcher esta ocupada. Cierra el launcher de "
                    "Paradox e intentalo de nuevo."
                ) from exc
            connection.execute("DELETE FROM playsets_mods WHERE playsetId = ?", (playset.id,))
            connection.executemany(
                """
                INSERT INTO playsets_mods (playsetId, modId, enabled, position)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (playset.id, entry.uid, int(entry.enabled), entry.position)
                    for entry in sorted(playset.mods, key=lambda m: m.position)
                ],
            )
            connection.execute(
                "UPDATE playsets SET loadOrder = ?, updatedOn = ? WHERE id = ?",
                (str(playset.load_order), now, playset.id),
            )
            connection.commit()
        _logger.info(
            "guardado playset '%s' con %d mods", playset.name, len(playset.mods)
        )

    def activate(self, playset_id: str) -> None:
        backup_file(self.db_path)
        with self._connect_rw() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise BackendError(
                    "la base del launcher esta ocupada. Cierra el launcher de Paradox."
                ) from exc
            exists = connection.execute(
                "SELECT 1 FROM playsets WHERE id = ?", (playset_id,)
            ).fetchone()
            if exists is None:
                raise BackendError(f"no existe el playset {playset_id}")
            connection.execute("UPDATE playsets SET isActive = 0 WHERE isActive = 1")
            connection.execute("UPDATE playsets SET isActive = 1 WHERE id = ?", (playset_id,))
            connection.commit()

    def create_playset(self, name: str) -> str:
        """Crea un playset vacio y devuelve su id."""
        backup_file(self.db_path)
        playset_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._connect_rw() as connection:
            connection.execute(
                """
                INSERT INTO playsets (id, name, isActive, loadOrder, createdOn, updatedOn)
                VALUES (?, ?, 0, 'custom', ?, ?)
                """,
                (playset_id, name, now, now),
            )
            connection.commit()
        return playset_id

    def register_mod(self, mod: Mod) -> str:
        """Inserta o actualiza el mod en la tabla `mods` del launcher.

        Sin esto, un mod instalado a mano se carga en la partida pero no
        aparece en la interfaz del launcher ni se puede meter en un playset,
        porque los playsets referencian `mods.id`, no la ruta del descriptor.
        """
        if not mod.registry_id:
            raise BackendError(f"'{mod.name}' no tiene descriptor en mod/")

        backup_file(self.db_path)
        with self._connect_rw() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise BackendError(
                    "la base del launcher esta ocupada. Cierra el launcher de Paradox."
                ) from exc

            key = _normalize_registry_id(mod.registry_id)
            existing = next(
                (
                    row["id"]
                    for row in connection.execute("SELECT id, gameRegistryId FROM mods")
                    if _normalize_registry_id(row["gameRegistryId"]) == key
                ),
                None,
            )
            values = (
                mod.steam_id,
                mod.steam_id,
                mod.registry_id,
                mod.name,
                mod.version,
                mod.supported_version,
                json.dumps(mod.tags, ensure_ascii=False),
                str(mod.folder) if mod.folder else None,
                mod.size,
            )
            if existing:
                connection.execute(
                    """
                    UPDATE mods
                       SET steamId = ?, remoteSteamId = ?, gameRegistryId = ?,
                           displayName = ?, version = ?, requiredVersion = ?, tags = ?,
                           dirPath = ?, size = ?, status = 'ready_to_play'
                     WHERE id = ?
                    """,
                    (*values, existing),
                )
                uid = existing
            else:
                uid = str(uuid.uuid4())
                # `source` se deja siempre en 'local', que es lo que el propio
                # launcher pone incluso en los mods que vienen del Workshop
                # cuando el contenido vive en la carpeta `mod/` del usuario.
                # Marcarlos como 'steam' haria que intentase gestionarlos como
                # suscripciones que no existen.
                connection.execute(
                    """
                    INSERT INTO mods (id, steamId, remoteSteamId, gameRegistryId,
                                      displayName, version, requiredVersion, tags,
                                      dirPath, size, status, source, createdDate, isNew)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready_to_play', 'local', ?, 0)
                    """,
                    (uid, *values, int(time.time())),
                )
            connection.commit()
        _logger.info("registrado '%s' como %s (%s)", mod.name, uid, mod.registry_id)
        return uid

    def rename_playset(self, playset_id: str, name: str) -> None:
        self._write_simple(
            "UPDATE playsets SET name = ?, updatedOn = ? WHERE id = ?",
            (name, time.strftime("%Y-%m-%d %H:%M:%S"), playset_id),
            f"renombrado el playset {playset_id} a '{name}'",
        )

    def delete_playset(self, playset_id: str) -> None:
        """Borra un playset. Sus mods siguen instalados.

        Se marca `isRemoved` ademas de borrar la fila porque el launcher
        sincroniza playsets con Paradox Mods y usa esa marca; borrar sin mas
        podria hacer que reapareciera en la siguiente sincronizacion.
        """
        self._write_simple(
            "UPDATE playsets SET isRemoved = 1, isActive = 0 WHERE id = ?",
            (playset_id,),
            f"borrado el playset {playset_id}",
        )

    def set_dlc_enabled(self, playset: Playset, dlc_id: str, enabled: bool) -> None:
        playset.dlcs[dlc_id] = enabled
        self._write_simple(
            """
            INSERT INTO playsets_dlcs (playsetId, dlcId, enabled) VALUES (?, ?, ?)
            ON CONFLICT(playsetId, dlcId) DO UPDATE SET enabled = excluded.enabled
            """,
            (playset.id, dlc_id, int(enabled)),
            f"DLC {dlc_id}: {'activado' if enabled else 'desactivado'}",
        )

    def _write_simple(self, sql: str, parametros: tuple, mensaje: str) -> None:
        """Una escritura corta con copia previa y el mismo trato de errores."""
        backup_file(self.db_path)
        with self._connect_rw() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise BackendError(
                    "la base del launcher esta ocupada. Cierra el launcher de Paradox."
                ) from exc
            connection.execute(sql, parametros)
            connection.commit()
        _logger.info("%s", mensaje)

    def unregister_mod(self, uid: str) -> bool:
        """Borra la fila del mod. Sus filas en playsets caen con ella.

        Las claves foraneas estan en cascada, asi que basta con la fila de
        `mods`: `playsets_mods` se limpia sola.
        """
        backup_file(self.db_path)
        with self._connect_rw() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise BackendError(
                    "la base del launcher esta ocupada. Cierra el launcher de Paradox."
                ) from exc
            cursor = connection.execute("DELETE FROM mods WHERE id = ?", (uid,))
            connection.commit()
            return cursor.rowcount > 0

    def apply_to_game(self, playset: Playset) -> Path | None:
        """Vuelca el orden del playset en `dlc_load.json`.

        Se conservan las claves que Loadstone no gestiona todavia, `disabled_dlcs`
        entre ellas: los `dlcId` de la base son claves cortas que no se pueden
        traducir sin ambiguedad a lo que espera este archivo.
        """
        mods_by_uid = {mod.uid: mod for mod in self.read_mods()}
        enabled: list[str] = []
        missing: list[str] = []
        for entry in sorted(playset.mods, key=lambda m: m.position):
            if not entry.enabled:
                continue
            mod = mods_by_uid.get(entry.uid)
            registry_id = mod.registry_id if mod else None
            if registry_id:
                enabled.append(registry_id.replace("\\", "/"))
            else:
                missing.append(mod.name if mod else entry.uid)
        if missing:
            raise BackendError(
                "estos mods no tienen descriptor que el juego pueda cargar: "
                + ", ".join(missing[:3])
                + ("..." if len(missing) > 3 else "")
            )

        payload: dict = {}
        if self.dlc_load_path.is_file():
            try:
                existing = json.loads(self.dlc_load_path.read_text(encoding="utf-8-sig"))
                if isinstance(existing, dict):
                    payload = existing
            except (OSError, json.JSONDecodeError):
                payload = {}
        payload.setdefault("disabled_dlcs", [])
        payload["enabled_mods"] = enabled

        desactivados = self._disabled_dlc_paths(playset)
        if desactivados is not None:
            payload["disabled_dlcs"] = desactivados

        backup_file(self.dlc_load_path)
        atomic_write_json(self.dlc_load_path, payload)
        _logger.info(
            "aplicados %d mods y %s a %s",
            len(enabled),
            f"{len(desactivados)} DLC desactivados"
            if desactivados is not None
            else "los DLC sin tocar",
            self.dlc_load_path.name,
        )
        return self.dlc_load_path

    def _disabled_dlc_paths(self, playset: Playset) -> list[str] | None:
        """Rutas de los DLC que el playset deja apagados.

        Devuelve `None` cuando no hay con que traducir las claves del playset
        a rutas, y entonces se conserva lo que ya hubiera en el archivo: es
        preferible no tocar los DLC a escribir rutas inventadas.

        La forma de cada entrada (`dlc/dlc014_utopia`) es la documentada por la
        comunidad, pero no se pudo confirmar contra una instalacion que tuviera
        DLC desactivados. Si fuera erronea, el juego ignoraria la entrada y
        cargaria el DLC igualmente.
        """
        if not playset.dlcs or self.game.install_path is None:
            return None
        instalados = {entrada.id: entrada for entrada in scan_dlc(self.game.install_path)}
        if not instalados:
            return None
        return sorted(
            instalados[dlc_id].folder
            for dlc_id, activo in playset.dlcs.items()
            if not activo and dlc_id in instalados
        )
