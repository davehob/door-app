import io
import datetime
from fastapi import FastAPI, Request, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
import pdfplumber

from db import engine, Order, Item

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Static assets (CSS/JS if needed)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ------------------------------
# PDF PARSER (simplified example)
# ------------------------------
def parse_pdf_bytes(pdf_bytes: bytes):
    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            table = page.extract_table()
            if not table:
                continue
            for row in table[1:]:  # skip header
                if not any(row):
                    continue
                rows.append({
                    "type": row[0] or "Door",
                    "style": row[1] or "",
                    "qty": row[2] or "0",
                    "width_in": row[3] or "",
                    "height_in": row[4] or "",
                    "note": row[5] or "",
                    "source_page": page_num,
                })
    return rows


# ------------------------------
# ROUTES
# ------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with Session(engine) as s:
        orders = s.query(Order).all()
        return templates.TemplateResponse("index.html", {"request": request, "orders": orders})


@app.post("/upload")
async def upload(request: Request, file: UploadFile):
    pdf_bytes = await file.read()
    rows = parse_pdf_bytes(pdf_bytes)

    with Session(engine) as s:
        order = Order(
            job_id=file.filename,
            created_at=datetime.datetime.utcnow()
        )
        s.add(order)
        s.flush()

        for r in rows:
            item = Item(
                order_id=order.id,
                type=r["type"],
                style=r["style"],
                qty=int(r["qty"]),
                width_in=r["width_in"],
                height_in=r["height_in"],
                note=r["note"],
                source_page=r["source_page"]
            )
            s.add(item)
        s.commit()

        return {
            "id": order.id,
            "job_id": order.job_id,
            "created_at": order.created_at,
            "saved_items": len(rows)
        }


@app.get("/orders/{order_id}", response_class=HTMLResponse, name="order_detail")
def order_detail(request: Request, order_id: int):
    with Session(engine) as s:
        order = s.get(Order, order_id)
        if not order:
            raise HTTPException(404, "Order not found")
        return templates.TemplateResponse("order_detail.html", {"request": request, "order": order})


# ------------------------------
# SETTINGS (per order)
# ------------------------------
@app.get("/orders/{order_id}/settings", response_class=HTMLResponse, name="order_settings_get")
def order_settings_get(request: Request, order_id: int):
    with Session(engine) as s:
        o = s.get(Order, order_id)
        if not o:
            raise HTTPException(404, "Order not found")
        return templates.TemplateResponse("settings.html", {"request": request, "order": o})


@app.post("/orders/{order_id}/settings", name="order_settings_post")
def order_settings_post(order_id: int,
    dealer_code: str = Form(default=""),
    job_name: str = Form(default=""),
    finish: str = Form(default=""),
    style_door_sfp: str = Form(default=""),
    style_door_flat: str = Form(default=""),
    style_drawer_sfp: str = Form(default=""),
    style_drawer_flat: str = Form(default=""),
    style_panel_code: str = Form(default=""),
    hinge_top_offset_in: str = Form(default=""),
    hinge_bottom_offset_in: str = Form(default=""),
    hinge_size_in: str = Form(default=""),
):
    with Session(engine) as s:
        o = s.get(Order, order_id)
        if not o:
            raise HTTPException(404)
        o.dealer_code = dealer_code or None
        o.job_name = job_name or None
        o.finish = finish or None
        o.style_door_sfp = style_door_sfp or None
        o.style_door_flat = style_door_flat or None
        o.style_drawer_sfp = style_drawer_sfp or None
        o.style_drawer_flat = style_drawer_flat or None
        o.style_panel_code = style_panel_code or None
        o.hinge_top_offset_in = hinge_top_offset_in or None
        o.hinge_bottom_offset_in = hinge_bottom_offset_in or None
        o.hinge_size_in = hinge_size_in or None
        s.commit()
    return RedirectResponse(url=f"/orders/{order_id}/settings?saved=1", status_code=303)


# ------------------------------
# DELETE ORDER
# ------------------------------
@app.post("/orders/{order_id}/delete")
def delete_order(order_id: int):
    with Session(engine) as s:
        o = s.get(Order, order_id)
        if not o:
            raise HTTPException(404)
        s.delete(o)
        s.commit()
    return RedirectResponse(url="/", status_code=303)