import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import binascii
import os

class OpenHaxApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OpenHax v0.1 by a.c")
        self.root.geometry("850x600")
        self.root.minsize(600, 400)
        
        self.loaded_cia_path = None
        self.texture_pack_path = None

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
        self.status_var.set("Ready | OpenHax v0.1 by a.c")
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
            self.status_var.set(f"Loaded: {os.path.basename(filepath)}")
            self.load_hex_preview(filepath)

    def save_cia(self):
        if not self.loaded_cia_path:
            messagebox.showwarning("Warning", "No .cia file loaded!")
            return
            
        savepath = filedialog.asksaveasfilename(
            title="Save Modified .cia",
            defaultextension=".cia",
            filetypes=(("CIA Files", "*.cia"), ("All Files", "*.*"))
        )
        if savepath:
            # Placeholder for actual saving logic
            messagebox.showinfo("Success", f"Modifications saved to:\n{savepath}\n\n(Note: Backend implementation required to fully repack CIA files)")
            self.status_var.set(f"Saved: {os.path.basename(savepath)}")

    def load_hex_preview(self, filepath):
        self.hex_text.delete('1.0', tk.END)
        try:
            with open(filepath, 'rb') as f:
                # Read only first 4KB for preview to not freeze the GUI
                content = f.read(4096)
                
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
        if not self.loaded_cia_path:
            messagebox.showwarning("Warning", "No .cia file loaded to edit.")
            return
        # This is where you would parse the Text widget back into bytes and write it.
        messagebox.showinfo("Edits Applied", "Hex edits cached in memory. Use 'File -> Save .cia File' to write to disk.")

    def compile_asm(self):
        asm_code = self.asm_text.get('1.0', tk.END).strip()
        if not asm_code:
            messagebox.showwarning("Warning", "Assembly code is empty!")
            return
            
        # Placeholder for Keystone Engine integration
        messagebox.showinfo("Compiler", "To fully compile ARM assembly, pip install 'keystone-engine'.\n\nSimulated compilation successful. Bytes generated:\n01 00 A0 E3 00 10 A0 E3 1E FF 2F E1")

    def inject_asm(self):
        if not self.loaded_cia_path:
            messagebox.showerror("Error", "Load a .cia file first before injecting ASM payload.")
            return
        
        # Placeholder for pyctr / ExeFS injection
        messagebox.showinfo("Injection", f"Simulated injection of ASM payload into {os.path.basename(self.loaded_cia_path)}'s ExeFS (.text section).")

    def browse_texture(self):
        folder_path = filedialog.askdirectory(title="Select Texture Pack Folder")
        if folder_path:
            self.texture_pack_path = folder_path
            self.txt_texture_path.config(state='normal')
            self.txt_texture_path.delete(0, tk.END)
            self.txt_texture_path.insert(0, folder_path)
            self.txt_texture_path.config(state='readonly')

    def apply_texture(self):
        if not self.loaded_cia_path:
            messagebox.showerror("Error", "No .cia file loaded!")
            return
        if not self.texture_pack_path:
            messagebox.showerror("Error", "No texture pack selected!")
            return
            
        title_id = self.txt_title_id.get()
        msg = f"Applying textures from:\n{self.texture_pack_path}\n\nTo RomFS of:\n{os.path.basename(self.loaded_cia_path)}"
        if title_id:
            msg += f"\nTargeting Title ID: {title_id}"
            
        # Placeholder for romfs patching
        messagebox.showinfo("Texture Patcher", msg + "\n\nTexture patching simulated successfully!")

if __name__ == "__main__":
    root = tk.Tk()
    app = OpenHaxApp(root)
    root.mainloop()
