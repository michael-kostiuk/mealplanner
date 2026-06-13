"""
POC: compare column-aware PDF extraction methods on a single recipe page.
Run: docker run --rm -v /path/to/backend:/app -w /app python:3.11-slim \
       bash -c "pip install pdfplumber pymupdf pymupdf4llm -q && python scripts/verner/poc_columns.py"
"""

PDF_PATH = "new recipe book verner.pdf"
TEST_PAGE = 2  # 0-indexed → page 3 (first recipe: Оладки з цукіні)

print("\n" + "=" * 70)
print("METHOD 1: pdfplumber extract_text() — default (no column awareness)")
print("=" * 70)
import pdfplumber

with pdfplumber.open(PDF_PATH) as pdf:
    page = pdf.pages[TEST_PAGE]
    print(page.extract_text())


print("\n" + "=" * 70)
print("METHOD 2: pdfplumber crop() — split page at midpoint by x coordinate")
print("=" * 70)
with pdfplumber.open(PDF_PATH) as pdf:
    page = pdf.pages[TEST_PAGE]
    w = page.width
    h = page.height
    mid = w * 0.42  # rough split; ingredient table is left ~40% of page

    left = page.crop((0, 0, mid, h))
    right = page.crop((mid, 0, w, h))

    left_text = left.extract_text() or ""
    right_text = right.extract_text() or ""

    print("--- LEFT COLUMN (ingredients) ---")
    print(left_text)
    print("\n--- RIGHT COLUMN (instructions) ---")
    print(right_text)


print("\n" + "=" * 70)
print("METHOD 3: pdfplumber extract_words() → cluster by x0 into columns")
print("=" * 70)
with pdfplumber.open(PDF_PATH) as pdf:
    page = pdf.pages[TEST_PAGE]
    words = page.extract_words(x_tolerance=3, y_tolerance=3)

    # find column split: gap in x0 distribution
    xs = sorted(set(round(w["x0"] / 10) * 10 for w in words))
    # simple heuristic: left col words start before 40% of page width
    threshold = page.width * 0.42

    left_words = [w for w in words if w["x0"] < threshold]
    right_words = [w for w in words if w["x0"] >= threshold]

    def words_to_lines(wlist):
        from collections import defaultdict

        rows = defaultdict(list)
        for w in wlist:
            row_key = round(w["top"] / 5) * 5
            rows[row_key].append(w)
        lines = []
        for key in sorted(rows):
            lines.append(" ".join(w["text"] for w in sorted(rows[key], key=lambda x: x["x0"])))
        return "\n".join(lines)

    print("--- LEFT COLUMN ---")
    print(words_to_lines(left_words))
    print("\n--- RIGHT COLUMN ---")
    print(words_to_lines(right_words))


print("\n" + "=" * 70)
print("METHOD 4: PyMuPDF get_text('blocks') — layout-aware block detection")
print("=" * 70)
import fitz  # pymupdf

doc = fitz.open(PDF_PATH)
page = doc[TEST_PAGE]
blocks = page.get_text("blocks")  # list of (x0, y0, x1, y1, text, block_no, block_type)
# sort top-to-bottom, then left-to-right
blocks_sorted = sorted(blocks, key=lambda b: (round(b[1] / 10), b[0]))
for b in blocks_sorted:
    x0, y0, x1, y1, text, *_ = b
    print(f"[x0={x0:.0f} y0={y0:.0f}] {text.strip()[:80]}")


print("\n" + "=" * 70)
print("METHOD 5: PyMuPDF get_text('dict') — fine-grained spans with coords")
print("=" * 70)
page = doc[TEST_PAGE]
page_dict = page.get_text("dict")
page_w = page_dict["width"]
col_split = page_w * 0.42

left_lines, right_lines = [], []
for block in page_dict["blocks"]:
    if block.get("type") != 0:
        continue
    for line in block["lines"]:
        spans = line.get("spans", [])
        if not spans:
            continue
        line_x0 = spans[0]["origin"][0]
        text = " ".join(s["text"] for s in spans).strip()
        if not text:
            continue
        if line_x0 < col_split:
            left_lines.append((line_x0, spans[0]["origin"][1], text))
        else:
            right_lines.append((line_x0, spans[0]["origin"][1], text))

print("--- LEFT COLUMN ---")
for _, _, t in sorted(left_lines, key=lambda x: x[1]):
    print(t)
print("\n--- RIGHT COLUMN ---")
for _, _, t in sorted(right_lines, key=lambda x: x[1]):
    print(t)


print("\n" + "=" * 70)
print("METHOD 6: pymupdf4llm — markdown conversion (LLM-friendly)")
print("=" * 70)
import pymupdf4llm

md = pymupdf4llm.to_markdown(PDF_PATH, pages=[TEST_PAGE])
print(md[:3000])

doc.close()
