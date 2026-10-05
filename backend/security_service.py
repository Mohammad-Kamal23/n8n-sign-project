"""Checks every document before it reaches the stamping engine, and cleans every document it returns.

  integrity    : SHA-256 of the input, returned with the result so a stamped file can be traced to its original
  validation   : the file must really be a PDF (magic bytes), not only be named .pdf
  sanitisation : author / producer / XMP metadata are removed from the output
"""
import hashlib


def get_file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_pdf(path):
    with open(path, "rb") as f:
        return f.read(5) == b"%PDF-"


def strip_metadata(doc):
    """Removes document metadata (PyMuPDF document, edited in place)."""
    doc.set_metadata({})
    try:
        doc.del_xml_metadata()
    except Exception:
        pass
    return doc


def run_full_security_check(path):
    """(ok, sha256, message) for a file on disk."""
    file_hash = get_file_hash(path)
    if not path.lower().endswith(".pdf") or not is_pdf(path):
        return False, file_hash, "Not a PDF"
    return True, file_hash, "Verified"
