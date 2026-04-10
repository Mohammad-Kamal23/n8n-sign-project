from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import StreamingResponse
import fitz  # PyMuPDF
import io

app = FastAPI(title="Professional Signage API")

STAMP_WIDTH = 120
STAMP_HEIGHT = 60
Y_OFFSET = 20
MIN_DISTANCE = 40 # Prevents stamps from overlapping on the same line

@app.get("/")
def read_root():
    return {"status": "FastAPI is running and ready to stamp!"}

@app.post("/process-document/")
async def process_document(file: UploadFile = File(...)):
    """Preserved for n8n workflow to fetch coordinates"""
    file_content = await file.read()
    doc = fitz.open(stream=file_content, filetype="pdf")
    
    anchors = ["Signa", "Signe", "Sian", "Stamp", "Stam", "توقيع", "الموقع", "المفوض", "اعتماد"]
    target_coords = None
    found_word = None

    for page_num in range(len(doc)):
        page = doc[page_num]
        for anchor in anchors:
            hits = page.search_for(anchor)
            if hits:
                hit = hits[0]
                found_word = anchor
                target_coords = {
                    "x": round(float((hit.x0 + hit.x1) / 2 - (STAMP_WIDTH / 2)), 2),
                    "y": round(float(hit.y1 + Y_OFFSET), 2),
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

# Helper function for robust Arabic/English search
def find_stamp_locations(page, anchors):
    locations = []
    # search_for easily catches RTL Arabic and bullet points
    for anchor in anchors:
        hits = page.search_for(anchor)
        for hit in hits:
            locations.append({
                "anchor": anchor,
                "center_x": (hit.x0 + hit.x1) / 2,
                "bottom_y": hit.y1
            })
    # Sort top-to-bottom so deduplication works correctly
    return sorted(locations, key=lambda loc: loc["bottom_y"])

@app.post("/stamp-document/")
async def stamp_document(
    file: UploadFile = File(...), 
    stamp: UploadFile = File(...), # SaaS Feature: Accept uploaded stamp
    x: float = Query(None), 
    y: float = Query(None), 
    page_num: int = Query(None)
):
    file_content = await file.read()
    stamp_content = await stamp.read() # Read the custom stamp bytes
    
    doc = fitz.open(stream=file_content, filetype="pdf")
    
    # Flexible anchors to catch corrupted text or Arabic ligatures
    anchors = ["Signa", "Signe", "Sian", "Stamp", "Stam", "توقيع", "الموقع", "وقع هنا", "ختم", "يصادق", "المفوض", "اعتماد"]
    
    stamps_applied = 0

    # 1. Manual Override (n8n integration)
    if x is not None and y is not None and page_num is not None:
        target_page = doc[page_num - 1]
        target_page.insert_image(fitz.Rect(x, y, x + STAMP_WIDTH, y + STAMP_HEIGHT), stream=stamp_content)
        stamps_applied += 1
        
    # 2. Automated Smart Stamping
    else:
        for page in doc:
            page_stamps = [] 
            locations = find_stamp_locations(page, anchors)
            
            for loc in locations:
                s_x0 = loc["center_x"] - (STAMP_WIDTH / 2)
                s_y0 = loc["bottom_y"] + Y_OFFSET
                new_rect = fitz.Rect(s_x0, s_y0, s_x0 + STAMP_WIDTH, s_y0 + STAMP_HEIGHT)

                # Spatial Deduplication: Check if there is a stamp too close to this one
                is_duplicate = False
                for existing in page_stamps:
                    if abs(new_rect.y0 - existing.y0) < MIN_DISTANCE:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    # Notice we use `stream=stamp_content` instead of `filename`
                    page.insert_image(new_rect, stream=stamp_content)
                    page_stamps.append(new_rect)
                    stamps_applied += 1

    # 3. Fail-Safe: Bottom Right
    if stamps_applied == 0:
        last_page = doc[-1]
        last_page.insert_image(fitz.Rect(400, 700, 400 + STAMP_WIDTH, 700 + STAMP_HEIGHT), stream=stamp_content)
    
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    doc.close()
    out_pdf.seek(0)
    return StreamingResponse(out_pdf, media_type="application/pdf")