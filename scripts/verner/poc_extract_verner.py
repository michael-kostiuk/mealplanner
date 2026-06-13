"""
POC: extract first few pages from verner.pdf to inspect text structure.
Run: docker run --rm -v /path/to/backend:/app -w /app python:3.11-slim \
       bash -c "pip install pdfplumber -q && python scripts/verner/poc_extract_verner.py"
"""

import pdfplumber

PDF_PATH = "new recipe book verner.pdf"
SAMPLE_PAGES = 15  # inspect first N pages
OUT_PATH = "app/fixtures/verner_sample.txt"

with pdfplumber.open(PDF_PATH) as pdf:
    total = len(pdf.pages)
    print(f"Total pages: {total}")

    lines = []
    for i, page in enumerate(pdf.pages[:SAMPLE_PAGES]):
        text = page.extract_text()
        lines.append(f"\n{'=' * 60}\n PAGE {i + 1}\n{'=' * 60}\n")
        lines.append(text or "[NO TEXT]")

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Wrote sample to {OUT_PATH}")
