# sr2006-extract

Lists and extracts the files in the `DATA.FAI` / `DATA.FAB` archive of **Sega Rally 2006** (PlayStation 2). Almost all of the game's data (textures, models, text, sound banks) is packed in this archive.

It has a simple window and a command line, and needs nothing but Python.

> This repository contains no game data. You need your own copy of the game.

## Requirements

- Python 3.8 or newer ([python.org](https://www.python.org/downloads/)). The window uses tkinter, which comes with the standard Python installer on Windows and macOS. On Linux you may need to install `python3-tk`.
- The files from your game disc: `DATA.FAI` and `DATA.FAB` must be in the same folder.

Tested with the Japanese release (SLPM-66212). The tool reads the table positions from the `DATA.FAI` header, so other releases may work too, but they have not been tested.

## Using the window

1. Double-click `sr2006_extract.py`, or run `python sr2006_extract.py` without arguments.
2. Press **Browse...** next to *Game folder* and choose the folder with `DATA.FAI` and `DATA.FAB`. The file list appears.
3. Optionally type a filter, for example `se/*` (the sound folder) or `*.dat`.
4. Choose an output folder. It defaults to `extracted` inside the game folder.
5. Press **Extract all shown** or select files and press **Extract selected**.

The folder structure inside the archive is kept.

## Using the command line

List everything, or only matching files:

```
python sr2006_extract.py list "path/to/game"
python sr2006_extract.py list "path/to/game" --filter "se/*"
```

Extract everything, or only matching files:

```
python sr2006_extract.py extract "path/to/game" -o "path/to/output"
python sr2006_extract.py extract "path/to/game" -o "path/to/output" --filter "se/*"
```

The filter is a wildcard pattern on the path inside the archive (`*` matches anything, including `/`). It is not case-sensitive.

The whole archive is about 2.4 GB in 18,796 files.

## Archive format

`DATA.FAI` is the index and `DATA.FAB` holds the file data. All values are little-endian.

| Offset in DATA.FAI | Meaning |
|---|---|
| `0x00` | `FAH\0` |
| `0x0C` | size of `DATA.FAI` |
| `0x10` | number of files |
| `0x14` | offset of the file table |
| `0x18` | size of the name table |
| `0x1C` | offset of the name table; the suffix table follows it |

Each entry in the file table is 16 bytes:

| Bytes | Meaning |
|---|---|
| u16 | suffix index |
| u16 | name index |
| u32 | offset in `DATA.FAB` |
| u32 | size |
| u32 | hash |

A file's path is *name + suffix*. Both indexes count in 4-byte units from the start of their table, and both strings end with a zero byte. For example, the name `se/r2k5sngs` and the suffix `.dat` give `se/r2k5sngs.dat`.

## Related

[sr2006-music-rip](https://github.com/JustMLC4real/sr2006-music-rip) rips the game's sequenced music (the tracks that are not ADX streams) to a PSF2 set, MIDI files and samples.

## Legal

This tool only reads files you already have. The extracted data belongs to Sega; do not redistribute it.
