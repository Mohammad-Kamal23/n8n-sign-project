import streamlit as st
import requests
from streamlit_pdf_viewer import pdf_viewer

# The internal Docker network URL to talk to your FastAPI backend
API_URL = "https://automated-signage.onrender.com/stamp-document/"

# Configure the page
st.set_page_config(page_title="Automated Signage", page_icon="✍️", layout="wide")

# Custom CSS for an "Amazing" look
st.markdown("""
<style>
    /* Main Background and Text */
    .stApp { background-color: #0E1117; color: #FAFAFA; }
    
    /* Custom Header Box */
    .header-box {
        padding: 1.5rem; 
        background-color: #1E2127; 
        border-radius: 10px;
        border-left: 5px solid #007BFF; 
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    
    /* Style the buttons */
    .stButton>button {
        background-color: #007BFF; 
        color: white; 
        border-radius: 5px;
        border: none; 
        padding: 10px 24px; 
        font-weight: bold;
        transition: 0.3s;
        width: 100%;
    }
    .stButton>button:hover {
        background-color: #0056b3;
        border-color: #0056b3;
    }
    
    /* Style the download button specifically */
    .stDownloadButton>button {
        background-color: #28a745;
    }
    .stDownloadButton>button:hover {
        background-color: #1e7e34;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<div class="header-box"><h1>✍️ Automated Document Signage</h1><p>Upload a document to detect anchor keywords and apply official digital stamps instantly.</p></div>', unsafe_allow_html=True)

# File Uploader
uploaded_file = st.file_uploader("Upload Document for Review (PDF)", type=["pdf"])

if uploaded_file:
    # Create two columns for a side-by-side view
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📄 Original Document")
        # Safely render the PDF using the dedicated viewer
        pdf_viewer(uploaded_file.getvalue(), width=700)

    with col2:
        st.subheader("✅ Approval & Stamping")
        st.write("Click below to process the document through the AI detection engine.")
        
        if st.button("Approve & Apply Digital Stamp"):
            with st.spinner("Analyzing text and applying stamps..."):
                # Send the file to your FastAPI backend
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                try:
                    response = requests.post(API_URL, files=files)
                    
                    if response.status_code == 200:
                        st.success("Stamping Complete! Found and stamped keywords.")
                        stamped_pdf = response.content

                        # Display the Stamped PDF safely
                        pdf_viewer(stamped_pdf, width=700)

                        # Provide Download Button
                        st.download_button(
                            label="⬇️ Download Signed PDF",
                            data=stamped_pdf,
                            file_name=f"signed_{uploaded_file.name}",
                            mime="application/pdf"
                        )
                    else:
                        st.error(f"Error processing document: {response.text}")
                except Exception as e:
                    st.error(f"Failed to connect to backend engine: {e}")