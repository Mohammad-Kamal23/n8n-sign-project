from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import StreamingResponse
import uvicorn
import fitz  # PyMuPDF
import io
import os

app = FastAPI(title="Signage Stamping API")

# --- Professional Placement Constants ---
STAMP_WIDTH = 130
STAMP_HEIGHT = 65
Y_OFFSET = 12
OVERLAP_LIMIT = 0.1 

@app.get("/")
def read_root():
    return {"status": "FastAPI is running and ready to stamp!"}

@app.post("/process-document/")
async def process_document(file: UploadFile = File(...)):
    """Preserved: Returns coordinates to n8n for human-in-the-loop approval"""
    file_content = await file.read()
    doc = fitz.open(stream=file_content, filetype="pdf")
    
    anchors = [
        "Signature", "Signed by", "Sign here", "Approved by", "Stamp",
        "توقيع", "الموقع", "وقع هنا", "ختم", "يصادق", "المفوض بالتوقيع", "اعتماد"
    ]
    
    target_coords = None
    found_word = None

    for page_num in range(len(doc)):
        page = doc[page_num]
        # Improved word-level extraction for better Arabic/English detection
        words = page.get_text("words") 
        for w in words:
            clean_text = w[4].strip().strip(':').strip('.')
            if any(anchor.lower() in clean_text.lower() for anchor in anchors):
                found_word = clean_text
                # Return professional centered coordinates
                target_coords = {
                    "x": round(float((w[0] + w[2]) / 2 - (STAMP_WIDTH / 2)), 2),
                    "y": round(float(w[3] + Y_OFFSET), 2), 
                    "page": page_num + 1
                }
                break
        if target_coords:
            break

    if not target_coords:
        last_page = doc[-1]
        target_coords = {
            "x": round(float(last_page.rect.width - 150), 2),
            "y": round(float(last_page.rect.height - 100), 2),
            "page": len(doc)
        }

    return {
        "filename": file.filename,
        "found_anchor": bool(found_word),
        "detected_word": found_word,
        "coordinates": target_coords,
        "total_pages": len(doc)
    }

@app.post("/stamp-document/")
async def stamp_document(
    file: UploadFile = File(...), 
    x: float = Query(None), 
    y: float = Query(None), 
    page_num: int = Query(None)
):
    """Preserved: Applies stamps. If x/y aren't provided, it uses 'Stamp Everywhere' logic."""
    file_content = await file.read()
    doc = fitz.open(stream=file_content, filetype="pdf")
    
    stamp_path = "stamp.png"
    if not os.path.exists(stamp_path):
        return {"error": "stamp.png not found"}

    anchors = [
        "Signature", "Signed by", "Sign here", "Approved by", "Stamp",
        "توقيع", "الموقع", "وقع هنا", "ختم", "يصادق", "المفوض بالتوقيع", "اعتماد"
    ]
    
    stamps_applied = 0
    applied_areas = []

    # 1. Manual Stamping (If n8n/User provides exact coordinates)
    if x is not None and y is not None and page_num is not None:
        target_page = doc[page_num - 1]
        stamp_rect = fitz.Rect(x, y, x + STAMP_WIDTH, y + STAMP_HEIGHT)
        target_page.insert_image(stamp_rect, filename=stamp_path)
        stamps_applied += 1

    # 2. Automated Stamping (The "Stamp Everywhere" Fix)
    else:
        for page in doc:
            words = page.get_text("words")
            for w in words:
                clean_text = w[4].strip().strip(':').strip('.')
                if any(anchor.lower() in clean_text.lower() for anchor in anchors):
                    # Calculate professional center-aligned placement
                    word_x_center = (w[0] + w[2]) / 2
                    word_y_bottom = w[3]
                    
                    s_x0 = word_x_center - (STAMP_WIDTH / 2)
                    s_y0 = word_y_bottom + Y_OFFSET
                    new_rect = fitz.Rect(s_x0, s_y0, s_x0 + STAMP_WIDTH, s_y0 + STAMP_HEIGHT)

                    # Collision Prevention: Don't stamp the same spot twice (Fixes English mess)
                    is_overlapping = False
                    for existing in applied_areas:
                        if new_rect.intersects(existing):
                            if (new_rect & existing).get_area() > (new_rect.get_area() * OVERLAP_LIMIT):
                                is_overlapping = True
                                break
                    
                    if not is_overlapping:
                        page.insert_image(new_rect, filename=stamp_path)
                        applied_areas.append(new_rect)
                        stamps_applied += 1

    # 3. Fail-Safe: Bottom Right of Last Page
    if stamps_applied == 0:
        last_page = doc[-1]
        s_x0 = round(float(last_page.rect.width - STAMP_WIDTH - 20), 2)
        s_y0 = round(float(last_page.rect.height - STAMP_HEIGHT - 20), 2)
        stamp_rect = fitz.Rect(s_x0, s_y0, s_x0 + STAMP_WIDTH, s_y0 + STAMP_HEIGHT)
        last_page.insert_image(stamp_rect, filename=stamp_path)
    
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    doc.close()
    out_pdf.seek(0)

    return StreamingResponse(
        out_pdf, 
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=stamped_{file.filename}"}
    )