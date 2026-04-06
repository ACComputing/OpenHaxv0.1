#!/usr/bin/env python3
"""
OpenHax — 3DS Hacking Suite (v0.4 by a.c)

CIA deep load: pyctr extracts primary NCCH RomFS + ExeFS to a temp folder; CIA Structure
tab browses them; hex can edit RomFS/ExeFS files; texture packs merge into extracted RomFS.
No full CIA binary rebuild in-app — export a modification bundle for makerom/ctrtool.

Roadmap / pip list: EMBEDDED_ROADMAP, EMBEDDED_PIP_REQUIREMENTS (no external .md).

Python 3.8+ recommended.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import re
import shutil
import tempfile
import zipfile
import importlib
import importlib.util
import subprocess
import threading
import sys
from datetime import datetime, timezone
from pathlib import Path

__version__ = "0.4"

# --- Embedded docs (no external OpenHax Roadmap.md / requirements.txt) -----------------

EMBEDDED_PIP_REQUIREMENTS = """\
# OpenHax recommended stack (same as Help → Pip requirements)
pyctr>=0.4.6
keystone-engine>=0.9.2
capstone>=5.0.0
Pillow>=10.0.0
customtkinter>=5.0.0
"""

EMBEDDED_PIP_INSTALL_LINE = (
    "python -m pip install "
    "pyctr keystone-engine capstone Pillow customtkinter"
)

EMBEDDED_ROADMAP = f"""\
OpenHax Roadmap (embedded in #Openhaxv0.py)

Current Version: v{__version__}
Goal: Daily-driver 3DS modding suite by v1.0.

Implemented in v0.4 (real)
  • CIA open: pyctr extracts primary NCCH RomFS + ExeFS to temp folders
  • CIA Structure tab: RomFS + ExeFS treeviews; double-click opens file in hex editor
  • Auto-extract .code → “Load code.bin from current CIA”
  • Texture pack merges into extracted RomFS when present; “changes pending” tracking
  • Export modification bundle (original CIA + romfs/ + exefs/) for external rebuild
  • CIA metadata (Title ID, version) + SMDH title when decryptable

Still not in pyctr / OpenHax
  • Writing a valid rebuilt .cia from edited RomFS/ExeFS (use makerom/ctrtool + bundle export)

---

Full roadmap to v1.0

Phase 1 — CIA (continued)
  [ ] Optional RomFS file replace dialog; progress UI for extract/rebuild
  [ ] makerom/ctrtool autodetect for one-click repack (where available)

Phase 2 — Hex editor power (v0.5)
  [ ] Region highlighting, bookmarks
  [ ] Search & replace (incl. RomFS files)
  [ ] Patch import: IPS, BPS, xdelta
  [ ] Richer undo/redo; optional mmap for files > 200 MB

Phase 3 — Texture & workflow (v0.6–0.7)
  [ ] Texture preview (Pillow): PNG, BCLIM, T3X
  [ ] LayeredFS: auto Title ID, export RomFS changes
  [ ] Batch CIAs; RomFS diff

Phase 4 — Polish & UI (v0.8–1.0)
  [ ] Optional CustomTkinter dark theme
  [ ] Errors/hints for encrypted CIAs; recent files; progress bars; plugins

Nice-to-haves (post v1.0)
  • Title key / seed helpers (legal use only)
  • GodMode9-style decrypt notes (warnings)
  • Disasm tied to code.bin; export IPS/BPS from edits

Recommended pip (see also EMBEDDED_PIP_REQUIREMENTS in source):
  {EMBEDDED_PIP_INSTALL_LINE}
"""

_KEYSTONE_CACHE = None
_PYCTR_CACHE = None
_CAPSTONE_CACHE = None
_PIL_CACHE = None
_CTK_CACHE = None


def _invalidate_dep_cache() -> None:
    """Clear cached find_spec results (call after pip install so status updates)."""
    global _KEYSTONE_CACHE, _PYCTR_CACHE, _CAPSTONE_CACHE, _PIL_CACHE, _CTK_CACHE
    global KEYSTONE_AVAILABLE, PYCTR_AVAILABLE
    _KEYSTONE_CACHE = None
    _PYCTR_CACHE = None
    _CAPSTONE_CACHE = None
    _PIL_CACHE = None
    _CTK_CACHE = None
    KEYSTONE_AVAILABLE = _dep_keystone()
    PYCTR_AVAILABLE = _dep_pyctr()


def _dep_keystone() -> bool:
    global _KEYSTONE_CACHE
    if _KEYSTONE_CACHE is None:
        _KEYSTONE_CACHE = importlib.util.find_spec("keystone") is not None
    return _KEYSTONE_CACHE


def _dep_pyctr() -> bool:
    global _PYCTR_CACHE
    if _PYCTR_CACHE is None:
        _PYCTR_CACHE = importlib.util.find_spec("pyctr") is not None
    return _PYCTR_CACHE


def _dep_capstone() -> bool:
    global _CAPSTONE_CACHE
    if _CAPSTONE_CACHE is None:
        _CAPSTONE_CACHE = importlib.util.find_spec("capstone") is not None
    return _CAPSTONE_CACHE


def _dep_pillow() -> bool:
    global _PIL_CACHE
    if _PIL_CACHE is None:
        _PIL_CACHE = importlib.util.find_spec("PIL") is not None
    return _PIL_CACHE


def _dep_customtkinter() -> bool:
    global _CTK_CACHE
    if _CTK_CACHE is None:
        _CTK_CACHE = importlib.util.find_spec("customtkinter") is not None
    return _CTK_CACHE


KEYSTONE_AVAILABLE = _dep_keystone()
PYCTR_AVAILABLE = _dep_pyctr()


def parse_cia_metadata(path: str) -> dict:
    """
    Best-effort CIA metadata via pyctr. Encrypted CIAs may fail — decrypt first (GodMode9, etc.).
    """
    meta: dict = {
        "format": Path(path).suffix.lower().lstrip("."),
        "title_id": None,
        "title_version": None,
        "content_count": None,
        "error": None,
        "hint": None,
    }
    if not path.lower().endswith(".cia"):
        return meta
    if not _dep_pyctr():
        meta["error"] = "pyctr not installed"
        return meta
    try:
        from pyctr.type.cia import CIAReader

        with CIAReader(path) as cia:
            meta["format"] = "CIA"
            tmd = cia.tmd
            meta["title_id"] = f"{tmd.title_id:016X}"
            meta["title_version"] = int(tmd.title_version)
            meta["content_count"] = int(tmd.content_count)
    except Exception as e:
        meta["error"] = str(e)
        meta["hint"] = "If this CIA is encrypted, decrypt first (GodMode9 / Decrypt9 / similar)."
    return meta


def romfs_collect_file_paths(node: dict, prefix: str = "") -> list[str]:
    """Walk pyctr RomFSReader._tree_root; return paths like ``/file`` for ``romfs.open()``."""
    out: list[str] = []
    for _k, ch in node.get("contents", {}).items():
        t = ch.get("type")
        if t == "file":
            rel = f"{prefix}/{ch['name']}" if prefix else ch["name"]
            out.append("/" + rel.replace("//", "/"))
        elif t == "dir":
            np = f"{prefix}/{ch['name']}" if prefix else ch["name"]
            out.extend(romfs_collect_file_paths(ch, np))
    return out


def extract_cia_structure(cia_path: str, work_dir: Path) -> dict:
    """
    Extract primary NCCH RomFS and ExeFS to ``work_dir/romfs`` and ``work_dir/exefs``.
    Returns status dict (errors per section; encrypted CIAs may fail partially).
    """
    from pyctr.type.cia import CIAReader

    out: dict = {
        "ok": True,
        "romfs_dir": None,
        "exefs_dir": None,
        "code_bin_path": None,
        "title_name": None,
        "product_code": None,
        "program_id": None,
        "primary_ncch": None,
        "exefs_entries": [],
        "romfs_error": None,
        "exefs_error": None,
        "romfs_file_count": 0,
    }
    romfs_dir = work_dir / "romfs"
    exefs_dir = work_dir / "exefs"

    with CIAReader(cia_path) as cia:
        keys = sorted(cia.contents.keys())
        if not keys:
            out["ok"] = False
            out["romfs_error"] = "No NCCH contents in CIA."
            out["exefs_error"] = out["romfs_error"]
            return out

        ncch_idx = keys[0]
        ncch = cia.contents[ncch_idx]
        out["primary_ncch"] = int(ncch_idx)

        try:
            out["product_code"] = str(ncch.product_code).strip()
        except Exception:
            pass
        try:
            out["program_id"] = f"{ncch.program_id:016X}"
        except Exception:
            pass

        # RomFS
        if ncch.romfs is not None:
            try:
                romfs_dir.mkdir(parents=True, exist_ok=True)
                paths = romfs_collect_file_paths(ncch.romfs._tree_root)
                for rp in paths:
                    rel = rp.lstrip("/").replace("\\", "/")
                    dest = romfs_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with ncch.romfs.open(rp) as inf:
                        dest.write_bytes(inf.read())
                out["romfs_dir"] = romfs_dir
                out["romfs_file_count"] = len(paths)
            except Exception as e:
                out["romfs_error"] = str(e)
        else:
            out["romfs_error"] = "No RomFS in primary NCCH (or not loaded)."

        # ExeFS
        if ncch.exefs is not None:
            try:
                exefs_dir.mkdir(parents=True, exist_ok=True)
                smdh = ncch.exefs.icon
                if smdh is not None:
                    try:
                        appt = smdh.get_app_title()
                        if appt is not None:
                            out["title_name"] = appt.short_desc
                    except Exception:
                        pass
                for name in ncch.exefs.entries:
                    with ncch.exefs.open(name) as inf:
                        data = inf.read()
                    (exefs_dir / name).write_bytes(data)
                out["exefs_dir"] = exefs_dir
                out["exefs_entries"] = list(ncch.exefs.entries.keys())
                cb = exefs_dir / ".code"
                if cb.is_file():
                    out["code_bin_path"] = cb
            except Exception as e:
                out["exefs_error"] = str(e)
        else:
            out["exefs_error"] = "No ExeFS in primary NCCH."

    return out


class HexEditorFrame(ttk.Frame):
    """
    Pure Tkinter hex editor: virtual rendering (visible rows only), nibble edit,
    offset column (blue), hex (black), ASCII (dark green), cursor highlights.
    """
    def __init__(self, master, cia_data=None, on_edit_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        self.cia_data = cia_data
        self.on_edit_callback = on_edit_callback
        
        self.bytes_per_row = 16
        self.font = ("Courier", 10)
        self.char_width = 8
        self.char_height = 14
        
        self.offset_chars = 8
        self.hex_chars = self.bytes_per_row * 3 - 1
        self.ascii_chars = self.bytes_per_row
        
        self.total_lines = 0
        self.visible_lines = 0
        self.top_line_index = 0
        
        self.cursor_pos = 0
        self.cursor_nibble = 0
        self._undo_stack: list[tuple[int, int]] = []
        self._undo_max = 256
        self._search_last_idx = -1

        self.setup_ui()
        self.bind_events()
        
    def setup_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x', side='top', pady=(0, 5))
        
        ttk.Label(toolbar, text="Go to offset (hex or decimal):").pack(side='left')
        self.goto_var = tk.StringVar()
        self.goto_entry = ttk.Entry(toolbar, textvariable=self.goto_var, width=12)
        self.goto_entry.pack(side='left', padx=5)
        self.goto_entry.bind('<Return>', self.goto_offset)
        ttk.Button(toolbar, text="Go", command=self.goto_offset).pack(side='left')
        
        self.status_label = ttk.Label(toolbar, text="Offset: 0x00000000")
        self.status_label.pack(side='right')

        toolbar2 = ttk.Frame(self)
        toolbar2.pack(fill='x', side='top', pady=(0, 5))
        ttk.Label(toolbar2, text="Search:").pack(side='left')
        self.search_var = tk.StringVar()
        ttk.Entry(toolbar2, textvariable=self.search_var, width=28).pack(side='left', padx=4)
        self.search_mode_var = tk.StringVar(value="hex")
        ttk.Combobox(
            toolbar2,
            textvariable=self.search_mode_var,
            values=("hex", "ascii"),
            width=7,
            state="readonly",
        ).pack(side='left', padx=4)
        ttk.Button(toolbar2, text="Find Next", command=self.search_next).pack(side='left')
        ttk.Label(toolbar2, text="(Ctrl+Z undo byte edit)", font=("TkDefaultFont", 8)).pack(side='right')

        self.canvas_frame = ttk.Frame(self)
        self.canvas_frame.pack(fill='both', expand=True)
        
        self.scrollbar = ttk.Scrollbar(self.canvas_frame, orient='vertical', command=self.on_scrollbar)
        self.scrollbar.pack(side='right', fill='y')
        
        self.canvas = tk.Canvas(self.canvas_frame, bg='white', cursor="xterm")
        self.canvas.pack(side='left', fill='both', expand=True)
        
    def bind_events(self):
        self.canvas.bind("<Configure>", self.on_resize)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel_linux)
        self.canvas.bind("<Button-5>", self.on_mousewheel_linux)
        
        self.canvas.bind("<Key>", self.on_key)
        self.canvas.bind("<Up>", lambda e: self.move_cursor(-self.bytes_per_row))
        self.canvas.bind("<Down>", lambda e: self.move_cursor(self.bytes_per_row))
        self.canvas.bind("<Left>", lambda e: self.move_cursor(-1, change_nibble=True))
        self.canvas.bind("<Right>", lambda e: self.move_cursor(1, change_nibble=True))
        self.canvas.bind("<Prior>", lambda e: self.move_cursor(-self.visible_lines * self.bytes_per_row))
        self.canvas.bind("<Next>", lambda e: self.move_cursor(self.visible_lines * self.bytes_per_row))
        self.canvas.bind("<Control-z>", self.undo_edit)
        self.canvas.bind("<Control-Z>", self.undo_edit)

    def undo_edit(self, event=None):
        if not self._undo_stack or self.cia_data is None:
            return "break"
        pos, old_byte = self._undo_stack.pop()
        self.cia_data[pos] = old_byte & 0xFF
        self.cursor_pos = pos
        self.cursor_nibble = 0
        if self.on_edit_callback:
            self.on_edit_callback()
        self.redraw()
        return "break"

    def _parse_search_hex(self, s: str) -> bytes | None:
        s = re.sub(r"\s+", "", s)
        if len(s) % 2 != 0 or not re.fullmatch(r"[0-9A-Fa-f]*", s):
            return None
        try:
            return bytes(int(s[i : i + 2], 16) for i in range(0, len(s), 2))
        except ValueError:
            return None

    def search_next(self):
        if self.cia_data is None:
            return
        raw = self.search_var.get().strip()
        if not raw:
            messagebox.showwarning("Search", "Enter a search string.")
            return
        mode = self.search_mode_var.get().lower()
        if mode == "ascii":
            needle = raw.encode("utf-8", errors="replace")
        else:
            needle = self._parse_search_hex(raw)
            if needle is None:
                messagebox.showerror("Search", "Invalid hex — use pairs like 00 01 FF.")
                return
        if not needle:
            return
        data = bytes(self.cia_data)
        start = self._search_last_idx + 1 if self._search_last_idx >= 0 else self.cursor_pos + 1
        if start >= len(data):
            start = 0
        pos = data.find(needle, start)
        if pos < 0 and start > 0:
            pos = data.find(needle, 0)
        if pos < 0:
            messagebox.showinfo("Search", "Not found.")
            self._search_last_idx = -1
            return
        self._search_last_idx = pos
        self.cursor_pos = pos
        self.cursor_nibble = 0
        target_line = pos // self.bytes_per_row
        if target_line < self.top_line_index or target_line >= self.top_line_index + self.visible_lines:
            self.top_line_index = max(0, target_line - self.visible_lines // 2)
            self.clamp_scroll()
            self.update_scrollbar()
        self.redraw()
        self.canvas.focus_set()

    def load_data(self, data):
        self.cia_data = data
        if self.cia_data is None:
            self.total_lines = 0
            self.canvas.delete("all")
            return
            
        self.total_lines = (len(self.cia_data) + self.bytes_per_row - 1) // self.bytes_per_row
        self.top_line_index = 0
        self.cursor_pos = 0
        self.cursor_nibble = 0
        self._undo_stack.clear()
        self._search_last_idx = -1
        self.update_scrollbar()
        self.redraw()
        self.canvas.focus_set()

    def on_resize(self, event):
        self.char_height = 16
        self.char_width = 8
        self.visible_lines = event.height // self.char_height
        self.update_scrollbar()
        self.redraw()

    def update_scrollbar(self):
        if self.total_lines <= 0:
            self.scrollbar.set(0, 1)
            return
            
        fraction_visible = self.visible_lines / self.total_lines
        if fraction_visible >= 1.0:
            self.scrollbar.set(0, 1)
        else:
            top_fraction = self.top_line_index / self.total_lines
            bottom_fraction = min(1.0, (self.top_line_index + self.visible_lines) / self.total_lines)
            self.scrollbar.set(top_fraction, bottom_fraction)

    def on_scrollbar(self, *args):
        if self.total_lines <= 0:
            return
        
        if args[0] == 'moveto':
            fraction = float(args[1])
            self.top_line_index = int(fraction * self.total_lines)
        elif args[0] == 'scroll':
            units = int(args[1])
            if args[2] == 'pages':
                self.top_line_index += units * max(1, self.visible_lines - 1)
            elif args[2] == 'units':
                self.top_line_index += units
                
        self.clamp_scroll()
        self.update_scrollbar()
        self.redraw()

    def clamp_scroll(self):
        max_top = max(0, self.total_lines - self.visible_lines)
        if self.top_line_index > max_top:
            self.top_line_index = max_top
        if self.top_line_index < 0:
            self.top_line_index = 0

    def on_mousewheel(self, event):
        if self.total_lines <= 0:
            return
        delta = -1 if event.delta > 0 else 1
        self.top_line_index += delta * 3
        self.clamp_scroll()
        self.update_scrollbar()
        self.redraw()

    def on_mousewheel_linux(self, event):
        if self.total_lines <= 0:
            return
        delta = -1 if event.num == 4 else 1
        self.top_line_index += delta * 3
        self.clamp_scroll()
        self.update_scrollbar()
        self.redraw()

    def goto_offset(self, event=None):
        if self.cia_data is None:
            return
        val = self.goto_var.get().strip()
        try:
            if val.lower().startswith("0x"):
                offset = int(val, 16)
            elif val.isdigit():
                offset = int(val, 10)
            else:
                offset = int(val, 16)

            if offset < 0:
                offset = 0
            if offset >= len(self.cia_data):
                offset = len(self.cia_data) - 1

            self.cursor_pos = offset
            self.cursor_nibble = 0

            target_line = offset // self.bytes_per_row
            if target_line < self.top_line_index or target_line >= self.top_line_index + self.visible_lines:
                self.top_line_index = max(0, target_line - self.visible_lines // 2)
                self.clamp_scroll()
                self.update_scrollbar()

            self.redraw()
            self.canvas.focus_set()
        except ValueError:
            messagebox.showerror(
                "Invalid Offset",
                "Enter a hex offset (e.g. 0x1000 or 1000) or a decimal number.",
            )

    def on_click(self, event):
        self.canvas.focus_set()
        if self.cia_data is None:
            return
        
        line_click = event.y // self.char_height
        target_line = self.top_line_index + line_click
        
        if target_line >= self.total_lines:
            return
            
        x = event.x
        
        offset_w = self.offset_chars * self.char_width
        space_w = 2 * self.char_width
        
        hex_start_x = offset_w + space_w
        hex_end_x = hex_start_x + self.hex_chars * self.char_width
        
        ascii_start_x = hex_end_x + space_w
        
        byte_index = -1
        nibble = 0
        
        if hex_start_x <= x <= hex_end_x:
            rel_x = x - hex_start_x
            char_idx = int(rel_x / self.char_width)
            
            byte_in_row = char_idx // 3
            if byte_in_row >= self.bytes_per_row:
                byte_in_row = self.bytes_per_row - 1
                
            char_in_byte = char_idx % 3
            if char_in_byte == 2:
                nibble = 0
            else:
                nibble = char_in_byte
                
            byte_index = target_line * self.bytes_per_row + byte_in_row
            
        elif x >= ascii_start_x:
            rel_x = x - ascii_start_x
            byte_in_row = int(rel_x / self.char_width)
            if byte_in_row >= self.bytes_per_row:
                byte_in_row = self.bytes_per_row - 1
            
            byte_index = target_line * self.bytes_per_row + byte_in_row
            nibble = 0
            
        if byte_index >= 0 and byte_index < len(self.cia_data):
            self.cursor_pos = byte_index
            self.cursor_nibble = nibble
            self.redraw()

    def move_cursor(self, delta_bytes, change_nibble=False):
        if self.cia_data is None:
            return
        
        if change_nibble:
            if delta_bytes > 0:
                if self.cursor_nibble == 0:
                    self.cursor_nibble = 1
                else:
                    self.cursor_nibble = 0
                    self.cursor_pos += 1
            else:
                if self.cursor_nibble == 1:
                    self.cursor_nibble = 0
                else:
                    self.cursor_nibble = 1
                    self.cursor_pos -= 1
        else:
            self.cursor_pos += delta_bytes
            
        if self.cursor_pos < 0:
            self.cursor_pos = 0
            self.cursor_nibble = 0
        elif self.cursor_pos >= len(self.cia_data):
            self.cursor_pos = len(self.cia_data) - 1
            self.cursor_nibble = 1
            
        cursor_line = self.cursor_pos // self.bytes_per_row
        if cursor_line < self.top_line_index:
            self.top_line_index = cursor_line
            self.update_scrollbar()
        elif cursor_line >= self.top_line_index + self.visible_lines:
            self.top_line_index = cursor_line - self.visible_lines + 1
            self.update_scrollbar()
            
        self.redraw()

    def on_key(self, event):
        if self.cia_data is None:
            return
        if (event.state & 0x4) and event.keysym.lower() == "z":
            return

        char = event.char.upper()
        if char in '0123456789ABCDEF':
            val = int(char, 16)
            current_byte = self.cia_data[self.cursor_pos]
            self._undo_stack.append((self.cursor_pos, current_byte))
            if len(self._undo_stack) > self._undo_max:
                self._undo_stack.pop(0)

            if self.cursor_nibble == 0:
                new_byte = (val << 4) | (current_byte & 0x0F)
                self.cia_data[self.cursor_pos] = new_byte
                self.cursor_nibble = 1
            else:
                new_byte = (current_byte & 0xF0) | val
                self.cia_data[self.cursor_pos] = new_byte
                self.cursor_nibble = 0
                self.move_cursor(1)

            if self.on_edit_callback:
                self.on_edit_callback()

            self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        if self.cia_data is None:
            return
        
        end_line = min(self.total_lines, self.top_line_index + self.visible_lines + 1)
        
        y = 0
        for line_idx in range(self.top_line_index, end_line):
            start_idx = line_idx * self.bytes_per_row
            end_idx = min(start_idx + self.bytes_per_row, len(self.cia_data))
            
            chunk = self.cia_data[start_idx:end_idx]
            
            offset_str = f"{start_idx:08X}"
            self.canvas.create_text(5, y, anchor='nw', text=offset_str, font=self.font, fill='blue')
            
            hex_x = 5 + (self.offset_chars + 2) * self.char_width
            for i, b in enumerate(chunk):
                bx = hex_x + (i * 3) * self.char_width
                byte_idx = start_idx + i
                
                if byte_idx == self.cursor_pos:
                    bg_x = bx
                    if self.cursor_nibble == 1:
                        bg_x += self.char_width
                        
                    self.canvas.create_rectangle(
                        bg_x, y, 
                        bg_x + self.char_width, y + self.char_height,
                        fill='black'
                    )
                    
                    char_high = f"{(b >> 4) & 0xF:X}"
                    char_low = f"{b & 0xF:X}"
                    
                    fill_high = 'white' if self.cursor_nibble == 0 else 'black'
                    fill_low = 'white' if self.cursor_nibble == 1 else 'black'
                    
                    self.canvas.create_text(bx, y, anchor='nw', text=char_high, font=self.font, fill=fill_high)
                    self.canvas.create_text(bx + self.char_width, y, anchor='nw', text=char_low, font=self.font, fill=fill_low)
                    
                else:
                    self.canvas.create_text(bx, y, anchor='nw', text=f"{b:02X}", font=self.font, fill='black')
            
            ascii_x = hex_x + (self.hex_chars + 2) * self.char_width
            ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
            
            for i, char in enumerate(ascii_str):
                ax = ascii_x + i * self.char_width
                byte_idx = start_idx + i
                if byte_idx == self.cursor_pos:
                    self.canvas.create_rectangle(ax, y, ax + self.char_width, y + self.char_height, fill='lightgray', outline='')
                self.canvas.create_text(ax, y, anchor='nw', text=char, font=self.font, fill='darkgreen')
                
            y += self.char_height
            
        self.status_label.config(text=f"Offset: 0x{self.cursor_pos:08X}")


class OpenHaxApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"OpenHax v{__version__} by a.c")
        self.root.geometry("900x640")
        self.root.minsize(600, 400)
        
        self.loaded_cia_path = None
        self.texture_pack_path = None
        self.codebin_path = None
        self.romfs_root_path = None
        self.cia_data = None
        self.cia_meta: dict = {}
        self.last_compiled_payload = b""
        self.edits_made = False

        # CIA deep extract (pyctr) — temp workspace
        self._cia_work_dir: Path | None = None
        self._romfs_dir: Path | None = None
        self._exefs_dir: Path | None = None
        self._code_bin_extracted: Path | None = None
        self._cia_blob_backup: bytearray | None = None
        self._deep_info: dict = {}
        self.hex_context: dict = {"kind": "cia", "path": None}
        self.structure_pending = False
        self._extract_in_progress = False

        style = ttk.Style()
        style.theme_use('clam')
        
        self.create_menu()
        self.create_notebook()
        self.create_statusbar()
        self.refresh_status_bar()

    def _on_asm_key_release(self, _event=None):
        self._highlight_asm_region("1.0", tk.END)

    def _highlight_asm_region(self, start, end):
        text = self.asm_text
        for tag in ("comment", "directive", "keyword"):
            text.tag_remove(tag, start, end)
        blob = text.get(start, end)
        arm_kw = frozenset(
            "mov mvn add adc sub sbc rsb rsc mul mla umull umlal smull smlal "
            "and orr eor bic lsl lsr asr ror cmp cmn tst teq str ldr ldrb strb "
            "ldrh strh ldrsh push pop stm ldm b bl bx nop"
            .split()
        )
        idx = "1.0"
        for line in blob.splitlines(keepends=True):
            line_end = text.index(f"{idx} + {len(line)} chars")
            stripped = line.lstrip()
            lead = len(line) - len(stripped)
            if stripped.startswith(";"):
                text.tag_add("comment", idx, line_end)
            elif stripped.startswith("."):
                first = stripped.split(None, 1)[0]
                d0 = text.index(f"{idx} + {lead} chars")
                d1 = text.index(f"{d0} + {len(first)} chars")
                text.tag_add("directive", d0, d1)
            else:
                for tok in stripped.replace(",", " ").split():
                    low = tok.strip().lower()
                    if low in arm_kw:
                        p = stripped.lower().find(low)
                        if p >= 0:
                            k0 = text.index(f"{idx} + {lead + p} chars")
                            k1 = text.index(f"{k0} + {len(low)} chars")
                            text.tag_add("keyword", k0, k1)
                        break
            idx = line_end

    def refresh_status_bar(self):
        k = _dep_keystone()
        p = _dep_pyctr()
        cs = _dep_capstone()
        dep = (
            f"Keystone:{'OK' if k else 'Missing'} | pyctr:{'OK' if p else 'Missing'} | "
            f"Capstone:{'OK' if cs else 'Missing'}"
        )
        if self.cia_data is None:
            self.status_var.set(f"Ready | OpenHax v{__version__} by a.c | {dep}")
            return
        name = os.path.basename(self.loaded_cia_path) if self.loaded_cia_path else "(unsaved buffer)"
        mod = " [MODIFIED]" if self.edits_made else ""
        tid = ""
        if self.cia_meta.get("title_id"):
            tid = f" | TID {self.cia_meta['title_id']}"
            if self.cia_meta.get("title_version") is not None:
                tid += f" v{self.cia_meta['title_version']}"
        err = ""
        if self.cia_meta.get("error"):
            emsg = str(self.cia_meta["error"])
            err = f" | CIA parse: {emsg[:40]}…" if len(emsg) > 40 else f" | CIA parse: {emsg}"
        staged = ""
        if getattr(self, "structure_pending", False):
            staged = " | Staged: PENDING (export bundle)"
        self.status_var.set(
            f"Loaded: {name} ({len(self.cia_data):,} bytes){tid}{mod}{staged}{err} | {dep}"
        )

    def create_menu(self):
        menubar = tk.Menu(self.root)
        
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open File…", command=self.open_cia)
        file_menu.add_command(label="Save As…", command=self.save_cia)
        file_menu.add_command(label="Export CIA modification bundle…", command=self.export_mod_bundle)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="User Guide", command=self.show_user_guide)
        help_menu.add_command(label="Roadmap (embedded)", command=self.show_roadmap)
        help_menu.add_command(label="Pip requirements (embedded)", command=self.show_pip_requirements)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        
        self.root.config(menu=menubar)

    def create_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill='both', padx=10, pady=10)

        self.tab_hex = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_hex, text="Hex Editor")
        self.setup_hex_editor_tab()

        self.tab_structure = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_structure, text="CIA Structure")
        self.setup_cia_structure_tab()

        self.tab_asm = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_asm, text="ARM ASM Writer")
        self.setup_asm_tab()

        self.tab_texture = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_texture, text="Apply Texture Pack")
        self.setup_texture_tab()

        self.tab_disasm = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_disasm, text="Disassembler (Capstone)")
        self.setup_disasm_tab()

    def setup_hex_editor_tab(self):
        top = ttk.Frame(self.tab_hex)
        top.pack(fill="x", padx=5, pady=(4, 0))
        self.hex_view_label = ttk.Label(top, text="Viewing: CIA binary (full file)")
        self.hex_view_label.pack(side="left")
        ttk.Button(top, text="Back to CIA binary", command=self.back_to_cia_binary).pack(side="right")

        self.hex_editor = HexEditorFrame(self.tab_hex, on_edit_callback=self.on_hex_edit)
        self.hex_editor.pack(expand=True, fill='both', padx=5, pady=5)

    def setup_cia_structure_tab(self):
        outer = ttk.Frame(self.tab_structure)
        outer.pack(fill="both", expand=True, padx=6, pady=6)

        self.structure_status_var = tk.StringVar(value="Open a decrypted .cia to extract RomFS/ExeFS.")
        ttk.Label(outer, textvariable=self.structure_status_var, wraplength=860).pack(anchor="w", pady=(0, 6))

        self.structure_pending_var = tk.StringVar(value="Changes pending: none")
        ttk.Label(outer, textvariable=self.structure_pending_var, foreground="#a05000").pack(anchor="w", pady=(0, 8))

        paned = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True)

        lf_rom = ttk.LabelFrame(paned, text="RomFS (extracted)")
        paned.add(lf_rom, weight=2)
        rom_wrap = ttk.Frame(lf_rom)
        rom_wrap.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree_romfs = ttk.Treeview(rom_wrap, columns=("size",), displaycolumns=("size",), height=18)
        self.tree_romfs.heading("#0", text="Path", anchor="w")
        self.tree_romfs.heading("size", text="Size")
        self.tree_romfs.column("#0", width=320, minwidth=80)
        self.tree_romfs.column("size", width=90, anchor="e")
        rsb = ttk.Scrollbar(rom_wrap, orient="vertical", command=self.tree_romfs.yview)
        self.tree_romfs.configure(yscrollcommand=rsb.set)
        self.tree_romfs.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")
        self.tree_romfs.bind("<Double-1>", self._on_romfs_tree_double)
        self._romfs_menu = tk.Menu(self.tree_romfs, tearoff=0)
        self._romfs_menu.add_command(label="Open in Hex Editor", command=self._romfs_menu_open_hex)
        self._romfs_menu.add_command(label="Replace file…", command=self._romfs_menu_replace)
        self.tree_romfs.bind("<Button-3>", self._on_romfs_tree_rightclick)

        lf_exe = ttk.LabelFrame(paned, text="ExeFS (extracted)")
        paned.add(lf_exe, weight=1)
        exe_wrap = ttk.Frame(lf_exe)
        exe_wrap.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree_exefs = ttk.Treeview(exe_wrap, columns=("size",), displaycolumns=("size",), height=18)
        self.tree_exefs.heading("#0", text="Entry", anchor="w")
        self.tree_exefs.heading("size", text="Size")
        self.tree_exefs.column("#0", width=140, minwidth=60)
        self.tree_exefs.column("size", width=90, anchor="e")
        esb = ttk.Scrollbar(exe_wrap, orient="vertical", command=self.tree_exefs.yview)
        self.tree_exefs.configure(yscrollcommand=esb.set)
        self.tree_exefs.pack(side="left", fill="both", expand=True)
        esb.pack(side="right", fill="y")
        self.tree_exefs.bind("<Double-1>", self._on_exefs_tree_double)

        row = ttk.Frame(outer)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Refresh trees", command=self.refresh_structure_trees).pack(side="left")

    def setup_asm_tab(self):
        frame = ttk.Frame(self.tab_asm)
        frame.pack(expand=True, fill='both', padx=5, pady=5)
        
        lbl_info = ttk.Label(frame, text="Write ARM Assembly (3DS Architecture - ARM11):")
        lbl_info.pack(anchor='w')

        self.asm_text = tk.Text(frame, font=("Courier", 11), undo=True)
        self.asm_text.pack(expand=True, fill='both', pady=5)
        self.asm_text.configure(
            insertbackground="black",
            selectbackground="#316AC5",
            selectforeground="white",
        )
        self.asm_text.tag_configure("comment", foreground="#008000")
        self.asm_text.tag_configure("directive", foreground="#800080")
        self.asm_text.tag_configure("keyword", foreground="#0000CC", font=("Courier", 11, "bold"))
        self.asm_text.bind("<KeyRelease>", self._on_asm_key_release)
        
        default_asm = "; OpenHax ARM ASM Payload\n; Target: 3DS (.cia ExeFS/.text section)\n\n.text\n.global _start\n\n_start:\n    MOV R0, #1\n    MOV R1, #0\n    BX LR\n"
        self.asm_text.insert('1.0', default_asm)
        self._highlight_asm_region("1.0", tk.END)

        btn_frame = ttk.Frame(self.tab_asm)
        btn_frame.pack(fill='x', padx=5, pady=5)
        self.asm_mode_var = tk.StringVar(value="ARM")
        ttk.Label(btn_frame, text="Mode:").pack(side='left', padx=(0, 4))
        ttk.Combobox(
            btn_frame,
            textvariable=self.asm_mode_var,
            values=("ARM", "THUMB"),
            width=8,
            state="readonly"
        ).pack(side='left', padx=(0, 10))
        
        ttk.Button(btn_frame, text="Compile ASM to Hex", command=self.compile_asm).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Inject into ExeFS code.bin", command=self.inject_asm).pack(side='left')

        target_frame = ttk.LabelFrame(self.tab_asm, text="ExeFS Injection Target")
        target_frame.pack(fill='x', padx=5, pady=(0, 5))

        row1 = ttk.Frame(target_frame)
        row1.pack(fill='x', padx=5, pady=5)
        ttk.Label(row1, text="code.bin path:").pack(side='left')
        self.codebin_entry = ttk.Entry(row1, state='readonly')
        self.codebin_entry.pack(side='left', expand=True, fill='x', padx=6)
        ttk.Button(row1, text="Browse...", command=self.browse_codebin).pack(side='left')
        ttk.Button(row1, text="Load code.bin from current CIA", command=self.load_codebin_from_cia).pack(side='left', padx=(8, 0))

        row2 = ttk.Frame(target_frame)
        row2.pack(fill='x', padx=5, pady=(0, 6))
        ttk.Label(row2, text="Patch offset (hex):").pack(side='left')
        self.codebin_offset_var = tk.StringVar(value="0x0")
        ttk.Entry(row2, textvariable=self.codebin_offset_var, width=14).pack(side='left', padx=6)

    def setup_texture_tab(self):
        frame = ttk.Frame(self.tab_texture)
        frame.pack(expand=True, fill='both', padx=20, pady=20)
        
        ttk.Label(
            frame,
            text="Texture pack (folder or .zip) merges into the loaded CIA's extracted RomFS when available:",
            wraplength=720,
        ).pack(anchor='w', pady=(0, 5))
        
        path_frame = ttk.Frame(frame)
        path_frame.pack(fill='x')
        
        self.txt_texture_path = ttk.Entry(path_frame, state='readonly')
        self.txt_texture_path.pack(side='left', expand=True, fill='x', padx=(0, 5))
        
        ttk.Button(path_frame, text="Browse...", command=self.browse_texture).pack(side='left')
        
        ttk.Label(frame, text="Target Title ID (Optional):").pack(anchor='w', pady=(15, 5))
        self.txt_title_id = ttk.Entry(frame)
        self.txt_title_id.pack(fill='x')

        ttk.Label(frame, text="Optional extracted RomFS root (for direct patch):").pack(anchor='w', pady=(15, 5))
        romfs_frame = ttk.Frame(frame)
        romfs_frame.pack(fill='x')
        self.txt_romfs_root = ttk.Entry(romfs_frame, state='readonly')
        self.txt_romfs_root.pack(side='left', expand=True, fill='x', padx=(0, 5))
        ttk.Button(romfs_frame, text="Browse...", command=self.browse_romfs_root).pack(side='left')

        ttk.Button(frame, text="Apply Texture Pack to loaded .CIA", command=self.apply_texture).pack(pady=12)
        ttk.Button(
            frame,
            text="Export LayeredFS (luma/titles/<TitleID>/romfs/)",
            command=self.export_layeredfs,
        ).pack(pady=(0, 8))

    def setup_disasm_tab(self):
        frame = ttk.Frame(self.tab_disasm)
        frame.pack(expand=True, fill="both", padx=8, pady=8)
        ttk.Label(
            frame,
            text="Disassemble the last compiled ARM payload (Capstone). Install: pip install capstone",
            wraplength=820,
        ).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Disassemble compiled payload", command=self.disassemble_payload).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Clear", command=lambda: self.disasm_text.delete("1.0", tk.END)).pack(side="left")
        self.disasm_text = scrolledtext.ScrolledText(frame, height=22, font=("Courier", 10), wrap=tk.NONE)
        self.disasm_text.pack(expand=True, fill="both")

    def disassemble_payload(self):
        if not self.last_compiled_payload:
            messagebox.showwarning("Disassembler", "Compile ASM first (ARM ASM Writer tab).")
            return
        if not _dep_capstone():
            messagebox.showerror(
                "Capstone missing",
                "Install Capstone for disassembly:\n\npip install capstone",
            )
            return
        try:
            from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

            mode = self.asm_mode_var.get().upper()
            arm_mode = CS_MODE_THUMB if mode == "THUMB" else CS_MODE_ARM
            md = Cs(CS_ARCH_ARM, arm_mode)
            lines = []
            for insn in md.disasm(self.last_compiled_payload, 0):
                lines.append(f"{insn.address:04x}:  {insn.mnemonic} {insn.op_str}")
            self.disasm_text.delete("1.0", tk.END)
            self.disasm_text.insert("1.0", "\n".join(lines) if lines else "(no instructions)")
        except Exception as e:
            messagebox.showerror("Disassembly Error", str(e))

    def export_layeredfs(self):
        tid = (self.txt_title_id.get().strip() or self.cia_meta.get("title_id") or "").replace(" ", "")
        if not re.fullmatch(r"[0-9A-Fa-f]{16}", tid):
            messagebox.showerror(
                "Title ID",
                "Enter a 16-digit hex Title ID (from metadata or manual), or load a decrypted CIA.",
            )
            return
        if not self.texture_pack_path:
            messagebox.showerror("Texture pack", "Select a texture folder or ZIP first.")
            return
        out_base = filedialog.askdirectory(title="Select folder to create luma/titles/… under")
        if not out_base:
            return
        romfs_root = Path(out_base) / "luma" / "titles" / tid.upper() / "romfs"
        try:
            romfs_root.mkdir(parents=True, exist_ok=True)
            src = Path(self.texture_pack_path)
            if src.is_file() and src.suffix.lower() == ".zip":
                with zipfile.ZipFile(src, "r") as zf:
                    zf.extractall(romfs_root)
            elif src.is_dir():
                for item in src.rglob("*"):
                    if item.is_file():
                        rel = item.relative_to(src)
                        dest = romfs_root / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest)
            else:
                raise ValueError("Invalid texture source")
            messagebox.showinfo("LayeredFS", f"Exported to:\n{romfs_root}")
            self.status_var.set(f"LayeredFS → {romfs_root}")
        except Exception as e:
            messagebox.showerror("LayeredFS Export", str(e))

    def create_statusbar(self):
        self.status_var = tk.StringVar()
        self.status_var.set(f"Ready | OpenHax v{__version__} by a.c")
        self.statusbar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)

    def show_user_guide(self):
        guide = tk.Toplevel(self.root)
        guide.title("OpenHax — User Guide")
        guide.geometry("720x520")
        guide.minsize(500, 360)
        txt = scrolledtext.ScrolledText(guide, wrap=tk.WORD, font=("Courier", 10), padx=8, pady=8)
        txt.pack(fill="both", expand=True)
        txt.insert(
            "1.0",
            f"""OpenHax v{__version__} — 3DS Hacking Suite (a.c)

DOCUMENTATION
  Roadmap and pip package list are embedded in this .py file (no separate .md).
  Help → Roadmap (embedded)  |  Help → Pip requirements (embedded)

REQUIREMENTS
  • pyctr is required to launch the main app (CIA Title ID / metadata).
  • keystone-engine: ARM/THUMB assembly compile.
  • capstone: disassembler tab.
  • Pillow / customtkinter: optional (installer can add them for future UI).

CIA STRUCTURE (after opening a .cia)
  • RomFS + ExeFS extracted to a temp folder; treeviews list files.
  • Double-click a file to open it in the hex editor; right-click RomFS file → Replace.
  • “Load code.bin from current CIA” on the ASM tab targets extracted ExeFS .code.

HEX EDITOR
  • Virtual rows, nibble edit, Ctrl+Z undo (per-byte stack).
  • “Back to CIA binary” returns from a RomFS/ExeFS file view.
  • Save As: writes the current buffer (RomFS/ExeFS file or raw CIA). Staged changes → export bundle.

ARM / EXeFS
  • Compile then inject into .code (in-place if using extracted ExeFS).

TEXTURES / LAYEREDFS
  • Apply pack merges into extracted RomFS when present; check “Changes pending” on CIA Structure.
  • Export LayeredFS → luma/titles/<TitleID>/romfs/ for Luma3DS.
  • File → Export modification bundle — original.cia + romfs/ + exefs/ for makerom/ctrtool.

Legal homebrew / dumps you own. Encrypted CIAs: decrypt with GodMode9 first.
""",
        )
        txt.configure(state="disabled")
        ttk.Button(guide, text="Close", command=guide.destroy).pack(pady=6)

    def show_roadmap(self):
        win = tk.Toplevel(self.root)
        win.title("OpenHax — Roadmap (embedded in source)")
        win.geometry("820x620")
        t = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Courier", 9), padx=8, pady=8)
        t.pack(fill="both", expand=True)
        t.insert("1.0", EMBEDDED_ROADMAP)
        t.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=6)

    def show_pip_requirements(self):
        win = tk.Toplevel(self.root)
        win.title("OpenHax — Pip requirements (embedded)")
        win.geometry("640x420")
        t = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Courier", 10), padx=8, pady=8)
        t.pack(fill="both", expand=True)
        t.insert(
            "1.0",
            EMBEDDED_PIP_REQUIREMENTS
            + "\n---\nOne-liner (console):\n"
            + EMBEDDED_PIP_INSTALL_LINE
            + "\n",
        )
        t.configure(state="normal")

        def _copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(EMBEDDED_PIP_INSTALL_LINE)
            self.root.update()
            messagebox.showinfo("Clipboard", "Copied pip install line to clipboard.", parent=win)

        row = ttk.Frame(win)
        row.pack(fill="x", pady=(0, 6))
        ttk.Button(row, text="Copy install line", command=_copy).pack(side="left", padx=8)
        ttk.Button(row, text="Close", command=win.destroy).pack(side="right", padx=8)

    def show_about(self):
        messagebox.showinfo(
            "About OpenHax",
            f"OpenHax v{__version__}\nCreated by a.c\n\n"
            "3DS hacking suite: virtualized hex editor, ARM/THUMB compile (Keystone),\n"
            "ExeFS code.bin patching, texture staging / RomFS overlay, dependency wizard."
        )

    def open_cia(self):
        filepath = filedialog.askopenfilename(
            title="Open file (CIA, CCI, CXI, or raw binary)",
            filetypes=(
                ("All supported", "*.cia *.3ds *.cci *.cxi *.cfa *.bin *.romfs *.exefs"),
                ("CIA", "*.cia"),
                ("3DS / CCI", "*.3ds *.cci"),
                ("CXI / CFA", "*.cxi *.cfa"),
                ("Binary / dumps", "*.bin"),
                ("All files", "*.*"),
            ),
        )
        if filepath:
            self._cleanup_cia_session()
            self.loaded_cia_path = filepath
            self.cia_meta = {}
            try:
                with open(filepath, "rb") as f:
                    self.cia_data = bytearray(f.read())
                if len(self.cia_data) > 100 * 1024 * 1024:
                    messagebox.showwarning(
                        "Large file",
                        "This file is over 100 MB.\n"
                        "Editing is fully in RAM; future versions may use mmap for speed.",
                    )
                low = filepath.lower()
                if low.endswith(".cia"):
                    self.cia_meta = parse_cia_metadata(filepath)
                    if self.cia_meta.get("title_id"):
                        self.txt_title_id.config(state="normal")
                        self.txt_title_id.delete(0, tk.END)
                        self.txt_title_id.insert(0, self.cia_meta["title_id"])
                        self.txt_title_id.config(state="normal")
                    if self.cia_meta.get("error"):
                        msg = f"Could not parse CIA metadata:\n{self.cia_meta['error']}"
                        if self.cia_meta.get("hint"):
                            msg += f"\n\n{self.cia_meta['hint']}"
                        messagebox.showwarning("CIA metadata", msg)
                self.edits_made = False
                self._cia_blob_backup = bytearray(self.cia_data)
                self.hex_context = {"kind": "cia", "path": filepath}
                self.hex_view_label.config(text="Viewing: CIA binary (full file)")
                self.hex_editor.load_data(self.cia_data)
                self.refresh_status_bar()
                if low.endswith(".cia") and _dep_pyctr():
                    self._start_cia_deep_extract(filepath)
            except Exception as e:
                self.cia_data = None
                self.cia_meta = {}
                self._cia_blob_backup = None
                self.hex_editor.load_data(None)
                messagebox.showerror("Error", f"Failed to open file:\n{e}")

    def on_hex_edit(self):
        self.edits_made = True
        k = self.hex_context.get("kind", "cia")
        if k in ("romfs", "exefs"):
            self.structure_pending = True
            self.structure_pending_var.set(
                "Changes pending: staged RomFS/ExeFS differ from original CIA — use Export bundle to repack."
            )
        self.refresh_status_bar()

    def _cleanup_cia_session(self) -> None:
        if self._cia_work_dir and Path(self._cia_work_dir).exists():
            try:
                shutil.rmtree(self._cia_work_dir, ignore_errors=True)
            except OSError:
                pass
        self._cia_work_dir = None
        self._romfs_dir = None
        self._exefs_dir = None
        self._code_bin_extracted = None
        self._deep_info = {}
        self._extract_in_progress = False
        self.structure_pending = False
        try:
            self.structure_pending_var.set("Changes pending: none")
        except Exception:
            pass
        try:
            self.tree_romfs.delete(*self.tree_romfs.get_children())
            self.tree_exefs.delete(*self.tree_exefs.get_children())
        except Exception:
            pass

    def _start_cia_deep_extract(self, cia_path: str) -> None:
        if not _dep_pyctr():
            return
        self._extract_in_progress = True
        self.structure_status_var.set("Extracting RomFS/ExeFS (background)…")

        def worker() -> None:
            try:
                work = Path(tempfile.mkdtemp(prefix="openhax_cia_"))
                info = extract_cia_structure(cia_path, work)
                self.root.after(0, lambda w=work, i=info: self._on_deep_extract_done(w, i))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self._on_deep_extract_fail(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_deep_extract_done(self, work: Path, info: dict) -> None:
        self._extract_in_progress = False
        self._cia_work_dir = work
        self._romfs_dir = info.get("romfs_dir")
        self._exefs_dir = info.get("exefs_dir")
        cb = info.get("code_bin_path")
        self._code_bin_extracted = Path(cb) if cb else None
        self._deep_info = info
        lines = []
        if info.get("title_name"):
            lines.append(f"Title: {info['title_name']}")
        if info.get("product_code"):
            lines.append(f"Product code: {info['product_code']}")
        if info.get("program_id"):
            lines.append(f"Program ID: {info['program_id']}")
        lines.append(f"Primary NCCH index: {info.get('primary_ncch')}")
        lines.append(f"RomFS files extracted: {info.get('romfs_file_count', 0)}")
        if info.get("romfs_error"):
            lines.append(f"RomFS: {info['romfs_error']}")
        if info.get("exefs_error"):
            lines.append(f"ExeFS: {info['exefs_error']}")
        self.structure_status_var.set("\n".join(lines))
        self.refresh_structure_trees()
        if self._romfs_dir:
            self.txt_romfs_root.config(state="normal")
            self.txt_romfs_root.delete(0, tk.END)
            self.txt_romfs_root.insert(0, str(self._romfs_dir))
            self.txt_romfs_root.config(state="readonly")
            self.romfs_root_path = str(self._romfs_dir)
        if self._code_bin_extracted and self._code_bin_extracted.is_file():
            self.load_codebin_from_cia()

    def _on_deep_extract_fail(self, msg: str) -> None:
        self._extract_in_progress = False
        self.structure_status_var.set(f"CIA deep extract failed:\n{msg}")

    def refresh_structure_trees(self) -> None:
        try:
            self.tree_romfs.delete(*self.tree_romfs.get_children())
            self.tree_exefs.delete(*self.tree_exefs.get_children())
        except Exception:
            return
        if self._romfs_dir and self._romfs_dir.is_dir():
            self._fill_romfs_tree(self._romfs_dir)
            try:
                self.tree_romfs.item("", open=True)  # expand root
            except Exception:
                pass
        if self._exefs_dir and self._exefs_dir.is_dir():
            for p in sorted(self._exefs_dir.iterdir(), key=lambda x: x.name.lower()):
                if p.is_file():
                    try:
                        sz = f"{p.stat().st_size:,}"
                    except OSError:
                        sz = "?"
                    self.tree_exefs.insert("", "end", iid=f"exefs:{p.name}", text=p.name, values=(sz,))

    def _fill_romfs_tree(self, base: Path, parent: str = "") -> None:
        if not self._romfs_dir:
            return
        try:
            items = sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError:
            return

        for p in items:
            rel = str(p.relative_to(self._romfs_dir))
            iid = f"romfs:{rel}"
            if p.is_dir():
                node = self.tree_romfs.insert(parent, "end", iid=iid, text=p.name, values=("",))
                self.tree_romfs.item(node, open=True)  # auto expand
                self._fill_romfs_tree(p, node)
            else:
                try:
                    sz = f"{p.stat().st_size:,}"
                except OSError:
                    sz = "?"
                self.tree_romfs.insert(parent, "end", iid=iid, text=p.name, values=(sz,))

    def _on_romfs_tree_double(self, _event: tk.Event) -> None:
        sel = self.tree_romfs.selection()
        if not sel:
            return
        self._open_romfs_iid(sel[0])

    def _on_exefs_tree_double(self, _event: tk.Event) -> None:
        sel = self.tree_exefs.selection()
        if not sel:
            return
        iid = sel[0]
        if not iid.startswith("exefs:") or not self._exefs_dir:
            return
        name = iid[6:]
        full = self._exefs_dir / name
        if full.is_file():
            self._load_file_into_hex(full, "exefs", name)

    def _on_romfs_tree_rightclick(self, event: tk.Event) -> None:
        iid = self.tree_romfs.identify_row(event.y)
        if not iid:
            return
        self.tree_romfs.selection_set(iid)
        self._romfs_menu_iid = iid
        try:
            self._romfs_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._romfs_menu.grab_release()

    def _romfs_menu_open_hex(self) -> None:
        iid = getattr(self, "_romfs_menu_iid", None)
        if iid:
            self._open_romfs_iid(iid)

    def _romfs_menu_replace(self) -> None:
        iid = getattr(self, "_romfs_menu_iid", None)
        if not iid or not iid.startswith("romfs:") or not self._romfs_dir:
            return
        rel = iid[6:]
        dest = self._romfs_dir / rel
        if not dest.is_file():
            messagebox.showinfo("Replace", "Select a file entry (not a folder).")
            return
        path = filedialog.askopenfilename(title="Replace with file", filetypes=(("All files", "*.*"),))
        if not path:
            return
        try:
            shutil.copy2(path, dest)
            self.structure_pending = True
            self.structure_pending_var.set(
                "Changes pending: RomFS file replaced — export bundle to repack a CIA."
            )
            self.refresh_structure_trees()
            messagebox.showinfo("Replaced", f"Updated:\n{dest}")
        except Exception as e:
            messagebox.showerror("Replace failed", str(e))

    def _open_romfs_iid(self, iid: str) -> None:
        if not iid.startswith("romfs:") or not self._romfs_dir:
            return
        rel = iid[6:]
        full = self._romfs_dir / rel
        if full.is_file():
            self._load_file_into_hex(full, "romfs", rel)

    def _load_file_into_hex(self, full: Path, kind: str, rel: str) -> None:
        if self._cia_blob_backup is None and self.cia_data is not None:
            self._cia_blob_backup = bytearray(self.cia_data)
        try:
            data = bytearray(full.read_bytes())
        except OSError as e:
            messagebox.showerror("Open", str(e))
            return
        self.cia_data = data
        self.hex_editor.load_data(self.cia_data)
        self.hex_context = {"kind": kind, "path": str(full), "rel": rel}
        self.hex_view_label.config(text=f"Viewing: {kind} — {rel}")
        self.edits_made = False
        self.notebook.select(self.tab_hex)

    def back_to_cia_binary(self) -> None:
        if not self.loaded_cia_path:
            messagebox.showwarning("CIA", "No CIA path — open a .cia first.")
            return
        if self._cia_blob_backup is not None:
            self.cia_data = bytearray(self._cia_blob_backup)
        else:
            try:
                with open(self.loaded_cia_path, "rb") as f:
                    self.cia_data = bytearray(f.read())
            except OSError as e:
                messagebox.showerror("Read CIA", str(e))
                return
        self.hex_editor.load_data(self.cia_data)
        self.hex_context = {"kind": "cia", "path": self.loaded_cia_path}
        self.hex_view_label.config(text="Viewing: CIA binary (full file)")
        self.edits_made = False
        self.refresh_status_bar()

    def load_codebin_from_cia(self) -> None:
        if self._code_bin_extracted and self._code_bin_extracted.is_file():
            p = str(self._code_bin_extracted)
            self.codebin_path = p
            self.codebin_entry.config(state="normal")
            self.codebin_entry.delete(0, tk.END)
            self.codebin_entry.insert(0, p)
            self.codebin_entry.config(state="readonly")
            self.refresh_status_bar()
        else:
            messagebox.showwarning(
                "code.bin",
                "No ExeFS .code extracted yet. Load a decrypted .cia and wait for CIA Structure extract.",
            )

    def export_mod_bundle(self) -> None:
        if not self.loaded_cia_path or not str(self.loaded_cia_path).lower().endswith(".cia"):
            messagebox.showerror("Export", "Open a .cia file first.")
            return
        out = filedialog.askdirectory(title="Choose folder to place openhax_export")
        if not out:
            return
        stem = Path(self.loaded_cia_path).stem
        root = Path(out) / f"{stem}_openhax_export"
        try:
            root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.loaded_cia_path, root / "original.cia")
            if self._romfs_dir and self._romfs_dir.is_dir():
                rd = root / "romfs"
                if rd.exists():
                    shutil.rmtree(rd)
                shutil.copytree(self._romfs_dir, rd)
            if self._exefs_dir and self._exefs_dir.is_dir():
                ed = root / "exefs"
                if ed.exists():
                    shutil.rmtree(ed)
                shutil.copytree(self._exefs_dir, ed)
            readme = root / "README_OPENHAX.txt"
            readme.write_text(
                "OpenHax modification bundle\n"
                f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n"
                "original.cia — untouched copy opened in OpenHax\n"
                "romfs/ — extracted RomFS mirror (edit here, then repack with makerom/ctrtool)\n"
                "exefs/ — extracted ExeFS entries including .code\n\n"
                "OpenHax does not rebuild signed CIAs in-app. Use your 3DS toolchain to "
                "re-inject RomFS/ExeFS into NCCH and rebuild the CIA.\n",
                encoding="utf-8",
            )
            messagebox.showinfo("Export", f"Bundle created:\n{root}")
            self.status_var.set(f"Exported bundle → {root}")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def save_cia(self):
        if self.cia_data is None:
            messagebox.showwarning("Warning", "No data loaded. Open a file first.")
            return

        kind = self.hex_context.get("kind", "cia")
        if kind == "romfs":
            p = Path(self.hex_context["path"])
            try:
                p.write_bytes(bytes(self.cia_data))
                self.edits_made = False
                self.structure_pending = True
                self.structure_pending_var.set(
                    "Changes pending: RomFS on disk updated — export bundle to repack."
                )
                self.refresh_status_bar()
                messagebox.showinfo("Saved", f"Wrote RomFS file:\n{p}")
            except Exception as e:
                messagebox.showerror("Save Error", str(e))
            return
        if kind == "exefs":
            p = Path(self.hex_context["path"])
            try:
                p.write_bytes(bytes(self.cia_data))
                self.edits_made = False
                self.structure_pending = True
                self.structure_pending_var.set(
                    "Changes pending: ExeFS on disk updated — export bundle to repack."
                )
                self.refresh_status_bar()
                messagebox.showinfo("Saved", f"Wrote ExeFS file:\n{p}")
            except Exception as e:
                messagebox.showerror("Save Error", str(e))
            return

        if self.structure_pending:
            if not messagebox.askyesno(
                "Save raw CIA bytes",
                "Staged RomFS/ExeFS may differ from this file.\n"
                "This saves only the full CIA bytes shown in the hex editor.\n"
                "Use File → Export modification bundle for repack workflows.\n\n"
                "Continue saving raw CIA?",
            ):
                return

        default_name = (
            os.path.basename(self.loaded_cia_path) if self.loaded_cia_path else "modified.cia"
        )
        savepath = filedialog.asksaveasfilename(
            title="Save modified file (raw CIA bytes)",
            initialfile=default_name,
            defaultextension=".cia",
            filetypes=(
                ("CIA files", "*.cia"),
                ("Binary", "*.bin"),
                ("All files", "*.*"),
            ),
        )
        if savepath:
            try:
                with open(savepath, "wb") as f:
                    f.write(self.cia_data)
                self.loaded_cia_path = savepath
                self.edits_made = False
                self.refresh_status_bar()
                messagebox.showinfo(
                    "Saved",
                    f"Wrote raw bytes to:\n{savepath}\n\n"
                    "This is not a RomFS-aware rebuild. For repack, use Export modification bundle.",
                )
            except Exception as e:
                messagebox.showerror("Save Error", str(e))
                return

    def compile_asm(self):
        asm_code = self.asm_text.get('1.0', tk.END).strip()
        if not asm_code:
            messagebox.showwarning("Warning", "Assembly code is empty!")
            return
        if not KEYSTONE_AVAILABLE:
            messagebox.showwarning(
                "Keystone Missing",
                "Install keystone-engine to compile ARM assembly:\n\npip install keystone-engine"
            )
            return

        mode = self.asm_mode_var.get().upper()
        try:
            ks_mod = importlib.import_module("keystone")
            ks_mode = ks_mod.KS_MODE_THUMB if mode == "THUMB" else ks_mod.KS_MODE_ARM
            ks = ks_mod.Ks(ks_mod.KS_ARCH_ARM, ks_mode)
            encoding, _ = ks.asm(asm_code)
            self.last_compiled_payload = bytes(encoding)
            hex_bytes = " ".join(f"{b:02X}" for b in self.last_compiled_payload)
            preview = hex_bytes[:900] + (" ..." if len(hex_bytes) > 900 else "")
            messagebox.showinfo(
                "Compile Success",
                f"Mode: {mode}\nBytes: {len(self.last_compiled_payload)}\n\n{preview}"
            )
            self.refresh_status_bar()
        except Exception as e:
            messagebox.showerror("Compile Error", str(e))

    def inject_asm(self):
        if not self.last_compiled_payload:
            messagebox.showwarning("No Payload", "Compile ASM first.")
            return
        if not self.codebin_path:
            messagebox.showerror("Error", "Select an extracted ExeFS code.bin target first.")
            return

        try:
            offset = int(self.codebin_offset_var.get().strip(), 16)
        except ValueError:
            messagebox.showerror("Offset Error", "Offset must be a valid hex value, e.g. 0x1234")
            return
        if offset < 0:
            messagebox.showerror("Offset Error", "Offset cannot be negative.")
            return

        try:
            with open(self.codebin_path, "rb") as f:
                code_data = bytearray(f.read())
            end = offset + len(self.last_compiled_payload)
            if end > len(code_data):
                code_data.extend(b"\x00" * (end - len(code_data)))
            code_data[offset:end] = self.last_compiled_payload

            src = Path(self.codebin_path)
            out_bytes = bytes(code_data)
            write_here = False
            if self._exefs_dir and src.is_file():
                try:
                    write_here = src.resolve().parent == self._exefs_dir.resolve()
                except OSError:
                    write_here = False
            if write_here and messagebox.askyesno(
                "Write ExeFS .code",
                "Patch the extracted ExeFS .code file in place?\n\n"
                "Yes = update staged exefs/ (mark changes pending)\n"
                "No = save a copy elsewhere",
            ):
                src.write_bytes(out_bytes)
                self.structure_pending = True
                self.structure_pending_var.set(
                    "Changes pending: .code patched — export bundle to repack."
                )
                self.refresh_status_bar()
                messagebox.showinfo(
                    "ExeFS",
                    "Patched staged .code.\nUse File → Export modification bundle for repack tools.",
                )
                return

            out_path = filedialog.asksaveasfilename(
                title="Save patched code.bin",
                initialfile=f"{src.stem}_patched{src.suffix}",
                defaultextension=".bin",
                filetypes=(("Binary", "*.bin"), ("All Files", "*.*")),
            )
            if not out_path:
                return
            with open(out_path, "wb") as f:
                f.write(out_bytes)

            self.refresh_status_bar()
            messagebox.showinfo(
                "ExeFS Injection Complete",
                "Payload written to saved file.\n\n"
                "Copy into extracted exefs/ or use your repack pipeline.",
            )
        except Exception as e:
            messagebox.showerror("Injection Error", str(e))

    def browse_codebin(self):
        path = filedialog.askopenfilename(
            title="Select extracted ExeFS code.bin",
            filetypes=(("Binary", "*.bin"), ("All Files", "*.*"))
        )
        if path:
            self.codebin_path = path
            self.codebin_entry.config(state='normal')
            self.codebin_entry.delete(0, tk.END)
            self.codebin_entry.insert(0, path)
            self.codebin_entry.config(state='readonly')

    def browse_romfs_root(self):
        path = filedialog.askdirectory(title="Select extracted RomFS root")
        if path:
            self.romfs_root_path = path
            self.txt_romfs_root.config(state='normal')
            self.txt_romfs_root.delete(0, tk.END)
            self.txt_romfs_root.insert(0, path)
            self.txt_romfs_root.config(state='readonly')

    def browse_texture(self):
        path = filedialog.askopenfilename(
            title="Select Texture Pack Folder or ZIP",
            filetypes=(("ZIP archives", "*.zip"), ("All Files", "*.*"))
        )
        if not path:
            path = filedialog.askdirectory(title="Select Texture Pack Folder")
        if path:
            self.texture_pack_path = path
            self.txt_texture_path.config(state='normal')
            self.txt_texture_path.delete(0, tk.END)
            self.txt_texture_path.insert(0, path)
            self.txt_texture_path.config(state='readonly')

    def _merge_folder_into_romfs(self, src: Path, dest_root: Path) -> int:
        n = 0
        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src)
                target = dest_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                n += 1
        return n

    def apply_texture(self):
        if self.cia_data is None or not self.loaded_cia_path:
            messagebox.showerror("Error", "No .cia file loaded!")
            return
        if not self.texture_pack_path:
            messagebox.showerror("Error", "No texture pack selected!")
            return

        target_romfs: Path | None = None
        if self._romfs_dir and self._romfs_dir.is_dir():
            target_romfs = self._romfs_dir
        elif self.romfs_root_path:
            target_romfs = Path(self.romfs_root_path)

        if target_romfs is None or not target_romfs.is_dir():
            messagebox.showerror(
                "RomFS",
                "No RomFS folder to merge into.\n"
                "Open a decrypted .cia and wait for CIA Structure extract, or set RomFS root manually.",
            )
            return

        title_id = self.txt_title_id.get()
        cia_name = Path(self.loaded_cia_path).name
        out_dir = Path(self.loaded_cia_path).with_name(Path(self.loaded_cia_path).stem + "_texture_patch")
        meta_path = out_dir / "openhax_texture_meta.txt"

        try:
            src = Path(self.texture_pack_path)
            copied = 0
            if src.is_file() and src.suffix.lower() == ".zip":
                with tempfile.TemporaryDirectory() as td:
                    td_path = Path(td)
                    with zipfile.ZipFile(src, "r") as zf:
                        zf.extractall(td_path)
                    copied = self._merge_folder_into_romfs(td_path, target_romfs)
            elif src.is_dir():
                copied = self._merge_folder_into_romfs(src, target_romfs)
            else:
                raise ValueError("Texture source must be a folder or .zip")

            if self._romfs_dir and target_romfs.resolve() == self._romfs_dir.resolve():
                self.structure_pending = True
                self.structure_pending_var.set(
                    "Changes pending: texture pack merged into extracted RomFS — export bundle to repack."
                )
                self.refresh_structure_trees()

            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.loaded_cia_path, out_dir / cia_name)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            meta_lines = [
                "OpenHax texture merge log",
                f"Version: {__version__}",
                f"Created (UTC): {ts}",
                f"CIA: {cia_name}",
                f"Texture Source: {self.texture_pack_path}",
                f"Merged into: {target_romfs}",
                f"Files copied: {copied}",
                f"Title ID: {title_id if title_id else '(not set)'}",
                "",
                "RomFS was patched on disk. Rebuild CIA with external tools; use Export modification bundle.",
            ]
            meta_path.write_text("\n".join(meta_lines), encoding="utf-8")

            self.refresh_status_bar()
            messagebox.showinfo(
                "Texture pack",
                f"Merged {copied} file(s) into RomFS:\n{target_romfs}\n\n"
                f"Log + CIA copy: {out_dir}",
            )
        except Exception as e:
            messagebox.showerror("Texture Patch Error", str(e))


class InstallerWizard:
    def __init__(self, root, on_launch):
        self.root = root
        self.on_launch = on_launch
        self.root.title("OpenHax Dependency Installer v1.0")
        self.root.geometry("700x600")
        self.root.minsize(640, 520)
        self.center_window()

        self.python_cmd = sys.executable
        self.install_in_progress = False
        # Order matters: pyctr first (required for main app launch).
        self.dependencies = {
            "pyctr": {
                "pip_name": "pyctr",
                "import_name": "pyctr",
                "desc": "Required — CIA/NCCH parsing, RomFS/ExeFS (OpenHax v0.4+)",
                "installed": False,
            },
            "keystone-engine": {
                "pip_name": "keystone-engine",
                "import_name": "keystone",
                "desc": "ARM/THUMB assembly compiler for payloads",
                "installed": False,
            },
            "capstone": {
                "pip_name": "capstone",
                "import_name": "capstone",
                "desc": "Disassembler (Disassembler tab)",
                "installed": False,
            },
            "Pillow": {
                "pip_name": "Pillow",
                "import_name": "PIL",
                "desc": "Image preview (future texture tools)",
                "installed": False,
            },
            "customtkinter": {
                "pip_name": "customtkinter",
                "import_name": "customtkinter",
                "desc": "Optional modern UI (future theme)",
                "installed": False,
            },
        }

        self.setup_ui()
        self.check_installed_deps()

    def center_window(self):
        self.root.update_idletasks()
        width = 700
        height = 600
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def setup_ui(self):
        container = ttk.Frame(self.root, padding=14)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="OpenHax Dependency Installer", font=("Arial", 18, "bold")).pack()
        ttk.Label(container, text="Install missing software, then launch OpenHax", font=("Arial", 10)).pack(pady=(2, 10))
        ttk.Separator(container, orient="horizontal").pack(fill="x", pady=8)

        deps_frame = ttk.LabelFrame(container, text="Dependencies", padding=10)
        deps_frame.pack(fill="x", pady=(0, 10))
        for dep_name, dep_info in self.dependencies.items():
            row = ttk.Frame(deps_frame)
            row.pack(fill="x", pady=6)
            left = ttk.Frame(row)
            left.pack(side="left", fill="x", expand=True)
            ttk.Label(left, text=dep_name, font=("Arial", 10, "bold")).pack(anchor="w")
            ttk.Label(left, text=dep_info["desc"], font=("Arial", 9)).pack(anchor="w")

            right = ttk.Frame(row)
            right.pack(side="right")
            status_var = tk.StringVar(value="Checking...")
            status_label = ttk.Label(right, textvariable=status_var, width=16)
            status_label.pack(side="left", padx=(0, 8))
            btn = ttk.Button(right, text=f"Install {dep_name.split('-')[0].upper()}",
                             command=lambda d=dep_name: self.install_dependency(d), width=18)
            btn.pack(side="left")
            dep_info["status_var"] = status_var
            dep_info["status_label"] = status_label
            dep_info["install_btn"] = btn

        log_frame = ttk.LabelFrame(container, text="Installation Log", padding=8)
        log_frame.pack(fill="both", expand=True, pady=(0, 10))
        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, font=("Courier", 9), wrap=tk.WORD)
        self.log_text.pack(fill="both", expand=True)

        self.progress_bar = ttk.Progressbar(container, mode="indeterminate")
        self.progress_bar.pack(fill="x", pady=(0, 10))

        bottom = ttk.Frame(container)
        bottom.pack(fill="x")
        self.install_all_btn = ttk.Button(bottom, text="Install All Missing", command=self.install_all, width=20)
        self.install_all_btn.pack(side="left")
        ttk.Button(bottom, text="Refresh Status", command=self.check_installed_deps, width=14).pack(side="left", padx=8)
        self.auto_btn = ttk.Button(bottom, text="Install Missing + Launch", command=self.install_all_then_launch, width=24)
        self.auto_btn.pack(side="right")
        self.launch_btn = ttk.Button(bottom, text="Launch OpenHax", command=self.launch_openhax, width=16)
        self.launch_btn.pack(side="right", padx=(0, 8))

    def log_message(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def check_dependency(self, dep_name):
        return importlib.util.find_spec(self.dependencies[dep_name]["import_name"]) is not None

    def check_installed_deps(self):
        all_installed = True
        for dep_name, dep_info in self.dependencies.items():
            installed = self.check_dependency(dep_name)
            dep_info["installed"] = installed
            if installed:
                dep_info["status_var"].set("Installed")
                dep_info["status_label"].configure(foreground="green")
                dep_info["install_btn"].configure(state="disabled", text="Installed")
            else:
                all_installed = False
                dep_info["status_var"].set("Not Installed")
                dep_info["status_label"].configure(foreground="red")
                dep_info["install_btn"].configure(
                    state="disabled" if self.install_in_progress else "normal",
                    text=f"Install {dep_name.split('-')[0].upper()}",
                )

        disabled = "disabled" if self.install_in_progress else "normal"
        self.install_all_btn.configure(state=disabled if not all_installed else "disabled")
        self.auto_btn.configure(state=disabled)
        self.launch_btn.configure(state="normal")

    def run_pip_install(self, package_name):
        cmd = [self.python_cmd, "-m", "pip", "install", package_name, "--upgrade"]
        self.log_message("$ " + " ".join(cmd))
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if proc.stdout is not None:
                for line in proc.stdout:
                    self.log_message("  " + line.rstrip())
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            self.log_message(f"ERROR: {e}")
            return False

    def _set_busy(self, busy):
        self.install_in_progress = busy
        if busy:
            self.progress_bar.start(10)
        else:
            self.progress_bar.stop()
        self.check_installed_deps()

    def install_dependency(self, dep_name):
        if self.install_in_progress or self.dependencies[dep_name]["installed"]:
            return

        self._set_busy(True)

        def task():
            self.log_message("=" * 60)
            self.log_message(f"Installing {dep_name}...")
            ok = self.run_pip_install(self.dependencies[dep_name]["pip_name"])
            self.log_message("SUCCESS" if ok else "FAILED")
            self.log_message("=" * 60)

            def done():
                self._set_busy(False)
                if ok:
                    _invalidate_dep_cache()
                self.check_installed_deps()
                if ok and self.check_dependency(dep_name):
                    messagebox.showinfo("Installed", f"{dep_name} installed successfully.")
                elif not ok:
                    messagebox.showerror("Install Failed", f"Failed to install {dep_name}.")
            self.root.after(0, done)

        threading.Thread(target=task, daemon=True).start()

    def install_all(self):
        self._install_missing_then(maybe_launch=False)

    def install_all_then_launch(self):
        self._install_missing_then(maybe_launch=True)

    def _install_missing_then(self, maybe_launch=False):
        if self.install_in_progress:
            return
        missing = [k for k, v in self.dependencies.items() if not v["installed"]]
        if not missing:
            if maybe_launch:
                self.launch_openhax()
            else:
                messagebox.showinfo("Done", "All dependencies are already installed.")
            return

        self._set_busy(True)

        def task():
            self.log_message("=" * 60)
            self.log_message("INSTALLING MISSING DEPENDENCIES")
            self.log_message("=" * 60)
            for dep in missing:
                self.log_message(f"Installing {dep}...")
                self.run_pip_install(self.dependencies[dep]["pip_name"])
            self.log_message("=" * 60)
            self.log_message("INSTALLATION PROCESS COMPLETED")
            self.log_message("=" * 60)

            def done():
                self._set_busy(False)
                _invalidate_dep_cache()
                self.check_installed_deps()
                if maybe_launch:
                    self.launch_openhax()
                else:
                    messagebox.showinfo("Complete", "Install process finished. Verify statuses above.")
            self.root.after(0, done)

        threading.Thread(target=task, daemon=True).start()

    def launch_openhax(self):
        self.on_launch()


if __name__ == "__main__":
    root = tk.Tk()

    def launch_app():
        if not _dep_pyctr():
            messagebox.showerror(
                "pyctr required",
                "OpenHax v0.4 requires pyctr for CIA metadata and planned NCCH tools.\n\n"
                "Install pyctr from the wizard (Install pyctr / Install All), then launch again.",
            )
            return
        for child in root.winfo_children():
            child.destroy()
        OpenHaxApp(root)

    InstallerWizard(root, on_launch=launch_app)
    root.mainloop()
