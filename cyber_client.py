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
import qrcode
import json
import tkinter as tk
from tkinter import Toplevel, Label, filedialog, ttk, messagebox
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
        """Draw a simple left->right gradient as a header with the app title."""
        canvas = tk.Canvas(parent, height=height, width=width, highlightthickness=0, bd=0, bg=self._bg)
        canvas.pack(fill=tk.X, expand=False)

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
        toast = tk.Toplevel(self.ui_root)
        toast.overrideredirect(True)
        toast.configure(bg=self._panel)
        lbl = tk.Label(toast, text=text, bg=self._panel, fg=self._fg, font=("Segoe UI", 10), padx=14, pady=8)
        lbl.pack()
        self.ui_root.update_idletasks()
        x = self.ui_root.winfo_x() + self.ui_root.winfo_width() - toast.winfo_reqwidth() - 20
        y = self.ui_root.winfo_y() + self.ui_root.winfo_height() - toast.winfo_reqheight() - 40
        toast.geometry("+{}+{}".format(x, y))
        toast.after(ms, toast.destroy)

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
    def show_2fa_setup_dialog(self, parent, username, secret):
        """Creates a popup displaying the 2FA QR code for Google Authenticator."""
        qr_win = tk.Toplevel(parent)
        qr_win.title("2FA Setup Required")
        qr_win.geometry("400x550")
        qr_win.resizable(False, False)
        qr_win.configure(bg="#0b0f19")
        qr_win.transient(parent)
        qr_win.grab_set()

        tk.Label(qr_win, text="Secure Your Account", font=("Segoe UI", 18, "bold"), 
                 bg="#0b0f19", fg="#00ffcc").pack(pady=(20, 5))
        tk.Label(qr_win, text="Scan this QR code with Google Authenticator", 
                 font=("Segoe UI", 10), bg="#0b0f19", fg="#94a3b8").pack()

        uri = f"otpauth://totp/VeilGuard:{username}?secret={secret}&issuer=VeilGuard"
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(uri)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="#ffffff", back_color="#1e293b").convert('RGB')
        qr_photo = ImageTk.PhotoImage(qr_img)

        qr_label = tk.Label(qr_win, image=qr_photo, bg="#0b0f19", bd=0)
        qr_label.image = qr_photo  
        qr_label.pack(pady=20)

        tk.Label(qr_win, text="Or enter this code manually:", 
                 font=("Segoe UI", 9), bg="#0b0f19", fg="#94a3b8").pack()
        
        secret_entry = tk.Entry(qr_win, font=("Consolas", 14, "bold"), bg="#1e293b", fg="#00ffcc", 
                                bd=0, justify="center", width=20)
        secret_entry.insert(0, secret)
        secret_entry.config(state="readonly")
        secret_entry.pack(pady=5, ipady=5)

        tk.Button(qr_win, text="I'VE SCANNED IT", command=qr_win.destroy,
                  bg="#7c3aed", fg="white", font=("Segoe UI", 11, "bold"), bd=0,
                  activebackground="#6d28d9", activeforeground="white", cursor="hand2").pack(fill="x", padx=50, pady=30, ipady=8)

        parent.wait_window(qr_win)
        
    def build_ui(self, root):
        self.ui_root = root
        self.ui_root.title("VeilGuard Client")
        self.ui_root.geometry("1000x660")
        self.ui_root.minsize(900, 560)

        self.create_styles()

        header = ttk.Frame(self.ui_root, style="TopBar.TFrame")
        header.pack(side=tk.TOP, fill=tk.X)
        self.ui_root.update_idletasks()
        self.draw_gradient_header(header, width=self.ui_root.winfo_width(), height=92)

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

        slider_frame = tk.Frame(top, bg=self._bg)
        slider_frame.pack(side=tk.LEFT, padx=20)
        
        tk.Label(slider_frame, text="Blur Level:", fg=self._muted, bg=self._bg, 
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=5)
        
        self.blur_slider = tk.Scale(slider_frame, from_=1, to=10, orient=tk.HORIZONTAL,
                                   bg=self._bg, fg=self._accent, highlightthickness=0,
                                   troughcolor=self._panel, activebackground=self._accent,
                                   font=("Segoe UI", 9), length=150, showvalue=True)
        self.blur_slider.set(5) 
        self.blur_slider.pack(side=tk.LEFT)

        Client.Tooltip(self.btns["choose"], "Pick an image from disk")
        Client.Tooltip(self.btns["face"], "Detect and blur all faces (server-side)")
        Client.Tooltip(self.btns["bg"], "Blur the background; keep people sharp (server-side)")
        Client.Tooltip(self.btns["user"], "Draw rectangles to blur areas; press ESC to finish (client-side)")
        Client.Tooltip(self.btns["logout"], "Close session and exit")

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

        bottom = ttk.Frame(self.ui_root)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=10)
        self.status_var = tk.StringVar(value="Ready · Choose an image or use server defaults.")
        ttk.Label(bottom, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT)
        self.spinner_label = ttk.Label(bottom, text="", style="Status.TLabel")
        self.spinner_label.pack(side=tk.RIGHT)

        self.ui_root.protocol("WM_DELETE_WINDOW", self.ui_root.destroy)

    # ======================
    # UI UTILITIES
    # ======================
    def ui_capture_camera(self):
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
                    save_path = os.path.join(os.getcwd(), "captured.jpg")
                    cv2.imwrite(save_path, frame)
                    self.selected_image_path = save_path
                    self.ui_set_status(f"Captured and selected image: {save_path}")

                    img = Image.open(save_path)
                    self.ui_show_preview(img, is_processed=False)
                    break
            cap.release()
            cv2.destroyAllWindows()
        except Exception as e:
            self.ui_set_status(f"Camera capture failed: {e}")
            try: cap.release()
            except: pass
            cv2.destroyAllWindows()

    def choose_image_dialog(self):
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
        def runner():
            try:
                self.ui_enable_controls(False)
                target(*args, **kwargs)
            finally:
                if not self.logged_out and needs_menu_sync:
                    try: self.receive_menu()
                    except: pass
                self.ui_enable_controls(True)
        threading.Thread(target=runner, daemon=True).start()

    # ======================
    # LOGIN / MENU UI
    # ======================
    def upgraded_login_dialog(self, parent, initial_error=""):
        """Ultra-modern UI for Login/Register with a 'Cyber' aesthetic."""
        self.login_win = tk.Toplevel(parent)
        self.login_win.title("VeilGuard | Secure Access")
        self.login_win.geometry("450x700") 
        self.login_win.resizable(False, False)
        
        BG_COLOR = "#050810"       
        INPUT_BG = "#111827"       
        FG_COLOR = "#ffffff"       
        ACCENT_COLOR = "#00ffcc"   
        ACCENT_HOVER = "#00ccaa"   
        MUTED_TEXT = "#64748b"     
        
        self.login_win.configure(bg=BG_COLOR)
        self.login_win.transient(parent)
        self.login_win.grab_set()

        self.is_login_mode = False  
        self.login_result = {"action": None, "u": None, "p": None, "totp": None}

        canvas = tk.Canvas(self.login_win, width=450, height=700, bg=BG_COLOR, highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        canvas.create_line(0, 150, 450, 50, fill="#1e293b", width=2)
        canvas.create_line(0, 600, 450, 650, fill="#1e293b", width=2)

        main_frame = tk.Frame(canvas, bg=BG_COLOR)
        main_frame.place(relx=0.5, rely=0.5, anchor="center", width=380)
        
        self.title_var = tk.StringVar(value="SYSTEM INITIALIZE")
        self.submit_btn_text = tk.StringVar(value="REGISTER ENTITY")
        self.toggle_btn_text = tk.StringVar(value="[ Switch to Login Protocol ]")

        tk.Label(main_frame, text="VEILGUARD", font=("Consolas", 26, "bold", "italic"),
                 bg=BG_COLOR, fg=ACCENT_COLOR).pack(anchor="center", pady=(0, 5))
        tk.Label(main_frame, textvariable=self.title_var, font=("Segoe UI", 12, "bold"),
                 bg=BG_COLOR, fg="#ffffff").pack(anchor="center", pady=(0, 20))

        self.err_label = tk.Label(main_frame, text=initial_error, fg="#ff0055", bg=BG_COLOR, font=("Consolas", 10, "bold"))
        self.err_label.pack(anchor="center", pady=(0, 10))

        tk.Label(main_frame, text="IDENTIFIER (USERNAME)", bg=BG_COLOR, fg=MUTED_TEXT, font=("Consolas", 9, "bold")).pack(anchor="w")
        u_frame = tk.Frame(main_frame, bg=INPUT_BG, bd=1, highlightthickness=1, highlightbackground="#334155")
        u_frame.pack(fill="x", pady=(2, 15))
        self.user_var = tk.StringVar()
        user_entry = tk.Entry(u_frame, textvariable=self.user_var, font=("Segoe UI", 12), bg=INPUT_BG, fg=FG_COLOR, bd=0, insertbackground=ACCENT_COLOR)
        user_entry.pack(fill="x", padx=10, ipady=6)
        
        user_entry.bind("<FocusIn>", lambda e: u_frame.config(highlightbackground=ACCENT_COLOR))
        user_entry.bind("<FocusOut>", lambda e: u_frame.config(highlightbackground="#334155"))

        tk.Label(main_frame, text="SECURITY KEY (PASSWORD)", bg=BG_COLOR, fg=MUTED_TEXT, font=("Consolas", 9, "bold")).pack(anchor="w")
        p_frame = tk.Frame(main_frame, bg=INPUT_BG, bd=1, highlightthickness=1, highlightbackground="#334155")
        p_frame.pack(fill="x", pady=(2, 5))
        self.pass_var = tk.StringVar()
        pass_entry = tk.Entry(p_frame, textvariable=self.pass_var, show="•", font=("Segoe UI", 12), bg=INPUT_BG, fg=FG_COLOR, bd=0, insertbackground=ACCENT_COLOR)
        pass_entry.pack(fill="x", padx=10, ipady=6)
        
        pass_entry.bind("<FocusIn>", lambda e: p_frame.config(highlightbackground=ACCENT_COLOR))
        pass_entry.bind("<FocusOut>", lambda e: p_frame.config(highlightbackground="#334155"))

        self.show_var = tk.BooleanVar()
        tk.Checkbutton(main_frame, text="Reveal Security Key", variable=self.show_var,
                       command=lambda: pass_entry.config(show="" if self.show_var.get() else "•"),
                       bg=BG_COLOR, fg=MUTED_TEXT, activebackground=BG_COLOR, activeforeground=FG_COLOR,
                       selectcolor=BG_COLOR, cursor="hand2", font=("Consolas", 9)).pack(anchor="w", pady=(0, 15))

        self.totp_label = tk.Label(main_frame, text="2FA AUTHENTICATION CODE", bg=BG_COLOR, fg=ACCENT_COLOR, font=("Consolas", 9, "bold"))
        self.totp_frame = tk.Frame(main_frame, bg=INPUT_BG, bd=1, highlightthickness=1, highlightbackground=ACCENT_COLOR)
        self.totp_var = tk.StringVar()
        self.totp_entry = tk.Entry(self.totp_frame, textvariable=self.totp_var, font=("Segoe UI", 16, "bold"), bg=INPUT_BG, fg=FG_COLOR, bd=0, insertbackground=ACCENT_COLOR, justify="center")
        self.totp_entry.pack(fill="x", padx=10, ipady=6)

        self.submit_btn = tk.Button(main_frame, textvariable=self.submit_btn_text, command=self._on_login_submit,
                               bg=ACCENT_COLOR, fg="#000000", font=("Consolas", 14, "bold"), bd=0,
                               activebackground=ACCENT_HOVER, activeforeground="#000000", cursor="hand2")
        self.submit_btn.pack(fill="x", pady=(20, 15), ipady=8)

        self.toggle_btn = tk.Button(main_frame, textvariable=self.toggle_btn_text, command=self._on_login_toggle,
                  bg=BG_COLOR, fg=MUTED_TEXT, activebackground=BG_COLOR, activeforeground=ACCENT_COLOR,
                  relief="flat", bd=0, cursor="hand2", font=("Consolas", 10))
        self.toggle_btn.pack(anchor="center")

        user_entry.focus_set()
        self.login_win.bind("<Return>", lambda e: self._on_login_submit())
        self.login_win.bind("<Escape>", lambda e: self._on_login_cancel())
        
        parent.wait_window(self.login_win)
        return self.login_result
    
    def _on_login_toggle(self):
        self.is_login_mode = not self.is_login_mode
        self.err_label.config(text="") 
        
        self.submit_btn.pack_forget()
        self.toggle_btn.pack_forget()
        
        if self.is_login_mode:
            self.title_var.set("AUTHENTICATION REQUIRED")
            self.submit_btn_text.set("AUTHORIZE ACCESS")
            self.toggle_btn_text.set("[ Switch to Registration Protocol ]")
            
            self.totp_label.pack(anchor="w", pady=(5, 0))
            self.totp_frame.pack(fill="x", pady=(2, 10))
        else:
            self.title_var.set("SYSTEM INITIALIZE")
            self.submit_btn_text.set("REGISTER ENTITY")
            self.toggle_btn_text.set("[ Switch to Login Protocol ]")
            
            self.totp_label.pack_forget()
            self.totp_frame.pack_forget()
            
        self.submit_btn.pack(fill="x", pady=(20, 15), ipady=8)
        self.toggle_btn.pack(anchor="center")

    def _on_login_submit(self):
        u, p = self.user_var.get().strip(), self.pass_var.get()
        totp_val = self.totp_var.get().strip()
        
        if not u or not p:
            self.err_label.config(text="ERROR: ALL FIELDS ARE REQUIRED.")
            return
            
        if self.is_login_mode and not totp_val:
            self.err_label.config(text="ERROR: 2FA CODE IS REQUIRED.")
            return
            
        self.login_result["action"] = "LOGIN" if self.is_login_mode else "REGISTER"
        self.login_result["u"] = u
        self.login_result["p"] = p
        self.login_result["totp"] = totp_val
        self.login_win.destroy()
        
    def _on_login_cancel(self):
        self.login_win.destroy()

    def send_credentials(self, parent, auto_file=None):
        """Handles sending credentials and 2FA codes. Retains auto_file for Stress Test compatibility."""
        if auto_file:
            if not os.path.exists(auto_file): return False
            try:
                with open(auto_file, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
                    if len(lines) >= 2:
                        u, p = lines[0].strip(), lines[1].strip()
                        action = "REGISTER" if "signup" in auto_file else "LOGIN"
                        self.encryptor.send_encrypted_message(self.client_socket, action)
                        self.encryptor.send_encrypted_message(self.client_socket, u)
                        self.encryptor.send_encrypted_message(self.client_socket, p)
                        if action == "LOGIN":
                            self.encryptor.send_encrypted_message(self.client_socket, "000000")
                        resp = self.encryptor.receive_encrypted_message(self.client_socket)
                        return resp.startswith("LOGIN_SUCCESS") or resp.startswith("REGISTER_SUCCESS")
            except Exception: return False
            return False

        if parent is None: return False

        current_error = "" 
        while True:
            result = self.upgraded_login_dialog(parent, initial_error=current_error)
            if not result or not result["action"]: return False
            
            action, client_id, password = result["action"], result["u"], result["p"]
            totp_code = result.get("totp", "")
            
            try:
                self.encryptor.send_encrypted_message(self.client_socket, action)
                self.encryptor.send_encrypted_message(self.client_socket, client_id)
                self.encryptor.send_encrypted_message(self.client_socket, password)
                
                if action == "LOGIN":
                    self.encryptor.send_encrypted_message(self.client_socket, totp_code)
                    
                response = self.encryptor.receive_encrypted_message(self.client_socket)
                
                if response.startswith("REGISTER_SUCCESS"):
                    parts = response.split("|")
                    secret = parts[1] if len(parts) > 1 else "N/A"
                    self.show_2fa_setup_dialog(parent, client_id, secret)
                    return True
                    
                elif response == "LOGIN_SUCCESS":
                    return True
                    
                current_error = response.replace("ERROR: ", "")
                self.client_socket.close()
                self.connect_to_server()
                self.encryptor = Encryption() 
            except Exception as e:
                messagebox.showerror("System Error", str(e), parent=parent)
                return False

    def receive_menu(self):
        try:
            menu = self.encryptor.receive_encrypted_message(self.client_socket)
            print("\nAvailable operations received from server.")
            return menu
        except Exception as e:
            print("Menu synchronization error: {}".format(e))
            return None

    # ======================
    # LOW-LEVEL IO HELPERS
    # ======================
    def pick_source_path(self):
        if self.selected_image_path and os.path.exists(self.selected_image_path):
            return self.selected_image_path
        for p in getattr(self, "usual_images", []):
            if os.path.exists(p): return p
        return None

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.client_socket.recv(min(4096, n - len(buf)))
            if not chunk: break
            buf += chunk
        return buf

    def recv_size_or_error(self):
        s = self.encryptor.receive_encrypted_message(self.client_socket)
        if s.startswith("[ERROR]"):
            raise RuntimeError(s)
        return int(s)

    # ======================
    # OPERATIONS (UI-ACTIONS)
    # ======================
    def ui_do_face(self):
        try:
            self.ui_set_status("Running: Blur Faces...")
            self.encryptor.send_encrypted_message(self.client_socket, "1")

            src = self.selected_image_path if (self.selected_image_path and os.path.exists(self.selected_image_path)) else None
            if src:
                with open(src, "rb") as f: data = f.read()
                self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
                ack = self.encryptor.receive_encrypted_message(self.client_socket)
                self.ui_set_status(ack)
                self.client_socket.sendall(data)
            else:
                self.encryptor.send_encrypted_message(self.client_socket, "0")
                ack = self.encryptor.receive_encrypted_message(self.client_socket)
                self.ui_set_status(ack)

            self.encryptor.send_encrypted_message(self.client_socket, str(self.blur_slider.get()))

            orig_size = self.recv_size_or_error()
            orig_bytes = self._recv_exact(orig_size)
            orig_img = Image.open(io.BytesIO(orig_bytes)).convert("RGB")
            self.ui_show_preview(orig_img, is_processed=False)

            out_size = self.recv_size_or_error()
            out_bytes = self._recv_exact(out_size)
            proc_img = Image.open(io.BytesIO(out_bytes)).convert("RGB")
            self.ui_show_preview(proc_img, is_processed=True)

            self.ui_set_status("Faces blurred successfully.")
        except Exception as e:
            self.ui_set_status("Face blur failed: {}".format(e))

    def ui_do_bg(self):
        try:
            self.ui_set_status("Running: Blur Background...")
            self.encryptor.send_encrypted_message(self.client_socket, "2")

            src = self.selected_image_path if (self.selected_image_path and os.path.exists(self.selected_image_path)) else None
            if src:
                with open(src, "rb") as f: data = f.read()
                self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
                ack = self.encryptor.receive_encrypted_message(self.client_socket)
                self.ui_set_status(ack)
                self.client_socket.sendall(data)
            else:
                self.encryptor.send_encrypted_message(self.client_socket, "0")
                ack = self.encryptor.receive_encrypted_message(self.client_socket)
                self.ui_set_status(ack)

            self.encryptor.send_encrypted_message(self.client_socket, str(self.blur_slider.get()))

            orig_size = self.recv_size_or_error()
            orig_bytes = self._recv_exact(orig_size)
            orig_img = Image.open(io.BytesIO(orig_bytes)).convert("RGB")
            self.ui_show_preview(orig_img, is_processed=False)

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

            _ = self.encryptor.receive_encrypted_message(self.client_socket)

            src_path = self.pick_source_path()
            if src_path is None:
                self.encryptor.send_encrypted_message(self.client_socket, "0")
            else:
                with open(src_path, "rb") as f: data = f.read()
                self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
                ack = self.encryptor.receive_encrypted_message(self.client_socket)  
                self.client_socket.sendall(data)

            orig_size = self.recv_size_or_error()
            orig_bytes = self._recv_exact(orig_size)
            orig_pil = Image.open(io.BytesIO(orig_bytes)).convert("RGB")
            self.ui_show_preview(orig_pil, is_processed=False)

            img_bgr = cv2.imdecode(np.frombuffer(orig_bytes, np.uint8), cv2.IMREAD_COLOR)
            if img_bgr is None: raise RuntimeError("Failed to decode ORIGINAL")

            cv2.namedWindow("Draw ROIs (ENTER=OK, ESC=cancel)", cv2.WINDOW_NORMAL)
            rois = cv2.selectROIs("Draw ROIs (ENTER=OK, ESC=cancel)", img_bgr, False, False)
            cv2.destroyAllWindows()

            rects = []
            if rois is not None and len(rois) > 0:
                for (x, y, w, h) in rois:
                    if int(w) > 0 and int(h) > 0:
                        rects.append([int(x), int(y), int(w), int(h)])

            self.encryptor.send_encrypted_message(self.client_socket, "[C_RECTS]")
            self.encryptor.send_encrypted_message(self.client_socket, json.dumps(rects))
            
            self.encryptor.send_encrypted_message(self.client_socket, str(self.blur_slider.get()))

            out_size = self.recv_size_or_error()
            out_bytes = self._recv_exact(out_size)
            proc_img = Image.open(io.BytesIO(out_bytes)).convert("RGB")
            self.ui_show_preview(proc_img, is_processed=True)

            self.ui_set_status("User ROI: processed on server.")
        except Exception as e:
            self.ui_set_status(f"User ROI server-side blur failed: {e}")

    def ui_do_logout(self):
        try:
            self.ui_set_status("Logging out...")
            self.encryptor.send_encrypted_message(self.client_socket, "4")
            msg = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(msg)
        finally:
            self.logged_out = True
            try: self.client_socket.close()
            except: pass
            self.ui_root.after(500, self.ui_root.destroy)

    # ======================
    # MAIN FLOW
    # ======================
    def run(self):
        try:
            self.connect_to_server()
            if not self.client_socket: return

            root = tk.Tk()
            root.withdraw()  

            splash = self.show_splash(root)

            def after_splash():
                try: alive = splash.winfo_exists()
                except tk.TclError: alive = 0

                if alive:
                    root.after(100, after_splash)
                    return
                root.deiconify()
                root.lift()
                root.attributes("-topmost", True)
                root.after(200, lambda: root.attributes("-topmost", False))
                
                ok = self.send_credentials(root)
                if not ok:
                    try:
                        if self.client_socket: self.client_socket.close()
                    except: pass
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
                try: self.client_socket.close()
                except: pass


if __name__ == "__main__":
    print("Starting VeilGuard Client...")
    client = Client()
    client.run()