# TOTK EventEditor

## Downloads

Download the latest release from the
[TOTK EventEditor releases page](https://github.com/cargocult-mods/TOTK-event-editor/releases).

For most users, download `TOTK-EventEditor_<version>-Windows.zip`, extract it,
and run `TOTK EventEditor.exe` or `TOTK Event Editor <version>.exe` from the
extracted folder.

Linux builds may appear on some releases, but they are experimental and
untested. The Windows zip is the supported release asset.

## What this is

TOTK EventEditor is a maintained EventEditor fork focused on Tears of the
Kingdom event-flow modding.

EventFlow files are the game's event scripts. In TOTK, they control many of the
things that happen during conversations, cutscenes, quest steps, shrine logic,
shop interactions, tutorials, and other scripted moments. An EventFlow usually
describes a flowchart: which actors are involved, which action or query each
actor should run, which branch comes next, and what parameters are passed into
those actions.

It lets you open, inspect, edit, and save `.bfevfl` and `.bfevfl.zs` event flow
files. It keeps the familiar EventEditor graph workflow while adding tools aimed
at common TOTK modding problems: compressed event files, message preview,
actor-aware action/query discovery, faster navigation, and release builds that
do not require setting up Python.

## Main features

- Open and save TOTK `.bfevfl.zs` files, including dictionary-compressed files.
- View flowcharts as editable node graphs.
- Inspect actors, actions, queries, forks, joins, switches, and entry points.
- Edit node type, actor, parameters, links, cases, and other event data.
- See Mals/MSBT message text while working with dialogue events.
- Browse actor-specific action/query possibilities with the Event Library.
- Import and export XML helpers for event-flow work.
- Drag files onto the app window to open them.
- Use GitHub release builds on Windows without installing Python.
- Check for updates from inside the app.

## Event Library

When editing an action or query node, click `Library...` beside the node type
dropdown. The library helps you understand what an actor can do in EventFlow:
which actions and queries have been found for that actor, which parameters they
usually take, and how they have been used in known event flows.

This is useful both while building an event flow and while researching how the
game normally does something. For example, it can help answer:

- what actions are available that might help me achieve my gameplay goals?
- how is this usually used?
- which actions or queries does this actor seem to support?
- what parameters should I expect to provide?
- is there an unusual use that might explain a special case?
- where is an example I can compare against?

The library uses examples from the current file, the inferred current mod, and
vanilla where available. Its vanilla data is cached so repeat lookups should be
much faster after the first scan.

## Recommended workflow

1. Open an event flow from your mod or from an extracted TOTK RomFS.
2. Use the graph, actor list, or entry point list to find the event you want.
3. Edit action and query nodes normally.
4. If you are unsure which node type or parameters are valid, open `Library...`.
5. Use known examples to compare against the pattern you need.
6. Save the `.bfevfl` or `.bfevfl.zs` file back into your mod.

## TOTK RomFS setup

For the best TOTK experience, EventEditor should know where your extracted TOTK
RomFS is.

This is needed for dictionary-backed `.bfevfl.zs` files and for vanilla library
scans.

The first time you open or save a `.zs` file without the path configured,
EventEditor will prompt you to locate `Pack/ZsDic.pack.zs`.

You can also set the path manually in the config file:

```ini
[paths]
totk_rom_root=/path/to/totk_romfs
```

EventEditor uses this folder to find files such as:

```text
Pack/ZsDic.pack.zs
Event/EventFlow/*.bfevfl.zs
Pack/Actor/*.pack.zs
```

## Configuration file

The configuration file is stored here:

- Windows: `%APPDATA%/eventeditor/eventeditor.ini`
- Linux or macOS: `~/.config/eventeditor/eventeditor.ini`

## Source install

Most Windows users should use the release zip instead.

To run from source, install Python 3.6+ 64-bit and then install EventEditor:

```sh
python -m pip install -e .
eventeditor
```

To run the tests:

```sh
python -m pip install -e .
python -m unittest discover -s tests
```

## Maintainer notes

Windows release builds are created by pushing a version tag:

```sh
git tag v1.3.10
git push origin v1.3.10
```

The Windows workflow builds a one-folder executable package rather than a
single-file executable because Qt WebEngine needs companion DLLs and resource
files.

There is also a manual Linux build workflow. It is experimental and should not
be treated as official support until it has been tested by real Linux users.

The app also supports a command-line `--event` selection path used by
`Go to Event` and release smoke tests.

## Breath of the Wild auto-completion

This fork is maintained for TOTK, but the older Breath of the Wild
auto-completion path is still present.

To enable BOTW actor/action/query auto-completion, add:

```ini
[paths]
rom_root=/path/to/game_rom
```

The path should contain:

```text
Pack/Bootup.pack/Actor/AIDef/AIDef_Game.product.sbyml
```

An easy way to get that file structure without extracting every archive is
[botwfstools](https://github.com/leoetlino/botwfstools).

Alternatively, JSON actor definitions can be generated from the currently open
event flow with `Flowchart` > `Export actor definition data to JSON`.

## Known issues

- Linux builds are experimental. If the main window is blank after opening a
  file, try running with `QTWEBENGINE_DISABLE_SANDBOX=1`.
- Unlinking events around fork/join structures can break graph generation. Be
  careful when editing those sections.
- The Event Library may report skipped files while collecting examples. This
  usually means a file could not be opened, decompressed, or parsed during the
  scan. It is not fatal for normal editing.

## Credits and provenance

This fork is based on the original open-source EventEditor project by
[leoetlino](https://github.com/leoetlino) and contributors.

The user-facing quality-of-life behavior reconstructed in this fork originated
with Alciel's EventEditor build. Credit for the original QoL design and behavior
goes to Alciel; this repository provides a maintained source reconstruction and
public release path for those changes.

Maintained by [cargocult-mods](https://github.com/cargocult-mods) with Codex
assistance.

## License

This software is licensed under the terms of the GNU General Public License,
version 2 or later.
