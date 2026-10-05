"""Downloads Florence-2 into the Docker image at build time, so the API starts without network access."""
import os
from unittest.mock import patch

from transformers import AutoModelForCausalLM, AutoProcessor
from transformers.dynamic_module_utils import get_imports

MODEL = os.getenv("FLORENCE_MODEL", "microsoft/Florence-2-base-ft")


def imports_without_flash_attn(filename):
    """Florence-2's remote code lists flash_attn as an import; it is optional, so drop it."""
    imports = get_imports(filename)
    if str(filename).endswith("modeling_florence2.py") and "flash_attn" in imports:
        imports.remove("flash_attn")
    return imports


if os.getenv("USE_FLORENCE", "1") == "1":
    print(f"Downloading {MODEL} ...")
    with patch("transformers.dynamic_module_utils.get_imports", imports_without_flash_attn):
        AutoProcessor.from_pretrained(MODEL, trust_remote_code=True)
        AutoModelForCausalLM.from_pretrained(MODEL, trust_remote_code=True)
    print("Florence-2 cached in the image.")
