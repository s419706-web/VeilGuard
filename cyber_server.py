# ======================
# VeilGuard - Server (fully documented, no type hints)
# ======================
# Features:
# 1) Blur Faces (MediaPipe FaceDetection, CPU)
# 2) Blur Background (MediaPipe SelfieSegmentation, CPU)
# 3) User ROI Blur (client-side; server stores original+final)
# 4) Logout
#
# Protocol notes for options 1 & 2:
# - Client sends OPTION ("1" or "2")
# - Client then sends either:
#     "0"              -> use server-side default image
#     "<N>" + <N bytes> -> use client's image
# - Server always responds by sending:
#     ORIGINAL  : "<size>\n" + <bytes>
#     PROCESSED : "<size>\n" + <bytes>
#
# For option 3 (User ROI):
# - Server sends an instruction message
# - Client sends ORIGINAL size + bytes, then FINAL size + bytes
# - Server saves both and echoes FINAL back (size + bytes)
#
# Implementation notes:
# - MediaPipe is assumed to be installed on the SERVER machine.
# - All debug prints removed (only GUI log).
# - No type annotations to remain compatible with older Python interpreters.

import json
import socket
import threading
import tkinter as tk
from tkinter import Label, scrolledtext, Toplevel, Listbox, Button
from constants import IP, PORT
from db_manager import DatabaseManager
from create_tables import create_all_tables, populate_media_types
import datetime
from PIL import Image, ImageTk
import os
import pygame
import time
from encrypt import Encryption
from tools_no_encryption import *   # get_hash_value
import cv2
import numpy as np
import random
import mediapipe as mp  # Assumed installed on server


class Server:
    def __init__(self):
        """
        Initialize database, basic GUI containers, and default server images.
        """
        # --- Database
        self.db_manager = DatabaseManager("localhost", "root", "davids74", "mysql")
        create_all_tables(self.db_manager)
        try:
            populate_media_types(self.db_manager)
        except Exception:
            # If table already populated, ignore.
            pass

        # DB lock for thread-safe access
        self.db_lock = threading.Lock()

        # --- Tkinter GUI basics (created later fully in create_gui)
        self.root = tk.Tk()
        self.root.withdraw()
        self.log_text = None
        self.client_listbox = None
        self.bg_image = None

        # --- Server default images (used when client sends "0")
        here = os.path.dirname(os.path.abspath(__file__))
        self.DEFAULT_IMAGES = [
            os.path.join(here, "test15.png"),
            os.path.join(here, "test16.png"),
            os.path.join(here, "test17.png"),
        ]

    # ======================
    # Optional audio (intro -> loop)
    # ======================
    def play_audio(self):
        """
        Try to play an intro track once, then queue a loop track.
        If the files are missing or mixer fails, do nothing (best-effort only).
        """
        try:
            pygame.mixer.init()
            intro = r"C:\Users\shapi\Downloads\alin\cool_intro.mp3"
            loop  = r"C:\Users\shapi\Downloads\alin\game-of-thrones-song.mp3"
            if not (os.path.exists(intro) and os.path.exists(loop)):
                return
            pygame.mixer.music.load(intro)
            pygame.mixer.music.play()
            pygame.mixer.music.queue(loop)
        except Exception:
            pass

    # ======================
    # GUI helpers
    # ======================
    def update_gui_log(self, message):
        """Append text to GUI log safely (ignore errors if GUI not ready yet)."""
        try:
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.config(state=tk.DISABLED)
            self.log_text.yview(tk.END)
        except Exception:
            pass

    def update_client_list(self):
        """Rebuild the clients list from DB."""
        try:
            self.client_listbox.delete(0, tk.END)
            with self.db_lock:
                clients = self.db_manager.get_rows_with_value("clients", "1", "1")
            for client in clients:
                self.client_listbox.insert(tk.END, client[0])
        except Exception:
            pass

    def show_client_details(self, client_id):
        """Show a popup window with DB info about a specific client."""
        with self.db_lock:
            data = self.db_manager.get_rows_with_value("clients", "client_id", client_id)
        if not data:
            return

        w = Toplevel()
        w.title("Client %s Details" % client_id)
        w.geometry("400x350")

        bg_path = r"C:\Users\shapi\Downloads\alin\background_img.jpg"
        if os.path.exists(bg_path):
            try:
                bg_image = ImageTk.PhotoImage(Image.open(bg_path))
                bg_label = Label(w, image=bg_image)
                bg_label.image = bg_image
                bg_label.place(relwidth=1, relheight=1)
            except Exception:
                pass

        c = data[0]
        details = [
            "ID: %s" % c[0],
            "IP: %s" % c[1],
            "Port: %s" % c[2],
            "Last Seen: %s" % c[3],
            "Total Actions: %s" % c[5],
            "Status: %s" % ("Existing" if c[5] > 0 else "New"),
        ]
        for d in details:
            Label(w, text=d, fg='white', bg='black').pack(anchor="w", padx=10, pady=2)

        Button(w, text="History",
               command=lambda: self.show_client_history(client_id),
               bg='gray', fg='white').pack(pady=10)

    def show_client_history(self, client_id):
        """Show another popup with all saved images (paths) for that client."""
        w = Toplevel()
        w.title("Client %s - History" % client_id)
        w.geometry("600x400")

        bg_path = r"C:\Users\shapi\Downloads\alin\background_img.jpg"
        if os.path.exists(bg_path):
            try:
                bg_image = ImageTk.PhotoImage(Image.open(bg_path))
                bg_label = Label(w, image=bg_image)
                bg_label.image = bg_image
                bg_label.place(relwidth=1, relheight=1)
            except Exception:
                pass

        Label(w, text="Client %s Image History" % client_id,
              font=("Arial", 12, "bold"), fg="white", bg="black").pack(pady=5)

        lb = Listbox(w, height=15, width=80, bg="black", fg="white", selectbackground="gray")
        lb.pack(padx=10, pady=5, expand=True, fill="both")

        with self.db_lock:
            rows = self.db_manager.get_rows_with_value("decrypted_media", "user_id", client_id)
        if not rows:
            lb.insert(tk.END, "No images found for this client.")
            return

        paths = [r[2] for r in rows]
        for p in paths:
            lb.insert(tk.END, p)

        lb.bind("<Double-Button-1>",
                lambda e: os.system('"%s"' % paths[lb.curselection()[0]]))

    # ======================
    # File helpers (save/original/processed)
    # ======================
    def _ensure_dir(self, path):
        os.makedirs(path, exist_ok=True)

    def save_bgr_image(self, bgr, base_dir, prefix):
        """
        Save a BGR image as JPG.
        The filename includes a timestamp to avoid overwrites.
        Returns the full saved path.
        """
        self._ensure_dir(base_dir)
        ts = int(time.time())
        path = os.path.join(base_dir, "%s_%d.jpg" % (prefix, ts))
        cv2.imwrite(path, bgr)
        return path

    def save_raw_image_bytes(self, image_bytes, base_dir, prefix):
        """
        Save raw image bytes (as-is) as a JPG file.
        The filename includes a timestamp to avoid overwrites.
        Returns the full saved path.
        """
        self._ensure_dir(base_dir)
        ts = int(time.time())
        path = os.path.join(base_dir, "%s_%d.jpg" % (prefix, ts))
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path

    def _load_server_default_image_bytes(self):
        """
        Load one of the server default images and return bytes.
        Raises FileNotFoundError if none exist.
        """
        existing = [p for p in self.DEFAULT_IMAGES if os.path.exists(p)]
        if not existing:
            raise FileNotFoundError("Put test15.png / test16.png / test17.png next to cyber_server.py")
        choice = random.choice(existing)
        with open(choice, "rb") as f:
            return f.read()

    # ======================
    # Small math helpers
    # ======================
    def _odd(self, n):
        """
        Return an odd integer >= 3, useful for Gaussian kernel size.
        """
        n = int(max(3, n))
        return n if (n % 2 == 1) else (n + 1)

    def _feather_mask(self, mask_255, radius):
        """
        Convert a 0/255 mask to soft float [0..1] using Gaussian blur.
        Softer edges => fewer halos on blending.
        """
        m = mask_255.astype(np.float32) / 255.0
        k = self._odd(max(3, int(radius)))
        m = cv2.GaussianBlur(m, (k, k), 0)
        m = np.clip(m, 0.0, 1.0)
        return m

    def _nms_boxes(self, boxes, iou_thresh):
        """
        Simple greedy NMS on a list of (x,y,w,h) boxes.
        Keeps larger boxes on heavy overlaps.
        """
        if not boxes:
            return []

        arr = np.array([[x, y, x + w, y + h] for (x, y, w, h) in boxes], dtype=np.float32)
        x1, y1, x2, y2 = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
        areas = (x2 - x1 + 1) * (y2 - y1 + 1)
        order = areas.argsort()[::-1]
        keep = []

        while order.size > 0:
            i = order[0]
            keep.append(i)

            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            w = np.maximum(0.0, xx2 - xx1 + 1)
            h = np.maximum(0.0, yy2 - yy1 + 1)
            inter = w * h
            iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

            inds = np.where(iou <= iou_thresh)[0]
            order = order[inds + 1]

        out = []
        for i in keep:
            xx1, yy1, xx2, yy2 = arr[i]
            out.append((int(xx1), int(yy1), int(xx2 - xx1), int(yy2 - yy1)))
        return out

    def _expand_box(self, x, y, w, h, img_w, img_h, sx=0.15, sy=0.25):
        """
        Slightly enlarge a face box to include forehead/chin.
        Keeps the box in image bounds.
        """
        nw = int(w * (1 + sx))
        nh = int(h * (1 + sy))
        nx = max(0, x - (nw - w) // 2)
        ny = max(0, y - (nh - h) // 2)
        if nx + nw > img_w:
            nw = img_w - nx
        if ny + nh > img_h:
            nh = img_h - ny
        return nx, ny, nw, nh

    # ======================
    # MediaPipe backends (no fallbacks)
    # ======================
    def apply_masked_blur(self, bgr, mask_255, ksize):
        """
        Receives:
        - bgr: image (BGR)
        - mask_255: uint8 mask (0=keep sharp, 255=blur)
        - ksize: blur kernel (int, normalized to odd >=3)
        Does:
        - feather mask for soft edges
        - Gaussian blur background only where mask==1
        Returns:
        - composited BGR
        """
        H, W = bgr.shape[:2]
        if mask_255.shape[:2] != (H, W):
            mask_255 = cv2.resize(mask_255, (W, H), interpolation=cv2.INTER_NEAREST)
        if mask_255.ndim == 3:
            mask_255 = cv2.cvtColor(mask_255, cv2.COLOR_BGR2GRAY)
        keep_blur = (mask_255 > 0).astype(np.uint8) * 255
        m = self._feather_mask(keep_blur, radius=max(12, min(H, W)//30))
        m3 = np.dstack([m, m, m])
        k = self._odd(ksize)
        blurred = cv2.GaussianBlur(bgr, (k, k), 0)
        out = (m3 * blurred.astype(np.float32) + (1.0 - m3) * bgr.astype(np.float32))
        out = np.clip(out, 0, 255).astype(np.uint8)
        return out

    def _mp_face_boxes(self, bgr, conf):
        """
        Run MediaPipe FaceDetection with model_selection 0 and 1
        (near + far faces), then merge with NMS.
        Returns a list of (x, y, w, h) boxes in pixels.
        """
        H, W = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        out = []
        mp_fd = mp.solutions.face_detection

        for model_sel in (0, 1):
            with mp_fd.FaceDetection(model_selection=model_sel,
                                     min_detection_confidence=conf) as fd:
                r = fd.process(rgb)
                if not r.detections:
                    continue
                for d in r.detections:
                    bb = d.location_data.relative_bounding_box
                    x = int(bb.xmin * W)
                    y = int(bb.ymin * H)
                    w = int(bb.width * W)
                    h = int(bb.height * H)
                    out.append((max(0, x), max(0, y), max(1, w), max(1, h)))

        return self._nms_boxes(out, 0.45)

    def _mp_person_mask(self, bgr):
        """
        Run MediaPipe SelfieSegmentation (people mask).
        Returns a 0/255 mask, where 255 marks person pixels.
        """
        mp_seg = mp.solutions.selfie_segmentation
        with mp_seg.SelfieSegmentation(model_selection=1) as seg:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            r = seg.process(rgb)
            if r.segmentation_mask is None:
                raise RuntimeError("MediaPipe returned no segmentation mask")
            mask = (r.segmentation_mask > 0.5).astype(np.uint8) * 255
            return mask

    # ======================
    # Blur operations (MediaPipe-only)
    # ======================
    def blur_faces_bgr(self, bgr, ksize):
        """
        Blur only face regions:
        1) Detect faces (near + far) with MediaPipe.
        2) For each face, draw an ellipse slightly larger than the box.
        3) Feather edges of the combined mask.
        4) Gaussian blur the image and composite only under the mask.
        """
        H, W = bgr.shape[:2]
        boxes = self._mp_face_boxes(bgr, 0.60)
        if not boxes:
            return bgr.copy()

        mask = np.zeros((H, W), dtype=np.uint8)
        for (x, y, w, h) in boxes:
            x, y, w, h = self._expand_box(x, y, w, h, W, H)
            cx, cy = x + w // 2, y + h // 2
            axes = (int(w * 0.56), int(h * 0.72))
            cv2.ellipse(mask, (cx, cy), axes, 0, 0, 360, 255, -1)

        m = self._feather_mask(mask, radius=max(12, min(H, W) // 30))
        m3 = np.dstack([m, m, m])

        k_auto = self._odd(max(19, min(101, int(min(H, W) * 0.05))))
        if ksize is None:
            k = k_auto
        else:
            k = self._odd(ksize)

        blurred = cv2.GaussianBlur(bgr, (k, k), 0)
        out = (m3 * blurred.astype(np.float32) + (1.0 - m3) * bgr.astype(np.float32))
        out = np.clip(out, 0, 255).astype(np.uint8)
        return out

    def blur_background_bgr_from_bytes(self, image_bytes, blur_strength):
        """
        Keep people sharp (foreground), blur the rest (background):
        1) Decode bytes to BGR.
        2) Get person mask with MediaPipe.
        3) Feather edges.
        4) Composite: foreground = original, background = blurred.
        """
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Failed to decode input bytes")

        keep_255 = self._mp_person_mask(bgr)
        keep = self._feather_mask(keep_255, radius=21)
        keep3 = np.dstack([keep, keep, keep])

        k = self._odd(blur_strength)
        blurred = cv2.GaussianBlur(bgr, (k, k), 0)
        out = (keep3 * bgr.astype(np.float32) + (1.0 - keep3) * blurred.astype(np.float32))
        out = np.clip(out, 0, 255).astype(np.uint8)
        return out

    # ======================
    # Client handling (authentication + menu loop)
    # ======================
    def handle_client(self, client_socket):
        client_id = 'unknown'
        encryptor = Encryption()  # per-client encryption instance
        try:
            # --- Authentication
            username = encryptor.receive_encrypted_message(client_socket)
            password = encryptor.receive_encrypted_message(client_socket)
            hashed_password = get_hash_value(password)

            client_ip, client_port = client_socket.getpeername()
            with self.db_lock:
                existing = self.db_manager.get_rows_with_value("clients", "client_id", username)

            if existing:
                stored_hash = existing[0][6]
                if stored_hash != hashed_password:
                    encryptor.send_encrypted_message(client_socket, "PASSWORD INCORRECT. DISCONNECTING.")
                    client_socket.close()
                    return
                else:
                    with self.db_lock:
                        self.db_manager.update_row("clients", "client_id", username,
                                                   ["last_seen"], [datetime.datetime.now()])
                    encryptor.send_encrypted_message(client_socket, "WELCOME BACK")
                    client_status = "EXISTING"
                    total_actions = existing[0][5]
            else:
                with self.db_lock:
                    self.db_manager.insert_row(
                        "clients",
                        "(client_id, client_ip, client_port, last_seen, ddos_status, total_sent_media, password_hash)",
                        "(%s, %s, %s, %s, %s, %s, %s)",
                        (username, client_ip, client_port, datetime.datetime.now(), False, 0, hashed_password)
                    )
                encryptor.send_encrypted_message(
                    client_socket,
                    "WELCOME TO VeilGuard SERVER! NEW ACCOUNT CREATED."
                )
                client_status = "NEW"
                total_actions = 0

            client_id = username
            self.update_gui_log("Client %s connected - Status: %s" % (client_id, client_status))
            self.update_client_list()

            # --- Main interaction loop
            while True:
                try:
                    encryptor.send_encrypted_message(
                        client_socket,
                        "\n1: Blur Faces\n2: Blur Background\n3: User-Selected Blur\n4: Logout"
                    )
                    option = encryptor.receive_encrypted_message(client_socket)

                    if option == "1":
                        self.handle_option_1_blur_faces(client_socket, client_id, encryptor)
                        total_actions += 1
                    elif option == "2":
                        self.handle_option_2_blur_background(client_socket, client_id, encryptor)
                        total_actions += 1
                    elif option == "3":
                        self.handle_option_3_user_selected_blur_receive(client_socket, client_id, encryptor)
                        total_actions += 1
                    elif option == "4":
                        self.handle_logout(client_socket, client_id, encryptor)
                        break
                    else:
                        encryptor.send_encrypted_message(client_socket, "Invalid option.")

                    if option in ("1", "2", "3"):
                        with self.db_lock:
                            self.db_manager.update_row("clients", "client_id", client_id,
                                                       ["total_sent_media"], [total_actions])

                except (ConnectionResetError, socket.error):
                    self.update_gui_log("Client %s disconnected abruptly." % client_id)
                    break
                except Exception as e:
                    self.update_gui_log("Error with client %s: %s" % (client_id, str(e)))
                    try:
                        encryptor.send_encrypted_message(client_socket, "[SERVER ERROR] %s" % str(e))
                    except Exception:
                        pass
                    break

        except Exception as e:
            self.update_gui_log("Connection error with %s: %s" % (client_id, str(e)))
        finally:
            try:
                client_socket.close()
                self.update_gui_log("Connection with %s closed" % client_id)
            except Exception as e:
                self.update_gui_log("Error closing socket for %s: %s" % (client_id, str(e)))
            finally:
                self.update_client_list()

    # ======================
    # Command handlers (1/2/3/4)
    # ======================
    def handle_option_1_blur_faces(self, client_socket, client_id, encryptor):
        """
        Faces blur flow:
        - Read size: "0" for default image, or "<N>" and then read N bytes.
        - Save ORIGINAL
        - Blur faces (ellipse mask + feather + Gaussian)
        - Save PROCESSED
        - Send ORIGINAL first, then PROCESSED
        """
        try:
            size_str = encryptor.receive_encrypted_message(client_socket)
            use_default = (size_str == "0")

            if use_default:
                encryptor.send_encrypted_message(client_socket, "[INFO] Using server default image...")
                buf = self._load_server_default_image_bytes()
            else:
                image_size = int(size_str)
                encryptor.send_encrypted_message(client_socket, "[INFO] Send the image...")
                buf = b""
                remaining = image_size
                while remaining > 0:
                    chunk = client_socket.recv(min(4096, remaining))
                    if not chunk:
                        break
                    buf += chunk
                    remaining -= len(chunk)

            # Save ORIGINAL
            orig_path = self.save_raw_image_bytes(buf, base_dir="processed",
                                                  prefix="%s_face_original" % client_id)
            with self.db_lock:
                self.db_manager.insert_decrypted_media(client_id, 101, orig_path)
            self.update_gui_log("Client %s: Face blur (original) -> %s" % (client_id, orig_path))

            # Decode + process
            np_arr = np.frombuffer(buf, dtype=np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                raise ValueError("Failed to decode image")
            out_bgr = self.blur_faces_bgr(img_bgr, 51)

            # Save PROCESSED
            out_path = self.save_bgr_image(out_bgr, base_dir="processed",
                                           prefix="%s_face_processed" % client_id)
            with self.db_lock:
                self.db_manager.insert_decrypted_media(client_id, 1, out_path)
            self.update_gui_log("Client %s: Face blur (processed) -> %s" % (client_id, out_path))

            # Send ORIGINAL
            encryptor.send_encrypted_message(client_socket, str(len(buf)))
            client_socket.sendall(buf)

            # Send PROCESSED
            ok, enc = cv2.imencode(".jpg", out_bgr)
            if not ok:
                raise ValueError("imencode failed")
            out_bytes = enc.tobytes()
            encryptor.send_encrypted_message(client_socket, str(len(out_bytes)))
            client_socket.sendall(out_bytes)

        except Exception as e:
            encryptor.send_encrypted_message(client_socket, "[ERROR] %s" % str(e))

    def handle_option_2_blur_background(self, client_socket, client_id, encryptor):
        """
        Background blur flow:
        - Read size: "0" for default image, or "<N>" and then read N bytes.
        - Save ORIGINAL
        - Use MediaPipe people mask to keep persons sharp and blur the rest.
        - Save PROCESSED
        - Send ORIGINAL first, then PROCESSED
        """
        try:
            size_str = encryptor.receive_encrypted_message(client_socket)
            use_default = (size_str == "0")

            if use_default:
                encryptor.send_encrypted_message(client_socket, "[INFO] Using server default image...")
                buf = self._load_server_default_image_bytes()
            else:
                image_size = int(size_str)
                encryptor.send_encrypted_message(client_socket, "[INFO] Send the image...")
                buf = b""
                remaining = image_size
                while remaining > 0:
                    chunk = client_socket.recv(min(4096, remaining))
                    if not chunk:
                        break
                    buf += chunk
                    remaining -= len(chunk)

            # Save ORIGINAL
            orig_path = self.save_raw_image_bytes(buf, base_dir="processed",
                                                  prefix="%s_background_original" % client_id)
            with self.db_lock:
                self.db_manager.insert_decrypted_media(client_id, 102, orig_path)
            self.update_gui_log("Client %s: Background blur (original) -> %s" % (client_id, orig_path))

            # Process (keep persons sharp)
            out_bgr = self.blur_background_bgr_from_bytes(buf, 51)

            # Save PROCESSED
            out_path = self.save_bgr_image(out_bgr, base_dir="processed",
                                           prefix="%s_background_processed" % client_id)
            with self.db_lock:
                self.db_manager.insert_decrypted_media(client_id, 2, out_path)
            self.update_gui_log("Client %s: Background blur (processed) -> %s" % (client_id, out_path))

            # Send ORIGINAL
            encryptor.send_encrypted_message(client_socket, str(len(buf)))
            client_socket.sendall(buf)

            # Send PROCESSED
            ok, enc = cv2.imencode(".jpg", out_bgr)
            if not ok:
                raise ValueError("imencode failed")
            out_bytes = enc.tobytes()
            encryptor.send_encrypted_message(client_socket, str(len(out_bytes)))
            client_socket.sendall(out_bytes)

        except Exception as e:
            encryptor.send_encrypted_message(client_socket, "[ERROR] %s" % str(e))

    def handle_option_3_user_selected_blur_receive(self, client_socket, client_id, encryptor):
        """
        Option 3 (User ROI blur, server-side processing):
        - Notify client server is ready
        - Receive either "0" (default image) or <N> + N bytes
        - Save ORIGINAL
        - Send ORIGINAL to client for display
        - Receive ROI list as JSON
        - Apply blur on ROIs
        - Save PROCESSED
        - Send processed image back
        """
        # Notify client
        encryptor.send_encrypted_message(
            client_socket,
            "[SERVER_READY] ROI server-side: send '0' for default image or <N> then N bytes."
        )

        size_str = encryptor.receive_encrypted_message(client_socket)
        if size_str == "0":
            buf = self._load_server_default_image_bytes()
        else:
            image_size = int(size_str)
            encryptor.send_encrypted_message(client_socket, "[INFO] Send the image...")
            buf, remaining = b"", image_size
            while remaining > 0:
                chunk = client_socket.recv(min(4096, remaining))
                if not chunk:
                    break
                buf += chunk
                remaining -= len(chunk)

        # Save ORIGINAL
        orig_path = self.save_raw_image_bytes(buf, base_dir="processed",
                                              prefix=f"{client_id}_roi_original")
        with self.db_lock:
            self.db_manager.insert_decrypted_media(client_id, 103, orig_path)

        # Send ORIGINAL back to client
        encryptor.send_encrypted_message(client_socket, str(len(buf)))
        client_socket.sendall(buf)

        # Receive ROI command
        cmd = encryptor.receive_encrypted_message(client_socket)  # Expecting "[C_RECTS]"
        if cmd != "[C_RECTS]":
            encryptor.send_encrypted_message(client_socket, "[ERROR] Expected [C_RECTS]")
            return

        # Receive ROI list JSON
        rects_json = encryptor.receive_encrypted_message(client_socket)
        try:
            rects = json.loads(rects_json)  # Format: [[x, y, w, h], ...]
            assert isinstance(rects, list)
        except Exception as e:
            encryptor.send_encrypted_message(client_socket, "[ERROR] Bad ROI JSON: %s" % str(e))
            return

        # Decode image
        arr = np.frombuffer(buf, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            encryptor.send_encrypted_message(client_socket, "[ERROR] Decode ORIGINAL failed")
            return

        # Apply blur on ROIs
        out = bgr.copy()
        for r in rects:
            if not (isinstance(r, (list, tuple)) and len(r) == 4):
                continue
            x, y, w, h = map(int, r)
            x = max(0, min(x, out.shape[1] - 1))
            y = max(0, min(y, out.shape[0] - 1))
            w = max(0, min(w, out.shape[1] - x))
            h = max(0, min(h, out.shape[0] - y))
            if w <= 0 or h <= 0:
                continue

            k = max(21, 2 * (min(w, h) // 3) + 1)
            patch = out[y:y + h, x:x + w]
            patch_blur = cv2.GaussianBlur(patch, (k, k), 0)
            out[y:y + h, x:x + w] = patch_blur

        # Save PROCESSED
        out_path = self.save_bgr_image(out, base_dir="processed",
                                       prefix=f"{client_id}_roi_processed")
        with self.db_lock:
            self.db_manager.insert_decrypted_media(client_id, 3, out_path)

        # Send processed image back
        ok, enc = cv2.imencode(".jpg", out)
        if not ok:
            encryptor.send_encrypted_message(client_socket, "[ERROR] imencode failed")
            return
        out_bytes = enc.tobytes()
        encryptor.send_encrypted_message(client_socket, str(len(out_bytes)))
        client_socket.sendall(out_bytes)

    def handle_logout(self, client_socket, client_id, encryptor):
        """
        Acknowledge logout, update last_seen, and close the socket gracefully.
        """
        try:
            self.update_gui_log("Client %s requested logout" % client_id)
            try:
                with self.db_lock:
                    self.db_manager.update_row("clients", "client_id", client_id,
                                               ["last_seen"], [datetime.datetime.now()])
            except Exception:
                pass
            encryptor.send_encrypted_message(client_socket, "GOODBYE")
        except Exception:
            pass
        finally:
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                client_socket.close()
            except Exception:
                pass
            self.update_gui_log("Connection with %s closed after logout" % client_id)

    # ======================
    # Server control
    # ======================
    def start_server(self):
        """
        Main accept loop. Spawns a new daemon thread per client.
        """
        try:
            server_socket = socket.socket()
            server_socket.bind((IP, PORT))
            server_socket.listen()
            self.update_gui_log("Server started on %s:%s" % (IP, PORT))
            while True:
                client_socket, _ = server_socket.accept()
                threading.Thread(target=self.handle_client,
                                 args=(client_socket,),
                                 daemon=True).start()
        except Exception as e:
            self.update_gui_log("[FATAL] %s" % str(e))

    def create_gui(self):
        """
        Build the Tkinter GUI and run it. The server loop runs on a background thread.
        """
        try:
            self.play_audio()
        except Exception:
            pass

        try:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = tk.Tk()
            self.root.title("VeilGuard Server GUI")
            self.root.geometry("500x500")

            bg_path = r"C:\Users\shapi\Downloads\alin\background_img.jpg"
            if os.path.exists(bg_path):
                try:
                    self.bg_image = ImageTk.PhotoImage(Image.open(bg_path))
                    bg_label = Label(self.root, image=self.bg_image)
                    bg_label.place(relwidth=1, relheight=1)
                except Exception:
                    pass

            self.log_text = scrolledtext.ScrolledText(
                self.root, state=tk.DISABLED, wrap=tk.WORD, height=10, bg='black', fg='white'
            )
            self.log_text.pack(expand=True, fill='both', padx=10, pady=5)

            Label(self.root, text="VeilGuard Customers",
                  font=("Arial", 14, "bold"), fg="white", bg="black").pack(pady=5)

            self.client_listbox = Listbox(self.root, bg='black', fg='white')
            self.client_listbox.pack(expand=True, fill='both', padx=10, pady=5)
            self.client_listbox.bind(
                "<Double-Button-1>",
                lambda e: self.show_client_details(self.client_listbox.get(self.client_listbox.curselection()))
            )

            threading.Thread(target=self.start_server, daemon=True).start()
            self.root.mainloop()

        except Exception as e:
            self.update_gui_log("[FATAL] %s" % str(e))


if __name__ == "__main__":
    server = Server()
    server.create_gui()
# =======================