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
        """Create a TCP socket and connect to the server defined in constants.py."""
        try:
            self.client_socket = socket.socket()
            self.client_socket.connect((IP, PORT))
            print("Connected to server at {}:{}".format(IP, PORT))
        except Exception as e:
            print("Connection failed: {}".format(e))
            self.client_socket = None

    # ======================
    # SPLASH
    # ======================
    def show_splash(self):
        """
        Show a 400x400 splash image for ~4 seconds, then close and continue.
        This runs in its own short Tk mainloop before the main UI.
        """
        root = tk.Tk()
        root.withdraw()  # Hide the main root

        splash = Toplevel(root)
        splash.geometry("400x400")
        splash.overrideredirect(True)

        # Update path to your splash image if needed
        img_path = r"C:\Users\shapi\Downloads\intro_img.png"
        try:
            logo = Image.open(img_path).resize((400, 400))
            logo_photo = ImageTk.PhotoImage(logo)
            label = Label(splash, image=logo_photo)
            label.image = logo_photo
            label.pack()
        except Exception:
            Label(splash, text="VeilGuard", font=("Segoe UI", 28)).pack(expand=True)

        def close_splash():
            splash.destroy()
            root.destroy()

        splash.after(4000, close_splash)
        root.mainloop()

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
        """
        Enable/disable the main action buttons while an operation runs.
        Also start/stop the spinner so the user knows something is happening.
        """
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

    # ======================
    # UI BUILD
    # ======================
    def build_ui(self):
        """Create the main window, top action bar, previews, and status bar."""
        self.ui_root = tk.Tk()
        self.ui_root.title("VeilGuard Client")
        self.ui_root.geometry("1000x660")
        self.ui_root.minsize(900, 560)

        self.create_styles()

        # Header
        header = ttk.Frame(self.ui_root, style="TopBar.TFrame")
        header.pack(side=tk.TOP, fill=tk.X)
        self.draw_gradient_header(header, width=self.ui_root.winfo_width(), height=92)

        # Action bar
        top = ttk.Frame(self.ui_root, style="TopBar.TFrame")
        top.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(8, 10))

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
        self.ui_root.mainloop()

    # ======================
    # UI UTILITIES
    # ======================
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

    def ui_run_async(self, target, *args, **kwargs):
        """
        Run any long operation in a background thread:
        - Disable buttons, show spinner
        - Re-enable and (optionally) re-sync menu at the end
        """
        def runner():
            try:
                self.ui_enable_controls(False)
                target(*args, **kwargs)
            finally:
                if not self.logged_out:
                    try:
                        self.receive_menu()
                    except Exception:
                        pass
                self.ui_enable_controls(True)
        threading.Thread(target=runner, daemon=True).start()

    # ======================
    # LOGIN / MENU
    # ======================
    def send_credentials(self):
        """
        Send username/password to the server.
        - If creds.txt exists -> read and use it.
        - Else -> open a small login window, then save to creds.txt.
        - If server says "PASSWORD INCORRECT" -> close and exit.
        """
        creds_file = "creds.txt"

        if os.path.exists(creds_file):
            with open(creds_file, "r") as f:
                lines = f.read().strip().split("\n")
                client_id = lines[0]
                password = lines[1]
        else:
            # Tiny login window
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

            client_id = creds.get("username", "")
            password = creds.get("password", "")

            with open(creds_file, "w") as f:
                f.write(client_id + "\n" + password)

        # Send encrypted
        self.encryptor.send_encrypted_message(self.client_socket, client_id)
        self.encryptor.send_encrypted_message(self.client_socket, password)

        # Read server response
        response = self.encryptor.receive_encrypted_message(self.client_socket)
        print(response)
        if "PASSWORD INCORRECT" in response:
            try:
                self.client_socket.close()
            except Exception:
                pass
            raise SystemExit()

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
        """
        Option 3 (User-selected blur with mouse, local):
        1) Send "3" and wait for the server's signal string.
        2) Open a small OpenCV editor:
           - Click and drag to draw a rectangle.
           - On release, that region is blurred immediately.
           - Repeat as needed. Press ESC to finish.
        3) Send ORIGINAL first (size + bytes), then FINAL (size + bytes).
        4) Receive the server echo-back of the FINAL image and show it on the right.
        """
        try:
            self.ui_set_status("Running: User ROI Blur... (use mouse; press ESC to finish)")
            self.encryptor.send_encrypted_message(self.client_socket, "3")

            signal = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(signal)

            # Load original (if user didn't choose -> ask to choose one now)
            if not self.selected_image_path or not os.path.exists(self.selected_image_path):
                self.choose_image_dialog()
                if not self.selected_image_path or not os.path.exists(self.selected_image_path):
                    raise RuntimeError("Please choose an image for User ROI Blur.")

            src = self.selected_image_path
            with open(src, "rb") as f:
                original_bytes = f.read()

            # Show original immediately on the left
            self.ui_show_preview(Image.open(io.BytesIO(original_bytes)).convert("RGB"), is_processed=False)

            img = cv2.imread(src)
            if img is None:
                raise FileNotFoundError("Image not found or cannot be opened!")

            img_display = img.copy()
            drawing = {"active": False, "ix": -1, "iy": -1}

            # Mouse callback: draw rect while dragging; blur region on release
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
                    # Normalize bounds (top-left to bottom-right)
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

            # Encode final as JPG bytes
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

            # Receive echo-back of FINAL and show on the right
            back_size = self.recv_size_or_error()
            rec = self._recv_exact(back_size)
            proc = Image.open(io.BytesIO(rec)).convert("RGB")
            self.ui_show_preview(proc, is_processed=True)
            self.ui_set_status("User ROI blur done.")
        except Exception as e:
            self.ui_set_status("User ROI blur failed: {}".format(e))

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
        """
        Main execution:
        - Connect
        - Splash
        - Login (creds popup if needed)
        - Pull menu once to sync
        - Build and run the main UI
        """
        try:
            self.connect_to_server()
            if not self.client_socket:
                return
            self.show_splash()
            self.send_credentials()
            self.receive_menu()   # initial sync
            self.build_ui()
        except KeyboardInterrupt:
            print("\nClient shutting down...")
        except Exception as e:
            print("Fatal error: {}".format(e))
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
