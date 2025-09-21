import os
from datetime import datetime
from encrypt import Encryption

class DataHider:
    def __init__(self, client_socket, db_manager, user_id):
        # Store references to client socket, database manager, and user ID
        self.client_socket = client_socket
        self.db_manager = db_manager
        self.user_id = user_id
        self.encryptor = Encryption()  # Initialize encryption handler

    def fetch_media_menu(self):
        try:
            # Get all available media options from the database
            media_menu = self.db_manager.get_all_rows("media_menu")
            if not media_menu:
                # If no media is available, inform the client and return None
                self.encryptor.send_encrypted_message(self.client_socket, "[ERROR] No media options available.")
                return None

            # Format the menu items into a string to send to the client
            menu_str = "\n".join([f"{item[0]}: {item[1] or item[2] or item[3]}" for item in media_menu])
            self.encryptor.send_encrypted_message(self.client_socket, menu_str)

            # Receive the selected media ID from the client
            selected_id = self.encryptor.receive_encrypted_message(self.client_socket)

            # Find the media item that matches the selected ID
            selected_media = next((item for item in media_menu if str(item[0]) == selected_id), None)

            if selected_media is None:
                # If the ID is not found, notify the client
                self.encryptor.send_encrypted_message(self.client_socket, f"[ERROR] Media ID '{selected_id}' not found.")
            return selected_media
        except Exception as e:
            # Handle any exception and send the error message back to the client
            print(f"[EXCEPTION in fetch_media_menu] {e}")
            self.encryptor.send_encrypted_message(self.client_socket, f"[EXCEPTION in fetch_media_menu] {e}")
            return None

    def receive_data_to_hide(self):
        try:
            # Receive the size of the incoming data
            size_str = self.encryptor.receive_encrypted_message(self.client_socket)
            size = int(size_str)
            print(f"[INFO] Expecting {size} bytes of data...")

            data = b''  # Initialize byte buffer

            # Receive the data in chunks until the full size is reached
            while len(data) < size:
                chunk = self.client_socket.recv(4096)
                if not chunk:
                    print("[ERROR] Unexpected disconnection while receiving data.")
                    break
                data += chunk

            # Warn if the actual size received does not match expected size
            if len(data) != size:
                print(f"[WARNING] Expected {size}, but got {len(data)} bytes.")

            return data
        except Exception as e:
            print(f"[EXCEPTION in receive_data_to_hide] {e}")
            raise  # Propagate exception to caller

    def create_hidden_file(self, media_path, data_to_hide):
        # Validate that media_path exists
        if not media_path or not os.path.exists(media_path):
            raise FileNotFoundError(f"[ERROR] Media path '{media_path}' does not exist or is invalid.")

        try:
            # Generate a unique output file name using user ID and current time
            output_path = f"hidden_{self.user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"

            # Read original media file
            with open(media_path, "rb") as media_file:
                media_data = media_file.read()

            # Write the media followed by hidden data into a new file
            with open(output_path, "wb") as output_file:
                output_file.write(media_data + data_to_hide)

            return output_path
        except Exception as e:
            # Raise an exception with a detailed error message
            raise IOError(f"[ERROR] Failed to create hidden file: {e}")

    def run(self):
        try:
            # Step 1: Get the media selection from the client
            selected_media = self.fetch_media_menu()
            if not selected_media:
                return  # Exit if media selection failed

            # Extract the media path from the selected row (based on 3 possible path columns)
            media_path = selected_media[1] or selected_media[2] or selected_media[3]
            if not media_path:
                self.encryptor.send_encrypted_message(self.client_socket, "[ERROR] No valid media path found in the selected media.")
                return

            print(f"[INFO] Selected media path: {media_path}")

            # Step 2: Receive the data to hide from the client
            data_to_hide = self.receive_data_to_hide()

            # Step 3: Attempt to create the hidden image
            try:
                output_path = self.create_hidden_file(media_path, data_to_hide)
            except Exception as e:
                # Send the error back to the client and abort
                self.encryptor.send_encrypted_message(self.client_socket, str(e))
                return

            # Step 4: Insert the output path into decrypted_media table for tracking
            self.db_manager.insert_decrypted_media(self.user_id, 1, output_path)

            # Step 5: Inform client of success
            self.encryptor.send_encrypted_message(self.client_socket, f"[SUCCESS] Data successfully hidden in {output_path}")

            # Return values used by the server to track and log
            return selected_media[0], 1, output_path
        except Exception as e:
            # Log and send any unexpected error
            print(f"[EXCEPTION in run()] {e}")
            self.encryptor.send_encrypted_message(self.client_socket, f"[EXCEPTION in run()] {e}")
