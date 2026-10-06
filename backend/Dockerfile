FROM python:3.10-slim

WORKDIR /app

# USE_FLORENCE=1 adds the Florence-2 detector (about 2 GB of RAM).
# The default image uses template matching only and runs in 512 MB.
ARG USE_FLORENCE=0
ENV USE_FLORENCE=${USE_FLORENCE} \
    HF_HOME=/opt/models_cache

COPY requirements.txt requirements-florence.txt ./
RUN if [ "$USE_FLORENCE" = "1" ]; then pip install --no-cache-dir -r requirements-florence.txt; \
    else pip install --no-cache-dir -r requirements.txt; fi

# Florence-2 weights are downloaded at build time, so the API starts without a download
COPY prefetch_models.py .
RUN if [ "$USE_FLORENCE" = "1" ]; then python prefetch_models.py; fi

COPY . .

# PORT is set by hosts such as Render; 8000 otherwise
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
