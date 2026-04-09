from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import StreamingResponse
import fitz  # PyMuPDF
import io
import os

app = FastAPI(title="Professional Signage API")

STAMP_WIDTH = 120
STAMP_HEIGHT = 60
Y_OFFSET = 15
OVERLAP_LIMIT = 0.05 

@app.get("/")
def read_root():
    return {"status": "FastAPI is running and ready to stamp!"}

@app.post("/process-document/")
async def process_document(file: UploadFile = File(...)):
    file_content = await file.read()
    doc = fitz.open(stream=file_content, filetype="pdf")
    
    # We use prefixes to handle the "Sianod" and "Stamn" typos in your PDF
    anchors = ["Signa", "Signe", "Sian", "Stamp", "Stam", "توقيع", "الموقع", "المفوض", "اعتماد"]
    
    target_coords = None
    found_word = None

    for page_num in range(len(doc)):
        page = doc[page_num]
        words = page.get_text("words") 
        for w in words:
            clean_text = w[4].strip().strip('•').strip('.').strip(':')
            if any(clean_text.startswith(a) or a in clean_text for a in anchors):
                found_word = clean_text
                target_coords = {
                    "x": round(float((w[0] + w[2]) / 2 - (STAMP_WIDTH / 2)), 2),
                    "y": round(float(w[3] + Y_OFFSET), 2), 
                    "page": page_num + 1
                }
                break
        if target_coords:
            break

    if not target_coords:
        target_coords = {"x": 400.0, "y": 700.0, "page": len(doc)}

    return {
        "filename": file.filename,
        "found_anchor": bool(found_word),
        "detected_word": found_word,
        "coordinates": target_coords,
        "total_pages": len(doc)
    }

@app.post("/stamp-document/")
async def stamp_document(file: UploadFile = File(...), x: float = Query(None), y: float = Query(None), page_num: int = Query(None)):
    file_content = await file.read()
    doc = fitz.open(stream=file_content, filetype="pdf")
    
    stamp_path = "stamp.png"
    if not os.path.exists(stamp_path):
        return {"error": "stamp.png not found"}

    # Flexible anchors to catch corrupted text or Arabic ligatures
    anchors = ["Signa", "Signe", "Sian", "Stamp", "Stam", "توقيع", "الموقع", "المفوض", "اعتماد"]
    
    stamps_applied = 0
    applied_areas = []

    if x is not None and y is not None and page_num is not None:
        target_page = doc[page_num - 1]
        stamp_rect = fitz.Rect(x, y, x + STAMP_WIDTH, y + STAMP_HEIGHT)
        target_page.insert_image(stamp_rect, filename=stamp_path)
        stamps_applied += 1
    else:
        for page in doc:
            words = page.get_text("words")
            page_rects = []
            for w in words:
                clean_text = w[4].strip().strip('•').strip('.').strip(':')
                
                # Flexible match: handles "Sianod" (Signed by) and ". توقيع"
                if any(clean_text.startswith(a) or a in clean_text for a in anchors):
                    center_x = (w[0] + w[2]) / 2
                    s_x0 = center_x - (STAMP_WIDTH / 2)
                    s_y0 = w[3] + Y_OFFSET
                    new_rect = fitz.Rect(s_x0, s_y0, s_x0 + STAMP_WIDTH, s_y0 + STAMP_HEIGHT)

                    # Strict collision check
                    if not any(new_rect.intersects(prev) for prev in page_rects):
                        page.insert_image(new_rect, filename=stamp_path)
                        page_rects.append(new_rect)
                        stamps_applied += 1

    if stamps_applied == 0:
        last_page = doc[-1]
        rect = fitz.Rect(400, 700, 400 + STAMP_WIDTH, 700 + STAMP_HEIGHT)
        last_page.insert_image(rect, filename=stamp_path)
    
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    doc.close()
    out_pdf.seek(0)
    return StreamingResponse(out_pdf, media_type="application/pdf")