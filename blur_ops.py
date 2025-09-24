# blur_ops.py
# ======================
# Algorithms (Server-side)
# ======================
# 1) Face Blur (auto):
#    - Convert BGR to Gray
#    - Detect faces using Haar Cascade
#    - Apply Gaussian blur on each face ROI
#    - Return blurred image (BGR)
#
# 2) Background Blur (via rembg):
#    - Read input bytes
#    - remove() returns RGBA with alpha (foreground)
#    - Read original (RGB) and blur as background
#    - Alpha-blend FG over blurred background
#    - Return BGR image

import cv2
import numpy as np
from PIL import Image
import io
from rembg import remove
import os
import time

CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

def blur_faces_bgr(img_bgr, ksize=51, cascade_path: str = CASCADE_PATH):
    """Auto face blur using Haar cascade with robust loading, resizing and hist-eq."""
    # Ensure odd kernel size for GaussianBlur
    if ksize % 2 == 0:
        ksize += 1

    # 1) Load cascade robustly
    face_cascade = cv2.CascadeClassifier(cascade_path)
    if face_cascade.empty():
        # Fallback to local file if present
        local_xml = os.path.join(os.getcwd(), "haarcascade_frontalface_default.xml")
        face_cascade = cv2.CascadeClassifier(local_xml)

    out = img_bgr.copy()

    # 2) Normalize orientation issues: work on a downscaled copy for detection
    h, w = out.shape[:2]
    target_w = 800 if w > 800 else w
    scale = target_w / float(w)
    det_img = cv2.resize(out, (int(w * scale), int(h * scale))) if scale != 1.0 else out.copy()

    gray = cv2.cvtColor(det_img, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)

    # 3) Try detection with slightly more permissive params
    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24)
    )

    # 4) If nothing found, try again with another set (more aggressive)
    if len(faces) == 0:
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.05, minNeighbors=3, minSize=(20, 20)
        )

    # 5) Blur detected ROIs on the full-size image
    for (x, y, w_box, h_box) in faces:
        # Map back to original scale if we resized
        if scale != 1.0:
            x = int(x / scale); y = int(y / scale)
            w_box = int(w_box / scale); h_box = int(h_box / scale)

        x2, y2 = x + w_box, y + h_box
        x, y = max(0, x), max(0, y)
        x2, y2 = min(out.shape[1], x2), min(out.shape[0], y2)
        roi = out[y:y2, x:x2]
        if roi.size == 0:
            continue
        roi_blur = cv2.GaussianBlur(roi, (ksize, ksize), 0)
        out[y:y2, x:x2] = roi_blur

    return out

def blur_background_bgr_using_rembg_bytes(image_bytes: bytes, blur_strength=51):
    """Background blur using rembg alpha matte and Gaussian blending."""
    if blur_strength % 2 == 0:
        blur_strength += 1

    output_image = remove(image_bytes)
    result_image = Image.open(io.BytesIO(output_image)).convert("RGBA")
    result_array = np.array(result_image)
    if result_array.shape[2] != 4:
        rgb = np.array(result_image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    fg_rgb = result_array[:, :, :3]
    alpha = result_array[:, :, 3]

    orig = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    original_rgb = np.array(orig)
    blurred_bg = cv2.GaussianBlur(original_rgb, (blur_strength, blur_strength), 0)

    mask = (alpha.astype(float) / 255.0)
    mask3 = np.dstack([mask, mask, mask])

    final_rgb = (fg_rgb * mask3 + blurred_bg * (1 - mask3)).astype(np.uint8)
    final_bgr = cv2.cvtColor(final_rgb, cv2.COLOR_RGB2BGR)
    return final_bgr
# Saving utilities : 
def safe_prefix(text: str) -> str:
    """Make a filesystem-safe prefix (letters, digits, underscore, dash)."""
    import re
    return re.sub(r'[^A-Za-z0-9_\-]+', '_', text.strip())

def save_bgr_image(img_bgr, base_dir="processed", prefix="out"):
    """Save BGR image to disk with a username/option-aware prefix."""
    os.makedirs(base_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    pref = safe_prefix(prefix)
    path = os.path.join(base_dir, f"{pref}_{ts}.jpg")
    cv2.imwrite(path, img_bgr)
    return path

def save_raw_image_bytes(image_bytes: bytes, base_dir="processed", prefix="orig"):
    """Save original image bytes (format-preserving) with a username/option-aware prefix."""
    os.makedirs(base_dir, exist_ok=True)
    img = Image.open(io.BytesIO(image_bytes))
    ext = (img.format or "JPEG").lower()
    ts = time.strftime("%Y%m%d_%H%M%S")
    pref = safe_prefix(prefix)
    path = os.path.join(base_dir, f"{pref}_{ts}.{ext}")
    with open(path, "wb") as f:
        f.write(image_bytes)
    return path