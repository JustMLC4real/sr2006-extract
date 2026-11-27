#!/usr/bin/env python3
"""
sr2006-extract - list and extract the DATA.FAI / DATA.FAB archive of
Sega Rally 2006 (PlayStation 2).

Run without arguments for the window, or use the command line:

  python sr2006_extract.py list    <game folder> [--filter PATTERN]
  python sr2006_extract.py extract <game folder> -o <output folder> [--filter PATTERN]

PATTERN is a wildcard pattern on the path inside the archive, for example
"se/*" or "*.dat". Without --filter every file is used.

Archive format
  DATA.FAI is the index, DATA.FAB holds the file data.
  DATA.FAI header (little endian):
    0x00  "FAH\\0"
    0x0C  size of DATA.FAI
    0x10  number of files
    0x14  offset of the file table
    0x18  size of the name table
    0x1C  offset of the name table (the suffix table follows it)
  File table, 16 bytes per file:
    u16 suffix index, u16 name index, u32 offset in DATA.FAB, u32 size,
    u32 hash
  A file's path is name + suffix; both indexes count in 4-byte units from
  the start of their table, and both strings end with a zero byte.
"""
import argparse
import fnmatch
import os
import struct
import sys
import threading

__version__ = '1.0.0'

CHUNK = 1 << 20


class ArchiveError(Exception):
    pass


class Entry:
    __slots__ = ('path', 'offset', 'size')

    def __init__(self, path, offset, size):
        self.path = path
        self.offset = offset
        self.size = size


def find_archive(path):
    """Accept the game folder, DATA.FAI or DATA.FAB -> (fai path, fab path)."""
    if os.path.isdir(path):
        folder = path
    else:
        folder = os.path.dirname(os.path.abspath(path))
    names = {n.upper(): n for n in os.listdir(folder)} if os.path.isdir(folder) else {}
    if 'DATA.FAI' not in names or 'DATA.FAB' not in names:
        raise ArchiveError(f'DATA.FAI and DATA.FAB not found in {folder}')
    return os.path.join(folder, names['DATA.FAI']), os.path.join(folder, names['DATA.FAB'])


def read_index(fai_path):
    """-> list of Entry, in archive order."""
    with open(fai_path, 'rb') as f:
        d = f.read()
    if len(d) < 0x20 or d[:4] != b'FAH\0':
        raise ArchiveError(f'{fai_path} is not a DATA.FAI index (no "FAH" header)')
    count, table, name_size, name_base = struct.unpack_from('<IIII', d, 0x10)
    suffix_base = name_base + name_size
    if table + 16 * count > len(d) or suffix_base > len(d):
        raise ArchiveError(f'{fai_path}: header points past the end of the file')

    def cstr(o):
        end = d.index(b'\0', o)
        return d[o:end].decode('latin-1')

    out = []
    for i in range(count):
        suffix, name, offset, size, _ = struct.unpack_from('<HHIII', d, table + 16 * i)
        out.append(Entry(cstr(name_base + 4 * name) + cstr(suffix_base + 4 * suffix), offset, size))
    return out


def matches(entry, pattern):
    if not pattern:
        return True
    return fnmatch.fnmatch(entry.path.lower(), pattern.lower())


def safe_target(outdir, path):
    """Output path for an archive path; refuses paths that leave outdir."""
    parts = [p for p in path.replace('\\', '/').split('/') if p not in ('', '.')]
    if not parts or any(p == '..' or ':' in p for p in parts):
        raise ArchiveError(f'unsafe path in archive: {path!r}')
    return os.path.join(outdir, *parts)


def extract(fab_path, entries, outdir, progress=None, cancel=None):
    """Write entries to outdir. progress(done_files, total_files, path) is
    called after every file; cancel() returning True stops early.
    Returns the number of files written."""
    total = len(entries)
    fab_size = os.path.getsize(fab_path)
    done = 0
    with open(fab_path, 'rb') as fab:
        for e in entries:
            if cancel and cancel():
                break
            if e.offset + e.size > fab_size:
                raise ArchiveError(f'{e.path}: data lies past the end of DATA.FAB')
            target = safe_target(outdir, e.path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            fab.seek(e.offset)
            left = e.size
            with open(target, 'wb') as f:
                while left:
                    block = fab.read(min(CHUNK, left))
                    if not block:
                        raise ArchiveError(f'{e.path}: DATA.FAB ended early')
                    f.write(block)
                    left -= len(block)
            done += 1
            if progress:
                progress(done, total, e.path)
    return done


def human(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024.0


# ----------------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------------
def cli(argv):
    p = argparse.ArgumentParser(
        prog='sr2006_extract.py',
        description='List and extract the DATA.FAI / DATA.FAB archive of Sega Rally 2006 (PS2). '
                    'Run without arguments to open the window.')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='cmd', required=True)
    pl = sub.add_parser('list', help='list the files in the archive')
    pl.add_argument('game', help='game folder (with DATA.FAI and DATA.FAB), or DATA.FAI itself')
    pl.add_argument('--filter', help='wildcard pattern, e.g. "se/*"')
    pe = sub.add_parser('extract', help='extract files')
    pe.add_argument('game', help='game folder (with DATA.FAI and DATA.FAB), or DATA.FAI itself')
    pe.add_argument('-o', '--output', required=True, help='output folder')
    pe.add_argument('--filter', help='wildcard pattern, e.g. "se/*"')
    a = p.parse_args(argv)

    try:
        fai, fab = find_archive(a.game)
        entries = [e for e in read_index(fai) if matches(e, a.filter)]
        if a.cmd == 'list':
            for e in entries:
                print(f'{e.offset:#010x} {e.size:>10} {e.path}')
            print(f'{len(entries)} file(s), {human(sum(e.size for e in entries))}', file=sys.stderr)
            return 0
        step = max(1, len(entries) // 100)

        def progress(done, total, path):
            if done % step == 0 or done == total:
                print(f'\r{done}/{total} {path[:60]:<60}', end='', file=sys.stderr, flush=True)

        n = extract(fab, entries, a.output, progress)
        print(f'\nExtracted {n} file(s) to {os.path.abspath(a.output)}', file=sys.stderr)
        return 0
    except (ArchiveError, OSError) as err:
        print(f'error: {err}', file=sys.stderr)
        return 1


# ----------------------------------------------------------------------------
# Window
# ----------------------------------------------------------------------------
def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f'sr2006-extract {__version__} - Sega Rally 2006 archive extractor')
    root.geometry('820x600')
    root.minsize(640, 420)

    state = {'entries': [], 'shown': [], 'fab': None, 'busy': False, 'cancel': False}
    game_var = tk.StringVar()
    out_var = tk.StringVar()
    filter_var = tk.StringVar()
    status_var = tk.StringVar(value='Choose the game folder (the one with DATA.FAI and DATA.FAB).')

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill='both', expand=True)
    frm.columnconfigure(1, weight=1)

    def browse_game():
        d = filedialog.askdirectory(title='Game folder (with DATA.FAI and DATA.FAB)')
        if d:
            game_var.set(d)
            if not out_var.get():
                out_var.set(os.path.join(d, 'extracted'))
            load()

    def browse_out():
        d = filedialog.askdirectory(title='Output folder')
        if d:
            out_var.set(d)

    ttk.Label(frm, text='Game folder').grid(row=0, column=0, sticky='w')
    gent = ttk.Entry(frm, textvariable=game_var)
    gent.grid(row=0, column=1, sticky='ew', padx=6)
    ttk.Button(frm, text='Browse...', command=browse_game).grid(row=0, column=2)
    ttk.Label(frm, text='Output folder').grid(row=1, column=0, sticky='w', pady=(6, 0))
    ttk.Entry(frm, textvariable=out_var).grid(row=1, column=1, sticky='ew', padx=6, pady=(6, 0))
    ttk.Button(frm, text='Browse...', command=browse_out).grid(row=1, column=2, pady=(6, 0))
    ttk.Label(frm, text='Filter').grid(row=2, column=0, sticky='w', pady=(6, 0))
    fent = ttk.Entry(frm, textvariable=filter_var)
    fent.grid(row=2, column=1, sticky='ew', padx=6, pady=(6, 0))
    ttk.Label(frm, text='e.g. se/*  or  *.dat').grid(row=2, column=2, sticky='w', pady=(6, 0))

    tree_frame = ttk.Frame(frm)
    tree_frame.grid(row=3, column=0, columnspan=3, sticky='nsew', pady=8)
    frm.rowconfigure(3, weight=1)
    tree = ttk.Treeview(tree_frame, columns=('size',), selectmode='extended')
    tree.heading('#0', text='Path in archive')
    tree.heading('size', text='Size')
    tree.column('#0', width=560)
    tree.column('size', width=110, anchor='e')
    sb = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side='left', fill='both', expand=True)
    sb.pack(side='right', fill='y')

    bar = ttk.Progressbar(frm, mode='determinate')
    bar.grid(row=4, column=0, columnspan=3, sticky='ew')
    ttk.Label(frm, textvariable=status_var).grid(row=5, column=0, columnspan=3, sticky='w', pady=(4, 0))
    btns = ttk.Frame(frm)
    btns.grid(row=6, column=0, columnspan=3, sticky='e', pady=(8, 0))
    b_sel = ttk.Button(btns, text='Extract selected')
    b_all = ttk.Button(btns, text='Extract all shown')
    b_open = ttk.Button(btns, text='Open output folder')
    b_stop = ttk.Button(btns, text='Stop')
    for b in (b_open, b_stop, b_sel, b_all):
        b.pack(side='left', padx=(6, 0))

    def refresh():
        tree.delete(*tree.get_children())
        pat = filter_var.get().strip()
        state['shown'] = [e for e in state['entries'] if matches(e, pat)]
        for i, e in enumerate(state['shown']):
            tree.insert('', 'end', iid=str(i), text=e.path, values=(human(e.size),))
        total = sum(e.size for e in state['shown'])
        if state['entries']:
            status_var.set(f'{len(state["shown"])} of {len(state["entries"])} files shown, {human(total)}.')

    def load():
        try:
            fai, fab = find_archive(game_var.get().strip())
            state['entries'] = read_index(fai)
            state['fab'] = fab
        except (ArchiveError, OSError) as err:
            state['entries'] = []
            refresh()
            status_var.set(str(err))
            return
        refresh()

    def set_busy(busy):
        state['busy'] = busy
        for b in (b_sel, b_all):
            b.state(['disabled'] if busy else ['!disabled'])
        b_stop.state(['!disabled'] if busy else ['disabled'])

    def run(entries):
        if state['busy']:
            return
        if not entries:
            messagebox.showinfo('Nothing to extract', 'No files are selected or shown.')
            return
        out = out_var.get().strip()
        if not out:
            messagebox.showwarning('Output folder', 'Choose an output folder first.')
            return
        state['cancel'] = False
        set_busy(True)
        bar.configure(maximum=len(entries), value=0)

        def progress(done, total, path):
            root.after(0, lambda: (bar.configure(value=done),
                                   status_var.set(f'{done}/{total}  {path}')))

        def work():
            try:
                n = extract(state['fab'], entries, out, progress, lambda: state['cancel'])
                msg = f'Extracted {n} of {len(entries)} file(s) to {out}'
            except (ArchiveError, OSError) as err:
                msg = f'Error: {err}'
            root.after(0, lambda: (status_var.set(msg), set_busy(False)))

        threading.Thread(target=work, daemon=True).start()

    def open_out():
        out = out_var.get().strip()
        if out and os.path.isdir(out):
            if sys.platform.startswith('win'):
                os.startfile(out)
            else:
                import subprocess
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', out])
        else:
            messagebox.showinfo('Output folder', 'The output folder does not exist yet.')

    b_sel.configure(command=lambda: run([state['shown'][int(i)] for i in tree.selection()]))
    b_all.configure(command=lambda: run(list(state['shown'])))
    b_stop.configure(command=lambda: state.update(cancel=True))
    b_open.configure(command=open_out)
    filter_var.trace_add('write', lambda *_: refresh())
    fent.bind('<Return>', lambda _e: refresh())
    gent.bind('<Return>', lambda _e: load())
    gent.bind('<FocusOut>', lambda _e: load() if game_var.get().strip() and not state['entries'] else None)
    set_busy(False)
    root.mainloop()
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        try:
            return gui()
        except ImportError:
            print('tkinter is not available; use the command line (see --help).', file=sys.stderr)
            return 1
    return cli(argv)


if __name__ == '__main__':
    sys.exit(main())
