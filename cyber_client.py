"""
VeilGuard Client
----------------
A Tkinter-based client that connects to the VeilGuard server and runs 3 operations:

  1) Blur Faces (server-side, returns ORIGINAL then PROCESSED)
  2) Blur Background (server-side, returns ORIGINAL then PROCESSED)
  3) User ROI Blur (client-side editor with mouse; sends ORIGINAL and FINAL)

Key ideas:
- Encrypted communication using `Encryption` (send/receive strings + raw bytes).
- Splash screen before login.
- Simple login popup; credentials are saved to creds.txt for next time.
- Modern dark UI with two preview panels: Original (left) and Processed (right).
- Threading so the UI stays responsive while network operations run.
- If no image is selected by the user, the client sends "0" so the server uses
  one of its default images (test15/16/17 on the server folder).
- For options 1/2 the server returns ORIGINAL first and then PROCESSED, so
  the client can show both panels even when using server defaults.
"""

# ======================
# IMPORTS
# ======================
import json
import tkinter as tk
from tkinter import Toplevel, Label, filedialog, ttk
import socket
import os
import time
from PIL import Image, ImageTk
from constants import IP, PORT, CHUNK_SIZE
from encrypt import Encryption
import cv2
import numpy as np
import threading
import io
import subprocess
import sys


# ======================
# CLIENT CLASS
# ======================
class Client:
    def __init__(self):
        """
        Prepare:
        - Network socket + Encryption helper
        - UI state (selected image; labels for previews; status text; buttons)
        - Flags for clean shutdown on logout
        """
        self.client_socket = None
        self.encryptor = Encryption()

        # UI state
        self.logged_out = False
        self.ui_root = None
        self.selected_image_path = None
        self.preview_orig = None
        self.preview_proc = None
        self.status_var = None
        self.btns = {}
        self.spinner_label = None

        # Theme colors (set later by create_styles)
        self._bg = "#0f1115"
        self._panel = "#171923"
        self._panel_hi = "#222533"
        self._fg = "#e6e6e6"
        self._muted = "#a9a9b3"
        self._accent = "#7c3aed"

        # Spinner control
        self._spinner_job = None
        self._spinner_phase = 0

    # ======================
    # NETWORK
    # ======================
    def connect_to_server(self):
        try:
            self.client_socket = socket.socket()
            self.client_socket.connect((IP, PORT))
        except Exception:
            self.client_socket = None

    # ======================
    # SPLASH
    # ======================
    def show_splash(self, root):
        splash = Toplevel(root)
        splash.overrideredirect(True)
        splash.configure(bg="black")

        w, h = 900, 500
        x = (splash.winfo_screenwidth() - w) // 2
        y = (splash.winfo_screenheight() - h) // 2
        splash.geometry(f"{w}x{h}+{x}+{y}")

        label = tk.Label(splash, bg="black")
        label.pack(fill="both", expand=True)

        base_dir = os.path.dirname(os.path.abspath(__file__))
        video_path = os.path.join(base_dir, "intro_video.mp4")

        # fallback: אין וידאו -> סגור אחרי 1200ms
        if not os.path.exists(video_path):
            tk.Label(splash, text="VeilGuard", fg="white", bg="black",
                    font=("Segoe UI", 28, "bold")).place(relx=0.5, rely=0.5, anchor="center")
            root.after(1200, splash.destroy)
            return splash

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            tk.Label(splash, text="VeilGuard", fg="white", bg="black",
                    font=("Segoe UI", 28, "bold")).place(relx=0.5, rely=0.5, anchor="center")
            root.after(1200, splash.destroy)
            return splash

        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps < 5:
            fps = 30
        delay = int(1000 / fps)

        def tick():
            if not splash.winfo_exists():
                cap.release()
                return

            ok, frame = cap.read()
            if not ok:
                cap.release()
                splash.destroy()
                return

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, (w, h))
            img = ImageTk.PhotoImage(Image.fromarray(frame))
            label.configure(image=img)
            label.image = img
            root.after(delay, tick)

        tick()
        return splash



    # ======================
    # STYLE / UI HELPERS
    # ======================
    def create_styles(self):
        """Apply a simple dark theme to ttk widgets."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self._bg = "#0f1115"
        self._panel = "#171923"
        self._panel_hi = "#222533"
        self._fg = "#e6e6e6"
        self._muted = "#a9a9b3"
        self._accent = "#7c3aed"

        # Base window background
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
        """
        Draw a simple left->right gradient as a header with the app title.
        This is purely cosmetic to make the UI look more modern.
        """
        canvas = tk.Canvas(parent, height=height, width=width, highlightthickness=0, bd=0, bg=self._bg)
        canvas.pack(fill=tk.X, expand=False)

        # Gradient from purple accent to dark bg
        start = (124, 58, 237)  # #7c3aed
        end = (15, 17, 21)      # #0f1115
        steps = width
        for i in range(steps):
            r = int(start[0] + (end[0] - start[0]) * (i / float(steps)))
            g = int(start[1] + (end[1] - start[1]) * (i / float(steps)))
            b = int(start[2] + (end[2] - start[2]) * (i / float(steps)))
            canvas.create_line(i, 0, i, height, fill="#%02x%02x%02x" % (r, g, b))

        canvas.create_text(22, height // 2, anchor="w",
                           text="VeilGuard — Image Privacy Client",
                           fill="white",
                           font=("Segoe UI Semibold", 18))
        return canvas

    def show_toast(self, text, ms=1800):
        """
        Small floating message (like a toast). Optional nice feedback for the user.
        """
        toast = tk.Toplevel(self.ui_root)
        toast.overrideredirect(True)
        toast.configure(bg=self._panel)
        lbl = tk.Label(toast, text=text, bg=self._panel, fg=self._fg, font=("Segoe UI", 10), padx=14, pady=8)
        lbl.pack()
        # Position near bottom-right
        self.ui_root.update_idletasks()
        x = self.ui_root.winfo_x() + self.ui_root.winfo_width() - toast.winfo_reqwidth() - 20
        y = self.ui_root.winfo_y() + self.ui_root.winfo_height() - toast.winfo_reqheight() - 40
        toast.geometry("+{}+{}".format(x, y))
        toast.after(ms, toast.destroy)

    # Spinner animation (3 dots) for long operations
    def spinner_start(self):
        if self._spinner_job:
            return
        self._spinner_phase = 0

        def tick():
            dots = ["", ".", "..", "..."]
            try:
                self.spinner_label.config(text=dots[self._spinner_phase])
            except Exception:
                pass
            self._spinner_phase = (self._spinner_phase + 1) % len(dots)
            self._spinner_job = self.ui_root.after(300, tick)
        tick()

    def spinner_stop(self):
        if self._spinner_job:
            try:
                self.ui_root.after_cancel(self._spinner_job)
            except Exception:
                pass
            self._spinner_job = None
        if self.spinner_label:
            try:
                self.spinner_label.config(text="")
            except Exception:
                pass

    class Tooltip:
        """Very small tooltip helper (hover text)."""
        def __init__(self, widget, text):
            self.widget = widget
            self.text = text
            self.tip = None
            widget.bind("<Enter>", self.show)
            widget.bind("<Leave>", self.hide)
        def show(self, _=None):
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
            self.tip.geometry("+{}+{}".format(x, y))
        def hide(self, _=None):
            if self.tip:
                self.tip.destroy()
                self.tip = None

    def ui_set_status(self, msg):
        """Thread-safe: update the bottom status label from any thread."""
        if self.status_var:
            def _set():
                self.status_var.set(msg)
            self.ui_root.after(0, _set)

    def ui_enable_controls(self, enable):
        def _apply():
            state = tk.NORMAL if enable else tk.DISABLED
            for b in self.btns.values():
                try:
                    b.config(state=state)
                except Exception:
                    pass
            if enable:
                self.spinner_stop()
            else:
                self.spinner_start()

        if self.ui_root:
            self.ui_root.after(0, _apply)


    # ======================
    # UI BUILD
    # ======================
    def build_ui(self, root):
        """Create the main window, top action bar, previews, and status bar."""
        self.ui_root = root
        self.ui_root.title("VeilGuard Client")
        self.ui_root.geometry("1000x660")
        self.ui_root.minsize(900, 560)

        self.create_styles()

        # Header
        header = ttk.Frame(self.ui_root, style="TopBar.TFrame")
        header.pack(side=tk.TOP, fill=tk.X)
        self.ui_root.update_idletasks()
        self.draw_gradient_header(header, width=self.ui_root.winfo_width(), height=92)

        # Action bar
        top = ttk.Frame(self.ui_root, style="TopBar.TFrame")
        top.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(8, 10))
        self.btns["capture"] = ttk.Button(
        top, text="📸  Capture from Camera",
        style="Action.TButton",
        command=lambda: self.ui_run_async(self.ui_capture_camera, needs_menu_sync=False)
        )
        self.btns["capture"].pack(side=tk.LEFT, padx=6)


        Client.Tooltip(self.btns["capture"], "Take a photo using your webcam")


        self.btns["choose"] = ttk.Button(top, text="📂  Choose Image",
                                         style="Action.TButton",
                                         command=self.choose_image_dialog)
        self.btns["choose"].pack(side=tk.LEFT, padx=6)

        self.btns["face"] = ttk.Button(top, text="🎭  Blur Faces",
                                       style="Action.TButton",
                                       command=lambda: self.ui_run_async(self.ui_do_face))
        self.btns["face"].pack(side=tk.LEFT, padx=6)

        self.btns["bg"] = ttk.Button(top, text="🖼️  Blur Background",
                                     style="Action.TButton",
                                     command=lambda: self.ui_run_async(self.ui_do_bg))
        self.btns["bg"].pack(side=tk.LEFT, padx=6)

        self.btns["user"] = ttk.Button(top, text="✂️  User ROI Blur",
                                       style="Action.TButton",
                                       command=lambda: self.ui_run_async(self.ui_do_user))
        self.btns["user"].pack(side=tk.LEFT, padx=6)

        self.btns["logout"] = ttk.Button(top, text="🚪  Logout",
                                         style="Action.TButton",
                                         command=lambda: self.ui_run_async(self.ui_do_logout))
        self.btns["logout"].pack(side=tk.RIGHT, padx=6)

        # Tooltips
        Client.Tooltip(self.btns["choose"], "Pick an image from disk")
        Client.Tooltip(self.btns["face"], "Detect and blur all faces (server-side)")
        Client.Tooltip(self.btns["bg"], "Blur the background; keep people sharp (server-side)")
        Client.Tooltip(self.btns["user"], "Draw rectangles to blur areas; press ESC to finish (client-side)")
        Client.Tooltip(self.btns["logout"], "Close session and exit")

        # Main content (two cards)
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

        # Status bar + spinner
        bottom = ttk.Frame(self.ui_root)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=10)
        self.status_var = tk.StringVar(value="Ready · Choose an image or use server defaults.")
        ttk.Label(bottom, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT)
        self.spinner_label = ttk.Label(bottom, text="", style="Status.TLabel")
        self.spinner_label.pack(side=tk.RIGHT)

        # Window close
        self.ui_root.protocol("WM_DELETE_WINDOW", self.ui_root.destroy)
        

    # ======================
    # UI UTILITIES
    # ======================
    def ui_capture_camera(self):
        """
        Capture a single image from the computer's webcam.
        Saves it as 'captured.jpg' and sets it as the selected image.
        """
        try:
            self.ui_set_status("Opening camera...")
            cap = cv2.VideoCapture(0)

            if not cap.isOpened():
                self.ui_set_status("❌ Failed to access the camera.")
                return

            self.ui_set_status("Press SPACE to capture, ESC to cancel.")

            while True:
                ret, frame = cap.read()
                if not ret:
                    self.ui_set_status("❌ Camera read failed.")
                    break

                cv2.imshow("Press SPACE to capture / ESC to cancel", frame)
                key = cv2.waitKey(1) & 0xFF

                if key == 27:  # ESC
                    self.ui_set_status("Camera capture canceled.")
                    break
                elif key == 32:  # SPACE
                    # Save the captured image
                    save_path = os.path.join(os.getcwd(), "captured.jpg")
                    cv2.imwrite(save_path, frame)
                    self.selected_image_path = save_path
                    self.ui_set_status(f"Captured and selected image: {save_path}")

                    # Show the captured image in the left preview
                    img = Image.open(save_path)
                    self.ui_show_preview(img, is_processed=False)
                    break

            cap.release()
            cv2.destroyAllWindows()

        except Exception as e:
            self.ui_set_status(f"Camera capture failed: {e}")
            try:
                cap.release()
            except Exception:
                pass
            cv2.destroyAllWindows()

    def choose_image_dialog(self):
        """
        Let the user pick an image. If successful, show it immediately on the left panel.
        If the user doesn't pick, operations 1/2 will use server defaults.
        """
        fp = filedialog.askopenfilename(
            title="Choose image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.gif"), ("All", "*.*")]
        )
        if fp:
            self.selected_image_path = fp
            self.ui_set_status("Selected image: {}".format(fp))
            try:
                img = Image.open(fp)
                self.ui_show_preview(img, is_processed=False)
            except Exception as e:
                self.ui_set_status("Failed to open image: {}".format(e))

    def ui_show_preview(self, pil_img, is_processed):
        """
        Show a PIL image inside the left (Original) or right (Processed) panel.
        The image is resized (thumbnail) to fit nicely.
        """
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

    def ui_run_async(self, target, *args, needs_menu_sync=True, **kwargs):
        """
        Run any long operation in a background thread:
        - Disable buttons, show spinner
        - Optionally sync the server menu at the end (only for network ops)
        """
        def runner():
            try:
                self.ui_enable_controls(False)
                target(*args, **kwargs)
            finally:
                if not self.logged_out and needs_menu_sync:
                    try:
                        self.receive_menu()
                    except Exception:
                        pass
                self.ui_enable_controls(True)
        threading.Thread(target=runner, daemon=True).start()

    # ======================
    # LOGIN / MENU
    # ======================
    def upgraded_login_dialog(self, parent, remember_path="creds.txt"):
        """
        Modal login dialog (Toplevel). Returns (username, password) or (None, None).
        """
        win = tk.Toplevel(parent)
        win.title("VeilGuard Login")
        win.geometry("420x260")
        win.resizable(False, False)
        win.configure(bg="#111318")
        win.transient(parent)
        win.grab_set()
        win.lift()
        win.attributes("-topmost", True)
        win.after(200, lambda: win.attributes("-topmost", False))
        # ---- Load remembered username ----
        saved_user = ""
        if os.path.exists(remember_path):
            try:
                with open(remember_path, "r", encoding="utf-8") as f:
                    saved_user = f.readline().strip()
            except Exception:
                pass

        frame = tk.Frame(win, bg="#111318")
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(frame, text="VeilGuard", font=("Segoe UI", 18, "bold"),
                bg="#111318", fg="white").pack(anchor="w", pady=(0, 12))

        tk.Label(frame, text="Username", bg="#111318", fg="white").pack(anchor="w")
        user_var = tk.StringVar(value=saved_user)
        user_entry = tk.Entry(frame, textvariable=user_var, font=("Segoe UI", 11))
        user_entry.pack(fill="x", pady=(4, 10))

        tk.Label(frame, text="Password", bg="#111318", fg="white").pack(anchor="w")
        pass_var = tk.StringVar()
        pass_entry = tk.Entry(frame, textvariable=pass_var, show="*", font=("Segoe UI", 11))
        pass_entry.pack(fill="x", pady=(4, 6))

        show_var = tk.BooleanVar()
        def toggle_show():
            pass_entry.config(show="" if show_var.get() else "*")

        tk.Checkbutton(
            frame, text="Show password", variable=show_var,
            command=toggle_show, bg="#111318", fg="white",
            activebackground="#111318", selectcolor="#111318"
        ).pack(anchor="w")

        err_label = tk.Label(frame, text="", fg="#ff6b6b", bg="#111318")
        err_label.pack(anchor="w", pady=(6, 0))

        result = {"u": None, "p": None}

        def submit():
            u = user_var.get().strip()
            p = pass_var.get()
            if not u:
                err_label.config(text="Username is required.")
                return
            if not p:
                err_label.config(text="Password is required.")
                return
            result["u"] = u
            result["p"] = p
            win.destroy()

        def cancel():
            win.destroy()

        btns = tk.Frame(frame, bg="#111318")
        btns.pack(fill="x", pady=(14, 0))

        tk.Button(btns, text="Login", command=submit, width=10).pack(side="right")
        tk.Button(btns, text="Cancel", command=cancel, width=10).pack(side="right", padx=6)

        user_entry.focus_set()
        win.bind("<Return>", lambda e: submit())
        win.bind("<Escape>", lambda e: cancel())

        parent.wait_window(win)
        return result["u"], result["p"]
    
    def send_credentials(self, parent):
        creds_file = "creds.txt"

        client_id = ""
        password = ""

        if os.path.exists(creds_file):
            try:
                with open(creds_file, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
                if len(lines) >= 2:
                    client_id = lines[0].strip()
                    password = lines[1].strip()
            except Exception:
                pass

        if not client_id or not password:
            client_id, password = self.upgraded_login_dialog(parent, creds_file)
            if not client_id:
                return False
            try:
                with open(creds_file, "w", encoding="utf-8") as f:
                    f.write(client_id + "\n" + password)
            except Exception:
                pass

        try:
            self.encryptor.send_encrypted_message(self.client_socket, client_id)
            self.encryptor.send_encrypted_message(self.client_socket, password)
            response = self.encryptor.receive_encrypted_message(self.client_socket)
        except Exception:
            return False

        if not response:
            return False

        if "PASSWORD INCORRECT" in response:
            try:
                if os.path.exists(creds_file):
                    os.remove(creds_file)
            except Exception:
                pass
            return False

        return True



    def receive_menu(self):
        """
        Read and print the server textual menu. This keeps both sides "in sync"
        after each operation. Not strictly needed for the UI, but useful.
        """
        try:
            menu = self.encryptor.receive_encrypted_message(self.client_socket)
            print("\nAvailable operations:")
            print(menu)
            return menu
        except Exception as e:
            print("Menu error: {}".format(e))
            return None

    # ======================
    # LOW-LEVEL IO HELPERS
    # ======================
    def pick_source_path(self):
        """
        Return a path to an image for processing if available, else None.
        """
        if self.selected_image_path and os.path.exists(self.selected_image_path):
            return self.selected_image_path

        for p in getattr(self, "usual_images", []):
            if os.path.exists(p):
                return p

        return None  # חשוב: לא לזרוק שגיאה

    def _recv_exact(self, n):
        """
        Receive exactly n bytes from the socket (or until the socket closes).
        We loop until we collect n bytes (or the peer closes).
        """
        buf = b""
        while len(buf) < n:
            chunk = self.client_socket.recv(min(4096, n - len(buf)))
            if not chunk:
                break
            buf += chunk
        return buf

    def recv_size_or_error(self):
        """
        Read a size string from the server. If the server sent an error message
        that starts with "[ERROR]", raise RuntimeError. Otherwise, convert to int.
        """
        s = self.encryptor.receive_encrypted_message(self.client_socket)
        if s.startswith("[ERROR]"):
            raise RuntimeError(s)
        return int(s)

    # ======================
    # OPERATIONS (UI-ACTIONS)
    # ======================
    def ui_do_face(self):
        """
        Option 1 (Blur Faces):
        1) Send "1" to select the operation.
        2) If the user selected an image -> send its size and bytes.
           Otherwise -> send "0" so the server uses a default image.
        3) Receive ORIGINAL first (size + bytes), display it on the left panel.
        4) Receive PROCESSED next (size + bytes), display it on the right panel.
        """
        try:
            self.ui_set_status("Running: Blur Faces...")
            self.encryptor.send_encrypted_message(self.client_socket, "1")

            # Use selected image if exists; otherwise let server use default
            src = self.selected_image_path if (self.selected_image_path and os.path.exists(self.selected_image_path)) else None
            if src:
                with open(src, "rb") as f:
                    data = f.read()
                self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
                ack = self.encryptor.receive_encrypted_message(self.client_socket)
                self.ui_set_status(ack)
                self.client_socket.sendall(data)
            else:
                self.encryptor.send_encrypted_message(self.client_socket, "0")
                ack = self.encryptor.receive_encrypted_message(self.client_socket)
                self.ui_set_status(ack)

            # ORIGINAL first
            orig_size = self.recv_size_or_error()
            orig_bytes = self._recv_exact(orig_size)
            orig_img = Image.open(io.BytesIO(orig_bytes)).convert("RGB")
            self.ui_show_preview(orig_img, is_processed=False)

            # PROCESSED second
            out_size = self.recv_size_or_error()
            out_bytes = self._recv_exact(out_size)
            proc_img = Image.open(io.BytesIO(out_bytes)).convert("RGB")
            self.ui_show_preview(proc_img, is_processed=True)

            self.ui_set_status("Faces blurred successfully.")
        except Exception as e:
            self.ui_set_status("Face blur failed: {}".format(e))

    def ui_do_bg(self):
        """
        Option 2 (Blur Background):
        Same IO flow as option 1:
          - Send "2"
          - Send image size+bytes OR "0" to use server default
          - Receive ORIGINAL first (show on the left)
          - Receive PROCESSED next (show on the right)
        """
        try:
            self.ui_set_status("Running: Blur Background...")
            self.encryptor.send_encrypted_message(self.client_socket, "2")

            src = self.selected_image_path if (self.selected_image_path and os.path.exists(self.selected_image_path)) else None
            if src:
                with open(src, "rb") as f:
                    data = f.read()
                self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
                ack = self.encryptor.receive_encrypted_message(self.client_socket)
                self.ui_set_status(ack)
                self.client_socket.sendall(data)
            else:
                self.encryptor.send_encrypted_message(self.client_socket, "0")
                ack = self.encryptor.receive_encrypted_message(self.client_socket)
                self.ui_set_status(ack)

            # ORIGINAL first
            orig_size = self.recv_size_or_error()
            orig_bytes = self._recv_exact(orig_size)
            orig_img = Image.open(io.BytesIO(orig_bytes)).convert("RGB")
            self.ui_show_preview(orig_img, is_processed=False)

            # PROCESSED second
            out_size = self.recv_size_or_error()
            out_bytes = self._recv_exact(out_size)
            proc_img = Image.open(io.BytesIO(out_bytes)).convert("RGB")
            self.ui_show_preview(proc_img, is_processed=True)

            self.ui_set_status("Background blurred successfully.")
        except Exception as e:
            self.ui_set_status("Background blur failed: {}".format(e))

   

    def ui_do_user(self):
        try:
            self.ui_set_status("Running: User ROI (server-side)...")
            self.encryptor.send_encrypted_message(self.client_socket, "3")

            # 1) READY
            _ = self.encryptor.receive_encrypted_message(self.client_socket)

            # 2) מקור תמונה
            src_path = self.pick_source_path()
            if src_path is None:
                self.encryptor.send_encrypted_message(self.client_socket, "0")
            else:
                with open(src_path, "rb") as f:
                    data = f.read()
                self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
                ack = self.encryptor.receive_encrypted_message(self.client_socket)  # "[INFO] Send the image..."
                self.client_socket.sendall(data)

            # 3) קבלת ORIGINAL לתצוגה ולבחירת ROI
            orig_size = self.recv_size_or_error()
            orig_bytes = self._recv_exact(orig_size)
            orig_pil = Image.open(io.BytesIO(orig_bytes)).convert("RGB")
            self.ui_show_preview(orig_pil, is_processed=False)

            img_bgr = cv2.imdecode(np.frombuffer(orig_bytes, np.uint8), cv2.IMREAD_COLOR)
            if img_bgr is None:
                raise RuntimeError("Failed to decode ORIGINAL")

            # 4) בחירת מלבנים (ENTER לאישור, ESC לביטול)
            cv2.namedWindow("Draw ROIs (ENTER=OK, ESC=cancel)", cv2.WINDOW_NORMAL)
            rois = cv2.selectROIs("Draw ROIs (ENTER=OK, ESC=cancel)", img_bgr, False, False)
            cv2.destroyAllWindows()

            rects = []
            if rois is not None and len(rois) > 0:
                for (x, y, w, h) in rois:
                    if int(w) > 0 and int(h) > 0:
                        rects.append([int(x), int(y), int(w), int(h)])

            # 5) שליחת ה-ROI לשרת (כ-JSON)
            self.encryptor.send_encrypted_message(self.client_socket, "[C_RECTS]")
            self.encryptor.send_encrypted_message(self.client_socket, json.dumps(rects))

            # 6) קבלת PROCESSED מהשרת והצגה
            out_size = self.recv_size_or_error()
            out_bytes = self._recv_exact(out_size)
            proc_img = Image.open(io.BytesIO(out_bytes)).convert("RGB")
            self.ui_show_preview(proc_img, is_processed=True)

            self.ui_set_status("User ROI: processed on server.")
        except Exception as e:
            self.ui_set_status(f"User ROI server-side blur failed: {e}")


    def ui_do_logout(self):
        """
        Option 4 (Logout):
        - Send "4" to the server and read its final message.
        - Mark logged_out, close socket, close UI after a short delay.
        """
        try:
            self.ui_set_status("Logging out...")
            self.encryptor.send_encrypted_message(self.client_socket, "4")
            msg = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(msg)
        finally:
            self.logged_out = True
            try:
                self.client_socket.close()
            except Exception:
                pass
            self.ui_root.after(500, self.ui_root.destroy)

    # ======================
    # MAIN FLOW
    # ======================
    def run(self):
        try:
            self.connect_to_server()
            if not self.client_socket:
                return

            # ROOT יחיד לכל התוכנית
            root = tk.Tk()
            root.withdraw()  # מסתירים עד שמסיימים ספלאש+לוגין

            # ספלאש וידאו (על אותו root)
            splash = self.show_splash(root)

            # כשהספלאש נסגר -> עושים login -> ואז פותחים UI
            def after_splash():
                # אם הספלאש כבר נהרס, לפעמים winfo_exists זורק TclError
                try:
                    alive = splash.winfo_exists()
                except tk.TclError:
                    alive = 0

                if alive:
                    root.after(100, after_splash)
                    return
                root.deiconify()
                root.lift()
                root.attributes("-topmost", True)
                root.after(200, lambda: root.attributes("-topmost", False))
                # עכשיו ממשיכים ללוגין
                ok = self.send_credentials(root)
                if not ok:
                    try:
                        if self.client_socket:
                            self.client_socket.close()
                    except Exception:
                        pass
                    root.destroy()
                    return

                self.receive_menu()

                root.deiconify()
                self.build_ui(root)


            after_splash()
            root.mainloop()

        except Exception as e:
            print("Fatal error:", e)
        finally:
            if self.client_socket:
                try:
                    self.client_socket.close()
                except Exception:
                    pass



# ======================
# ENTRY POINT
# ======================
if __name__ == "__main__":
    print("Starting VeilGuard Client...")
    client = Client()
    client.run()
