"""Document stamping service: finds where an approval stamp belongs on a PDF and places it there.

Two detectors look for signature / stamp zones on every page and their boxes are fused:
  1. OpenCV template matching against example zones in signature_stamp_templates/ (fast, exact, bilingual layouts);
  2. Florence-2 phrase grounding, "signature line or blank space for stamp" (zero-shot fallback for unseen layouts).
Overlapping boxes from both are merged (non-maximum suppression) so a zone is never stamped twice. If no zone is
found, an audit page is appended and stamped, so every processed document carries an approval.

Endpoints
  POST /process-path      {"file_path": ...}  used by the n8n workflow: stamps a PDF from the shared folder and
                          writes it to OUTBOX_PATH
  POST /stamp-document/   multipart (file, stamp) used by the UI: manual placement with ?x=&y=&page_num=
                          (PDF points, 1-based page), automatic placement without them; returns the stamped PDF
  GET  /  and  /health    status: templates loaded, Florence-2 on or off, stamp in use

Every setting is an environment variable (see ../.env.example). Florence-2 is used only with USE_FLORENCE=1 and the
packages in requirements-florence.txt; otherwise the service runs on template matching alone.
"""
import io
import os

import cv2
import numpy as np
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image

from security_service import run_full_security_check, strip_metadata

try:
    import pymupdf as fitz          # PyMuPDF >= 1.24.3
except ImportError:                 # older PyMuPDF
    import fitz

app = FastAPI(title="Document stamping service (OpenCV + Florence-2)")

# ==========================================
# SETTINGS (environment variables)
# ==========================================
STAMP_WIDTH = float(os.getenv("STAMP_WIDTH", "90"))            # PDF points
STAMP_HEIGHT = float(os.getenv("STAMP_HEIGHT", "45"))
STAMP_PATH = os.getenv("STAMP_PATH", "stamp.png")              # your stamp image (not in the repository)
EXAMPLE_STAMP_PATH = "stamp.example.png"                       # synthetic stamp used when STAMP_PATH is missing
INPUT_ROOT = os.getenv("INPUT_ROOT", "/home/node/simulated_cloud")   # /process-path only reads files below this folder
OUTBOX_PATH = os.getenv("OUTBOX_PATH", "/home/node/simulated_cloud/03_outbox")
TEMPLATES_DIR = os.getenv("TEMPLATES_DIR", "signature_stamp_templates")
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.8"))   # template match score needed (0-1)
FORBIDDEN_ZONE = float(os.getenv("FORBIDDEN_ZONE", "50"))     # ignore matches centred in the top-left corner (points)
USE_FLORENCE = os.getenv("USE_FLORENCE", "0") == "1"
FLORENCE_MODEL = os.getenv("FLORENCE_MODEL", "microsoft/Florence-2-base-ft")
FLORENCE_PROMPT = os.getenv("FLORENCE_PROMPT", "signature line or blank space for stamp")
RENDER_ZOOM = 2                                                # pages are rendered at 2x for both detectors

# ==========================================
# TEMPLATES (OpenCV)
# ==========================================
templates = []
if os.path.isdir(TEMPLATES_DIR):
    for name in sorted(os.listdir(TEMPLATES_DIR)):
        if name.lower().endswith((".png", ".jpg", ".jpeg")):
            img = cv2.imread(os.path.join(TEMPLATES_DIR, name), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                templates.append((name, img))
print(f"-> OpenCV template matching: {len(templates)} templates from '{TEMPLATES_DIR}'")

# ==========================================
# FLORENCE-2 (optional zero-shot fallback)
# ==========================================
processor = model = None
if USE_FLORENCE:
    try:
        from unittest.mock import patch

        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
        from transformers.dynamic_module_utils import get_imports

        def _imports_without_flash_attn(filename):
            """Florence-2's remote code lists flash_attn as an import; it is optional, so drop it."""
            imports = get_imports(filename)
            if str(filename).endswith("modeling_florence2.py") and "flash_attn" in imports:
                imports.remove("flash_attn")
            return imports

        with patch("transformers.dynamic_module_utils.get_imports", _imports_without_flash_attn):
            processor = AutoProcessor.from_pretrained(FLORENCE_MODEL, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(FLORENCE_MODEL, trust_remote_code=True)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        print(f"-> Florence-2 ready on {device.upper()}")
    except Exception as e:                                      # the service still works with templates only
        print(f"-> Florence-2 not available ({e}); using template matching only")
        processor = model = None


# ==========================================
# UTILITIES
# ==========================================
def load_stamp_bytes():
    path = STAMP_PATH if os.path.exists(STAMP_PATH) else EXAMPLE_STAMP_PATH
    if not os.path.exists(path):
        raise HTTPException(status_code=500, detail=f"No stamp image: put yours at {STAMP_PATH} or set STAMP_PATH")
    with open(path, "rb") as f:
        return remove_white_background(f.read())


def remove_white_background(image_bytes):
    """Near-white pixels of the stamp image become transparent, so the page shows through."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    a = np.array(img)
    white = (a[..., 0] > 220) & (a[..., 1] > 220) & (a[..., 2] > 220)
    a[white] = (255, 255, 255, 0)
    out = io.BytesIO()
    Image.fromarray(a).save(out, format="PNG")
    return out.getvalue()


def non_max_suppression(boxes, overlap_thresh=0.3):
    """Merges boxes that cover the same zone (from either detector), so a zone is stamped once."""
    if len(boxes) == 0:
        return []
    boxes = np.array(boxes).astype("float")
    pick = []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    idxs = np.argsort(y2)
    while len(idxs) > 0:
        last = len(idxs) - 1
        i = idxs[last]
        pick.append(i)
        xx1 = np.maximum(x1[i], x1[idxs[:last]])
        yy1 = np.maximum(y1[i], y1[idxs[:last]])
        xx2 = np.minimum(x2[i], x2[idxs[:last]])
        yy2 = np.minimum(y2[i], y2[idxs[:last]])
        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)
        overlap = (w * h) / area[idxs[:last]]
        idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > overlap_thresh)[0])))
    return boxes[pick].astype("int").tolist()


def render_page(page):
    pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM))
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)


# ==========================================
# DETECTORS
# ==========================================
def find_via_opencv(page):
    """Zones that match one of the example templates (score >= MATCH_THRESHOLD), in PDF points."""
    if not templates:
        return []
    img = render_page(page)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY if img.shape[2] == 3 else cv2.COLOR_RGBA2GRAY)
    boxes = []
    for _, template in templates:
        if template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
            continue
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        for x, y in zip(*np.where(res >= MATCH_THRESHOLD)[::-1]):
            x0, y0 = x / RENDER_ZOOM, y / RENDER_ZOOM
            boxes.append([x0, y0, x0 + template.shape[1] / RENDER_ZOOM, y0 + template.shape[0] / RENDER_ZOOM])
    return boxes


def find_via_florence(page):
    """Zero-shot phrase grounding with Florence-2, in PDF points."""
    if model is None:
        return []
    img = render_page(page)
    pil_img = Image.fromarray(img[..., :3])
    task = "<CAPTION_TO_PHRASE_GROUNDING>"
    inputs = processor(text=task + " " + FLORENCE_PROMPT, images=pil_img, return_tensors="pt").to(model.device)
    ids = model.generate(input_ids=inputs["input_ids"], pixel_values=inputs["pixel_values"], max_new_tokens=1024, num_beams=3)
    text = processor.batch_decode(ids, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(text, task=task, image_size=pil_img.size)
    return [[b[0] / RENDER_ZOOM, b[1] / RENDER_ZOOM, b[2] / RENDER_ZOOM, b[3] / RENDER_ZOOM]
            for b in parsed.get(task, {}).get("bboxes", [])]


# ==========================================
# STAMPING
# ==========================================
def place(page, center_x, center_y, stamp_content):
    """Puts the stamp centred on (center_x, center_y), kept 10 pt inside the page."""
    r = page.rect
    x0 = max(10, min(center_x - STAMP_WIDTH / 2, r.width - STAMP_WIDTH - 10))
    y0 = max(10, min(center_y - STAMP_HEIGHT / 2, r.height - STAMP_HEIGHT - 10))
    page.insert_image(fitz.Rect(x0, y0, x0 + STAMP_WIDTH, y0 + STAMP_HEIGHT), stream=stamp_content)
    return x0, y0


def stamp_pdf(doc, stamp_content, x=None, y=None, page_num=None):
    """Manual placement when x, y, page_num are given, otherwise automatic. Returns a summary dict."""
    applied, last = 0, (0.0, 0.0, 1)
    if x is not None and y is not None and page_num is not None:
        if not 1 <= page_num <= len(doc):
            raise HTTPException(status_code=400, detail=f"page_num must be between 1 and {len(doc)}")
        sx, sy = place(doc[page_num - 1], x, y, stamp_content)
        return {"mode": "manual", "stamps_applied": 1, "last_stamp_x": sx, "last_stamp_y": sy, "page_number": page_num}

    for i, page in enumerate(doc):
        for box in non_max_suppression(find_via_opencv(page) + find_via_florence(page)):
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            if cx < FORBIDDEN_ZONE and cy < FORBIDDEN_ZONE:       # phantom matches in the top-left corner
                continue
            sx, sy = place(page, cx, cy, stamp_content)
            applied += 1
            last = (sx, sy, i + 1)

    if applied == 0:                                             # no zone found: stamp an appended audit page
        page = doc.new_page(-1)
        page.insert_text((50, 70), "Automated Document AI - Audit & Approval Page", fontsize=16, color=(0.2, 0.2, 0.2))
        page.insert_text((50, 100), "No signature or stamp zone was detected in the original document.", fontsize=11, color=(0.5, 0.5, 0.5))
        page.insert_text((50, 120), "This stamp is the administrative approval for the preceding pages.", fontsize=11, color=(0.5, 0.5, 0.5))
        sx, sy = place(page, page.rect.width / 2, 200 + STAMP_HEIGHT / 2, stamp_content)
        applied, last = 1, (sx, sy, len(doc))
    return {"mode": "auto", "stamps_applied": applied, "last_stamp_x": last[0], "last_stamp_y": last[1], "page_number": last[2]}


# ==========================================
# ENDPOINTS
# ==========================================
@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok", "templates": len(templates), "florence": model is not None,
            "stamp": STAMP_PATH if os.path.exists(STAMP_PATH) else (EXAMPLE_STAMP_PATH + " (example)")}


@app.post("/process-path")
async def process_path(payload: dict = Body(...)):
    """Called by the n8n workflow with a file in the shared folder; writes stamped_<name> to OUTBOX_PATH."""
    file_path = payload.get("file_path") or ""
    real = os.path.realpath(file_path)
    if not real.startswith(os.path.realpath(INPUT_ROOT) + os.sep):
        return {"status": "error", "message": f"Only files under {INPUT_ROOT} can be processed"}
    if not os.path.isfile(real):
        return {"status": "error", "message": f"File not found: {file_path}"}
    ok, file_hash, message = run_full_security_check(real)
    if not ok:
        return {"status": "error", "message": message, "sha256": file_hash}

    doc = fitz.open(real)
    result = stamp_pdf(doc, load_stamp_bytes())
    strip_metadata(doc)
    os.makedirs(OUTBOX_PATH, exist_ok=True)
    filename = os.path.basename(real)
    out_path = os.path.join(OUTBOX_PATH, f"stamped_{filename}")
    doc.save(out_path)
    doc.close()
    return {"status": "success", "filename": filename, "output_path": out_path, "sha256": file_hash, **result}


@app.post("/stamp-document/")
async def stamp_document(
    file: UploadFile = File(...),
    stamp: UploadFile = File(...),
    x: float = Query(None),
    y: float = Query(None),
    page_num: int = Query(None),
):
    """Used by the UI: the uploaded stamp is placed at (x, y) on page_num, or automatically when they are omitted."""
    doc = fitz.open(stream=await file.read(), filetype="pdf")
    result = stamp_pdf(doc, remove_white_background(await stamp.read()), x, y, page_num)
    strip_metadata(doc)
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    out.seek(0)
    headers = {"X-Stamps-Applied": str(result["stamps_applied"]), "X-Stamp-Mode": result["mode"]}
    return StreamingResponse(out, media_type="application/pdf", headers=headers)
