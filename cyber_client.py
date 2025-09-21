# ======================
# IMPORT STATEMENTS
# ======================
from tkinter import Label, scrolledtext, Toplevel, Listbox, Button
import tkinter as tk
import socket
import os
import random
import time
from PIL import Image, ImageTk
from constants import IP, PORT, CHUNK_SIZE
from encrypt import Encryption

# ======================
# CLIENT CLASS DEFINITION
# ======================
class Client:
    def __init__(self):
        """Initialize client with default image paths and encryption"""
        # List of images that can have hidden data extracted
        self.decrypted_list_paths = [
            r"C:\Users\shapi\Downloads\mail_photo.jpg"
        ]
        
        # List of regular images for hiding data/verification
        self.usual_images = [
            r"C:\Users\shapi\Downloads\alin\img1.jpg",
            r"C:\Users\shapi\Downloads\alin\img2.jpg",
            r"C:\Users\shapi\Downloads\alin\img3.jpg"
        ]
        
        # Networking components
        self.client_socket = None
        self.encryptor = Encryption()

    # ======================
    # NETWORK CONNECTION
    # ======================
    def connect_to_server(self):
        """Establish connection to the server"""
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
        root = tk.Tk()
        root.withdraw()  # מסתיר את ה-root הראשי

        splash = Toplevel(root)
        splash.geometry("400x400")
        splash.overrideredirect(True)

        logo = Image.open(r"C:\Users\shapi\Downloads\intro_img.jpg").resize((400, 400))
        logo_photo = ImageTk.PhotoImage(logo)
        label = Label(splash, image=logo_photo)
        label.image = logo_photo
        label.pack()

        # סוגר את הספלש אחרי 4 שניות
        def close_splash():
            splash.destroy()
            root.destroy()  # סוגר את root לחלוטין

        splash.after(4000, close_splash)
        root.mainloop()
        # ======================
        # AUTHENTICATION
        # ======================
    def send_credentials(self):
        """Send username/password to server for authentication"""
        creds_file = "creds.txt"

        if os.path.exists(creds_file):
            # אם יש קובץ – קורא ממנו
            with open(creds_file, "r") as f:
                lines = f.read().strip().split("\n")
                client_id = lines[0]
                password = lines[1]
        else:
            # אם אין קובץ – פותח UI קטן עם tkinter
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

            # שמירת הנתונים לקובץ לשימוש עתידי
            with open(creds_file, "w") as f:
                f.write(client_id + "\n" + password)

        # שולח לשרת מוצפן
        self.encryptor.send_encrypted_message(self.client_socket, client_id)
        self.encryptor.send_encrypted_message(self.client_socket, password)

        # תגובת שרת
        response = self.encryptor.receive_encrypted_message(self.client_socket)
        print(response)

        if "PASSWORD INCORRECT" in response:
            self.client_socket.close()
            exit()

    # ======================
    # MENU HANDLING
    # ======================
    def receive_menu(self):
        """Receive and display server menu options"""
        try:
            menu = self.encryptor.receive_encrypted_message(self.client_socket)
            print("\nAvailable operations:")
            print(menu)
            return menu
        except Exception as e:
            print(f"Menu error: {e}")
            return None

    # ======================
    # OPERATION HANDLERS
    # ======================

    def handle_hide_option(self):
        """Handle data hiding operation"""
        print("\n[Data Hiding Mode]")
        
        try:
            # Get available media types from server
            media_menu = self.encryptor.receive_encrypted_message(self.client_socket)
            
            if "No media options available." in media_menu:
                print("No media options available.")
                return

            print("\nAvailable media types:")
            print(media_menu)

            # Extract valid IDs from menu
            valid_ids = [
                line.split(":")[0].strip() 
                for line in media_menu.strip().split("\n") 
                if ":" in line and line[0].isdigit()
            ]

            if not valid_ids:
                print("No valid media IDs found.")
                return

            # Random selection 
            selected_media_id = random.choice(valid_ids)
            
            #open img we are hiding in
            if os.path.exists(selected_media_id):
                    Image.open(selected_media_id).show()
            
            print("Selected media type ID:", selected_media_id)
            self.encryptor.send_encrypted_message(self.client_socket, selected_media_id)

            # Select random image to hide
            data_to_hide_path = random.choice(self.usual_images)
            print("Using image:", data_to_hide_path)
            
            #opening picture: 
            if os.path.exists(data_to_hide_path):
                    Image.open(data_to_hide_path).show()

            if not os.path.exists(data_to_hide_path):
                print("Image not found!")
                return

            # Send image data
            with open(data_to_hide_path, "rb") as file:
                data = file.read()
                
            self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
            time.sleep(0.1)  # Small delay for server
            self.client_socket.sendall(data)

            # Handle server response
            response = self.encryptor.receive_encrypted_message(self.client_socket)
            print("[Server]:", response)

            # Open result if successful
            if response.startswith("[SUCCESS]") and "in " in response:
                output_path = response.split("in ")[-1].strip()
                if os.path.exists(output_path):
                    Image.open(output_path).show()

        except Exception as e:
            print(f"Hiding operation failed: {e}")

    def handle_decode_option(self):
        """Handle data extraction operation"""
        print("\n[Data Decoding Mode]")
        
        # Select random image with hidden data
        media_path = random.choice(self.decrypted_list_paths)
        print("Processing file:", media_path)

        if not os.path.exists(media_path):
            print("File not found!")
            return

        # Send image to server
        with open(media_path, "rb") as file:
            data = file.read()

        self.encryptor.send_encrypted_message(self.client_socket, str(len(data)))
        time.sleep(0.1)
        self.client_socket.sendall(data)

        try:
            # Get number of hidden images
            num_images = int(self.encryptor.receive_encrypted_message(self.client_socket))
            print(f"Found {num_images} hidden images")
            
            # Receive each hidden image
            for i in range(num_images):
                image_size = int(self.encryptor.receive_encrypted_message(self.client_socket))
                self.encryptor.send_encrypted_message(self.client_socket, "ACK")
                
                # Receive image data
                image_data = b''
                while len(image_data) < image_size:
                    image_data += self.client_socket.recv(4096)
                
                # Save decoded image
                output_path = f"decoded_image_{i+1}.jpg"
                with open(output_path, "wb") as file:
                    file.write(image_data)
                
                print(f"Saved decoded image: {output_path}")
                Image.open(output_path).show()
                
        except Exception as e:
            print(f"Decoding failed: {e}")

    def handle_auth_check_option(self):
        """Handle image authenticity verification"""
        print("\n[Authenticity Check Mode]")
        
        # Select random image for verification
        path = random.choice(self.usual_images)
        print("Verifying image:", path)

        if not os.path.exists(path):
            print("Image not found!")
            return

        # Read and send image data
        with open(path, "rb") as file:
            image_data = file.read()

        # Send image size first
        self.encryptor.send_encrypted_message(self.client_socket, str(len(image_data)))
        
        # Wait for server ready signal
        ready_msg = self.encryptor.receive_encrypted_message(self.client_socket)
        print("[Server]:", ready_msg)
        
        # Send actual image data
        self.client_socket.sendall(image_data)
        
        # Get verification result
        response = self.encryptor.receive_encrypted_message(self.client_socket)
        print("[Verification Result]:", response)

    # ======================
    # MAIN CLIENT LOOP
    # ======================
    def run(self):
        """Main client execution flow"""
        try:
            # Setup connection
            self.connect_to_server()
            if not self.client_socket:
                return
            
            #create the splash screen
            self.show_splash()
            
            # Authenticate
            self.send_credentials()

            # Main interaction loop
            while True:
                menu = self.receive_menu()
                if not menu:
                    break

                #Let the client pick the option
                option = input("Enter option 1-4: ")
                self.encryptor.send_encrypted_message(self.client_socket, option)

                # Handle selected operation
                if option == "1":
                    self.handle_hide_option()
                elif option == "2":
                    self.handle_decode_option()
                elif option == "3":
                    self.handle_auth_check_option()
                elif option == "4":
                    
                    print(self.encryptor.receive_encrypted_message(self.client_socket))
                    break  # Logout
                else:
                    print("Invalid selection")

        except KeyboardInterrupt:
            print("\nClient shutting down...")
        except Exception as e:
            print(f"Fatal error: {e}")
        finally:
            # Cleanup
            if hasattr(self, 'client_socket') and self.client_socket:
                try:
                    self.client_socket.close()
                    print("Connection closed")
                except:
                    pass

# ======================
# ENTRY POINT
# ======================
if __name__ == "__main__":
    print("Starting Masker Client...")
    client = Client()
    client.run()