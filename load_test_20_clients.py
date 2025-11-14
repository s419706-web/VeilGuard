"""
load_test_20_clients.py
-----------------------
Headless load-test:
- Spawns NUM_CLIENTS threads
- Each connects to VeilGuard server
- Logs in using creds.txt (same as GUI client)
- Runs one operation (1/2/3) with server-default image
- Logs out

No Tkinter, no user input.
"""

import threading
import socket
import time
import os
import json

from encrypt import Encryption
from constants import IP, PORT

# =======================
# CONFIG
# =======================
NUM_CLIENTS = 20       # how many concurrent clients
OPERATION   = "1"         # "1" = Blur Faces, "2" = Blur Background, "3" = User ROI flow
USE_DEFAULT_IMAGE = True  # we always use server default images here
CREDS_FILE = "creds.txt"  # SAME file used by your GUI client


# =======================
# CREDENTIALS LOADING
# =======================
def load_single_creds():
    """
    Read username/password from creds.txt exactly like the GUI client:
        line 1: username
        line 2: password
    """
    if not os.path.exists(CREDS_FILE):
        raise RuntimeError(
            f"{CREDS_FILE} not found. "
            "Run the GUI client once, log in, so it creates creds.txt."
        )

    with open(CREDS_FILE, "r", encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
        if len(lines) < 2:
            raise RuntimeError(f"{CREDS_FILE} has invalid format (need 2 lines).")
        username = lines[0].strip()
        password = lines[1].strip()
    return username, password


# =======================
# HEADLESS CLIENT
# =======================
class HeadlessClient:
    """
    Minimal non-GUI client that talks to the VeilGuard server using
    the same Encryption + protocol as the real GUI client, but without Tkinter.
    """

    def __init__(self, username, password, index):
        self.username = username
        self.password = password
        self.index = index
        self.sock = None
        self.enc = Encryption()

    def connect(self):
        """Open a TCP connection to the server."""
        self.sock = socket.socket()
        self.sock.connect((IP, PORT))

    def close(self):
        """Close the socket if open."""
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

    def send_credentials(self):
        """
        Log in without any user interaction:
        - send username/password encrypted
        - check server response for incorrect password
        """
        self.enc.send_encrypted_message(self.sock, self.username)
        self.enc.send_encrypted_message(self.sock, self.password)
        resp = self.enc.receive_encrypted_message(self.sock)
        if resp is None:
            raise RuntimeError(f"#{self.index:02d} {self.username}: No response on login")
        if "INCORRECT" in resp.upper():
            raise RuntimeError(f"#{self.index:02d} {self.username}: Auth failed: {resp}")

    def recv_exact(self, n):
        """
        Read exactly n raw bytes from the socket (or until connection closes).
        """
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(min(4096, n - len(buf)))
            if not chunk:
                break
            buf += chunk
        return buf

    def receive_menu(self):
        """
        Read the server textual menu (if sent). Fail silently if anything goes wrong.
        """
        try:
            return self.enc.receive_encrypted_message(self.sock)
        except Exception:
            return None

    # -----------------------
    # Operations
    # -----------------------
    def run_operation(self, option):
        """
        Perform one operation:
          "1": Blur Faces
          "2": Blur Background
          "3": User-Selected ROI blur (server-side, with empty ROI list here)
        All use server default image (USE_DEFAULT_IMAGE = True).
        """
        # 1) Choose operation
        self.enc.send_encrypted_message(self.sock, option)

        if option in ("1", "2"):
            # For load-test: always use server default image
            if USE_DEFAULT_IMAGE:
                self.enc.send_encrypted_message(self.sock, "0")
                _ = self.enc.receive_encrypted_message(self.sock)  # e.g. "[INFO] Using server default image..."
            else:
                raise NotImplementedError("For this load test we assume USE_DEFAULT_IMAGE=True")

            # Receive ORIGINAL size and bytes
            size_str = self.enc.receive_encrypted_message(self.sock)
            if size_str is None:
                raise RuntimeError("No size for ORIGINAL")
            if size_str.startswith("[ERROR]"):
                raise RuntimeError(size_str)
            orig_size = int(size_str)
            _ = self.recv_exact(orig_size)

            # Receive PROCESSED size and bytes
            size_str = self.enc.receive_encrypted_message(self.sock)
            if size_str is None:
                raise RuntimeError("No size for PROCESSED")
            if size_str.startswith("[ERROR]"):
                raise RuntimeError(size_str)
            proc_size = int(size_str)
            _ = self.recv_exact(proc_size)

        elif option == "3":
            # Option 3: ROI-based blur on server.
            # For this load-test client, we send an *empty* ROI list just to exercise the flow.

            # 1) Wait for "[SERVER_READY]" banner
            _ = self.enc.receive_encrypted_message(self.sock)

            # 2) Ask server to use default image ("0")
            self.enc.send_encrypted_message(self.sock, "0")

            # 3) Receive ORIGINAL for ROI selection (we don't actually draw ROIs here)
            size_str = self.enc.receive_encrypted_message(self.sock)
            if size_str is None:
                raise RuntimeError("No size for ORIGINAL in option 3")
            if size_str.startswith("[ERROR]"):
                raise RuntimeError(size_str)
            orig_size = int(size_str)
            _ = self.recv_exact(orig_size)

            # 4) Send empty ROI list as JSON
            self.enc.send_encrypted_message(self.sock, "[C_RECTS]")
            self.enc.send_encrypted_message(self.sock, json.dumps([]))

            # 5) Receive PROCESSED result (which will be identical to ORIGINAL in this case)
            size_str = self.enc.receive_encrypted_message(self.sock)
            if size_str is None:
                raise RuntimeError("No size for PROCESSED in option 3")
            if size_str.startswith("[ERROR]"):
                raise RuntimeError(size_str)
            out_size = int(size_str)
            _ = self.recv_exact(out_size)
        else:
            raise ValueError(f"Unsupported option: {option}")

    def logout(self):
        """
        Send logout command ("4") and read final message if available.
        """
        try:
            self.enc.send_encrypted_message(self.sock, "4")
            _ = self.enc.receive_encrypted_message(self.sock)  # "GOODBYE"
        except Exception:
            pass


# =======================
# THREAD WORKER
# =======================
def client_worker(barrier, username, password, index):
    c = HeadlessClient(username, password, index)
    try:
        c.connect()
        c.send_credentials()

        # Wait until all clients finished login, then start op together
        barrier.wait()

        _ = c.receive_menu()         # initial menu
        c.run_operation(OPERATION)   # run op 1/2/3
        _ = c.receive_menu()         # menu after op
        c.logout()

        print(f"[OK] #{index:02d} {username} finished.")
    except Exception as e:
        print(f"[ERR] #{index:02d} {username}: {e}")
    finally:
        c.close()


# =======================
# MAIN
# =======================
def main():
    username, password = load_single_creds()
    print(f"Starting load test with {NUM_CLIENTS} clients on {IP}:{PORT}, op={OPERATION}")
    print(f"All clients use username='{username}' from {CREDS_FILE}")

    barrier = threading.Barrier(NUM_CLIENTS)
    threads = []

    for i in range(NUM_CLIENTS):
        t = threading.Thread(
            target=client_worker,
            args=(barrier, username, password, i),
            daemon=True
        )
        threads.append(t)

    # Start all client threads
    for t in threads:
        t.start()
        # אפשר להשאיר stagger קטן או לבטל אותו – זה רק “ריכוך” להגנה/OS
        time.sleep(0.02)

    # Wait for all threads to finish
    for t in threads:
        t.join()

    print("All clients finished.")


if __name__ == "__main__":
    main()
