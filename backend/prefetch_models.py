# prefetch_models.py
import os
from unittest.mock import patch
from transformers import AutoProcessor, AutoModelForCausalLM
from transformers.dynamic_module_utils import get_imports
import easyocr

print("Starting Enterprise Model Pre-Fetch Sequence...")

# --- THE FLASH ATTENTION HACK ---
# This intercepts HuggingFace's aggressive import checker and removes flash_attn
def fixed_get_imports(filename: str | os.PathLike) -> list[str]:
    if not str(filename).endswith("modeling_florence2.py"):
        return get_imports(filename)
    imports = get_imports(filename)
    if "flash_attn" in imports:
        imports.remove("flash_attn")
    return imports

print("-> Downloading Florence-2-base-ft (with import bypass)...")
model_id = "microsoft/Florence-2-base-ft"

# Apply the patch while loading the model
with patch("transformers.dynamic_module_utils.get_imports", fixed_get_imports):
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)

print("-> Downloading EasyOCR Weights (EN/AR)...")
reader = easyocr.Reader(['en', 'ar'], gpu=False)

print("\nSUCCESS: All AI Models Cached into Docker Image.")