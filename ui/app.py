import streamlit as st
import requests
from streamlit_pdf_viewer import pdf_viewer
from pdf2image import convert_from_bytes
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import ImageDraw

# API Endpoint
API_URL = "http://fastapi:8000/stamp-document/"

st.set_page_config(page_title="Automated Signage", page_icon="✍️", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    .header-box {
        padding: 1.5rem; background-color: #1E2127; border-radius: 10px;
        border-left: 5px solid #007BFF; margin-bottom: 2rem; box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .stButton>button {
        background-color: #007BFF; color: white; border-radius: 5px;
        border: none; padding: 10px 24px; font-weight: bold; transition: 0.3s; width: 100%;
    }
    .stButton>button:hover { background-color: #0056b3; border-color: #0056b3; }
    .btn-manual>button { background-color: #FF8C00 !important; }
    .btn-manual>button:hover { background-color: #CC7000 !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="header-box"><h1>✍️ Interactive Document Signage (SaaS)</h1><p>Use AI to auto-detect signature fields, or click anywhere on the document to apply a manual override.</p></div>', unsafe_allow_html=True)

st.subheader("🛠️ Configuration")
col_up1, col_up2 = st.columns(2)

with col_up1:
    uploaded_pdf = st.file_uploader("1. Upload Document (PDF)", type=["pdf"])
with col_up2:
    uploaded_stamp = st.file_uploader("2. Upload Stamp (PNG/JPG)", type=["png", "jpg", "jpeg"])

if uploaded_pdf and uploaded_stamp:
    # Convert PDF to images. DPI=72 ensures 1 pixel = 1 PDF point for perfect math mapping.
    with st.spinner("Rendering Interactive Canvas..."):
        images = convert_from_bytes(uploaded_pdf.getvalue(), dpi=72)
    
    col1, col2 = st.columns([1.5, 1])

    with col1:
        st.subheader("🎯 Interactive Canvas")
        page_num = st.selectbox("Select Page to View", range(1, len(images) + 1))
        
        st.write("👉 **Click anywhere on the document to set custom stamp coordinates.**")
        
        # Display the image and track clicks
        base_image = images[page_num - 1].copy()
        
        # This component returns a dictionary with 'x' and 'y' when clicked
        coords = streamlit_image_coordinates(base_image, key=f"canvas_{page_num}")

    with col2:
        st.subheader("⚙️ Processing Engine")
        
        # Ensure we always send the files in the request
        files = {
            "file": (uploaded_pdf.name, uploaded_pdf.getvalue(), "application/pdf"),
            "stamp": (uploaded_stamp.name, uploaded_stamp.getvalue(), "image/png")
        }

        # --- OPTION 1: MANUAL OVERRIDE ---
        if coords:
            x, y = coords["x"], coords["y"]
            st.info(f"📍 **Target Locked:** Page {page_num} | X: {x} | Y: {y}")
            st.markdown('<div class="btn-manual">', unsafe_allow_html=True)
            
            if st.button("Apply Stamp at Clicked Location"):
                with st.spinner("Applying manual override..."):
                    # Send specific coordinates to the backend
                    params = {"x": x, "y": y, "page_num": page_num}
                    response = requests.post(API_URL, files=files, params=params)
                    
                    if response.status_code == 200:
                        st.success("Manual Stamping Complete!")
                        stamped_pdf = response.content
                        pdf_viewer(stamped_pdf, width=500)
                        st.download_button("⬇️ Download Signed PDF", data=stamped_pdf, file_name=f"manual_{uploaded_pdf.name}", mime="application/pdf")
                    else:
                        st.error(f"Backend Error: {response.text}")
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("Click on the document to unlock manual placement.")

        st.markdown("---")

        # --- OPTION 2: AI AUTO-DETECT ---
        st.write("Or let the Vision OCR Engine find the keywords automatically.")
        if st.button("🤖 Run AI Auto-Detect"):
            with st.spinner("AI is scanning pixels and analyzing text..."):
                # Send NO coordinates, forcing the backend to use the Triple-Layer OCR Decision Tree
                response = requests.post(API_URL, files=files)
                
                if response.status_code == 200:
                    st.success("AI Stamping Complete!")
                    stamped_pdf = response.content
                    pdf_viewer(stamped_pdf, width=500)
                    st.download_button("⬇️ Download AI Signed PDF", data=stamped_pdf, file_name=f"auto_{uploaded_pdf.name}", mime="application/pdf")
                else:
                    st.error(f"Backend Error: {response.text}")