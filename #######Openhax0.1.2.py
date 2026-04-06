import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import shutil
import zipfile
import importlib
import importlib.util
import subprocess
import threading
import sys
from pathlib import Path

KEYSTONE_AVAILABLE = importlib.util.find_spec("keystone") is not None
PYCTR_AVAILABLE = importlib.util.find_spec("pyctr") is not None

class HexEditorFrame(ttk.Frame):
    """
    A pure Tkinter Hex Editor widget that supports large files by only rendering
    the visible portion. It allows viewing and editing bytes directly.
    """
    def __init__(self, master, cia_data=None, on_edit_callback=None, **kwargs):
        super().__init__(master, **kwargs)
        self.cia_data = cia_data
        self.on_edit_callback = on_edit_callback
        
        self.bytes_per_row = 16
        self.font = ("Courier", 10)
        self.char_width = 8  # approx width in pixels for Courier 10
        self.char_height = 14 # approx height in pixels
        
        self.offset_chars = 8
        self.hex_chars = self.bytes_per_row * 3 - 1
        self.ascii_chars = self.bytes_per_row
        
        self.total_lines = 0
        self.visible_lines = 0
        self.top_line_index = 0
        
        self.cursor_pos = 0 # byte index
        self.cursor_nibble = 0 # 0 for high nibble, 1 for low nibble
        
        self.setup_ui()
        self.bind_events()
        
    def setup_ui(self):
        # Top toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x', side='top', pady=(0, 5))
        
        ttk.Label(toolbar, text="Go to offset (hex):").pack(side='left')
        self.goto_var = tk.StringVar()
        self.goto_entry = ttk.Entry(toolbar, textvariable=self.goto_var, width=12)
        self.goto_entry.pack(side='left', padx=5)
        self.goto_entry.bind('<Return>', self.goto_offset)
        ttk.Button(toolbar, text="Go", command=self.goto_offset).pack(side='left')
        
        self.status_label = ttk.Label(toolbar, text="Offset: 0x00000000")
        self.status_label.pack(side='right')

        # Main editor area
        self.canvas_frame = ttk.Frame(self)
        self.canvas_frame.pack(fill='both', expand=True)
        
        self.scrollbar = ttk.Scrollbar(self.canvas_frame, orient='vertical', command=self.on_scrollbar)
        self.scrollbar.pack(side='right', fill='y')
        
        # We use a canvas to draw text for performance on large files
        self.canvas = tk.Canvas(self.canvas_frame, bg='white', cursor="xterm")
        self.canvas.pack(side='left', fill='both', expand=True)
        
    def bind_events(self):
        self.canvas.bind("<Configure>", self.on_resize)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel_linux) # Linux scroll up
        self.canvas.bind("<Button-5>", self.on_mousewheel_linux) # Linux scroll down
        
        # Keyboard events for editing
        self.canvas.bind("<Key>", self.on_key)
        self.canvas.bind("<Up>", lambda e: self.move_cursor(-self.bytes_per_row))
        self.canvas.bind("<Down>", lambda e: self.move_cursor(self.bytes_per_row))
        self.canvas.bind("<Left>", lambda e: self.move_cursor(-1, change_nibble=True))
        self.canvas.bind("<Right>", lambda e: self.move_cursor(1, change_nibble=True))
        self.canvas.bind("<Prior>", lambda e: self.move_cursor(-self.visible_lines * self.bytes_per_row)) # Page Up
        self.canvas.bind("<Next>", lambda e: self.move_cursor(self.visible_lines * self.bytes_per_row))   # Page Down

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
        self.update_scrollbar()
        self.redraw()
        self.canvas.focus_set()

    def on_resize(self, event):
        # Calculate how many lines can fit
        # We estimate font height to be roughly 14px, but let's measure it if possible
        # For simplicity, using a fixed estimate that works well with Courier 10
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
        if self.total_lines <= 0: return
        
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
        if self.total_lines <= 0: return
        # Windows/Mac
        delta = -1 if event.delta > 0 else 1
        self.top_line_index += delta * 3
        self.clamp_scroll()
        self.update_scrollbar()
        self.redraw()

    def on_mousewheel_linux(self, event):
        if self.total_lines <= 0: return
        delta = -1 if event.num == 4 else 1
        self.top_line_index += delta * 3
        self.clamp_scroll()
        self.update_scrollbar()
        self.redraw()

    def goto_offset(self, event=None):
        if self.cia_data is None: return
        val = self.goto_var.get().strip()
        try:
            if val.lower().startswith('0x'):
                offset = int(val, 16)
            else:
                offset = int(val, 16) # Assume hex even without 0x
                
            if offset < 0: offset = 0
            if offset >= len(self.cia_data): offset = len(self.cia_data) - 1
            
            self.cursor_pos = offset
            self.cursor_nibble = 0
            
            # Scroll to make it visible
            target_line = offset // self.bytes_per_row
            if target_line < self.top_line_index or target_line >= self.top_line_index + self.visible_lines:
                self.top_line_index = max(0, target_line - self.visible_lines // 2)
                self.clamp_scroll()
                self.update_scrollbar()
                
            self.redraw()
            self.canvas.focus_set()
        except ValueError:
            messagebox.showerror("Invalid Offset", "Please enter a valid hexadecimal offset.")

    def on_click(self, event):
        self.canvas.focus_set()
        if self.cia_data is None: return
        
        # Calculate which line was clicked
        line_click = event.y // self.char_height
        target_line = self.top_line_index + line_click
        
        if target_line >= self.total_lines:
            return
            
        # Calculate X position mapping
        x = event.x
        
        # Layout:
        # OFFSET (8) + Space (2) + HEX (47) + Space (2) + ASCII (16)
        
        offset_w = self.offset_chars * self.char_width
        space_w = 2 * self.char_width
        
        hex_start_x = offset_w + space_w
        hex_end_x = hex_start_x + self.hex_chars * self.char_width
        
        ascii_start_x = hex_end_x + space_w
        
        byte_index = -1
        nibble = 0
        
        if hex_start_x <= x <= hex_end_x:
            # Clicked in hex area
            rel_x = x - hex_start_x
            char_idx = int(rel_x / self.char_width)
            
            # Each byte is 3 chars: "FF "
            byte_in_row = char_idx // 3
            if byte_in_row >= self.bytes_per_row:
                byte_in_row = self.bytes_per_row - 1
                
            char_in_byte = char_idx % 3
            if char_in_byte == 2: # Clicked on space
                nibble = 0
                # Snap to next or previous? Let's just say nibble 0 of that byte
            else:
                nibble = char_in_byte
                
            byte_index = target_line * self.bytes_per_row + byte_in_row
            
        elif x >= ascii_start_x:
            # Clicked in ASCII area
            rel_x = x - ascii_start_x
            byte_in_row = int(rel_x / self.char_width)
            if byte_in_row >= self.bytes_per_row:
                byte_in_row = self.bytes_per_row - 1
            
            byte_index = target_line * self.bytes_per_row + byte_in_row
            nibble = 0 # Default to high nibble when clicking ASCII
            
        if byte_index >= 0 and byte_index < len(self.cia_data):
            self.cursor_pos = byte_index
            self.cursor_nibble = nibble
            self.redraw()

    def move_cursor(self, delta_bytes, change_nibble=False):
        if self.cia_data is None: return
        
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
            
        # Clamp
        if self.cursor_pos < 0:
            self.cursor_pos = 0
            self.cursor_nibble = 0
        elif self.cursor_pos >= len(self.cia_data):
            self.cursor_pos = len(self.cia_data) - 1
            self.cursor_nibble = 1
            
        # Auto-scroll
        cursor_line = self.cursor_pos // self.bytes_per_row
        if cursor_line < self.top_line_index:
            self.top_line_index = cursor_line
            self.update_scrollbar()
        elif cursor_line >= self.top_line_index + self.visible_lines:
            self.top_line_index = cursor_line - self.visible_lines + 1
            self.update_scrollbar()
            
        self.redraw()

    def on_key(self, event):
        if self.cia_data is None: return
        
        char = event.char.upper()
        if char in '0123456789ABCDEF':
            val = int(char, 16)
            current_byte = self.cia_data[self.cursor_pos]
            
            if self.cursor_nibble == 0:
                # Modify high nibble
                new_byte = (val << 4) | (current_byte & 0x0F)
                self.cia_data[self.cursor_pos] = new_byte
                self.cursor_nibble = 1
            else:
                # Modify low nibble
                new_byte = (current_byte & 0xF0) | val
                self.cia_data[self.cursor_pos] = new_byte
                self.cursor_nibble = 0
                self.move_cursor(1) # Auto advance
                
            if self.on_edit_callback:
                self.on_edit_callback()
                
            self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        if self.cia_data is None: return
        
        end_line = min(self.total_lines, self.top_line_index + self.visible_lines + 1)
        
        y = 0
        for line_idx in range(self.top_line_index, end_line):
            start_idx = line_idx * self.bytes_per_row
            end_idx = min(start_idx + self.bytes_per_row, len(self.cia_data))
            
            chunk = self.cia_data[start_idx:end_idx]
            
            # Offset
            offset_str = f"{start_idx:08X}"
            self.canvas.create_text(5, y, anchor='nw', text=offset_str, font=self.font, fill='blue')
            
            # Hex Data
            hex_x = 5 + (self.offset_chars + 2) * self.char_width
            for i, b in enumerate(chunk):
                bx = hex_x + (i * 3) * self.char_width
                byte_idx = start_idx + i
                
                # Highlight cursor
                if byte_idx == self.cursor_pos:
                    # Draw cursor background
                    bg_x = bx
                    if self.cursor_nibble == 1:
                        bg_x += self.char_width
                        
                    self.canvas.create_rectangle(
                        bg_x, y, 
                        bg_x + self.char_width, y + self.char_height,
                        fill='black'
                    )
                    
                    # Draw text over cursor
                    char_high = f"{(b >> 4) & 0xF:X}"
                    char_low = f"{b & 0xF:X}"
                    
                    fill_high = 'white' if self.cursor_nibble == 0 else 'black'
                    fill_low = 'white' if self.cursor_nibble == 1 else 'black'
                    
                    self.canvas.create_text(bx, y, anchor='nw', text=char_high, font=self.font, fill=fill_high)
                    self.canvas.create_text(bx + self.char_width, y, anchor='nw', text=char_low, font=self.font, fill=fill_low)
                    
                else:
                    self.canvas.create_text(bx, y, anchor='nw', text=f"{b:02X}", font=self.font, fill='black')
            
            # ASCII Data
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
        self.root.title("OpenHax v0.2 by a.c")
        self.root.geometry("850x600")
        self.root.minsize(600, 400)
        
        self.loaded_cia_path = None
        self.texture_pack_path = None
        self.codebin_path = None
        self.romfs_root_path = None
        self.cia_data = None
        self.last_compiled_payload = b""
        self.edits_made = False

        # Setup UI Theme
        style = ttk.Style()
        style.theme_use('clam')
        
        self.create_menu()
        self.create_notebook()
        self.create_statusbar()

    def create_menu(self):
        menubar = tk.Menu(self.root)
        
        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open .cia File", command=self.open_cia)
        file_menu.add_command(label="Save .cia File", command=self.save_cia)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        
        # Help Menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        
        self.root.config(menu=menubar)

    def create_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill='both', padx=10, pady=10)

        # Tab 1: Hex Editor
        self.tab_hex = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_hex, text="Hex Editor")
        self.setup_hex_editor_tab()

        # Tab 2: ARM ASM Writer
        self.tab_asm = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_asm, text="ARM ASM Writer")
        self.setup_asm_tab()

        # Tab 3: Texture Pack
        self.tab_texture = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_texture, text="Apply Texture Pack")
        self.setup_texture_tab()

    def setup_hex_editor_tab(self):
        self.hex_editor = HexEditorFrame(self.tab_hex, on_edit_callback=self.on_hex_edit)
        self.hex_editor.pack(expand=True, fill='both', padx=5, pady=5)

    def setup_asm_tab(self):
        frame = ttk.Frame(self.tab_asm)
        frame.pack(expand=True, fill='both', padx=5, pady=5)
        
        lbl_info = ttk.Label(frame, text="Write ARM Assembly (3DS Architecture - ARM11):")
        lbl_info.pack(anchor='w')

        self.asm_text = tk.Text(frame, font=("Courier", 11), undo=True)
        self.asm_text.pack(expand=True, fill='both', pady=5)
        
        # Default ASM boilerplate
        default_asm = "; OpenHax ARM ASM Payload\n; Target: 3DS (.cia ExeFS/.text section)\n\n.text\n.global _start\n\n_start:\n    MOV R0, #1\n    MOV R1, #0\n    BX LR\n"
        self.asm_text.insert('1.0', default_asm)

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

        row2 = ttk.Frame(target_frame)
        row2.pack(fill='x', padx=5, pady=(0, 6))
        ttk.Label(row2, text="Patch offset (hex):").pack(side='left')
        self.codebin_offset_var = tk.StringVar(value="0x0")
        ttk.Entry(row2, textvariable=self.codebin_offset_var, width=14).pack(side='left', padx=6)

    def setup_texture_tab(self):
        frame = ttk.Frame(self.tab_texture)
        frame.pack(expand=True, fill='both', padx=20, pady=20)
        
        ttk.Label(frame, text="Select Texture Pack Folder or .zip to inject into RomFS:").pack(anchor='w', pady=(0, 5))
        
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

        ttk.Button(frame, text="Apply Texture Pack to loaded .CIA", command=self.apply_texture).pack(pady=20)

    def create_statusbar(self):
        self.status_var = tk.StringVar()
        dep = []
        dep.append("Keystone:OK" if KEYSTONE_AVAILABLE else "Keystone:Missing")
        dep.append("pyctr:OK" if PYCTR_AVAILABLE else "pyctr:Missing")
        self.status_var.set(f"Ready | OpenHax v0.2 by a.c | {' | '.join(dep)}")
        self.statusbar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)

    # --- FUNCTIONALITY MODULES ---

    def show_about(self):
        messagebox.showinfo(
            "About OpenHax",
            "OpenHax v0.2\nCreated by a.c\n\n"
            "3DS hacking suite with robust pure-Tkinter Hex Editor (supports large files),\n"
            "ARM payload compile, ExeFS code.bin patching workflow, and RomFS texture staging."
        )

    def open_cia(self):
        filepath = filedialog.askopenfilename(
            title="Open .cia File",
            filetypes=(("CIA Files", "*.cia"), ("All Files", "*.*"))
        )
        if filepath:
            self.loaded_cia_path = filepath
            try:
                # Read file into a bytearray so it's mutable
                with open(filepath, "rb") as f:
                    self.cia_data = bytearray(f.read())
                self.status_var.set(
                    f"Loaded: {os.path.basename(filepath)} ({len(self.cia_data):,} bytes)"
                )
                self.edits_made = False
                self.hex_editor.load_data(self.cia_data)
            except Exception as e:
                self.cia_data = None
                self.hex_editor.load_data(None)
                messagebox.showerror("Error", f"Failed to open file:\n{e}")

    def on_hex_edit(self):
        self.edits_made = True
        display_name = os.path.basename(self.loaded_cia_path) if self.loaded_cia_path else "(unsaved)"
        self.status_var.set(f"Loaded: {display_name} [MODIFIED]")

    def save_cia(self):
        if not self.loaded_cia_path or self.cia_data is None:
            messagebox.showwarning("Warning", "No .cia file loaded in memory!")
            return
            
        savepath = filedialog.asksaveasfilename(
            title="Save Modified .cia",
            defaultextension=".cia",
            filetypes=(("CIA Files", "*.cia"), ("All Files", "*.*"))
        )
        if savepath:
            try:
                with open(savepath, "wb") as f:
                    f.write(self.cia_data)
                self.edits_made = False
                self.status_var.set(f"Saved: {os.path.basename(savepath)}")
                messagebox.showinfo("Success", f"Saved modified CIA bytes to:\n{savepath}")
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
            # Import lazily via importlib so missing optional deps remain non-fatal.
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
            self.status_var.set(f"ASM compiled ({len(self.last_compiled_payload)} bytes, {mode})")
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
            out_path = filedialog.asksaveasfilename(
                title="Save patched code.bin",
                initialfile=f"{src.stem}_patched{src.suffix}",
                defaultextension=".bin",
                filetypes=(("Binary", "*.bin"), ("All Files", "*.*"))
            )
            if not out_path:
                return
            with open(out_path, "wb") as f:
                f.write(code_data)

            self.status_var.set(
                f"Patched code.bin @ {hex(offset)} ({len(self.last_compiled_payload)} bytes)"
            )
            messagebox.showinfo(
                "ExeFS Injection Complete",
                "Payload written into code.bin.\n\n"
                "Use your preferred 3DS repack/signing pipeline to rebuild CIA."
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

    def apply_texture(self):
        if self.cia_data is None or not self.loaded_cia_path:
            messagebox.showerror("Error", "No .cia file loaded!")
            return
        if not self.texture_pack_path:
            messagebox.showerror("Error", "No texture pack selected!")
            return

        title_id = self.txt_title_id.get()
        cia_name = Path(self.loaded_cia_path).name
        out_dir = Path(self.loaded_cia_path).with_name(Path(self.loaded_cia_path).stem + "_texture_patch")
        textures_out = out_dir / "romfs_textures"
        patched_cia_path = out_dir / cia_name
        meta_path = out_dir / "openhax_texture_meta.txt"

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.loaded_cia_path, patched_cia_path)
            if textures_out.exists():
                shutil.rmtree(textures_out)
            textures_out.mkdir(parents=True, exist_ok=True)

            src = Path(self.texture_pack_path)
            if src.is_file() and src.suffix.lower() == ".zip":
                with zipfile.ZipFile(src, "r") as zf:
                    zf.extractall(textures_out)
            elif src.is_dir():
                for item in src.rglob("*"):
                    rel = item.relative_to(src)
                    target = textures_out / rel
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
            else:
                raise ValueError("Texture source must be a folder or .zip")

            meta_lines = [
                "OpenHax Texture Patch Package",
                "Version: 0.2",
                f"CIA: {cia_name}",
                f"Texture Source: {self.texture_pack_path}",
                f"Title ID: {title_id if title_id else '(not set)'}",
                "",
                "This package contains a CIA copy plus extracted texture assets.",
                "Full RomFS repack with pyctr can be added in a later version."
            ]
            meta_path.write_text("\n".join(meta_lines), encoding="utf-8")

            copied_into_romfs = 0
            if self.romfs_root_path:
                romfs_root = Path(self.romfs_root_path)
                if romfs_root.is_dir():
                    for item in textures_out.rglob("*"):
                        if item.is_file():
                            rel = item.relative_to(textures_out)
                            target = romfs_root / rel
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(item, target)
                            copied_into_romfs += 1

            self.status_var.set(f"Texture package staged: {out_dir.name}")
            messagebox.showinfo(
                "Texture Pack Applied",
                f"Package created:\n{out_dir}\n\n"
                f"Includes CIA copy and romfs_textures staging folder.\n"
                f"Direct RomFS patched files: {copied_into_romfs}"
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
        self.dependencies = {
            "keystone-engine": {
                "pip_name": "keystone-engine",
                "import_name": "keystone",
                "desc": "ARM/THUMB assembly compiler for 3DS payloads",
                "installed": False,
            },
            "pyctr": {
                "pip_name": "pyctr",
                "import_name": "pyctr",
                "desc": "CIA/CCI/3DS file handling and RomFS extraction",
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
        for child in root.winfo_children():
            child.destroy()
        OpenHaxApp(root)

    InstallerWizard(root, on_launch=launch_app)
    root.mainloop()
