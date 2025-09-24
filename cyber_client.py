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
- Login via small Tk window (persisting credentials in creds.txt).
- Modern UI: choose image, run operations, and see Original vs. Processed previews.
- Robust threading so the UI remains responsive during long operations.
"""

# IMPORT STATEMENTS
# ======================
from tkinter import Label, scrolledtext, Toplevel, Listbox, Button, ttk, filedialog
import tkinter as tk
import socket
import os
import random
import time
from PIL import Image, ImageTk
from constants import IP, PORT, CHUNK_SIZE
from encrypt import Encryption
import cv2
import numpy as np
import threading
import subprocess
import sys
import io


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
        # List of images used for operations (fallbacks if user doesn't choose)
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
        self.btns = {}

    # ======================
    # NETWORK CONNECTION
    # ======================
    def connect_to_server(self):
        """
        Establish a TCP connection to the server using IP/PORT from constants.py.
        Prints a confirmation if connected; otherwise logs the exception and
        keeps client_socket as None.
        """
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
        """
        Show a temporary splash screen (400x400), then close it automatically
        after 4 seconds. This runs a short Tk mainloop dedicated for the splash.
        """
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

        # Close splash after ~4 seconds
        splash.after(4000, close_splash)
        root.mainloop()

    # ----------------------
    # UI helpers
    # ----------------------
    def ui_set_status(self, msg: str):
        """
        Thread-safe setter for the bottom status label.
        Uses `after(0, ...)` to schedule GUI updates on the main thread.
        """
        if self.status_var:
            def _set():
                self.status_var.set(msg)
            self.ui_root.after(0, _set)

    def ui_enable_controls(self, enable: bool):
        """
        Enable/disable the main action buttons while an operation is running.
        Prevents duplicate clicks and keeps the UI predictable.
        """
        state = tk.NORMAL if enable else tk.DISABLED
        for b in self.btns.values():
            b.config(state=state)

    def open_file_no_temp(self, path: str):
        """
        Open a file with the OS default app without creating temporary copies.
        Useful if you want to preview saved files outside the app.
        """
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)

    def choose_image_dialog(self):
        """
        Open a file picker and let the user select a local image.
        On success, update status and show the Original preview immediately.
        """
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
        """
        Show a PIL image inside the corresponding preview panel (Original/Processed).
        The image is thumbnailed to fit the preview area.
        """
        max_w, max_h = 420, 280
        im = pil_img.copy()
        im.thumbnail((max_w, max_h))
        tk_img = ImageTk.PhotoImage(im)

        def _apply():
            if is_processed:
                self.preview_proc.config(image=tk_img)
                self.preview_proc.image = tk_img  # Keep reference
            else:
                self.preview_orig.config(image=tk_img)
                self.preview_orig.image = tk_img  # Keep reference
        self.ui_root.after(0, _apply)

    def ui_show_pair(self, orig_pil: Image.Image, proc_pil: Image.Image):
        """
        Convenience helper that updates both preview panels at once.
        """
        self.ui_show_preview(orig_pil, is_processed=False)
        self.ui_show_preview(proc_pil, is_processed=True)

    def ui_run_async(self, target, *args, **kwargs):
        """
        Run a long operation (`target`) in a background thread:
        - Disables UI controls while running.
        - Re-enables controls afterwards.
        - After operation completes, pulls a fresh menu (unless already logged out).
        """
        def runner():
            try:
                self.ui_enable_controls(False)
                target(*args, **kwargs)
            finally:
                # Pull fresh menu only if still connected (not after logout)
                if not getattr(self, "logged_out", False):
                    try:
                        self.receive_menu()
                    except Exception:
                        pass
                self.ui_enable_controls(True)
        threading.Thread(target=runner, daemon=True).start()

    def build_ui(self):
        """
        Build and display the main client UI:
        - Top action bar with Choose Image / Blur operations / Logout.
        - Two preview panes (Original, Processed).
        - Status bar at the bottom.
        """
        self.ui_root = tk.Tk()
        self.ui_root.title("VeilGuard Client")
        self.ui_root.geometry("980x620")

        # Top controls frame
        top = ttk.Frame(self.ui_root, padding=10)
        top.pack(side=tk.TOP, fill=tk.X)

        # Buttons
        self.btns["choose"] = ttk.Button(top, text="Choose Image", command=self.choose_image_dialog)
        self.btns["choose"].pack(side=tk.LEFT, padx=5)

        self.btns["face"] = ttk.Button(top, text="Blur Faces", command=lambda: self.ui_run_async(self.ui_do_face))
        self.btns["face"].pack(side=tk.LEFT, padx=5)

        self.btns["bg"] = ttk.Button(top, text="Blur Background", command=lambda: self.ui_run_async(self.ui_do_bg))
        self.btns["bg"].pack(side=tk.LEFT, padx=5)

        self.btns["user"] = ttk.Button(top, text="User ROI Blur", command=lambda: self.ui_run_async(self.ui_do_user))
        self.btns["user"].pack(side=tk.LEFT, padx=5)

        self.btns["logout"] = ttk.Button(top, text="Logout", command=lambda: self.ui_run_async(self.ui_do_logout))
        self.btns["logout"].pack(side=tk.LEFT, padx=5)

        # Previews
        mid = ttk.Frame(self.ui_root, padding=10)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(mid, text="Original")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        right = ttk.LabelFrame(mid, text="Processed")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.preview_orig = ttk.Label(left)
        self.preview_orig.pack(fill=tk.BOTH, expand=True)
        self.preview_proc = ttk.Label(right)
        self.preview_proc.pack(fill=tk.BOTH, expand=True)

        # Status
        bottom = ttk.Frame(self.ui_root, padding=10)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(bottom, textvariable=self.status_var).pack(side=tk.LEFT)

        # Handle window close (X)
        self.ui_root.protocol("WM_DELETE_WINDOW", self.ui_root.destroy)

        # Initial hint
        self.ui_set_status("Choose an image or use defaults (test15/16/17).")

        # Main UI loop
        self.ui_root.mainloop()

    # ======================
    # AUTHENTICATION
    # ======================
    def send_credentials(self):
        """
        Send username/password to the server (encrypted).
        - If creds.txt exists, read username/password from there.
        - Otherwise, open a small Tk login UI and save the result to creds.txt.
        - Close the client if the server reports an incorrect password.
        """
        creds_file = "creds.txt"

        if os.path.exists(creds_file):
            # Read credentials from file
            with open(creds_file, "r") as f:
                lines = f.read().strip().split("\n")
                client_id = lines[0]
                password = lines[1]
        else:
            # Show a simple login dialog
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
                """Collect credentials and close the login window."""
                creds["username"] = username_entry.get()
                creds["password"] = password_entry.get()
                root.destroy()

            tk.Button(root, text="Login", command=submit).grid(row=2, column=0, columnspan=2, pady=10)
            root.mainloop()

            client_id = creds["username"]
            password = creds["password"]

            # Persist credentials for future sessions
            with open(creds_file, "w") as f:
                f.write(client_id + "\n" + password)

        # Transmit encrypted credentials
        self.encryptor.send_encrypted_message(self.client_socket, client_id)
        self.encryptor.send_encrypted_message(self.client_socket, password)

        # Server response
        response = self.encryptor.receive_encrypted_message(self.client_socket)
        print(response)

        if "PASSWORD INCORRECT" in response:
            self.client_socket.close()
            exit()

    # ======================
    # MENU HANDLING
    # ======================
    def receive_menu(self):
        """
        Receive and print the server's textual menu. This helps keep the client
        and server in sync (also after GUI-triggered operations). Returns the menu string.
        """
        try:
            menu = self.encryptor.receive_encrypted_message(self.client_socket)
            print("\nAvailable operations:")
            print(menu)
            return menu
        except Exception as e:
            print(f"Menu error: {e}")
            return None

    # ======================
    # OPERATION HANDLERS (UI)
    # ======================
    def pick_source_path(self):
        """
        Determine which image to use:
        - If the user selected a path and it exists, use it.
        - Otherwise, iterate default list and return the first existing file.
        Raises FileNotFoundError if nothing is found.
        """
        if self.selected_image_path and os.path.exists(self.selected_image_path):
            return self.selected_image_path
        for p in self.usual_images:
            if os.path.exists(p):
                return p
        raise FileNotFoundError("No valid image found in selected path or defaults.")

    def recv_size_or_error(self):
        """
        Receive either the size (stringified integer) of the upcoming image bytes
        or an error string starting with '[ERROR]'. Returns the integer size or
        raises RuntimeError if an error string is received.
        """
        s = self.encryptor.receive_encrypted_message(self.client_socket)
        if s.startswith("[ERROR]"):
            raise RuntimeError(s)
        return int(s)

    def ui_do_face(self):
        """
        UI action for option 1 (Blur Faces):
        - Send option '1' to server.
        - Send selected or default image bytes.
        - Receive processed image bytes, show in 'Processed' preview.
        - Update status throughout.
        """
        try:
            self.ui_set_status("Running: Blur Faces...")
            # Send option
            self.encryptor.send_encrypted_message(self.client_socket, "1")

            # Pick and send image
            src = self.pick_source_path()
            with open(src, "rb") as f:
                data = f.read()
            self.ui_show_preview(Image.open(src), is_processed=False)

            self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
            ack = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(ack)
            self.client_socket.sendall(data)

            # Receive processed
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

        except Exception as e:
            self.ui_set_status(f"Face blur failed: {e}")

    def ui_do_bg(self):
        """
        UI action for option 2 (Blur Background):
        - Send option '2' to server.
        - Send selected or default image bytes.
        - Receive processed image bytes, show in 'Processed' preview.
        """
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

        except Exception as e:
            self.ui_set_status(f"Background blur failed: {e}")

    def ui_do_user(self):
        """
        UI action for option 3 (User ROI Blur):
        - Send option '3' to server and wait for the interactive signal message.
        - Launch a simple OpenCV editor: click-drag-release to blur selected ROIs.
          Press ESC to finish.
        - Send ORIGINAL bytes first, then FINAL (blurred) bytes to server.
        - Receive an echo-back of the final image and show it in 'Processed'.
        """
        try:
            self.ui_set_status("Running: User ROI Blur... (use mouse, press ESC to finish)")
            self.encryptor.send_encrypted_message(self.client_socket, "3")

            # Wait for server signal
            signal = self.encryptor.receive_encrypted_message(self.client_socket)
            self.ui_set_status(signal)

            # Load original
            src = self.pick_source_path()
            with open(src, "rb") as f:
                original_bytes = f.read()
            self.ui_show_preview(Image.open(src), is_processed=False)

            img = cv2.imread(src)
            if img is None:
                raise FileNotFoundError("Image not found or cannot be opened!")
            img_display = img.copy()
            drawing = {"active": False, "ix": -1, "iy": -1}

            # OpenCV editor: draw rectangles to blur ROIs; release to apply
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

            # Encode final
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

        except Exception as e:
            self.ui_set_status(f"User ROI blur failed: {e}")

    def ui_do_logout(self):
        """
        UI action for option 4 (Logout):
        - Send '4' and wait for server 'GOODBYE'.
        - Mark the client as logged_out, close the socket, and close the UI.
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
            except:
                pass
            self.ui_root.after(500, self.ui_root.destroy)

    # ======================
    # MAIN CLIENT LOOP
    # ======================
    def run(self):
        """
        Main client execution flow:
        - Connect to the server; abort if failed.
        - Show splash, then authenticate.
        - Pull a menu once (sync point).
        - Build and run the main UI window.
        - On termination, close the socket gracefully if it is still open.
        """
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
