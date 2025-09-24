"""
VeilGuard Server
----------------
Tkinter-based server GUI that accepts encrypted client connections and supports:
1) Blur Faces (server-side)
2) Blur Background (server-side)
3) User-Selected Blur (client-side interactive; server stores original/final)

Features:
- Client authentication with username/password hashing
- SQLite database for client and media tracking
- Real-time GUI updates with client list and logs
- Background music during server operation
- Robust error handling and logging
- Saves original and processed images with user/option-aware filenames
"""

# ======================
# IMPORTS AND DEPENDENCIES
# ======================
import os, warnings
# in order to hide the pygame support prompt on import ( cosmetic)
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API",
    category=UserWarning
)

import pygame

import socket
import threading
import tkinter as tk
from tkinter import Label, scrolledtext, Toplevel, Listbox, Button
from constants import IP, PORT
from db_manager import DatabaseManager
from create_tables import create_all_tables, populate_media_types
import datetime
from PIL import Image, ImageTk
import pygame
import time
from encrypt import Encryption
from tools_no_encryption import *  
from blur_ops import *
import cv2
import numpy as np


# ======================
# SERVER CLASS DEFINITION
# ======================
class Server:
    def __init__(self):
        """Initialize server components and database connection."""
        # Database setup
        self.db_manager = DatabaseManager("localhost", "root", "davids74", "mysql")
        create_all_tables(self.db_manager)
        populate_media_types(self.db_manager)
        
        # Encryption setup
        self.encryptor = Encryption()
        
        # GUI initialization
        self.root = tk.Tk()
        self.root.withdraw()
        self.log_text = None
        self.client_listbox = None
        self.bg_image = None
        self.client_details_images = {}

    # ======================
    # AUDIO FUNCTIONS
    # ======================
    def play_audio(self):
        """Play intro once, then loop the cool track forever."""
        try:

            pygame.mixer.init()

            intro = r"C:\Users\shapi\Downloads\alin\cool_intro.mp3"
            loop_track = r"C:\Users\shapi\Downloads\game-of-thrones-song.mp3"

            # Play intro once
            pygame.mixer.music.load(intro)
            pygame.mixer.music.set_volume(1.0)  # optional
            pygame.mixer.music.play(loops=0, fade_ms=300)

            # After intro finishes, start loop_track forever (in a tiny background thread)
            def _loop_after_intro():
                import time
                # Wait until intro ends
                while pygame.mixer.music.get_busy():
                    time.sleep(0.2)
                # Now loop the cool track forever
                pygame.mixer.music.load(loop_track)
                pygame.mixer.music.play(loops=-1, fade_ms=300)

            threading.Thread(target=_loop_after_intro, daemon=True).start()

        except Exception as e:
            try:
                self.update_gui_log(f"Audio error: {e}")
            except Exception:
                pass


    # ======================
    # GUI UPDATE FUNCTIONS
    # ======================
    def update_gui_log(self, message):
        def _append():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.config(state=tk.DISABLED)
            self.log_text.yview(tk.END)
        self.root.after(0, _append)


    def update_client_list(self):
        """Refresh the list of connected clients."""
        self.client_listbox.delete(0, tk.END)
        clients = self.db_manager.get_rows_with_value("clients", "1", "1")
        for client in clients:
            self.client_listbox.insert(tk.END, client[0])

    # ======================
    # CLIENT INFO DISPLAY
    # ======================
    def show_client_details(self, client_id):
        """Show popup with client details."""
        client_data = self.db_manager.get_rows_with_value("clients", "client_id", client_id)
        if not client_data:
            return
            
        # Window setup
        details_window = Toplevel()
        details_window.title(f"Client {client_id} Details")
        details_window.geometry("400x350")
        
        # Background image
        bg_image = ImageTk.PhotoImage(Image.open(r"C:\Users\shapi\Downloads\alin\background_img.jpg"))
        bg_label = Label(details_window, image=bg_image)
        bg_label.image = bg_image
        bg_label.place(relwidth=1, relheight=1)
        
        # Client information fields
        client = client_data[0]
        details = [
            f"ID: {client[0]}", f"IP: {client[1]}", 
            f"Port: {client[2]}", f"Last Seen: {client[3]}",
            f"Total Actions: {client[5]}", 
            f"Status: {'Existing' if client[5] > 0 else 'New'}"
        ]
        
        # Display each detail
        for detail in details:
            lbl = Label(details_window, text=detail, fg='white', bg='black')
            lbl.pack(anchor="w", padx=10, pady=2)
        
        # History button
        history_button = Button(details_window, text="History", 
                              command=lambda: self.show_client_history(client_id),
                              bg='gray', fg='white')
        history_button.pack(pady=10)

    def show_client_history(self, client_id):
        """Display client's image history in new window."""
        # Window setup
        history_window = Toplevel()
        history_window.title(f"Client {client_id} - History")
        history_window.geometry("600x400")
        
        # Background image
        bg_image = ImageTk.PhotoImage(Image.open(r"C:\Users\shapi\Downloads\background_img.jpg"))
        bg_label = Label(history_window, image=bg_image)
        bg_label.image = bg_image
        bg_label.place(relwidth=1, relheight=1)
        
        # History label
        history_label = Label(history_window, 
                            text=f"Client {client_id} Image History",
                            font=("Arial", 12, "bold"), 
                            fg="white", bg="black")
        history_label.pack(pady=5)
        
        # Image listbox
        image_listbox = Listbox(history_window, height=15, width=80,
                              bg="black", fg="white", selectbackground="gray")
        image_listbox.pack(padx=10, pady=5, expand=True, fill="both")
        
        # Populate with images
        images = self.db_manager.get_rows_with_value("decrypted_media", "user_id", client_id)
        if not images:
            image_listbox.insert(tk.END, "No images found for this client.")
        else:
            image_paths = [img[2] for img in images]
            for path in image_paths:
                image_listbox.insert(tk.END, path)
            
            # Double-click to open image
            image_listbox.bind("<Double-Button-1>", 
                             lambda e: os.system(f'"{image_paths[image_listbox.curselection()[0]]}"'))

    # ======================
    # CLIENT HANDLING
    # ======================
    def handle_client(self, client_socket):
        """Main client connection handler."""
        client_id = 'unknown'
        try:
            # Authentication phase
            username = self.encryptor.receive_encrypted_message(client_socket)
            password = self.encryptor.receive_encrypted_message(client_socket)
            hashed_password = get_hash_value(password)

            client_ip, client_port = client_socket.getpeername()
            existing_client = self.db_manager.get_rows_with_value("clients", "client_id", username)

            # Verify or create account
            if existing_client:
                stored_hash = existing_client[0][6]
                if stored_hash != hashed_password:
                    self.encryptor.send_encrypted_message(client_socket, "PASSWORD INCORRECT. DISCONNECTING.")
                    client_socket.close()
                    return
                else:
                    self.db_manager.update_row("clients", "client_id", username, ["last_seen"], [datetime.datetime.now()])
                    self.encryptor.send_encrypted_message(client_socket, "WELCOME BACK")
                    client_status = "EXISTING"
                    total_actions = existing_client[0][5]
            else:
                self.db_manager.insert_row(
                    "clients",
                    "(client_id, client_ip, client_port, last_seen, ddos_status, total_sent_media, password_hash)",
                    "(%s, %s, %s, %s, %s, %s, %s)",
                    (username, client_ip, client_port, datetime.datetime.now(), False, 0, hashed_password)
                )
                self.encryptor.send_encrypted_message(client_socket, "WELCOME TO VEILGUARD SERVER! NEW ACCOUNT CREATED.")
                client_status = "NEW"
                total_actions = 0

            client_id = username
            self.update_gui_log(f"Client {client_id} connected - Status: {client_status}")
            self.update_client_list()

            # Main command loop
            while True:
                try:
                    # Send menu and get option
                    self.encryptor.send_encrypted_message(
                        client_socket,
                        "\n1: Blur Faces\n2: Blur Background\n3: User-Selected Blur\n4: Logout"
                    )
                    option = self.encryptor.receive_encrypted_message(client_socket)

                    # Process commands
                    if option == "1":
                        self.handle_option_1_blur_faces(client_socket, client_id)
                        total_actions += 1
                    elif option == "2":
                        self.handle_option_2_blur_background(client_socket, client_id)
                        total_actions += 1
                    elif option == "3":
                        self.handle_option_3_user_selected_blur_receive(client_socket, client_id)
                        total_actions += 1
                    elif option == "4":
                        self.handle_logout(client_socket, client_id)
                        break
                    else:
                        self.encryptor.send_encrypted_message(client_socket, "Invalid option.")

                    # Update action count
                    if option in ("1", "2", "3"):
                        self.db_manager.update_row(
                            "clients", "client_id", client_id, 
                            ["total_sent_media"], [total_actions]
                        )

                except (ConnectionResetError, socket.error) as e:
                    self.update_gui_log(f"Client {client_id} disconnected abruptly: {str(e)}")
                    break
                except Exception as e:
                    self.update_gui_log(f"Error with client {client_id}: {str(e)}")
                    try:
                        self.encryptor.send_encrypted_message(client_socket, f"[SERVER ERROR] {str(e)}")
                    except:
                        pass
                    break

        except Exception as e:
            self.update_gui_log(f"Connection error with {client_id}: {str(e)}")
        finally:
            try:
                client_socket.close()
                self.update_gui_log(f"Connection with {client_id} closed")
            except Exception as e:
                self.update_gui_log(f"Error closing socket for {client_id}: {str(e)}")
            finally:
                self.update_client_list()

    # ======================
    # COMMAND HANDLERS
    # ======================
    def handle_option_1_blur_faces(self, client_socket, client_id):
        """Receive image -> save original -> face blur -> save -> send back -> show both."""
        try:
            image_size = int(self.encryptor.receive_encrypted_message(client_socket))
            self.encryptor.send_encrypted_message(client_socket, "[INFO] Send the image...")
            buf, remaining = b'', image_size
            while remaining > 0:
                chunk = client_socket.recv(min(4096, remaining))
                if not chunk:
                    break
                buf += chunk
                remaining -= len(chunk)

            # Save original with username + option
            orig_path = save_raw_image_bytes(buf, base_dir="processed", prefix=f"{client_id}_face_original")
            self.db_manager.insert_decrypted_media(client_id, 101, orig_path)
            self.update_gui_log(f"Client {client_id}: Face blur (original) -> {orig_path}")

            # Process
            np_arr = np.frombuffer(buf, dtype=np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                raise ValueError("Failed to decode image")

            out_bgr = blur_faces_bgr(img_bgr, ksize=51)

            # Save processed with username + option
            out_path = save_bgr_image(out_bgr, base_dir="processed", prefix=f"{client_id}_face_processed")
            self.db_manager.insert_decrypted_media(client_id, 1, out_path)
            self.update_gui_log(f"Client {client_id}: Face blur (processed) -> {out_path}")

            # Show both
            try:
                os.startfile(orig_path); time.sleep(0.4)
                os.startfile(out_path)
            except Exception:
                pass

            # Send processed back
            ok, enc = cv2.imencode(".jpg", out_bgr)
            if not ok:
                raise ValueError("imencode failed")
            out_bytes = enc.tobytes()
            self.encryptor.send_encrypted_message(client_socket, str(len(out_bytes)))
            client_socket.sendall(out_bytes)

        except Exception as e:
            self.encryptor.send_encrypted_message(client_socket, f"[ERROR] {str(e)}")

    def handle_option_2_blur_background(self, client_socket, client_id):
        """Receive image -> save original -> background blur -> save -> send back -> show both."""
        try:
            image_size = int(self.encryptor.receive_encrypted_message(client_socket))
            self.encryptor.send_encrypted_message(client_socket, "[INFO] Send the image...")
            buf, remaining = b'', image_size
            while remaining > 0:
                chunk = client_socket.recv(min(4096, remaining))
                if not chunk:
                    break
                buf += chunk
                remaining -= len(chunk)

            # Save original with username + option
            orig_path = save_raw_image_bytes(buf, base_dir="processed", prefix=f"{client_id}_background_original")
            self.db_manager.insert_decrypted_media(client_id, 102, orig_path)
            self.update_gui_log(f"Client {client_id}: Background blur (original) -> {orig_path}")

            # Process
            out_bgr = blur_background_bgr_using_rembg_bytes(buf, blur_strength=51)

            # Save processed with username + option
            out_path = save_bgr_image(out_bgr, base_dir="processed", prefix=f"{client_id}_background_processed")
            self.db_manager.insert_decrypted_media(client_id, 2, out_path)
            self.update_gui_log(f"Client {client_id}: Background blur (processed) -> {out_path}")

            # Show both
            try:
                os.startfile(orig_path); time.sleep(0.4)
                os.startfile(out_path)
            except Exception:
                pass

            # Send back
            ok, enc = cv2.imencode(".jpg", out_bgr)
            if not ok:
                raise ValueError("imencode failed")
            out_bytes = enc.tobytes()
            self.encryptor.send_encrypted_message(client_socket, str(len(out_bytes)))
            client_socket.sendall(out_bytes)

        except Exception as e:
            self.encryptor.send_encrypted_message(client_socket, f"[ERROR] {str(e)}")

    def handle_option_3_user_selected_blur_receive(self, client_socket, client_id):
        """Instruct client; receive ORIGINAL then FINAL; save both; echo FINAL; show both."""
        try:
            self.encryptor.send_encrypted_message(
                client_socket,
                "[CLIENT_INTERACTIVE] Do local ROI blur. Then send ORIGINAL first, then FINAL on ESC."
            )

            # Receive ORIGINAL
            orig_size = int(self.encryptor.receive_encrypted_message(client_socket))
            self.encryptor.send_encrypted_message(client_socket, "[INFO] Send ORIGINAL...")
            orig_buf, remaining = b'', orig_size
            while remaining > 0:
                chunk = client_socket.recv(min(4096, remaining))
                if not chunk:
                    break
                orig_buf += chunk
                remaining -= len(chunk)

            orig_path = save_raw_image_bytes(orig_buf, base_dir="processed", prefix=f"{client_id}_userblur_original")
            self.db_manager.insert_decrypted_media(client_id, 103, orig_path)
            self.update_gui_log(f"Client {client_id}: User blur (original) -> {orig_path}")

            # Receive FINAL
            fin_size = int(self.encryptor.receive_encrypted_message(client_socket))
            self.encryptor.send_encrypted_message(client_socket, "[INFO] Send FINAL...")
            fin_buf, remaining = b'', fin_size
            while remaining > 0:
                chunk = client_socket.recv(min(4096, remaining))
                if not chunk:
                    break
                fin_buf += chunk
                remaining -= len(chunk)

            np_arr = np.frombuffer(fin_buf, dtype=np.uint8)
            img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                raise ValueError("Failed to decode final user-blurred image")

            fin_path = save_bgr_image(img_bgr, base_dir="processed", prefix=f"{client_id}_userblur_processed")
            self.db_manager.insert_decrypted_media(client_id, 3, fin_path)
            self.update_gui_log(f"Client {client_id}: User blur (processed) -> {fin_path}")

            # Show both
            try:
                os.startfile(orig_path); time.sleep(0.4)
                os.startfile(fin_path)
            except Exception:
                pass

            # Echo back FINAL
            ok, enc = cv2.imencode(".jpg", img_bgr)
            if not ok:
                raise ValueError("imencode failed")
            out_bytes = enc.tobytes()
            self.encryptor.send_encrypted_message(client_socket, str(len(out_bytes)))
            client_socket.sendall(out_bytes)

        except Exception as e:
            self.encryptor.send_encrypted_message(client_socket, f"[ERROR] {str(e)}")

    def handle_logout(self, client_socket, client_id):
        """Send goodbye, update GUI/DB, then gracefully close the socket."""
        try:
            self.update_gui_log(f"Client {client_id} requested logout")
            # Optional: update last_seen
            try:
                self.db_manager.update_row("clients", "client_id", client_id, ["last_seen"], [datetime.datetime.now()])
            except Exception:
                pass
            # Send goodbye
            self.encryptor.send_encrypted_message(client_socket, "GOODBYE")
        except Exception:
            pass
        finally:
            # Graceful shutdown
            try:
                client_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                client_socket.close()
            except Exception:
                pass
            self.update_gui_log(f"Connection with {client_id} closed after logout")

    # ======================
    # SERVER CONTROL
    # ======================
    def start_server(self):
        """Main server listening loop."""
        server_socket = socket.socket()
        server_socket.bind((IP, PORT))
        server_socket.listen()
        self.update_gui_log("VeilGuard server started...")
        while True:
            client_socket, _ = server_socket.accept()
            threading.Thread(target=self.handle_client, args=(client_socket,), daemon=True).start()

    def create_gui(self):
        """Initialize and run the server GUI."""
        # Play intro audio
        self.play_audio()

        # Main window setup
        self.root.destroy()
        self.root = tk.Tk()
        self.root.title("VeilGuard Server")
        self.root.geometry("500x500")

        # Background
        self.bg_image = ImageTk.PhotoImage(Image.open(r"C:\Users\shapi\Downloads\background_img.jpg"))
        bg_label = Label(self.root, image=self.bg_image)
        bg_label.place(relwidth=1, relheight=1)

        # Log display
        self.log_text = scrolledtext.ScrolledText(
            self.root, state=tk.DISABLED, wrap=tk.WORD, height=10, bg='black', fg='white'
        )
        self.log_text.pack(expand=True, fill='both', padx=10, pady=5)

        # Client list
        Label(
            self.root, text="VeilGuard Customers", 
            font=("Arial", 14, "bold"), fg="white", bg="black"
        ).pack(pady=5)

        self.client_listbox = Listbox(self.root, bg='black', fg='white')
        self.client_listbox.pack(expand=True, fill='both', padx=10, pady=5)
        self.client_listbox.bind(
            "<Double-Button-1>",
            lambda e: self.show_client_details(self.client_listbox.get(self.client_listbox.curselection()))
        )

        # Start server thread
        threading.Thread(target=self.start_server, daemon=True).start()
        self.root.mainloop()


# ======================
# MAIN ENTRY POINT
# ======================
if __name__ == "__main__":
    server = Server()
    server.create_gui()
# ======================