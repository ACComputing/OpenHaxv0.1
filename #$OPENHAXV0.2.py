import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import shutil
import struct
import zipfile
import importlib.util
from pathlib import Path

KEYSTONE_AVAILABLE = importlib.util.find_spec("keystone") is not None
PYCTR_AVAILABLE = importlib.util.find_spec("pyctr") is not None

class OpenHaxApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OpenHax v0.1 by a.c")
        self.root.geometry("850x600")
        self.root.minsize(600, 400)
        
        self.loaded_cia_path = None
        self.texture_pack_path = None
        self.cia_data = None
        self.hex_preview_size = 4096
        self.last_compiled_payload = b""

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
        frame = ttk.Frame(self.tab_hex)
        frame.pack(expand=True, fill='both', padx=5, pady=5)
        
        lbl_info = ttk.Label(frame, text="Hex Viewer/Editor (Previewing first 4KB to prevent memory overload):")
        lbl_info.pack(anchor='w')

        # Text widget for Hex with Scrollbar
        self.hex_text = tk.Text(frame, wrap='none', font=("Courier", 10), undo=True)
        scroll_y = ttk.Scrollbar(frame, orient='vertical', command=self.hex_text.yview)
        scroll_x = ttk.Scrollbar(frame, orient='horizontal', command=self.hex_text.xview)
        
        self.hex_text.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        
        scroll_y.pack(side='right', fill='y')
        scroll_x.pack(side='bottom', fill='x')
        self.hex_text.pack(expand=True, fill='both')

        # Buttons
        btn_frame = ttk.Frame(self.tab_hex)
        btn_frame.pack(fill='x', padx=5, pady=5)
        
        ttk.Button(btn_frame, text="Reload Preview", command=self.reload_hex_preview).pack(side='left')
        ttk.Button(btn_frame, text="Apply Hex Edits to Memory", command=self.apply_hex_edits).pack(side='right')

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
        ttk.Button(btn_frame, text="Inject into .CIA", command=self.inject_asm).pack(side='left')

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

        ttk.Button(frame, text="Apply Texture Pack to loaded .CIA", command=self.apply_texture).pack(pady=20)

    def create_statusbar(self):
        self.status_var = tk.StringVar()
        dep = []
        dep.append("Keystone:OK" if KEYSTONE_AVAILABLE else "Keystone:Missing")
        dep.append("pyctr:OK" if PYCTR_AVAILABLE else "pyctr:Missing")
        self.status_var.set(f"Ready | OpenHax v0.1 by a.c | {' | '.join(dep)}")
        self.statusbar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w')
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)

    # --- FUNCTIONALITY MODULES ---

    def show_about(self):
        messagebox.showinfo("About OpenHax", "OpenHax v0.1\nCreated by a.c\n\nA 3DS ARM ASM writer, .cia Hex Editor, and Texture Pack patcher UI framework.")

    def open_cia(self):
        filepath = filedialog.askopenfilename(
            title="Open .cia File",
            filetypes=(("CIA Files", "*.cia"), ("All Files", "*.*"))
        )
        if filepath:
            self.loaded_cia_path = filepath
            try:
                with open(filepath, "rb") as f:
                    self.cia_data = bytearray(f.read())
                self.status_var.set(
                    f"Loaded: {os.path.basename(filepath)} ({len(self.cia_data):,} bytes)"
                )
                self.load_hex_preview()
            except Exception as e:
                self.cia_data = None
                messagebox.showerror("Error", f"Failed to open file:\n{e}")

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
            except Exception as e:
                messagebox.showerror("Save Error", str(e))
                return
            messagebox.showinfo("Success", f"Saved modified CIA bytes to:\n{savepath}")
            self.status_var.set(f"Saved: {os.path.basename(savepath)}")

    def reload_hex_preview(self):
        if self.cia_data is None:
            return
        self.load_hex_preview()

    def load_hex_preview(self):
        self.hex_text.delete('1.0', tk.END)
        try:
            if self.cia_data is None:
                return
            content = bytes(self.cia_data[:self.hex_preview_size])
            hex_lines = []
            for i in range(0, len(content), 16):
                chunk = content[i:i+16]
                hex_str = ' '.join(f'{b:02X}' for b in chunk)
                
                # ASCII Representation
                ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
                
                # Format: Offset | Hex Data | ASCII
                hex_lines.append(f"{i:08X}  {hex_str:<48}  |{ascii_str}|")
                
            self.hex_text.insert('1.0', '\n'.join(hex_lines))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file:\n{e}")

    def apply_hex_edits(self):
        if self.cia_data is None:
            messagebox.showwarning("Warning", "No .cia file loaded to edit.")
            return
        lines = self.hex_text.get("1.0", tk.END).splitlines()
        edited = 0
        try:
            for raw in lines:
                line = raw.strip()
                if not line:
                    continue
                if "|" in line:
                    line = line.split("|", 1)[0].rstrip()
                if "  " not in line:
                    continue
                off_str, hex_part = line.split("  ", 1)
                offset = int(off_str, 16)
                byte_tokens = [t for t in hex_part.strip().split(" ") if t]
                for idx, tok in enumerate(byte_tokens):
                    if len(tok) != 2:
                        continue
                    value = int(tok, 16)
                    pos = offset + idx
                    if 0 <= pos < len(self.cia_data):
                        self.cia_data[pos] = value
                        edited += 1
            self.status_var.set(f"Applied hex edits in memory ({edited} bytes touched)")
            messagebox.showinfo("Edits Applied", f"Hex edits applied to memory.\nBytes touched: {edited}")
        except Exception as e:
            messagebox.showerror("Parse Error", f"Hex edit parse failed:\n{e}")

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
        if self.cia_data is None or not self.loaded_cia_path:
            messagebox.showerror("Error", "Load a .cia file first before injecting ASM payload.")
            return
        if not self.last_compiled_payload:
            messagebox.showwarning("No Payload", "Compile ASM first.")
            return

        base = Path(self.loaded_cia_path)
        out_path = filedialog.asksaveasfilename(
            title="Save CIA with ASM payload",
            initialfile=f"{base.stem}_asm{base.suffix}",
            defaultextension=".cia",
            filetypes=(("CIA Files", "*.cia"), ("All Files", "*.*"))
        )
        if not out_path:
            return

        # Simple binary patch payload format:
        # [OPENHAX1][payload_len:4 little endian][payload bytes]
        patched = bytearray(self.cia_data)
        patched += b"OPENHAX1"
        patched += struct.pack("<I", len(self.last_compiled_payload))
        patched += self.last_compiled_payload
        try:
            with open(out_path, "wb") as f:
                f.write(patched)
            messagebox.showinfo(
                "Injection Complete",
                "ASM payload embedded and file written.\n\n"
                "Note: This is raw payload embedding, not full ExeFS relocation."
            )
            self.status_var.set(f"Injected ASM -> {os.path.basename(out_path)}")
        except Exception as e:
            messagebox.showerror("Injection Error", str(e))

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
                f"CIA: {cia_name}",
                f"Texture Source: {self.texture_pack_path}",
                f"Title ID: {title_id if title_id else '(not set)'}",
                "",
                "This package contains a CIA copy plus extracted texture assets.",
                "Full RomFS repack with pyctr can be added in a later version."
            ]
            meta_path.write_text("\n".join(meta_lines), encoding="utf-8")
            self.status_var.set(f"Texture package staged: {out_dir.name}")
            messagebox.showinfo(
                "Texture Pack Applied",
                f"Package created:\n{out_dir}\n\n"
                "Includes CIA copy and romfs_textures staging folder."
            )
        except Exception as e:
            messagebox.showerror("Texture Patch Error", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = OpenHaxApp(root)
    root.mainloop()
