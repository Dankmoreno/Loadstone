# Formatos de mods y playsets en los juegos de Paradox

Notas de ingenieria inversa tomadas de una instalacion real el 2026-10-11.
Donde algo no se pudo confirmar, se dice explicitamente.

Juegos observados: Stellaris v4.5.1, CK3 1.19.0.4, Victoria 3 1.13.9,
HOI4 1.19.0.0, Europa Universalis V (sin version legible, ver abajo).

## Dos ecosistemas en paralelo

Paradox esta migrando del launcher externo a un gestor dentro del juego, y
ahora mismo conviven los dos. Esto es lo que determina la arquitectura de
Loadstone: un backend por ecosistema, detras de la misma interfaz.

| Juego | Backend | Archivos que manda |
|---|---|---|
| Stellaris, CK3, Victoria 3, HOI4, EU4 | launcher v2 | `launcher-v2.sqlite` + `dlc_load.json` |
| Europa Universalis V | gestor in-game | `playsets.json` |

La carpeta de datos es siempre
`%USERPROFILE%/Documents/Paradox Interactive/<Nombre del juego>`, y el campo
`gameDataPath` de `launcher-settings.json` lo confirma con el token
`%USER_DOCUMENTS%`.

## Identificar la instalacion: `launcher-settings.json`

Esta en la raiz de la instalacion (Stellaris, HOI4, EU4) o en `launcher/`
(CK3, Victoria 3). EU5 **no lo trae**: abandono el launcher externo, asi que
hay que reconocerlo por el nombre de la carpeta.

```json
{
  "gameId": "stellaris",
  "version": "Cygnus v4.5.1 (358e)",
  "modsCompatibilityVersion": "4.5",
  "rawVersion": "v4.5.1",
  "gameDataPath": "%USER_DOCUMENTS%/Paradox Interactive/Stellaris",
  "exePath": "./stellaris.exe"
}
```

`modsCompatibilityVersion` es el campo util y el menos evidente: fija **cuanta
precision cuenta** al comparar versiones. Vale `4.5` en Stellaris (importan
mayor y menor) pero `1` en CK3 (solo la mayor). Comparar siempre todos los
componentes marcaria como incompatibles casi todos los mods de CK3.

Las dos distribuciones de contenido que hay en circulacion:

- moderna: todo bajo `game/`, mas `clausewitz/` y `jomini/` (CK3, V3, EU5).
- anterior: contenido plano en la raiz, con `common/` y `dlc/` (Stellaris, HOI4).

## Descriptores de mods

Un mod se declara dos veces:

- `mod/<id>.mod` en la carpeta de datos: **es lo que el juego lee**. Apunta al
  contenido con `path=` (carpeta) o `archive=` (zip).
- `descriptor.mod` dentro del propio mod: lo empaqueta el autor. Si los dos
  existen, manda el de `mod/`.

```
path="C:/Users/<user>/Documents/Paradox Interactive/Stellaris/mod/1087781345"
name="Mod Menu"
picture="thumbnail.jpg"
remote_file_id="1087781345"
tags={
	"Utilities"
	"Mod Menu"
}
supported_version="v4.3.*"
```

Claves vistas en 213 descriptores de Stellaris, con su frecuencia:

| clave | en `mod/*.mod` | en `descriptor.mod` | notas |
|---|---|---|---|
| `name` | 213 | 200 | nombre visible, y la clave con la que se resuelven dependencias |
| `tags` | 213 | 200 | lista de cadenas |
| `supported_version` | 213 | 200 | admite comodines: `v4.3.*`, `v*.*.*` |
| `remote_file_id` | 211 | 198 | id del Workshop de Steam |
| `path` | 201 | 18 | absoluta, con barras normales |
| `picture` | 133 | 120 | relativa a la carpeta del mod |
| `version` | - | 158 | version del mod, no del juego |
| `dependencies` | 12 | 12 | lista de **nombres visibles** |
| `archive` | 12 | - | mod sin descomprimir |

Detalles del formato que importan al parsear:

- Las claves pueden repetirse legalmente: `replace_path` aparece una vez por
  carpeta que el mod sustituye entera. Un parser basado en dict pierde datos.
- Los comentarios van con `#` hasta fin de linea.
- Hay valores sin comillas (`version=1.2.3`).
- Codificacion UTF-8, a veces con BOM, y cp1252 en mods viejos o editados a mano.

Sobre `dependencies`: Paradox **no da identificadores**. El descriptor escribe
el nombre visible del mod del que depende y el launcher lo busca por texto. En
la practica los autores ponen el nombre, el id del Workshop o el nombre de la
carpeta, asi que casarlas es inevitablemente aproximado. No existe nada
equivalente a `loadAfter` ni `loadBefore` de RimWorld.

## Backend launcher v2

### `launcher-v2.sqlite`

Base sqlite gestionada con knex (trae `knex_migrations`). Tablas relevantes:

```sql
mods(id PK, pdxId, steamId, gameRegistryId, name, displayName, version,
     requiredVersion, tags json, dirPath, archivePath, status, source, size, ...)
playsets(id PK, name, isActive, loadOrder, pdxId, createdOn, updatedOn,
         isRemoved, state, ...)
playsets_mods(playsetId FK, modId FK, enabled, position)
playsets_dlcs(playsetId FK, dlcId, enabled)
mods_dependencies(modId, modVersion, dependencyType, dependencyId, dependencyName)
metadata_relationships(id, modMetadataId, relationshipId, relationshipType, ...)
dlc(id, name, dirPath)
key_value_pairs(name, value)
```

Lo que hay que saber para escribir aqui:

- `gameRegistryId` vale `mod/1087781345.mod`: es la clave que cruza la base con
  el disco, y literalmente lo que va en `dlc_load.json`.
- El orden de carga es `playsets_mods.position`, y `playsets.loadOrder` dice el
  modo: `custom` o `alphabetical`.
- `requiredVersion` es el `supported_version` del descriptor.
- `tags` es una cadena JSON, no una tabla.
- Las dependencias estan repartidas en dos tablas segun su origen:
  `mods_dependencies` para lo que viene del descriptor y
  `metadata_relationships` para lo que viene de Paradox Mods.
- En la instalacion observada, `mods.source` era `local` en los 213 mods y la
  tabla `dlc` estaba vacia, asi que los valores de `source` para Steam y
  Paradox Mods no se pudieron confirmar.

### `dlc_load.json`

**Es el unico archivo que el ejecutable del juego lee al arrancar.** La base de
datos solo alimenta la interfaz del launcher.

```json
{"disabled_dlcs":[],"enabled_mods":["mod/1087781345.mod","mod/1121692237.mod"]}
```

El orden de `enabled_mods` **es** el orden de carga: el ultimo gana y
sobrescribe los archivos de los anteriores.

De aqui sale una consecuencia practica: escribir solo la base no cambia nada en
la partida, y escribir solo el JSON hace que el launcher muestre algo distinto
de lo que se va a jugar. Hay que escribir los dos.

`disabled_dlcs` queda sin resolver: los `dlcId` de `playsets_dlcs` son claves
cortas (`utopia`, `leviathans`) y este archivo historicamente espera rutas
(`dlc/dlc001_...`). Con la tabla `dlc` vacia no hubo forma de confirmar el
mapeo, asi que Loadstone preserva el contenido existente y no lo toca.

## Backend del gestor in-game (EU5)

`Documents/Paradox Interactive/Europa Universalis V/playsets.json`. No hay
sqlite, no hay `dlc_load.json` y no hay carpeta `launcher/` en la instalacion.

```json
{
	"file_version":	"1.0.0",
	"playsets":	[{
			"name":	"Coleccion inicial",
			"isActive":	true,
			"isAutomaticallySorted":	true,
			"orderedListMods":	[],
			"DLC":	[{
					"paradoxAppId":	"d015_ancient_monuments_pack",
					"isEnabled":	true
				}]
		}]
}
```

Observaciones:

- El JSON se escribe con tabuladores y `: ` tras la clave, como el resto de los
  archivos del motor.
- Los playsets no tienen id; el `name` es lo unico que los distingue.
- `isAutomaticallySorted` sustituye a `loadOrder`.
- Los `paradoxAppId` de la lista `DLC` aparecen duplicados en dos formatos
  (`d015_ancient_monuments_pack` y `Ancient Monument Pack`) en la instalacion
  observada. Sin explicacion confirmada.

**Sin confirmar:** `orderedListMods` estaba vacio porque no habia ningun mod
instalado, asi que la forma de sus elementos esta inferida. El backend de
Loadstone acepta cadenas y objetos, y al escribir reutiliza la forma que
encontro al leer en lugar de imponer una.

## Otros archivos de la carpeta de datos

| archivo | para que sirve |
|---|---|
| `mods_registry.json` | cache del launcher; no es fuente de verdad |
| `playsets_backup/`, `launcher-v2_backup.sqlite` | copias del propio launcher |
| `continue_game.json` | ultima partida; referencia el playset usado |
| `pdx_settings.txt` / `.json` | ajustes del juego, no de mods |
| `dlc_signature` | firma de DLC; no tocar |

## Descarga desde el Workshop con SteamCMD

**Comprobado el 2026-10-12 en Stellaris (appid 281990), con login anonimo y
sin poseer el juego en la cuenta de Steam:**

```
$ steamcmd.exe +login anonymous +workshop_download_item 281990 1087781345 +quit
Connecting anonymously to Steam Public...OK
Downloading item 1087781345 ...
Success. Downloaded item 1087781345 to "...\steamapps\workshop\content8199087781345" (372760 bytes)
```

Es decir: Valve permite la descarga anonima de contenido del Workshop para este
appid. No hace falta cuenta propietaria ni saltarse ninguna comprobacion. Esto
hace viable la integracion con SteamCMD incluso para instalaciones que no vienen
de Steam (GOG, Microsoft Store, copias movidas a mano).

### Que juegos permiten descarga anonima

Probados los cinco el 2026-10-12, en una sola sesion de SteamCMD, con ids
reales sacados de las paginas publicas del Workshop de cada juego:

| Juego | appid | item probado | resultado |
|---|---|---|---|
| Stellaris | 281990 | 1087781345, 3811650794 | **Success** |
| Crusader Kings III | 1158310 | 3006147147 | ERROR, `Failure` |
| Victoria 3 | 529340 | 2882576273, 3338866707 | ERROR, `Failure` |
| Hearts of Iron IV | 394360 | 3788321641, 3791133471 | ERROR, `Failure` |
| Europa Universalis IV | 236850 | 3794814613, 3804356450 | ERROR, `Failure` |

El control importa: los ids que fallan se verificaron uno a uno contra
`steamcommunity.com/sharedfiles/filedetails/`, y todos son items publicados y
vivos del appid correspondiente ("Scrollable Character Interaction Window" en
CK3, "Eldia" en Victoria 3, "Minsk Rules Spain" en HOI4, "Formable Nations
Conditions Optimization" en EU4). Ademas, en esa misma sesion un id de
Stellaris obtenido por el mismo metodo si descargo. La causa es la aplicacion,
no el id ni la red.

Conclusion practica: **solo Stellaris permite descarga anonima**. Para los
otros cuatro hace falta `+login <usuario>` con una cuenta que posea el juego.
Eso cambia como hay que invocar SteamCMD: con cuenta pide la clave y el codigo
de Steam Guard por consola, asi que no se puede capturar su salida sin
colgarlo. En ese caso Loadstone hereda la terminal y deduce el resultado
mirando si quedo contenido en `steamapps/workshop/content/<appid>/<id>/`.

Esto puede cambiar si Valve o los editores tocan la configuracion, asi que el
codigo no lo da por sentado: lo intenta y lee el resultado.

Lo que baja es la carpeta del mod tal cual, con su `descriptor.mod` dentro, en
`steamapps/workshop/content/<appid>/<pubfileid>/`. Dos consecuencias:

1. **El juego no lo ve.** Falta el `mod/<id>.mod` en la carpeta de datos que
   apunte ahi con `path=`, y falta el registro en `launcher-v2.sqlite`. Ese
   paso hay que darlo aparte, y es el mismo que necesita un mod instalado a
   mano desde un zip.
2. **Sirve para detectar mods desactualizados.** En la prueba, la copia del
   Workshop traia `supported_version="v4.4.*"` y la instalada localmente
   `v4.3.*`: el autor habia publicado una actualizacion. Comparar ambos
   descriptores da una deteccion de desactualizados sin depender de la API web
   de Steam.

Detalles practicos de SteamCMD:

- La primera ejecucion se auto-actualiza y tarda; las siguientes son rapidas.
- Escribe dentro de su propia carpeta (`steamapps/workshop/content/...`), no en
  la biblioteca de Steam del sistema.
- La salida usa retornos de carro para las barras de progreso: conviene
  normalizarla antes de parsearla.
- El resultado se reconoce por las cadenas `Success. Downloaded item` y
  `ERROR! Download item ... failed`.
- Los mods pueden traer basura del autor; el de la prueba incluia un `.git`.

## Prior art

- **Irony Mod Manager** (C#/Avalonia): el referente para deteccion de
  conflictos y generacion de un mod-parche fusionado. No soporta EU5. Deja un
  `IronyModManager_IntegrityCheck.txt` en la carpeta de datos.
- **CWTools**: parser y validador de script de Clausewitz, base de la extension
  de VS Code.
- **Launcher de Paradox**: ordena alfabeticamente o a mano, y no dice nada sobre
  conflictos de archivos.
