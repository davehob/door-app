import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starlette.status import HTTP_302_FOUND
from starlette.middleware.cors import CORSMiddleware

from db import (
    get_engine, ensure_schema, list_orders, get_order, create_order,
    delete_order, list_items_for_order, upsert_settings_for_order,
    get_settings_for_order, add_item_to_order
)
from parsing import parse_pdf_bytes

# ------------ App & paths ------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Single, unified DB path
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "doorapp.db"))
engine = get_engine(DB_PATH)
ensure_schema(engine)

# ------------ Helpers ------------
def flash_redirect(url: str, request: Request, message: str = "") -> RedirectResponse:
    # extremely simple no-cookie flash: add ?ok=... to url
    if message:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}ok={message}"
    return RedirectResponse(url, status_code=HTTP_302_FOUND)

# ------------ Routes ------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: Optional[str] = None, page: int = 1):
    orders = list_orders(engine, q=q, page=page, page_size=50)
    ok = request.query_params.get("ok", "")
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "orders": orders, "q": q or "", "ok": ok}
    )

# convenience: /settings -> last order settings (if exists)
@app.get("/settings")
def settings_root_redirect(request: Request):
    orders = list_orders(engine, page=1, page_size=1)
    if not orders:
        return flash_redirect("/", request, "No orders yet")
    last_id = orders[0]["id"]
    return RedirectResponse(f"/orders/{last_id}/settings", status_code=HTTP_302_FOUND)

@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: int):
    order = get_order(engine, order_id)
    if not order:
        return RedirectResponse("/", status_code=HTTP_302_FOUND)
    items = list_items_for_order(engine, order_id)
    settings = get_settings_for_order(engine, order_id) or {}
    ok = request.query_params.get("ok", "")
    return templates.TemplateResponse(
        "order.html",
        {"request": request, "order": order, "items": items, "settings": settings, "ok": ok}
    )

@app.post("/upload")
async def upload(job_id: str = Form(...), file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    rows = parse_pdf_bytes(pdf_bytes)  # returns list of dicts incl. type Door/Drawer Front/Panel
    oid = create_order(engine, job_id)
    saved = 0
    for r in rows:
        add_item_to_order(
            engine,
            order_id=oid,
            type=r.get("type"),            # Door / Drawer Front / Panel
            style=r.get("style_final", ""),# style_final from parser if present
            qty=int(r.get("qty", 1)),
            width_in=float(r.get("width_in", 0)),
            height_in=float(r.get("height_in", 0)),
            note=r.get("note", "")
        )
        saved += 1
    return JSONResponse({"id": oid, "job_id": job_id, "created_at": datetime.utcnow().isoformat() + "Z", "saved_items": saved})

@app.post("/orders/{order_id}/delete")
def remove_order(order_id: int):
    delete_order(engine, order_id)
    return RedirectResponse("/", status_code=HTTP_302_FOUND)

# ----- Settings (per-order) -----
@app.get("/orders/{order_id}/settings", response_class=HTMLResponse)
def get_settings(request: Request, order_id: int):
    order = get_order(engine, order_id)
    if not order:
        return RedirectResponse("/", status_code=HTTP_302_FOUND)
    settings = get_settings_for_order(engine, order_id) or {
        "dealer_code": "",
        "job_name": order["job_id"],
        "finish": "",
        "door_sfp_code": "",
        "door_flat_code": "",
        "drawer_sfp_code": "",
        "drawer_flat_code": "",
        "panel_code": "",
        "hinge_top_offset_in": 3.0,
        "hinge_bottom_offset_in": 3.0,
        "hinge_size_in": 5.0
    }
    ok = request.query_params.get("ok", "")
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "order": order, "settings": settings, "ok": ok}
    )

@app.post("/orders/{order_id}/settings")
async def post_settings(
    request: Request,
    order_id: int,
    dealer_code: str = Form(""),
    job_name: str = Form(""),
    finish: str = Form(""),
    door_sfp_code: str = Form(""),
    door_flat_code: str = Form(""),
    drawer_sfp_code: str = Form(""),
    drawer_flat_code: str = Form(""),
    panel_code: str = Form(""),
    hinge_top_offset_in: float = Form(3.0),
    hinge_bottom_offset_in: float = Form(3.0),
    hinge_size_in: float = Form(5.0),
):
    payload = {
        "dealer_code": dealer_code.strip(),
        "job_name": job_name.strip(),
        "finish": finish.strip(),
        "door_sfp_code": door_sfp_code.strip(),
        "door_flat_code": door_flat_code.strip(),
        "drawer_sfp_code": drawer_sfp_code.strip(),
        "drawer_flat_code": drawer_flat_code.strip(),
        "panel_code": panel_code.strip(),
        "hinge_top_offset_in": float(hinge_top_offset_in),
        "hinge_bottom_offset_in": float(hinge_bottom_offset_in),
        "hinge_size_in": float(hinge_size_in),
    }
    upsert_settings_for_order(engine, order_id, payload)
    return flash_redirect(f"/orders/{order_id}/settings", request, "Settings saved")

# ----- Manual add/split items (basic) -----
@app.post("/orders/{order_id}/items")
def add_item(
    order_id: int,
    type: str = Form(...),               # 'Door' | 'Drawer Front' | 'Panel'
    style: str = Form(""),
    qty: int = Form(1),
    width_in: float = Form(...),
    height_in: float = Form(...),
    note: str = Form("")
):
    add_item_to_order(engine, order_id, type=type, style=style, qty=qty,
                      width_in=width_in, height_in=height_in, note=note)
    return RedirectResponse(f"/orders/{order_id}?ok=Item+added", status_code=HTTP_302_FOUND)