# ======================
# IMPORTS AND DEPENDENCIES
# ======================
import socket
import threading
import tkinter as tk
from tkinter import Label, scrolledtext, Toplevel, Listbox, Button
from constants import IP, PORT
from db_manager import DatabaseManager
from create_tables import create_all_tables, populate_media_menu
from hide_png import DataHider
from decode_png import ImageExtractor
import datetime
from PIL import Image, ImageTk
import os
import pygame
import time
from encrypt import Encryption
from tools_no_encryption import *  
from img_auth_checker import *

# ======================
# SERVER CLASS DEFINITION
# ======================
class Server:
    def __init__(self):
        """Initialize server components and database connection"""
        # Database setup
        self.db_manager = DatabaseManager("localhost", "root", "davids74", "mysql")
        create_all_tables(self.db_manager)
        populate_media_menu(self.db_manager)
        
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
        """Play background music during server operation"""
        pygame.mixer.init()
        pygame.mixer.music.load("C:\\Users\\shapi\\Downloads\\cool_intro.mp3")
        pygame.mixer.music.play()
        pygame.mixer.music.queue("C:\\Users\\shapi\\Downloads\\game-of-thrones-song.mp3")

    # ======================
    # GUI UPDATE FUNCTIONS
    # ======================
    def update_gui_log(self, message):
        """Append messages to the server log display"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.config(state=tk.DISABLED)
        self.log_text.yview(tk.END)

    def update_client_list(self):
        """Refresh the list of connected clients"""
        self.client_listbox.delete(0, tk.END)
        clients = self.db_manager.get_rows_with_value("clients", "1", "1")
        for client in clients:
            self.client_listbox.insert(tk.END, client[0])

    # ======================
    # CLIENT INFO DISPLAY
    # ======================
    def show_client_details(self, client_id):
        """Show popup with client details"""
        client_data = self.db_manager.get_rows_with_value("clients", "client_id", client_id)
        if not client_data:
            return
            
        # Window setup
        details_window = Toplevel()
        details_window.title(f"Client {client_id} Details")
        details_window.geometry("400x350")
        
        # Background image
        bg_image = ImageTk.PhotoImage(Image.open(r"C:\Users\shapi\Downloads\background_img.jpg"))
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
        """Display client's image history in new window"""
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
        """Main client connection handler"""
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
                self.encryptor.send_encrypted_message(client_socket, "WELCOME TO MASKER SERVER! NEW ACCOUNT CREATED.")
                client_status = "NEW"
                total_actions = 0

            client_id = username
            self.update_gui_log(f"Client {client_id} connected - Status: {client_status}")
            self.update_client_list()

            # Main command loop
            while True:
                try:
                    # Send menu and get option
                    self.encryptor.send_encrypted_message(client_socket, "\n1: Hide Data\n2: Decode Data\n3: Verify Image Authenticity\n4: Logout")
                    option = self.encryptor.receive_encrypted_message(client_socket)

                    # Process commands
                    if option == "1":
                        self.handle_hide_option(client_socket, client_id)
                        total_actions += 1
                    elif option == "2":
                        self.handle_decode_option(client_socket, client_id)
                        total_actions += 1
                    elif option == "3":
                        self.handle_verify_option(client_socket, client_id)
                        total_actions += 1
                    elif option == "4":
                        self.handle_logout(client_socket, client_id)
                        break
                    else:
                        self.encryptor.send_encrypted_message(client_socket, "Invalid option.")

                    # Update action count
                    if option in ("1", "2","3"):
                        self.db_manager.update_row("clients", "client_id", client_id, 
                                                ["total_sent_media"], [total_actions])

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
    def handle_hide_option(self, client_socket, client_id):
        """Handle data hiding request"""
        hider = DataHider(client_socket, self.db_manager, client_id)
        result = hider.run()
        if result is not None and all(result):
            media_id, media_type_id, path = result
            self.db_manager.insert_decrypted_media(client_id, media_type_id, path)
        else:
            self.update_gui_log(f"Client {client_id}: Hide operation failed")

    def handle_decode_option(self, client_socket, client_id):
        """Handle image decoding request"""
        extractor = ImageExtractor(client_socket, self.db_manager, client_id)
        media_id, media_type, path = extractor.run()
        self.db_manager.insert_decrypted_media(client_id, media_id, path)

    def handle_verify_option(self, client_socket, client_id):
        try:
            # 1. Receive image from client
            image_size = int(self.encryptor.receive_encrypted_message(client_socket))
            self.encryptor.send_encrypted_message(client_socket, "[INFO] Send the image...")
            
            # 2. Save original temporarily
            timestamp = int(time.time())
            original_path = f"verify_{client_id}_{timestamp}.jpg"
            with open(original_path, "wb") as f:
                remaining = image_size
                while remaining > 0:
                    chunk = client_socket.recv(min(4096, remaining))
                    f.write(chunk)
                    remaining -= len(chunk)

            # 3. Perform verification
            checker = ImageAuthChecker()
            is_fake = checker.is_image_fake(original_path)
            result = "Fake" if is_fake else "Real"
            result_path = "Fake.jpg" if is_fake else "Real.jpg"
            
            # 4. Show BOTH images in GUI
            self.update_gui_log(f"Client {client_id} verification: Original + {result} result shown - Verification completed")
            
            # Open both images (original first, then result)
            os.startfile(original_path)
            time.sleep(0.5)  # Small delay
            os.startfile(result_path)
            
            # Store BOTH with new types
            self.db_manager.insert_row(
                "decrypted_media",
                "(user_id, media_type_id, path_to_decrypted_media)",
                "(%s, %s, %s)",
                (client_id, 4, original_path)  # Type 4 for original
            )
            self.db_manager.insert_row(
                "decrypted_media",
                "(user_id, media_type_id, path_to_decrypted_media)",
                "(%s, %s, %s)",
                (client_id, 5, result_path)  # Type 5 for result
            )
            
            # 6. Send text result
            self.encryptor.send_encrypted_message(client_socket, f"[RESULT] Image is {result}")

        except Exception as e:
            self.encryptor.send_encrypted_message(client_socket, f"[ERROR] {str(e)}")
            
    def handle_logout(self, client_socket, client_id):
        """Handle client logout"""
        self.update_gui_log(f"Client {client_id} logged out")
        self.encryptor.send_encrypted_message(client_socket, "GOODBYE")

    # ======================
    # SERVER CONTROL
    # ======================
    def start_server(self):
        """Main server listening loop"""
        server_socket = socket.socket()
        server_socket.bind((IP, PORT))
        server_socket.listen()
        self.update_gui_log("Server started...")
        while True:
            client_socket, _ = server_socket.accept()
            threading.Thread(target=self.handle_client, args=(client_socket,), daemon=True).start()

    def create_gui(self):
        """Initialize and run the server GUI"""
        # Play intro audio
        self.play_audio()

        

        # Main window setup
        self.root.destroy()
        self.root = tk.Tk()
        self.root.title("Server GUI")
        self.root.geometry("500x500")

        # Background
        self.bg_image = ImageTk.PhotoImage(Image.open(r"C:\Users\shapi\Downloads\background_img.jpg"))
        bg_label = Label(self.root, image=self.bg_image)
        bg_label.place(relwidth=1, relheight=1)

        # Log display
        self.log_text = scrolledtext.ScrolledText(self.root, 
                                                state=tk.DISABLED, 
                                                wrap=tk.WORD, 
                                                height=10, 
                                                bg='black', 
                                                fg='white')
        self.log_text.pack(expand=True, fill='both', padx=10, pady=5)

        # Client list
        Label(self.root, text="MASKER Customers", 
             font=("Arial", 14, "bold"), 
             fg="white", bg="black").pack(pady=5)

        self.client_listbox = Listbox(self.root, bg='black', fg='white')
        self.client_listbox.pack(expand=True, fill='both', padx=10, pady=5)
        self.client_listbox.bind("<Double-Button-1>", 
                               lambda e: self.show_client_details(self.client_listbox.get(self.client_listbox.curselection())))

        # Start server thread
        threading.Thread(target=self.start_server, daemon=True).start()
        self.root.mainloop()

# ======================
# MAIN ENTRY POINT
# ======================
if __name__ == "__main__":
    server = Server()
    server.create_gui()