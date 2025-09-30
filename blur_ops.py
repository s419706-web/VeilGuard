# blur_ops.py
# =============================================================================
# VeilGuard - Image Operations (Face Blur, Background Blur, Saving Helpers)
# -----------------------------------------------------------------------------
# Robust, explainable face/background blur without external model files.
# - Face blur pipeline:
#     1) Try MediaPipe Face Mesh (exact face hulls).
#     2) Else multi-scale detection (MediaPipe near+far + Haar).
#     3) For each face: build a soft mask (dilate + feather), choose a blur
#        kernel based on face size, and composite per-face (no harsh halos).
#
# - Background blur:
#     Person mask (MP seg / rembg / saliency) ORed with a "face safety" mask
#     → foreground stays sharp, background blurred.
# =============================================================================

from __future__ import annotations
import os
import io
import time
from typing import List, Tuple, Optional

import cv2
import numpy as np

# --- Optional: MediaPipe (recommended but not mandatory) ---
try:
    import mediapipe as mp
    _HAS_MEDIAPIPE = True
except Exception:
    _HAS_MEDIAPIPE = False

# --- Optional: rembg (nice-to-have for background) ---
try:
    from rembg import remove as rembg_remove
    _HAS_REMBG = True
except Exception:
    _HAS_REMBG = False


# =============================================================================
# Utilities
# =============================================================================

def _odd(n: int) -> int:
    """Ensure kernel size is odd and >= 3."""
    n = int(max(3, n))
    return n if n % 2 == 1 else n + 1


def _feather_mask(mask_255: np.ndarray, radius: int) -> np.ndarray:
    """
    Feather a uint8 mask (0/255) with a Gaussian blur, normalize to [0..1].
    Larger radius -> softer, more natural edges.
    """
    m = mask_255.astype(np.float32) / 255.0
    k = _odd(max(3, int(radius)))
    m = cv2.GaussianBlur(m, (k, k), 0)
    return np.clip(m, 0.0, 1.0)


def _nms_boxes(boxes: List[Tuple[int, int, int, int]], iou_thresh: float = 0.45) -> List[Tuple[int, int, int, int]]:
    """Greedy Non-Maximum Suppression on (x,y,w,h) boxes."""
    if not boxes:
        return []
    b = np.array([[x, y, x+w, y+h] for (x, y, w, h) in boxes], dtype=np.float32)
    x1, y1, x2, y2 = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
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
    return [tuple(map(int, (b[i, 0], b[i, 1], b[i, 2] - b[i, 0], b[i, 3] - b[i, 1]))) for i in keep]


def _skin_mask_ycrcb(bgr: np.ndarray) -> np.ndarray:
    """Quick skin heuristic in YCrCb (coarse but helpful as a filter)."""
    ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    return cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))


def _roi_skin_fraction(skin_mask_255: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """Fraction of 'skin-like' pixels inside ROI."""
    roi = skin_mask_255[max(0, y):y+h, max(0, x):x+w]
    return float(np.mean(roi > 0)) if roi.size else 0.0


def _expand_box(x, y, w, h, scale_w=0.15, scale_h=0.25, img_w=None, img_h=None):
    """Expand a box slightly and clamp to image bounds."""
    nw = int(w * (1 + scale_w))
    nh = int(h * (1 + scale_h))
    nx = x - (nw - w) // 2
    ny = y - (nh - h) // 2
    if img_w is not None and img_h is not None:
        nx = max(0, nx); ny = max(0, ny)
        nw = min(nw, img_w - nx); nh = min(nh, img_h - ny)
    return nx, ny, nw, nh


# =============================================================================
# MediaPipe helpers (optional)
# =============================================================================

def _mesh_face_hulls(bgr: np.ndarray,
                     min_conf: float = 0.6,
                     max_faces: int = 12) -> List[np.ndarray]:
    """
    Face Mesh → convex face hulls for very accurate masks.
    """
    if not _HAS_MEDIAPIPE:
        return []
    H, W = bgr.shape[:2]
    hulls: List[np.ndarray] = []
    mp_fm = mp.solutions.face_mesh
    with mp_fm.FaceMesh(static_image_mode=True,
                        max_num_faces=max_faces,
                        refine_landmarks=True,
                        min_detection_confidence=min_conf,
                        min_tracking_confidence=0.6) as fm:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = fm.process(rgb)
        if not res.multi_face_landmarks:
            return []
        oval_edges = mp_fm.FACEMESH_FACE_OVAL
        for lm in res.multi_face_landmarks:
            idxs = set([i for edge in oval_edges for i in edge])
            pts = []
            for i in idxs:
                p = lm.landmark[i]
                x = int(round(p.x * W)); y = int(round(p.y * H))
                if 0 <= x < W and 0 <= y < H:
                    pts.append([x, y])
            if len(pts) < 8:  # fallback: all landmarks
                pts = []
                for p in lm.landmark:
                    x = int(round(p.x * W)); y = int(round(p.y * H))
                    if 0 <= x < W and 0 <= y < H:
                        pts.append([x, y])
            if len(pts) >= 3:
                hulls.append(cv2.convexHull(np.asarray(pts, dtype=np.int32)))
    return hulls


def _mediapipe_face_boxes_anyrange(bgr: np.ndarray,
                                   conf_near: float = 0.50,
                                   conf_far: float = 0.50) -> List[Tuple[int, int, int, int]]:
    """
    FaceDetection twice: near (model 0) + far (model 1).
    """
    if not _HAS_MEDIAPIPE:
        return []
    H, W = bgr.shape[:2]
    boxes = []
    mp_fd = mp.solutions.face_detection
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    with mp_fd.FaceDetection(model_selection=0, min_detection_confidence=conf_near) as fd0:
        r0 = fd0.process(rgb)
        if r0.detections:
            for det in r0.detections:
                bb = det.location_data.relative_bounding_box
                x = max(0, int(bb.xmin * W)); y = max(0, int(bb.ymin * H))
                w = max(1, int(bb.width * W)); h = max(1, int(bb.height * H))
                boxes.append((x, y, w, h))

    with mp_fd.FaceDetection(model_selection=1, min_detection_confidence=conf_far) as fd1:
        r1 = fd1.process(rgb)
        if r1.detections:
            for det in r1.detections:
                bb = det.location_data.relative_bounding_box
                x = max(0, int(bb.xmin * W)); y = max(0, int(bb.ymin * H))
                w = max(1, int(bb.width * W)); h = max(1, int(bb.height * H))
                boxes.append((x, y, w, h))
    return boxes


def _mediapipe_person_mask(bgr: np.ndarray, min_area_frac: float = 0.003) -> Optional[np.ndarray]:
    """
    SelfieSegmentation → binary mask (255=person), supports multi-person.
    """
    if not _HAS_MEDIAPIPE:
        return None
    mp_selfie = mp.solutions.selfie_segmentation
    with mp_selfie.SelfieSegmentation(model_selection=1) as seg:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = seg.process(rgb)
        if res.segmentation_mask is None:
            return None
        m = (res.segmentation_mask > 0.5).astype(np.uint8) * 255
        # keep meaningful components only
        num, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        if num > 1:
            out = np.zeros_like(m)
            img_area = m.shape[0] * m.shape[1]
            min_area = max(1, int(img_area * min_area_frac))
            for lbl in range(1, num):
                if stats[lbl, cv2.CC_STAT_AREA] >= min_area:
                    out[labels == lbl] = 255
            m = out
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k, iterations=1)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, iterations=2)
        return m


# =============================================================================
# Haar + Multi-scale (no external downloads)
# =============================================================================

def _haarcascade_face_boxes(bgr: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Frontal + profile Haar as a fallback."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    res: List[Tuple[int, int, int, int]] = []

    fpath = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face = cv2.CascadeClassifier(fpath)
    if not face.empty():
        faces = face.detectMultiScale(gray, scaleFactor=1.06, minNeighbors=4,
                                      flags=cv2.CASCADE_SCALE_IMAGE, minSize=(22, 22))
        res += [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]

    try:
        ppath = cv2.data.haarcascades + "haarcascade_profileface.xml"
        prof = cv2.CascadeClassifier(ppath)
        if not prof.empty():
            pf = prof.detectMultiScale(gray, scaleFactor=1.06, minNeighbors=4,
                                       flags=cv2.CASCADE_SCALE_IMAGE, minSize=(22, 22))
            res += [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in pf]
    except Exception:
        pass

    return res


def _multiscale_face_boxes(bgr: np.ndarray,
                           scales: List[float] = [1.0, 1.5, 2.0, 2.6, 3.2],
                           max_dim: int = 2200) -> List[Tuple[int, int, int, int]]:
    """
    Upscale → detect (MP near+far + Haar) → map back → NMS.
    Works very well for small/distant faces.
    """
    H, W = bgr.shape[:2]
    all_boxes: List[Tuple[int, int, int, int]] = []

    for s in scales:
        newW = int(W * s); newH = int(H * s)
        if max(newW, newH) > max_dim:
            r = max_dim / max(newW, newH)
            newW = int(newW * r); newH = int(newH * r)
        if newW < 40 or newH < 40:
            continue

        up = cv2.resize(bgr, (newW, newH), interpolation=cv2.INTER_CUBIC)
        boxes_mp = _mediapipe_face_boxes_anyrange(up, 0.50, 0.50) if _HAS_MEDIAPIPE else []
        boxes_ha = _haarcascade_face_boxes(up)

        sx, sy = W / float(newW), H / float(newH)
        for (x, y, w, h) in boxes_mp + boxes_ha:
            ox = int(round(x * sx)); oy = int(round(y * sy))
            ow = int(round(w * sx)); oh = int(round(h * sy))
            ox = max(0, min(W - 1, ox)); oy = max(0, min(H - 1, oy))
            ow = max(1, min(W - ox, ow)); oh = max(1, min(H - oy, oh))
            all_boxes.append((ox, oy, ow, oh))

    return _nms_boxes(all_boxes, iou_thresh=0.45)


# =============================================================================
# FACE BLUR (strong, per-face compositing; pleasant result)
# =============================================================================

def _build_face_masks(bgr: np.ndarray) -> List[Tuple[np.ndarray, int]]:
    """
    Build a list of (mask_255, blur_kernel) for each detected face.
    - Prefer Face Mesh hulls (accurate), else multi-scale boxes.
    - Each mask is dilated a bit + heavily feathered (no harsh edges).
    - Blur kernel is proportional to face size (tiny faces get mild blur).
    """
    H, W = bgr.shape[:2]
    result: List[Tuple[np.ndarray, int]] = []

    # 1) Try exact hulls (best look)
    hulls = _mesh_face_hulls(bgr, min_conf=0.60, max_faces=16)
    if hulls:
        img_area = H * W
        skin = _skin_mask_ycrcb(bgr)
        for hull in hulls:
            x, y, w, h = cv2.boundingRect(hull)
            area = w * h
            if area < 0.0004 * img_area or area > 0.55 * img_area:
                continue
            # require some "skin-like" pixels inside hull (helps avoid odd shapes)
            tmp = np.zeros((H, W), dtype=np.uint8)
            cv2.fillConvexPoly(tmp, hull, 255)
            if _roi_skin_fraction(skin, x, y, w, h) < 0.07:
                continue

            # base mask from hull
            mask = np.zeros((H, W), dtype=np.uint8)
            cv2.fillConvexPoly(mask, hull, 255)

            # dilate to cover hairline/cheeks a bit more
            grow = max(3, int(0.06 * np.hypot(w, h)))
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_odd(grow), _odd(grow)))
            mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, k, iterations=1)

            # feather radius proportional to face size
            feather = max(12, int(0.18 * min(w, h)))

            # blur kernel: proportional to face size, clamped
            ksize = _odd(int(max(15, min(151, 0.38 * min(w, h)))))

            result.append((mask, ksize))

        if result:
            return result

    # 2) Fallback: multi-scale boxes
    boxes = _multiscale_face_boxes(bgr)
    if not boxes:
        return []

    skin = _skin_mask_ycrcb(bgr)
    img_area = H * W

    for (x, y, w, h) in boxes:
        area = w * h
        if area < 0.00025 * img_area or area > 0.55 * img_area:
            continue
        aspect = w / (h + 1e-6)
        if not (0.58 <= aspect <= 1.95):
            continue
        if _roi_skin_fraction(skin, x, y, w, h) < 0.11:
            continue

        # build an ellipse mask from an expanded box (looks natural)
        x, y, w, h = _expand_box(x, y, w, h, img_w=W, img_h=H)
        cx, cy = x + w // 2, y + h // 2
        axes = (int(w * 0.56), int(h * 0.72))
        base = np.zeros((H, W), dtype=np.uint8)
        cv2.ellipse(base, (cx, cy), axes, 0, 0, 360, 255, -1)

        # dilate a bit + feather proportional to size
        grow = max(3, int(0.05 * np.hypot(w, h)))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_odd(grow), _odd(grow)))
        base = cv2.morphologyEx(base, cv2.MORPH_DILATE, k, iterations=1)

        # blur kernel proportional to face size (clamped)
        ksize = _odd(int(max(13, min(141, 0.35 * min(w, h)))))

        result.append((base, ksize))

    return result


def blur_faces_bgr(bgr: np.ndarray, ksize: int | None = None, **kwargs) -> np.ndarray:
    """
    If ksize is provided, it's treated as a minimum blur strength for each face.
    """
    H, W = bgr.shape[:2]
    faces = _build_face_masks(bgr)
    if not faces:
        return bgr.copy()

    out = bgr.copy()
    for mask_255, ksize_face in faces:
        # feather the mask
        radius = max(10, int(0.16 * min(H, W)))
        m = _feather_mask(mask_255, radius=radius)
        m3 = np.dstack([m] * 3)

        # choose blur kernel per face; if ksize provided, enforce at least that size
        k_use = _odd(ksize_face)
        if ksize is not None:
            k_use = _odd(max(k_use, int(ksize)))

        blurred = cv2.GaussianBlur(bgr, (k_use, k_use), 0)
        out = (m3 * blurred.astype(np.float32) + (1.0 - m3) * out.astype(np.float32)).astype(np.float32)

    return np.clip(out, 0, 255).astype(np.uint8)


# =============================================================================
# BACKGROUND BLUR (with face safety)
# =============================================================================

def _alpha_from_rembg(bgr: np.ndarray) -> Optional[np.ndarray]:
    """Extract alpha via rembg if available; otherwise None."""
    if not _HAS_REMBG:
        return None
    ok, enc = cv2.imencode(".png", bgr)
    if not ok:
        return None
    out_bytes = rembg_remove(enc.tobytes())
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(out_bytes)).convert("RGBA")
        return np.array(img)[:, :, 3]
    except Exception:
        return None


def _simple_saliency_mask(bgr: np.ndarray) -> np.ndarray:
    """Very simple saliency fallback → binary mask."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Laplacian(gray, cv2.CV_32F)
    edges = cv2.convertScaleAbs(edges)
    norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    sal = cv2.addWeighted(edges, 0.6, norm, 0.4, 0)
    _, m = cv2.threshold(sal, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel, iterations=1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel, iterations=2)
    return m


def blur_background_bgr_using_rembg_bytes(
    image_bytes: bytes,
    blur_strength: int = 51,
    face_safety_dilate: int = 13
) -> np.ndarray:
    """
    Background blur with person+face safety:
      1) Person mask (MP seg / rembg / saliency).
      2) Face safety mask from detectors (so faces never get blurred).
      3) Feather → composite sharp FG over blurred BG.
    """
    np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Failed to decode input bytes")

    H, W = bgr.shape[:2]

    # Person mask
    fg_mask_255 = None
    if _HAS_MEDIAPIPE:
        try:
            fg_mask_255 = _mediapipe_person_mask(bgr)
        except Exception:
            fg_mask_255 = None
    if fg_mask_255 is None:
        alpha = _alpha_from_rembg(bgr)
        if alpha is not None:
            _, fg_mask_255 = cv2.threshold(alpha, 0, 255, cv2.THRESH_BINARY)
    if fg_mask_255 is None:
        fg_mask_255 = _simple_saliency_mask(bgr)

    # Face safety mask
    face_mask = np.zeros((H, W), dtype=np.uint8)
    try:
        for (x, y, w, h) in _multiscale_face_boxes(bgr, scales=[1.0, 1.5, 2.0], max_dim=2000):
            x, y, w, h = _expand_box(x, y, w, h, img_w=W, img_h=H)
            cx, cy = x + w // 2, y + h // 2
            axes = (int(w * 0.56), int(h * 0.72))
            cv2.ellipse(face_mask, (cx, cy), axes, 0, 0, 360, 255, -1)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_odd(face_safety_dilate), _odd(face_safety_dilate)))
        face_mask = cv2.dilate(face_mask, k, iterations=1)
    except Exception:
        pass

    keep_255 = cv2.bitwise_or(fg_mask_255, face_mask)
    keep = _feather_mask(keep_255, radius=21)
    keep3 = np.dstack([keep] * 3)

    k = _odd(blur_strength)
    blurred = cv2.GaussianBlur(bgr, (k, k), 0)
    out = (keep3 * bgr.astype(np.float32) + (1.0 - keep3) * blurred.astype(np.float32))
    return np.clip(out, 0, 255).astype(np.uint8)


# =============================================================================
# Saving helpers
# =============================================================================

def _ensure_dir(path: str):
    """Create directory if not exists."""
    os.makedirs(path, exist_ok=True)


def save_bgr_image(bgr: np.ndarray, base_dir: str = "processed", prefix: str = "output") -> str:
    """Save BGR ndarray as JPG with a timestamped name, return the path."""
    _ensure_dir(base_dir)
    ts = int(time.time())
    path = os.path.join(base_dir, f"{prefix}_{ts}.jpg")
    cv2.imwrite(path, bgr)
    return path


def save_raw_image_bytes(image_bytes: bytes, base_dir: str = "processed", prefix: str = "input") -> str:
    """Save raw bytes (JPG/PNG) to disk with a timestamped name, return the path."""
    _ensure_dir(base_dir)
    ts = int(time.time())
    path = os.path.join(base_dir, f"{prefix}_{ts}.jpg")
    with open(path, "wb") as f:
        f.write(image_bytes)
    return path
# =============================================================================