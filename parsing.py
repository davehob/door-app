import io, math, re
from fractions import Fraction
from typing import Optional, Iterable, Dict, Any
import pdfplumber

# Doors & Drawer Fronts
LINE_DOOR_DR = re.compile(
    r"^(?P<unit_blob>(?:\d+\)\d+\s+)+)?"
    r"(?P<qty>\d+)\s+"
    r"(?P<w_whole>\d+)(?:\s+(?P<w_frac>\d+/\d+))?\s+x\s+"
    r"(?P<h_whole>\d+)(?:\s+(?P<h_frac>\d+/\d+))?\s+"
    r"(?P<type>Door|Drawer Front)"
    r"(?:\s+\((?P<style>[^)]+)\))?",
    re.IGNORECASE,
)

# Panels (e.g., "Flat Panel", "Side Panel Left/Right", "Side Panel")
LINE_PANEL = re.compile(
    r"^(?P<unit_blob>(?:\d+\)\d+\s+)+)?"
    r"(?P<qty>\d+)\s+"
    r"(?P<w_whole>\d+)(?:\s+(?P<w_frac>\d+/\d+))?\s+x\s+"
    r"(?P<h_whole>\d+)(?:\s+(?P<h_frac>\d+/\d+))?\s+"
    r"(?P<panel>(?:.*\bPanel\b.*))$",
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
    tl = (t or "").lower()
    if tl.startswith("drawer front"): return "Drawer Front"
    return "Door"

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
                line = raw.strip()
                if "Continued to Next Page" in line or "Continued from Last Page" in line:
                    continue

                m1 = LINE_DOOR_DR.search(line)
                if m1:
                    unit_blob = m1.group("unit_blob") or ""
                    qty = int(m1.group("qty"))
                    width  = frac_to_up_decimal(m1.group("w_whole"), m1.group("w_frac"), places)
                    height = frac_to_up_decimal(m1.group("h_whole"), m1.group("h_frac"), places)
                    t_norm = normalize_type(m1.group("type"))
                    lbl = style_label(m1.group("style"))

                    unit_note = unit_blob_to_note(unit_blob, joiner)
                    base_note = t_norm
                    note = base_note if not unit_note else f"{base_note}{joiner}{unit_note}"

                    yield {
                        "type": t_norm, "style": lbl, "qty": qty,
                        "width_in": f"{width:.{places}f}",
                        "height_in": f"{height:.{places}f}",
                        "note": note, "source_page": page_num,
                        "hinge": None
                    }
                    continue

                m2 = LINE_PANEL.search(line)
                if m2:
                    unit_blob = m2.group("unit_blob") or ""
                    qty = int(m2.group("qty"))
                    width  = frac_to_up_decimal(m2.group("w_whole"), m2.group("w_frac"), places)
                    height = frac_to_up_decimal(m2.group("h_whole"), m2.group("h_frac"), places)

                    panel_text = m2.group("panel")
                    panel_note_tokens = []
                    pl = panel_text.lower()
                    if "side panel" in pl and "left" in pl:
                        panel_note_tokens.append("Side Panel Left")
                    elif "side panel" in pl and "right" in pl:
                        panel_note_tokens.append("Side Panel Right")
                    elif "side panel" in pl:
                        panel_note_tokens.append("Side Panel")
                    elif "flat panel" in pl:
                        panel_note_tokens.append("Flat Panel")
                    else:
                        panel_note_tokens.append("Panel")

                    unit_note = unit_blob_to_note(unit_blob, joiner)
                    note = joiner.join([t for t in (panel_note_tokens[0], unit_note) if t])

                    yield {
                        "type": "Panel", "style": "Panel", "qty": qty,
                        "width_in": f"{width:.{places}f}",
                        "height_in": f"{height:.{places}f}",
                        "note": note or "Panel", "source_page": page_num,
                        "hinge": None
                    }