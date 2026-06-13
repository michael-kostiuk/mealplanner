"""
Extract food photos from new recipe book verner.pdf — one JPEG per recipe page.

Strategy (confirmed by investigation):
  Every recipe page (3-121) contains exactly 2 raster images:
    1. A shared background texture (xref shared across pages, width > 4000px) — skip
    2. The food photo (unique per page, ~1536x1024 JPEG) — extract this one
  Ingredient tables are vector PDFForm XObjects (not in get_images).

Output: app/fixtures/verner_images/page_NNN.jpg

Run (needs PyMuPDF which is not installed locally):
    docker run --rm -v $(pwd):/app -w /app python:3.11-slim \
        bash -c "pip install pymupdf -q && python scripts/verner/extract_verner_images.py"
"""

import os
import fitz

PDF_PATH = "new recipe book verner.pdf"
OUT_DIR = "app/fixtures/verner_images"

BACKGROUND_XREFS: set[int] = set()
BG_MIN_WIDTH = 4000  # background texture is 4276px wide

os.makedirs(OUT_DIR, exist_ok=True)

doc = fitz.open(PDF_PATH)

# first pass: collect background xrefs (shared objects, large width)
for page_idx in range(2, 121):
    for img in doc[page_idx].get_images(full=True):
        xref, _, width, height = img[0], img[1], img[2], img[3]
        if width >= BG_MIN_WIDTH:
            BACKGROUND_XREFS.add(xref)

print(f"Background xrefs to skip: {BACKGROUND_XREFS}")

extracted = 0
skipped = 0
warnings = []

for page_idx in range(2, 121):  # pages 3-121
    page_num = page_idx + 1
    out_path = os.path.join(OUT_DIR, f"page_{page_num:03d}.jpg")

    if os.path.exists(out_path):
        skipped += 1
        continue

    page = doc[page_idx]
    candidates = [
        img
        for img in page.get_images(full=True)
        if img[0] not in BACKGROUND_XREFS and img[2] >= 400
    ]

    if not candidates:
        warnings.append(f"page {page_num}: no food photo found")
        continue

    # take the largest candidate by area
    best = max(candidates, key=lambda i: i[2] * i[3])
    xref = best[0]

    image_data = doc.extract_image(xref)
    ext = image_data["ext"]
    raw = image_data["image"]

    # save as jpg regardless of source format
    if ext == "jpeg":
        with open(out_path, "wb") as f:
            f.write(raw)
    else:
        # convert via pixmap if not already JPEG
        pix = fitz.Pixmap(doc, xref)
        if pix.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        pix.save(out_path.replace(".jpg", f".{ext}"))
        out_path = out_path.replace(".jpg", f".{ext}")

    extracted += 1
    w, h = best[2], best[3]
    if (extracted - 1) % 20 == 0 or page_num in (80, 84):
        print(
            f"  page {page_num:03d}: {w}x{h} {ext} {len(raw) // 1024}KB -> {os.path.basename(out_path)}"
        )

doc.close()

print(f"\nDone. extracted={extracted}  skipped(already exist)={skipped}")
if warnings:
    print(f"Warnings ({len(warnings)}):")
    for w in warnings:
        print(f"  {w}")
print(f"Images saved to: {OUT_DIR}/")
