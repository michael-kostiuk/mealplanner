"""
Extract all pages from verner.pdf to raw text using pymupdf4llm.
One file per page: app/fixtures/verner_pages/page_NNN.txt
Run: docker run --rm -v /path/to/backend:/app -w /app python:3.11-slim \
       bash -c "pip install pymupdf pymupdf4llm -q && python scripts/verner/extract_verner_raw.py"
"""

import os
import pymupdf4llm
import fitz

PDF_PATH = "new recipe book verner.pdf"
OUT_DIR = "app/fixtures/verner_pages"

os.makedirs(OUT_DIR, exist_ok=True)

doc = fitz.open(PDF_PATH)
total = len(doc)
doc.close()

print(f"Extracting {total} pages...")

for i in range(total):
    md = pymupdf4llm.to_markdown(PDF_PATH, pages=[i])
    out_path = os.path.join(OUT_DIR, f"page_{i + 1:03d}.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    if (i + 1) % 10 == 0 or i + 1 == total:
        print(f"  {i + 1}/{total}")

print(f"Done. Pages written to {OUT_DIR}/")
