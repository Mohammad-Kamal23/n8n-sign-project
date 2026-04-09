from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import StreamingResponse
import uvicorn
import fitz  # PyMuPDF
import io
import os

app = FastAPI(title="Signage Stamping API")

@app.get("/")
def read_root():
    return {"status": "FastAPI is running and ready to stamp!"}

@app.post("/process-document/")
async def process_document(file: UploadFile = File(...)):
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
        for word in anchors:
            text_instances = page.search_for(word)
            if text_instances:
                match = text_instances[0]
                found_word = word
                target_coords = {
                    "x": round(float(match.x0), 2),
                    "y": round(float(match.y1 + 15), 2), 
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
    # We make these optional so your n8n workflow doesn't break
    x: float = Query(None), 
    y: float = Query(None), 
    page_num: int = Query(None)
):
    # 1. Load the PDF
    file_content = await file.read()
    doc = fitz.open(stream=file_content, filetype="pdf")
    
    # 2. Check for the stamp image
    stamp_path = "stamp.png"
    if not os.path.exists(stamp_path):
        return {"error": "stamp.png not found"}

    # The exact same anchor list
    anchors = [
        "Signature", "Signed by", "Sign here", "Approved by", "Stamp",
        "توقيع", "الموقع", "وقع هنا", "ختم", "يصادق", "المفوض بالتوقيع", "اعتماد"
    ]
    
    stamps_applied = 0
    
    # 3. The "Stamp Everywhere" Loop (No Breaks!)
    for i in range(len(doc)):
        page = doc[i]
        for word in anchors:
            text_instances = page.search_for(word)
            
            # If the word is found multiple times, stamp all of them
            for match in text_instances:
                # Calculate coordinates
                stamp_x = round(float(match.x0), 2)
                stamp_y = round(float(match.y1 + 15), 2)
                
                # Define size and apply
                stamp_rect = fitz.Rect(stamp_x, stamp_y, stamp_x + 150, stamp_y + 75)
                page.insert_image(stamp_rect, filename=stamp_path)
                stamps_applied += 1

    # 4. Fail-Safe: If no words were found at all, stamp the bottom right of the last page
    if stamps_applied == 0:
        last_page = doc[-1]
        stamp_x = round(float(last_page.rect.width - 150), 2)
        stamp_y = round(float(last_page.rect.height - 100), 2)
        stamp_rect = fitz.Rect(stamp_x, stamp_y, stamp_x + 150, stamp_y + 75)
        last_page.insert_image(stamp_rect, filename=stamp_path)
    
    # 5. Save to memory buffer
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    doc.close()
    out_pdf.seek(0)

    return StreamingResponse(
        out_pdf, 
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=signed_everywhere_{file.filename}"}
    )