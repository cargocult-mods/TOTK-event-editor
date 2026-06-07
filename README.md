# TOTK-event-editor

Maintained by [cargocult-mods](https://github.com/cargocult-mods) and [Codex](https://github.com/openai/codex).

TOTK-event-editor is a maintained EventEditor fork developed around Tears of the
Kingdom modding workflow. It keeps the original EventEditor workflow while adding
compressed `.bfevfl.zs` handling, Mals/MSBT message text display, graph editing
quality-of-life features, XML import/export helpers, tests, and Windows release builds.

### Credits and provenance

This fork is based on the original open-source EventEditor project by leoetlino
and contributors.

The user-facing QoL behavior reconstructed in this fork originated with Alciel's
EventEditor build. Credit for the original QoL design and behavior goes to Alciel;
this repository provides a maintained source reconstruction and public release path
for those changes.

### Setup

Install Python 3.6+ (**64 bit version**) and PyQt5, then run `pip install eventeditor`.

### Windows executable downloads

Tagged releases can include a prebuilt Windows zip. Download
`EventEditor-Windows.zip` from the GitHub release, extract it, and run
`TOTK EventEditor.exe` from the extracted `TOTK EventEditor` folder.

Maintainers can create that zip from GitHub Actions by pushing a version tag:

```sh
git tag v1.3.10
git push origin v1.3.10
```

The release workflow builds a one-folder executable package instead of a single-file
executable because Qt WebEngine needs companion DLLs and resource files.

### Testing

To run the source tests:

```sh
python -m pip install -e .
python -m unittest discover -s tests
```

### Configuration

The configuration file is stored:

* On Linux or macOS: at `~/.config/eventeditor/eventeditor.ini`
* On Windows: at `%APPDATA%/eventeditor/eventeditor.ini`

For dictionary-backed `.bfevfl.zs` files, EventEditor needs access to
`Pack/ZsDic.pack.zs`. You can either open a file directly from an extracted RomFS
tree that contains that dictionary pack or set:

```ini
[paths]
totk_rom_root=/path/to/totk_romfs
```

The first time you open or save a `.zs` file without that path configured, EventEditor
will prompt you to locate `Pack/ZsDic.pack.zs`.

### Auto-completion

#### Breath of the Wild

In order to enable auto-completion for actors, actions, and queries, add:

```ini
[paths]
rom_root=/path/to/game_rom
```

to EventEditor's configuration file, where `/path/to/game_rom` is a path such that
`/path/to/game_rom/Pack/Bootup.pack/Actor/AIDef/AIDef_Game.product.sbyml` exists.
An easy, recommended way to get the required file structure without extracting every archive
is to use [botwfstools](https://github.com/leoetlino/botwfstools).

#### Other games

Alternatively, JSON actor definitions can be generated under *Flowchart* > *Export actor definition data to JSON*. This will generate information for auto-completion from the currently open event flow. The first time this is run, a prompt will appear asking for where to save this information.

This action can be safely repeated in case other event flows contain actors, actions, or queries that have yet to be included in the JSON file (existing entries will not be overwritten).

### Known issues

* On Linux, if the main window view is a completely blank screen, even after opening a file, try running `QTWEBENGINE_DISABLE_SANDBOX=1 eventeditor` to start the tool.

* Unlinking events while in fork/join will break graph generation most of the time. So using that option is not recommended when fork/join events are involved.

### What needs to be done

* Timeline files (reverse engineering)

* Collect event info from EventInfo and have a metadata file for each event flow, so that:
    * EventInfo can be automatically regenerated
    * All copies of an event flow can be automatically updated

* Node order shuffling to get less crossings. This used to be a dagre.js feature but it got removed...

### License

This software is licensed under the terms of the GNU General Public License, version 2 or later.
