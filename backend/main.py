from fastapi import FastAPI, File, UploadFile, Query, Body
from fastapi.responses import StreamingResponse
import fitz  # PyMuPDF
import io
import os
import cv2
import numpy as np
from PIL import Image
import torch
from unittest.mock import patch
from transformers import AutoProcessor, AutoModelForCausalLM
from transformers.dynamic_module_utils import get_imports

app = FastAPI(title="SaaS Document AI (Enterprise Hybrid Vision)")

# ==========================================
# HYPERPARAMETERS & PATHS
# ==========================================
STAMP_WIDTH = 90
STAMP_HEIGHT = 45
DEFAULT_STAMP_PATH = "stamp.png"  
OUTBOX_PATH = "/home/node/simulated_cloud/03_outbox"
TEMPLATES_DIR = "signature_stamp_templates"
FORBIDDEN_ZONE = 50  # Prevents the "Top-Left Corner" hallucination

# ==========================================
# FLASH ATTENTION BYPASS HACK
# ==========================================
def fixed_get_imports(filename: str | os.PathLike) -> list[str]:
    """Bypasses the HuggingFace flash_attn requirement crash."""
    if not str(filename).endswith("modeling_florence2.py"):
        return get_imports(filename)
    imports = get_imports(filename)
    if "flash_attn" in imports:
        imports.remove("flash_attn")
    return imports

# ==========================================
# GLOBAL AI INITIALIZATION
# ==========================================
print("Booting Enterprise Hybrid Vision Engine...")

# 1. Load OpenCV Templates (The "Sniper")
templates = []
if os.path.exists(TEMPLATES_DIR):
    for file in os.listdir(TEMPLATES_DIR):
        if file.lower().endswith((".png", ".jpg", ".jpeg")):
            path = os.path.join(TEMPLATES_DIR, file)
            # Load in grayscale for faster math processing
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                templates.append((file, img))
    print(f"-> OpenCV Sniper loaded {len(templates)} target templates.")
else:
    print(f"-> WARNING: Folder '{TEMPLATES_DIR}' not found. OpenCV Sniper disabled.")

# 2. Load Florence-2 VLM (The "Human Eye Fallback")
try:
    model_id = "microsoft/Florence-2-base-ft"
    print("-> Warming up Florence-2 Vision-Language Model...")
    with patch("transformers.dynamic_module_utils.get_imports", fixed_get_imports):
        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)
        
        # Engage RTX GPU if available
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
    print(f"-> Florence-2 VLM Online ({device.upper()} Engaged).")
except Exception as e:
    print(f"-> Failed to load Florence-2: {e}")
    model = None

# ==========================================
# UTILITIES
# ==========================================
def remove_white_background(image_bytes):
    """Converts absolute white pixels in the stamp to transparent."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    data = img.getdata()
    new_data = [(255, 255, 255, 0) if item[0] > 220 and item[1] > 220 and item[2] > 220 else item for item in data]
    img.putdata(new_data)
    out_io = io.BytesIO()
    img.save(out_io, format="PNG")
    return out_io.getvalue()

def non_max_suppression(boxes, overlapThresh=0.3):
    """Prevents double-stamping if two templates match the exact same area."""
    if len(boxes) == 0: return []
    boxes = np.array(boxes).astype("float")
    pick = []
    x1, y1, x2, y2 = boxes[:,0], boxes[:,1], boxes[:,2], boxes[:,3]
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
        idxs = np.delete(idxs, np.concatenate(([last], np.where(overlap > overlapThresh)[0])))
    return boxes[pick].astype("int").tolist()

# ==========================================
# VISION LAYERS
# ==========================================
def find_via_opencv(page):
    """Scans the page for exact pixel matches against your target templates."""
    if not templates: return []
    
    zoom = 2
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    gray_page = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
    raw_boxes = []
    threshold = 0.8  # 80% visual match required
    
    for name, template in templates:
        if template.shape[0] > gray_page.shape[0] or template.shape[1] > gray_page.shape[1]:
            continue 
            
        res = cv2.matchTemplate(gray_page, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        
        for pt in zip(*loc[::-1]):
            x0, y0 = pt[0] / zoom, pt[1] / zoom 
            x1 = x0 + (template.shape[1] / zoom)
            y1 = y0 + (template.shape[0] / zoom)
            raw_boxes.append([x0, y0, x1, y1])
            
    return raw_boxes

def find_via_florence(page):
    """Zero-shot object detection using Microsoft Florence-2."""
    if model is None: return []
    
    zoom = 2
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    pil_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    task_prompt = "<CAPTION_TO_PHRASE_GROUNDING>"
    text_input = "signature line or blank space for stamp"
    prompt = task_prompt + " " + text_input
    
    inputs = processor(text=prompt, images=pil_img, return_tensors="pt").to(model.device)
    generated_ids = model.generate(
        input_ids=inputs["input_ids"],
        pixel_values=inputs["pixel_values"],
        max_new_tokens=1024,
        num_beams=3
    )
    generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
    parsed_answer = processor.post_process_generation(generated_text, task=task_prompt, image_size=(pix.width, pix.height))
    
    boxes = []
    if task_prompt in parsed_answer and "bboxes" in parsed_answer[task_prompt]:
        for bbox in parsed_answer[task_prompt]["bboxes"]:
            boxes.append([bbox[0]/zoom, bbox[1]/zoom, bbox[2]/zoom, bbox[3]/zoom])
            
    return boxes

# ==========================================
# AUTOMATED N8N ROUTING ENDPOINT
# ==========================================
@app.post("/process-path")
async def process_path(payload: dict = Body(...)):
    file_path = payload.get("file_path")
    if not file_path or not os.path.exists(file_path):
        return {"status": "error", "message": f"File not found: {file_path}"}

    if not os.path.exists(DEFAULT_STAMP_PATH):
        return {"status": "error", "message": "Stamp (stamp.png) is missing."}

    with open(DEFAULT_STAMP_PATH, "rb") as f:
        stamp_content = remove_white_background(f.read())

    doc = fitz.open(file_path)
    stamps_applied = 0
    final_x, final_y, final_page = 0, 0, 1

    # Scan ALL pages sequentially
    for i in range(len(doc)):
        page = doc[i]
        page_rect = page.rect
        
        # --- LAYER FUSION ---
        # 1. Gather raw boxes from BOTH models simultaneously
        opencv_boxes = find_via_opencv(page)
        florence_boxes = find_via_florence(page)
        
        # 2. Merge and apply NMS to remove duplicates across both engines
        all_potential_boxes = opencv_boxes + florence_boxes
        final_boxes = non_max_suppression(all_potential_boxes)

        # 3. Apply Stamps dynamically
        for box in final_boxes:
            # DYNAMIC CENTERING: Calculate the true center of the matched area
            center_x = (box[0] + box[2]) / 2
            center_y = (box[1] + box[3]) / 2
            
            # THE MARGIN GUARD: Ignore phantom matches in the top-left corner
            if center_x < FORBIDDEN_ZONE and center_y < FORBIDDEN_ZONE:
                print(f"Skipping phantom match in corner at ({center_x}, {center_y})")
                continue

            # Place stamp perfectly centered over the detected zone
            s_x0 = center_x - (STAMP_WIDTH / 2)
            s_y0 = center_y - (STAMP_HEIGHT / 2)
            
            # Boundary Safety: Ensure the stamp never bleeds off the page
            s_x0 = max(10, min(s_x0, page_rect.width - STAMP_WIDTH - 10))
            s_y0 = max(10, min(s_y0, page_rect.height - STAMP_HEIGHT - 10))
            
            new_rect = fitz.Rect(s_x0, s_y0, s_x0 + STAMP_WIDTH, s_y0 + STAMP_HEIGHT)
            page.insert_image(new_rect, stream=stamp_content)
            
            stamps_applied += 1
            final_x, final_y, final_page = s_x0, s_y0, i + 1

    # ==========================================
    # LAYER 3: AUDIT PAGE FALLBACK (Kept Intact)
    # ==========================================
    if stamps_applied == 0:
        print("Fallback Triggered: AI found no anchors. Appending Audit Page.")
        new_page = doc.new_page(-1)
        
        title = "Automated Document AI - Audit & Approval Page"
        subtitle = "No specific visual anchor zones were detected in the original document."
        action = "This stamp serves as the official administrative approval for the preceding pages."
        
        new_page.insert_text((50, 70), title, fontsize=16, color=(0.2, 0.2, 0.2))
        new_page.insert_text((50, 100), subtitle, fontsize=11, color=(0.5, 0.5, 0.5))
        new_page.insert_text((50, 120), action, fontsize=11, color=(0.5, 0.5, 0.5))
        
        s_x0 = (new_page.rect.width / 2) - (STAMP_WIDTH / 2)
        s_y0 = 200 
        fallback_rect = fitz.Rect(s_x0, s_y0, s_x0 + STAMP_WIDTH, s_y0 + STAMP_HEIGHT)
        
        new_page.insert_image(fallback_rect, stream=stamp_content)
        stamps_applied += 1
        final_x, final_y, final_page = s_x0, s_y0, len(doc)

    # Save output
    os.makedirs(OUTBOX_PATH, exist_ok=True)
    filename = os.path.basename(file_path)
    out_path = os.path.join(OUTBOX_PATH, f"stamped_{filename}")
    doc.save(out_path)
    doc.close()

    return {
        "status": "success",
        "filename": filename,
        "output_path": out_path,
        "stamps_applied": stamps_applied,
        "last_stamp_x": final_x,
        "last_stamp_y": final_y,
        "page_number": final_page
    }

# ==========================================
# MANUAL UI ENDPOINT (Kept Intact)
# ==========================================
@app.post("/stamp-document/")
async def stamp_document(
    file: UploadFile = File(...), 
    stamp: UploadFile = File(...), 
    x: float = Query(None), 
    y: float = Query(None), 
    page_num: int = Query(None)
):
    file_content = await file.read()
    raw_stamp_content = await stamp.read() 
    stamp_content = remove_white_background(raw_stamp_content)
    doc = fitz.open(stream=file_content, filetype="pdf")
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    doc.close()
    out_pdf.seek(0)
    return StreamingResponse(out_pdf, media_type="application/pdf")