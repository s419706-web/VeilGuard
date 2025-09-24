# VeilGuard — Quick README

## What it is (very short)

Client–server image privacy suite:

* **Server** (Tkinter) receives encrypted images, runs: **Face Blur**, **Background Blur**, stores originals & results in MySQL, and returns processed images.
* **Client** (Tkinter) lets you pick an image, run operations, preview Original vs. Processed, and supports **User ROI Blur** locally (mouse-draw rectangles).

---

## Requirements (minimal)

### Server

* **OS:** Windows recommended
* **Python:** 3.9+
* **MySQL** running locally (or update creds in code)
* **Python packages:**

  ```
  pygame
  opencv-python
  pillow
  rembg
  numpy
  mysql-connector-python
  ```
* Configure `constants.py` (same `PORT` as client).

### Client

* **OS:** Windows recommended
* **Python:** 3.9+
* **Python packages:**

  ```
  opencv-python
  pillow
  numpy
  ```
* Files required: `cyber_client.py`, `encrypt.py`, `constants.py` (from this project).

---

## Run the client from a different PC (connecting to your server)

1. **Copy client files** to the other PC:
   `cyber_client.py`, `encrypt.py`, `constants.py` (and any image assets you want).

2. **Install Python & deps** on the other PC:

   ```powershell
   pip install opencv-python pillow numpy
   ```

3. **Point the client to your server**:
   Edit `constants.py` on the client PC:

   ```python
   IP = "<SERVER_PC_LOCAL_IP>"   # e.g. "192.168.1.23"
   PORT = 4444                   # must match the server
   CHUNK_SIZE = 4096
   ```

4. **Allow the port on the server PC**:
   On the server machine, open Windows Defender Firewall → inbound rule for `PORT` (e.g. 4444).
   Ensure both PCs are on the same network (LAN). (Over the internet = port forwarding/VPN—**not recommended** for demos.)

5. **Start the server** on the server PC:

   ```powershell
   python cyber_server.py
   ```

6. **Run the client** on the other PC:

   ```powershell
   python cyber_client.py
   ```

   * First run shows login (creates `creds.txt`).
   * Choose an image, click **Blur Faces / Blur Background / User ROI Blur**.
   * **Logout** when done.


