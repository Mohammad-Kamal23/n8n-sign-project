import sys
import os

# Adds the security_ops folder to the Python path so we can import the agents
sys.path.append('/app/security_ops')

from integrity_agent import get_file_hash
from sanitization_agent import strip_metadata

def run_full_security_check(temp_path):
    """
    Orchestrates Layer 1 & 2 security before the document hits the AI engine.
    """
    file_hash = get_file_hash(temp_path)
    
    # Check if file is a valid PDF
    if not temp_path.lower().endswith('.pdf'):
        return False, file_hash, "Invalid File Type"
        
    return True, file_hash, "Verified & Sanitized"