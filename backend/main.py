from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import StreamingResponse
import fitz  # PyMuPDF
import io
import os

app = FastAPI(title="Professional Signage API")

# --- Professional Placement & Size Constants ---
STAMP_WIDTH = 115   # Controlled size for a professional look
STAMP_HEIGHT = 55
Y_OFFSET = 18       # Increased distance to prevent covering text
COLLISION_LIMIT = 0.05 # Strict overlap prevention (5% max)

@app.get("/")
def read_root():
    return {"status": "FastAPI is running and ready to stamp!"}

@app.post("/process-document/")
async def process_document(file: UploadFile = File(...)):
    """Preserved: Returns coordinates to n8n for human-in-the-loop approval"""
    file_content = await file.read()
    doc = fitz.open(stream=file_content, filetype="pdf")
    
    # Anchor list exactly as defined in your documentation
    anchors = [
        "Signature", "Signed by", "Sign here", "Approved by", "Stamp",
        "توقيع", "الموقع", "وقع هنا", "ختم", "يصادق", "المفوض بالتوقيع", "اعتماد"
    ]
    
    target_coords = None
    found_word = None

    for page_num in range(len(doc)):
        page = doc[page_num]
        # Dual-detection approach for maximum accuracy
        for anchor in anchors:
            instances = page.search_for(anchor)
            if instances:
                match = instances[0]
                found_word = anchor
                # Calculate professional centered placement
                target_coords = {
                    "x": round(float((match.x0 + match.x1)/2 - (STAMP_WIDTH/2)), 2),
                    "y": round(float(match.y1 + Y_OFFSET), 2), 
                    "page": page_num + 1
                }
                break
        if target_coords:
            break

    if not target_coords:
        last_page = doc[-1]
        target_coords = {"x": 400.0, "y": 700.0, "page": len(doc)}

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
    """Applies stamps with spatial prevention to ensure professional alignment."""
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

    # 1. Manual Stamping (Preserved for n8n)
    if x is not None and y is not None and page_num is not None:
        target_page = doc[page_num - 1]
        stamp_rect = fitz.Rect(x, y, x + STAMP_WIDTH, y + STAMP_HEIGHT)
        target_page.insert_image(stamp_rect, filename=stamp_path)
        stamps_applied += 1

    # 2. Automated "Professional" Stamping
    else:
        for page in doc:
            applied_on_page = [] # Reset for every page to prevent cross-page skipping

            for anchor in anchors:
                # search_for is superior for Arabic bullet points and RTL text
                instances = page.search_for(anchor)
                
                for inst in instances:
                    # Professional horizontal centering
                    center_x = (inst.x0 + inst.x1) / 2
                    s_x0 = center_x - (STAMP_WIDTH / 2)
                    s_y0 = inst.y1 + Y_OFFSET
                    
                    new_rect = fitz.Rect(s_x0, s_y0, s_x0 + STAMP_WIDTH, s_y0 + STAMP_HEIGHT)

                    # Logic: Prevent stamping too close to another stamp
                    is_collision = False
                    for existing in applied_on_page:
                        if new_rect.intersects(existing):
                            intersection = new_rect & existing
                            if intersection.get_area() > (new_rect.get_area() * COLLISION_LIMIT):
                                is_collision = True
                                break
                    
                    if not is_collision:
                        page.insert_image(new_rect, filename=stamp_path)
                        applied_on_page.append(new_rect)
                        stamps_applied += 1

    # 3. Fail-Safe: Bottom Right
    if stamps_applied == 0:
        last_page = doc[-1]
        rect = fitz.Rect(400, 700, 400 + STAMP_WIDTH, 700 + STAMP_HEIGHT)
        last_page.insert_image(rect, filename=stamp_path)
    
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    doc.close()
    out_pdf.seek(0)

    return StreamingResponse(
        out_pdf, 
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=signed_{file.filename}"}
    )