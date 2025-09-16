import io
import math
import re
from typing import List, Dict, Any
import pdfplumber

FRACT_RE = re.compile(r"^(\d+)\s+(\d+)/(\d+)$")  # e.g., '14 7/8'

def frac_to_dec(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0
    # 14 7/8
    m = FRACT_RE.match(s)
    if m:
        whole = int(m.group(1))
        num = int(m.group(2))
        den = int(m.group(3))
        return round(whole + num/den, 3)
    # 7/8 only
    if "/" in s and " " not in s:
        num, den = s.split("/", 1)
        return round(int(num)/int(den), 3)
    try:
        return round(float(s), 3)
    except Exception:
        return 0.0

def classify(row_text: str) -> str:
    t = row_text.lower()
    if "drawer front" in t:
        return "Drawer Front"
    if "door" in t:
        return "Door"
    if "panel" in t or "side panel" in t or "flat panel" in t:
        return "Panel"
    return "Door"  # default

def panel_kind(note_text: str) -> str:
    t = (note_text or "").lower()
    if "side panel left" in t or "panel left" in t:
        return "Side Panel Left"
    if "side panel right" in t or "panel right" in t:
        return "Side Panel Right"
    if "flat panel" in t:
        return "Flat Panel"
    return "Panel"

UNIT_TOKEN_RE = re.compile(r"(?P<qty>\d+)\)(?P<unit>\d+)")  # "2)12" -> qty=2, unit=12

def parse_pdf_bytes(pdf_bytes: bytes) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            text = p.extract_text() or ""
            lines = [ln for ln in text.splitlines() if ln.strip()]
            for ln in lines:
                # extremely simple row spotting; you can harden this for your exact forms
                if "Door" in ln or "Drawer Front" in ln or "Panel" in ln:
                    cols = re.split(r"\s{2,}", ln.strip())
                    if len(cols) < 5:
                        continue
                    # crude assumptions: [style, qty, width, height, note...]
                    style_raw = cols[0]
                    qty = int(re.sub(r"\D", "", cols[1]) or "1")
                    width_in = frac_to_dec(cols[2])
                    height_in = frac_to_dec(cols[3])
                    note_str = " ".join(cols[4:]).strip()

                    # attach unit tokens (1)9 => 1x#9
                    tokens = []
                    for m in UNIT_TOKEN_RE.finditer(ln):
                        tokens.append(f'{m.group("qty")}x#{m.group("unit")}')
                    unit_note = " | ".join(tokens)
                    final_note = f"{note_str}".strip()
                    if unit_note:
                        final_note = (final_note + " | " + unit_note).strip(" |")

                    t = classify(ln)
                    if t == "Panel":
                        pk = panel_kind(note_str)
                        if pk and pk != "Panel":
                            final_note = (final_note + f" | {pk}").strip(" |")

                    # style mapping left to UI settings
                    out.append({
                        "type": t,
                        "style_raw": style_raw,
                        "style_final": "",  # filled by settings later when exporting
                        "qty": qty,
                        "width_in": width_in,
                        "height_in": height_in,
                        "note": final_note
                    })
    return out