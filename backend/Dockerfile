FROM python:3.10-slim

WORKDIR /app

# --- Install Linux graphics libraries for OpenCV/EasyOCR ---
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# --- Install Python Dependencies ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- AI Model Caching Environment ---
# We force HuggingFace to save the models inside our app folder so they persist.
ENV HF_HOME=/app/models_cache

# --- Pre-Fetch Models ---
# Copy ONLY the prefetch script so Docker caches this layer permanently
COPY prefetch_models.py .
RUN python prefetch_models.py

# --- Copy Application Code ---
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]