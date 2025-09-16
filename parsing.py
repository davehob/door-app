import io, math, re
from fractions import Fraction
from typing import Optional, Iterable, Dict, Any
import pdfplumber

LINE_RE = re.compile(
    r"^(?P<unit_blob>(?:\d+\)\d+\s+)+)?"
    r"(?P<qty>\d+)\s+"
    r"(?P<w_whole>\d+)(?:\s+(?P<w_frac>\d+/\d+))?\s+x\s+"
    r"(?P<h_whole>\d+)(?:\s+(?P<h_frac>\d+/\d+))?\s+"
    r"(?P<type>Door|Drawer Front)"
    r"(?:\s+\((?P<style>[^)]+)\))?",
    re.IGNORECASE,
)
UNIT_TOKEN_RE = re.compile(r"(?P<qty>\d+)\)(?P<unit>\d+)")

def ceil_to_decimals(v: float, places: int) -> float:
    return math.ceil(v * (10 ** places)) / (10 ** places)

def frac_to_up_decimal(whole: str, frac: Optional[str], places: int) -> float:
    val = float(whole)
    if frac:
        num, den = frac.split("/")
        val += float(Fraction(int(num), int(den)))
    return ceil_to_decimals(val, places)

def unit_blob_to_note(blob: Optional[str], joiner: str) -> str:
    if not blob: return ""
    parts = [f"{m.group('qty')}x#{m.group('unit')}" for m in UNIT_TOKEN_RE.finditer(blob.strip())]
    return joiner.join(parts)

def normalize_type(t: str) -> str:
    return "Drawer Front" if (t or "").lower().startswith("drawer front") else "Door"

def style_label(style_raw: Optional[str]) -> str:
    s = (style_raw or "").lower()
    if "sfp" in s: return "SFP"
    if "flatdr" in s or "flat" in s: return "Flat"
    return ""

def parse_pdf(pdf_bytes: bytes, places: int, joiner: str) -> Iterable[Dict[str, Any]]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for raw in text.splitlines():
                if "Continued to Next Page" in raw or "Continued from Last Page" in raw:
                    continue
                m = LINE_RE.search(raw.strip())
                if not m: continue

                unit_blob = m.group("unit_blob") or ""
                qty = int(m.group("qty"))
                width  = frac_to_up_decimal(m.group("w_whole"), m.group("w_frac"), places)
                height = frac_to_up_decimal(m.group("h_whole"), m.group("h_frac"), places)
                t_norm = normalize_type(m.group("type"))
                lbl = style_label(m.group("style"))

                unit_note = unit_blob_to_note(unit_blob, joiner)
                note = t_norm if not unit_note else f"{t_norm}{joiner}{unit_note}"

                yield {
                    "type": t_norm, "style": lbl, "qty": qty,
                    "width_in": f"{width:.{places}f}",
                    "height_in": f"{height:.{places}f}",
                    "note": note, "source_page": page_num
                }
