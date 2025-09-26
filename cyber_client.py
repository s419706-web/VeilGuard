"""
VeilGuard Client
----------------
A Tkinter-based client application that connects to the VeilGuard server and
executes three image-processing operations:

1) Blur Faces (server-side)
2) Blur Background (server-side)
3) User ROI Blur (client-side interactive editor; final image is sent to server)

Features:
- Encrypted communication (via `Encryption`).
- Splash screen shown before the login phase.
- Login via a small Tk window (persisting credentials in creds.txt).
- Modern UI: choose image, run operations, and see Original vs. Processed previews.
- Robust threading so the UI remains responsive during long operations.
"""

# ======================
# IMPORT STATEMENTS
# ======================
from tkinter import Label, Toplevel, ttk, filedialog
import tkinter as tk
import socket
import os
import time
from PIL import Image, ImageTk
from constants import IP, PORT, CHUNK_SIZE  # CHUNK_SIZE kept for future use
from encrypt import Encryption
import cv2
import numpy as np
import threading
import subprocess
import sys
import io


# ======================
# TOP-LEVEL UI HELPERS (no nested classes)
# ======================
class Tooltip:
    """Lightweight tooltip helper for Tk widgets."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _=None):
        if self.tip:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.overrideredirect(True)
        self.tip.configure(bg="#111217")
        lbl = tk.Label(self.tip, text=self.text, bg="#111217", fg="#d9d9d9",
                       font=("Segoe UI", 9), padx=8, pady=4)
        lbl.pack()
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip.geometry(f"+{x}+{y}")

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ======================
# CLIENT CLASS DEFINITION
# ======================
class Client:
    def __init__(self):
        """
        Initialize the client with:
        - Default image candidates for operations.
        - Network objects and encryption wrapper.
        - UI state holders and flags.
        """
        # Default images used if user does not choose one
        self.usual_images = [
            r"C:\Users\shapi\Downloads\alin\test15.png",
            r"C:\Users\shapi\Downloads\alin\test16.png",
            r"C:\Users\shapi\Downloads\alin\test17.png"
        ]

        # Networking components
        self.client_socket = None
        self.encryptor = Encryption()

        # UI state
        self.logged_out = False
        self.ui_root = None
        self.selected_image_path = None
        self.preview_orig = None
        self.preview_proc = None
        self.status_var = None
        self.spinner_label = None
        self.btns = {}
        self._spinner_job = None
        self._spinner_phase = 0

        # Theme colors (set by create_styles)
        self._bg = "#0f1115"
        self._panel = "#171923"
        self._panel_hi = "#222533"
        self._fg = "#e6e6e6"
        self._muted = "#a9a9b3"
        self._accent = "#7c3aed"

    # ======================
    # NETWORK CONNECTION
    # ======================
    def connect_to_server(self):
        """Establish a TCP connection to the server."""
        try:
            self.client_socket = socket.socket()
            self.client_socket.connect((IP, PORT))
            print("Connected to server at", f"{IP}:{PORT}")
        except Exception as e:
            print(f"Connection failed: {e}")
            self.client_socket = None

    # ======================
    # SPLASH SCREEN
    # ======================
    def show_splash(self):
        """Display a 400x400 splash screen for ~4 seconds."""
        root = tk.Tk()
        root.withdraw()  # Hide the main root to display only the splash window

        splash = Toplevel(root)
        splash.geometry("400x400")
        splash.overrideredirect(True)  # No window decorations

        logo = Image.open(r"C:\Users\shapi\Downloads\intro_img.png").resize((400, 400))
        logo_photo = ImageTk.PhotoImage(logo)
        label = Label(splash, image=logo_photo)
        label.image = logo_photo  # Keep reference to avoid garbage collection
        label.pack()

        def close_splash():
            """Close the splash window and fully destroy the temporary root."""
            splash.destroy()
            root.destroy()

        splash.after(4000, close_splash)
        root.mainloop()

    # ======================
    # UI: THEME/STYLES/HEADER
    # ======================
    def create_styles(self):
        """Configure a modern dark theme for ttk widgets."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Colors
        self._bg = "#0f1115"
        self._panel = "#171923"
        self._panel_hi = "#222533"
        self._fg = "#e6e6e6"
        self._muted = "#a9a9b3"
        self._accent = "#7c3aed"

        # Window bg
        self.ui_root.configure(bg=self._bg)

        # Frames / labelframes
        style.configure("TopBar.TFrame", background=self._bg)
        style.configure("Card.TLabelframe",
                        background=self._panel,
                        foreground=self._fg,
                        borderwidth=0,
                        padding=10)
        style.configure("Card.TLabelframe.Label", foreground=self._muted)
        style.configure("TFrame", background=self._bg)

        # Buttons
        style.configure("Action.TButton",
                        background=self._panel,
                        foreground=self._fg,
                        padding=(14, 10),
                        borderwidth=0,
                        focusthickness=3,
                        focuscolor=self._accent,
                        font=("Segoe UI", 11, "bold"))
        style.map("Action.TButton",
                  background=[("active", self._panel_hi)],
                  foreground=[("disabled", "#777777")])

        # Labels
        style.configure("Status.TLabel", background=self._bg, foreground=self._muted, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self._bg, foreground="white", font=("Segoe UI Semibold", 20))

    def draw_gradient_header(self, parent, width=980, height=90):
        """Draw a simple left→right gradient header on a Canvas."""
        canvas = tk.Canvas(parent, height=height, width=width, highlightthickness=0, bd=0, bg=self._bg)
        canvas.pack(fill=tk.X, expand=False)
        start = (124, 58, 237)   # #7c3aed
        end   = (15, 17, 21)     # bg
        steps = max(1, width)
        for i in range(steps):
            r = int(start[0] + (end[0]-start[0]) * (i/steps))
            g = int(start[1] + (end[1]-start[1]) * (i/steps))
            b = int(start[2] + (end[2]-start[2]) * (i/steps))
            canvas.create_line(i, 0, i, height, fill=f"#{r:02x}{g:02x}{b:02x}")
        canvas.create_text(22, height//2, anchor="w",
                           text="VeilGuard — Image Privacy Client",
                           fill="white",
                           font=("Segoe UI Semibold", 18))
        return canvas

    # ======================
    # UI: SMALL UTILITIES
    # ======================
    def show_toast(self, text, ms=1800):
        """Small floating toast message near the bottom-right of the window."""
        toast = tk.Toplevel(self.ui_root)
        toast.overrideredirect(True)
        toast.configure(bg=self._panel)
        lbl = tk.Label(toast, text=text, bg=self._panel, fg=self._fg, font=("Segoe UI", 10), padx=14, pady=8)
        lbl.pack()
        self.ui_root.update_idletasks()
        x = self.ui_root.winfo_x() + self.ui_root.winfo_width() - toast.winfo_reqwidth() - 20
        y = self.ui_root.winfo_y() + self.ui_root.winfo_height() - toast.winfo_reqheight() - 40
        toast.geometry(f"+{x}+{y}")
        toast.after(ms, toast.destroy)

    def spinner_start(self):
        """Start a simple animated status spinner (ellipsis)."""
        if self._spinner_job:
            return
        self._spinner_phase = 0

        def tick():
            dots = ["", ".", "..", "..."]
            if self.spinner_label:
                self.spinner_label.config(text=dots[self._spinner_phase])
            self._spinner_phase = (self._spinner_phase + 1) % len(dots)
            self._spinner_job = self.ui_root.after(300, tick)

        tick()

    def spinner_stop(self):
        """Stop the animated status spinner."""
        if self._spinner_job:
            try:
                self.ui_root.after_cancel(self._spinner_job)
            except Exception:
                pass
            self._spinner_job = None
        if self.spinner_label:
            self.spinner_label.config(text="")

    def ui_set_status(self, msg: str):
        """Thread-safe setter for the bottom status label."""
        if self.status_var:
            def _set():
                self.status_var.set(msg)
            self.ui_root.after(0, _set)

    def ui_enable_controls(self, enable: bool):
        """Enable/disable buttons and toggle spinner during long operations."""
        state = tk.NORMAL if enable else tk.DISABLED
        for b in self.btns.values():
            b.config(state=state)
        if enable:
            self.spinner_stop()
        else:
            self.spinner_start()

    def open_file_no_temp(self, path: str):
        """Open a file with the OS default app without creating temporary copies."""
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)

    def choose_image_dialog(self):
        """Open a file picker, set selection, and preview it."""
        fp = filedialog.askopenfilename(
            title="Choose image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.gif"), ("All", "*.*")]
        )
        if fp:
            self.selected_image_path = fp
            self.ui_set_status(f"Selected image: {fp}")
            try:
                img = Image.open(fp)
                self.ui_show_preview(img, is_processed=False)
            except Exception as e:
                self.ui_set_status(f"Failed to open image: {e}")

    def ui_show_preview(self, pil_img: Image.Image, is_processed: bool):
        """Show a PIL image inside the corresponding preview panel."""
        max_w, max_h = 420, 280
        im = pil_img.copy()
        im.thumbnail((max_w, max_h))
        tk_img = ImageTk.PhotoImage(im)

        def _apply():
            if is_processed:
                self.preview_proc.config(image=tk_img)
                self.preview_proc.image = tk_img
            else:
                self.preview_orig.config(image=tk_img)
                self.preview_orig.image = tk_img
        self.ui_root.after(0, _apply)

    def ui_show_pair(self, orig_pil: Image.Image, proc_pil: Image.Image):
        """Update both preview panels at once."""
        self.ui_show_preview(orig_pil, is_processed=False)
        self.ui_show_preview(proc_pil, is_processed=True)

    def ui_run_async(self, target, *args, **kwargs):
        """
        Run a long operation in a background thread:
        - Disables UI controls while running.
        - Re-enables controls afterwards.
        - Pulls a fresh menu (unless already logged out).
        """
        def runner():
            try:
                self.ui_enable_controls(False)
                target(*args, **kwargs)
            finally:
                if not getattr(self, "logged_out", False):
                    try:
                        self.receive_menu()
                    except Exception:
                        pass
                self.ui_enable_controls(True)
        threading.Thread(target=runner, daemon=True).start()

    # ======================
    # AUTHENTICATION
    # ======================
    def send_credentials(self):
        """
        Send username/password to the server (encrypted).
        - If creds.txt exists, read from it.
        - Otherwise, prompt via a small Tk login window and save to creds.txt.
        - Exit if server reports incorrect password.
        """
        creds_file = "creds.txt"
        if os.path.exists(creds_file):
            with open(creds_file, "r") as f:
                lines = f.read().strip().split("\n")
                client_id = lines[0]
                password = lines[1]
        else:
            root = tk.Tk()
            root.title("Login")

            tk.Label(root, text="Username:").grid(row=0, column=0, padx=5, pady=5)
            tk.Label(root, text="Password:").grid(row=1, column=0, padx=5, pady=5)

            username_entry = tk.Entry(root)
            password_entry = tk.Entry(root, show="*")
            username_entry.grid(row=0, column=1, padx=5, pady=5)
            password_entry.grid(row=1, column=1, padx=5, pady=5)

            creds = {}

            def submit():
                creds["username"] = username_entry.get()
                creds["password"] = password_entry.get()
                root.destroy()

            tk.Button(root, text="Login", command=submit).grid(row=2, column=0, columnspan=2, pady=10)
            root.mainloop()

            client_id = creds["username"]
            password = creds["password"]

            with open(creds_file, "w") as f:
                f.write(client_id + "\n" + password)

        self.encryptor.send_encrypted_message(self.client_socket, client_id)
        self.encryptor.send_encrypted_message(self.client_socket, password)

        response = self.encryptor.receive_encrypted_message(self.client_socket)
        print(response)
        if "PASSWORD INCORRECT" in response:
            self.client_socket.close()
            exit()

    # ======================
    # MENU HANDLING
    # ======================
    def receive_menu(self):
        """Receive and print the server's textual menu. Returns the menu string."""
        try:
            menu = self.encryptor.receive_encrypted_message(self.client_socket)
            print("\nAvailable operations:")
            print(menu)
            return menu
        except Exception as e:
            print(f"Menu error: {e}")
            return None

    # ======================
    # OPERATION HELPERS
    # ======================
    def pick_source_path(self):
        """Return a valid image path (selected or one of the defaults)."""
        if self.selected_image_path and os.path.exists(self.selected_image_path):
            return self.selected_image_path
        for p in self.usual_images:
            if os.path.exists(p):
                return p
        raise FileNotFoundError("No valid image found in selected path or defaults.")

    def recv_size_or_error(self):
        """Receive an int size or raise on '[ERROR]...' message."""
        s = self.encryptor.receive_encrypted_message(self.client_socket)
        if s.startswith("[ERROR]"):
            raise RuntimeError(s)
        return int(s)

    # ======================
    # UI ACTIONS (OPTIONS 1–4)
    # ======================
    def ui_do_face(self):
        """Option 1: Blur Faces (server-side)."""
        try:
            self.ui_set_status("Running: Blur Faces...")
            self.encryptor.send_encrypted_message(self.client_socket, "1")

            src = self.pick_source_path()
            with open(src, "rb") as f:
                data = f.read()
            self.ui_show_preview(Image.open(src), is_processed=False)

            self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
            ack = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(ack)
            self.client_socket.sendall(data)

            out_size = self.recv_size_or_error()
            out = b''
            while len(out) < out_size:
                chunk = self.client_socket.recv(4096)
                if not chunk:
                    break
                out += chunk

            proc = Image.open(io.BytesIO(out)).convert("RGB")
            self.ui_show_preview(proc, is_processed=True)
            self.ui_set_status("Faces blurred successfully.")
            self.show_toast("Faces blurred successfully")

        except Exception as e:
            self.ui_set_status(f"Face blur failed: {e}")

    def ui_do_bg(self):
        """Option 2: Blur Background (server-side)."""
        try:
            self.ui_set_status("Running: Blur Background...")
            self.encryptor.send_encrypted_message(self.client_socket, "2")

            src = self.pick_source_path()
            with open(src, "rb") as f:
                data = f.read()
            self.ui_show_preview(Image.open(src), is_processed=False)

            self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
            ack = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(ack)
            self.client_socket.sendall(data)

            out_size = self.recv_size_or_error()
            out = b''
            while len(out) < out_size:
                chunk = self.client_socket.recv(4096)
                if not chunk:
                    break
                out += chunk

            proc = Image.open(io.BytesIO(out)).convert("RGB")
            self.ui_show_preview(proc, is_processed=True)
            self.ui_set_status("Background blurred successfully.")
            self.show_toast("Background blurred successfully")

        except Exception as e:
            self.ui_set_status(f"Background blur failed: {e}")

    def ui_do_user(self):
        """Option 3: User ROI Blur (client-side editor, then send final to server)."""
        try:
            self.ui_set_status("Running: User ROI Blur... (use mouse, press ESC to finish)")
            self.encryptor.send_encrypted_message(self.client_socket, "3")

            # Wait for server instruction
            signal = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(signal)

            # Load original locally
            src = self.pick_source_path()
            with open(src, "rb") as f:
                original_bytes = f.read()
            self.ui_show_preview(Image.open(src), is_processed=False)

            img = cv2.imread(src)
            if img is None:
                raise FileNotFoundError("Image not found or cannot be opened!")
            img_display = img.copy()
            drawing = {"active": False, "ix": -1, "iy": -1}

            def draw_rectangle(event, x, y, flags, param):
                if event == cv2.EVENT_LBUTTONDOWN:
                    drawing["active"] = True
                    drawing["ix"], drawing["iy"] = x, y
                elif event == cv2.EVENT_MOUSEMOVE and drawing["active"]:
                    nonlocal img_display
                    img_display = img.copy()
                    cv2.rectangle(img_display, (drawing["ix"], drawing["iy"]), (x, y), (0, 255, 0), 2)
                elif event == cv2.EVENT_LBUTTONUP:
                    drawing["active"] = False
                    x1, y1, x2, y2 = drawing["ix"], drawing["iy"], x, y
                    x1, x2 = sorted([max(0, x1), max(0, x2)])
                    y1, y2 = sorted([max(0, y1), max(0, y2)])
                    roi = img[y1:y2, x1:x2]
                    if roi.size > 0:
                        k = 51 if 51 % 2 == 1 else 53
                        roi_blur = cv2.GaussianBlur(roi, (k, k), 0)
                        img[y1:y2, x1:x2] = roi_blur
                        img_display = img.copy()

            cv2.namedWindow("Blur Editor")
            cv2.setMouseCallback("Blur Editor", draw_rectangle)
            while True:
                cv2.imshow("Blur Editor", img_display)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC
                    break
            cv2.destroyAllWindows()

            ok, enc = cv2.imencode(".jpg", img)
            if not ok:
                raise RuntimeError("Encoding failed")
            final_bytes = enc.tobytes()

            # Send ORIGINAL first
            self.encryptor.send_encrypted_message(self.client_socket, str(len(original_bytes)))
            ack1 = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(ack1)
            self.client_socket.sendall(original_bytes)

            # Then FINAL
            self.encryptor.send_encrypted_message(self.client_socket, str(len(final_bytes)))
            ack2 = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(ack2)
            self.client_socket.sendall(final_bytes)

            # Receive echo-back and preview it
            back_size = self.recv_size_or_error()
            rec = b''
            while len(rec) < back_size:
                chunk = self.client_socket.recv(4096)
                if not chunk:
                    break
                rec += chunk
            proc = Image.open(io.BytesIO(rec)).convert("RGB")
            self.ui_show_preview(proc, is_processed=True)
            self.ui_set_status("User ROI blur done.")
            self.show_toast("User ROI blur done")

        except Exception as e:
            self.ui_set_status(f"User ROI blur failed: {e}")

    def ui_do_logout(self):
        """Option 4: Logout gracefully (close socket & UI)."""
        try:
            self.ui_set_status("Logging out...")
            self.encryptor.send_encrypted_message(self.client_socket, "4")
            msg = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(msg)
        finally:
            self.logged_out = True
            try:
                self.client_socket.close()
            except:
                pass
            self.ui_root.after(500, self.ui_root.destroy)

    # ======================
    # BUILD MODERN UI
    # ======================
    def build_ui(self):
        """Build the modern VeilGuard client UI."""
        self.ui_root = tk.Tk()
        self.ui_root.title("VeilGuard Client")
        self.ui_root.geometry("1000x660")
        self.ui_root.minsize(900, 560)

        # Styles
        self.create_styles()

        # Header (gradient)
        header = ttk.Frame(self.ui_root, style="TopBar.TFrame")
        header.pack(side=tk.TOP, fill=tk.X)
        self.ui_root.update_idletasks()
        width = max(980, self.ui_root.winfo_width())
        self.draw_gradient_header(header, width=width, height=92)

        # Action bar
        top = ttk.Frame(self.ui_root, style="TopBar.TFrame")
        top.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(8, 10))

        self.btns["choose"] = ttk.Button(top, text="📂  Choose Image   Ctrl+O",
                                         style="Action.TButton",
                                         command=self.choose_image_dialog)
        self.btns["choose"].pack(side=tk.LEFT, padx=6)

        self.btns["face"] = ttk.Button(top, text="🎭  Blur Faces   Ctrl+1",
                                       style="Action.TButton",
                                       command=lambda: self.ui_run_async(self.ui_do_face))
        self.btns["face"].pack(side=tk.LEFT, padx=6)

        self.btns["bg"] = ttk.Button(top, text="🖼️  Blur Background   Ctrl+2",
                                     style="Action.TButton",
                                     command=lambda: self.ui_run_async(self.ui_do_bg))
        self.btns["bg"].pack(side=tk.LEFT, padx=6)

        self.btns["user"] = ttk.Button(top, text="✂️  User ROI Blur   Ctrl+3",
                                       style="Action.TButton",
                                       command=lambda: self.ui_run_async(self.ui_do_user))
        self.btns["user"].pack(side=tk.LEFT, padx=6)

        self.btns["logout"] = ttk.Button(top, text="🚪  Logout   Ctrl+L",
                                         style="Action.TButton",
                                         command=lambda: self.ui_run_async(self.ui_do_logout))
        self.btns["logout"].pack(side=tk.RIGHT, padx=6)

        # Tooltips
        Tooltip(self.btns["choose"], "Pick an image from disk")
        Tooltip(self.btns["face"], "Detect and blur all faces (server-side)")
        Tooltip(self.btns["bg"], "Keep subject sharp, blur the background (server-side)")
        Tooltip(self.btns["user"], "Draw rectangles to blur areas (client-side). Press ESC to finish.")
        Tooltip(self.btns["logout"], "Close session and exit")

        # Main content (cards)
        mid = ttk.Frame(self.ui_root)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=16, pady=8)

        left = ttk.Labelframe(mid, text="Original", style="Card.TLabelframe")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8), pady=0)
        right = ttk.Labelframe(mid, text="Processed", style="Card.TLabelframe")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=0)

        self.preview_orig = ttk.Label(left, background=self._panel)
        self.preview_orig.pack(fill=tk.BOTH, expand=True)
        self.preview_proc = ttk.Label(right, background=self._panel)
        self.preview_proc.pack(fill=tk.BOTH, expand=True)

        # Status bar with spinner
        bottom = ttk.Frame(self.ui_root)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=10)
        self.status_var = tk.StringVar(value="Ready · Choose an image or use defaults (test15/16/17).")
        ttk.Label(bottom, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT)
        self.spinner_label = ttk.Label(bottom, text="", style="Status.TLabel")
        self.spinner_label.pack(side=tk.RIGHT)

        # Shortcuts
        self.ui_root.bind("<Control-o>", lambda e: self.choose_image_dialog())
        self.ui_root.bind("<Control-1>", lambda e: self.ui_run_async(self.ui_do_face))
        self.ui_root.bind("<Control-2>", lambda e: self.ui_run_async(self.ui_do_bg))
        self.ui_root.bind("<Control-3>", lambda e: self.ui_run_async(self.ui_do_user))
        self.ui_root.bind("<Control-l>", lambda e: self.ui_run_async(self.ui_do_logout))

        # Window close
        self.ui_root.protocol("WM_DELETE_WINDOW", self.ui_root.destroy)

        # Initial hint
        self.ui_set_status("Ready · Choose an image or use defaults (test15/16/17).")
        self.ui_root.mainloop()

    # ======================
    # MAIN CLIENT LOOP
    # ======================
    def run(self):
        """Main client execution flow."""
        try:
            self.connect_to_server()
            if not self.client_socket:
                return

            self.show_splash()
            self.send_credentials()

            # Pull initial menu (sync point)
            self.receive_menu()

            # Launch GUI
            self.build_ui()

        except KeyboardInterrupt:
            print("\nClient shutting down...")
        except Exception as e:
            print(f"Fatal error: {e}")
        finally:
            if hasattr(self, 'client_socket') and self.client_socket:
                try:
                    self.client_socket.close()
                except:
                    pass


# ======================
# ENTRY POINT
# ======================
if __name__ == "__main__":
    print("Starting VeilGuard Client...")
    client = Client()
    client.run()
