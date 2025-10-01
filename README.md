
# VeilGuard — Quick README 

**What it is:** A client–server image privacy suite.  
- **Server (Tkinter)** receives encrypted images, runs **Face Blur**, **Background Blur**, stores originals & results in MySQL, and returns processed images to the client.  
- **Client (Tkinter)** lets you pick an image (or use server defaults), run operations, preview **Original** vs **Processed**, and do **User ROI Blur** locally (draw rectangles; ESC to finish).

---

## Requirements

### Server
- **OS:** Windows recommended  
- **Python:** 3.9+  
- **MySQL:** running locally (or update credentials in code)  
- **Python packages (install):**
  ```powershell
  pip install mediapipe opencv-python pillow numpy mysql-connector-python pygame
````

* Configure `constants.py` (same `PORT` as the client).
* Place default images in the server folder (next to `cyber_server.py`):

  ```
  test15.png, test16.png, test17.png
  ```

### Client

* **OS:** Windows recommended
* **Python:** 3.9+
* **Python packages (install):**

  ```powershell
  pip install opencv-python pillow numpy
  ```
* Required files: `cyber_client.py`, `encrypt.py`, `constants.py`.

---

## How to Run (Same PC)

1. **Start the server**

```powershell
python cyber_server.py
```

2. **Start the client**

```powershell
python cyber_client.py
```

* First run shows a login (creates `creds.txt` locally).
* If you **don’t select an image**, the client can send `"0"` and the **server will use its default images** (`test15/16/17`).
* Choose one:

  * **Blur Faces** (server-side)
  * **Blur Background** (server-side)
  * **User ROI Blur** (client-side; draw rectangles, press **ESC** to finish)
* **Logout** when done.

---

## Run the Client from a Different PC (LAN)

1. Copy client files to the other PC: `cyber_client.py`, `encrypt.py`, `constants.py`.
2. Install client deps:

```powershell
pip install opencv-python pillow numpy
```

3. Edit `constants.py` on the client PC to point to your server:

```python
IP = "<SERVER_PC_LOCAL_IP>"  # e.g. "192.168.1.23"
PORT = 4444                  # must match the server
CHUNK_SIZE = 4096
```

4. On the **server PC**, open Windows Defender Firewall and allow inbound TCP on the chosen `PORT` (e.g., 4444).
5. Make sure both PCs are on the same LAN.
6. Start the server on the server PC, then run the client on the client PC.

---

## Notes

* For **server-default images** (no file selected), the server returns **ORIGINAL first** and then **PROCESSED**, so the client always shows both previews.
* **User ROI Blur** runs locally; the final image is then sent to the server for saving/history.
* Database tables: `clients` and `decrypted_media` (update credentials/host in `db_manager` usage if needed).

---

## Save Changes with Git

```powershell
git status
git add -A
git commit -m "short message"
git push
```

If you need to set the remote:

```powershell
git remote set-url origin https://github.com/<your-username>/VeilGuard.git
git branch -M main
git push -u origin main
```

```
```
