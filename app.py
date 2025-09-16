# app.py — Door Admin (FastAPI + Jinja2 + htmx)
# Run: uvicorn app:app --host 0.0.0.0 --port 8000
from fastapi import FastAPI, Request, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from db import engine, init_db, Order, Item, Setting
from parsing import parse_pdf
from exporters import build_order_excel

init_db()
app = FastAPI(title="Door Admin")
templates = Jinja2Templates(directory="templates")

# Helpers
def get_setting(s: Session, key: str, default: str) -> str:
    rec = s.query(Setting).filter_by(key=key).first()
    return rec.value if rec else default

@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/orders", status_code=303)

# Orders list
@app.get("/orders", response_class=HTMLResponse)
def orders_list(request: Request, page: int = 1, q: str | None = None):
    PAGE = 20
    with Session(engine) as s:
        stmt = select(Order).order_by(Order.id.desc())
        if q:
            stmt = stmt.filter(Order.job_id.contains(q))
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        orders = s.execute(stmt.limit(PAGE).offset((page - 1) * PAGE)).scalars().all()
    page_count = max(1, (total + PAGE - 1) // PAGE)
    return templates.TemplateResponse("orders_list.html", {
        "request": request, "orders": orders, "page": page, "page_count": page_count, "q": q
    })

# Upload PDF
@app.post("/upload")
async def upload_pdf(file: UploadFile, job_id: str = Form(default="")):
    pdf_bytes = await file.read()
    if not pdf_bytes or (
        file.content_type not in ("application/pdf", "application/octet-stream")
        and not file.filename.lower().endswith(".pdf")
    ):
        raise HTTPException(status_code=400, detail="Please upload a PDF.")
    # rounding + note joiner from global setting (legacy defaults)
    with Session(engine) as s:
        places = int(get_setting(s, "decimal_precision", "3"))
        joiner = get_setting(s, "note_joiner", " | ")
    rows = list(parse_pdf(pdf_bytes, places=places, joiner=joiner))
    # store
    with Session(engine) as s:
        order = Order(job_id=job_id)
        s.add(order); s.flush()
        for r in rows:
            s.add(Item(order_id=order.id, **r))
        s.commit()
        return {"id": order.id, "job_id": order.job_id, "created_at": order.created_at.isoformat(), "saved_items": len(rows)}

# Order detail
@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: int, type: str | None = None):
    with Session(engine) as s:
        order = s.get(Order, order_id)
        if not order: raise HTTPException(404, "Order not found")
        items = order.items
        if type:
            items = [i for i in items if i.type == type]
        return templates.TemplateResponse("order_detail.html", {
            "request": request, "order": order, "items": items, "f_type": type
        })

# Delete order (uses hidden input "_method"="delete")
@app.post("/orders/{order_id}")
def order_delete(order_id: int, method: str = Form(alias="_method")):
    if method.lower() != "delete":
        raise HTTPException(status_code=400, detail="Invalid method")
    with Session(engine) as s:
        o = s.get(Order, order_id)
        if not o: raise HTTPException(status_code=404, detail="Order not found")
        s.delete(o); s.commit()
    return RedirectResponse("/orders", status_code=303)

# Inline item edit (qty/width/height/note/hinge)
@app.post("/items/{item_id}/edit", response_class=HTMLResponse)
async def item_edit(request: Request, item_id: int, field: str = Form(...), value: str = Form(...)):
    with Session(engine) as s:
        it = s.get(Item, item_id)
        if not it: raise HTTPException(404, "Item not found")
        if field not in {"qty","width_in","height_in","note","hinge"}:
            raise HTTPException(400, "Bad field")

        if field == "qty":
            try: it.qty = int(value)
            except: raise HTTPException(400, "qty must be integer")
        elif field in {"width_in","height_in"}:
            if field == "width_in": it.width_in = value
            else: it.height_in = value
        elif field == "hinge":
            if value not in {"L","R","None",""}: raise HTTPException(400, "hinge must be L, R or None")
            it.hinge = None if value in {"","None"} else value
        else:
            it.note = value

        s.commit(); s.refresh(it)
        order = s.get(Order, it.order_id)
        return templates.TemplateResponse("_items_table.html", {"request": request, "items": order.items})

@app.delete("/items/{item_id}", response_class=HTMLResponse)
def item_delete(request: Request, item_id: int):
    with Session(engine) as s:
        it = s.get(Item, item_id)
        if not it: raise HTTPException(404, "Item not found")
        order_id = it.order_id
        s.delete(it); s.commit()
        order = s.get(Order, order_id)
        return templates.TemplateResponse("_items_table.html", {"request": request, "items": order.items})

# Add a blank item to this order
@app.post("/orders/{order_id}/items/new", response_class=HTMLResponse)
def item_new(request: Request, order_id: int):
    with Session(engine) as s:
        o = s.get(Order, order_id)
        if not o: raise HTTPException(404)
        it = Item(order_id=o.id, type="Door", style="SFP", qty=1,
                  width_in="0.000", height_in="0.000", note="Manual", source_page=0, hinge=None)
        s.add(it); s.commit()
        o = s.get(Order, order_id)
        return templates.TemplateResponse("_items_table.html", {"request": request, "items": o.items})

# Split an item into two with custom quantities
@app.post("/items/{item_id}/split", response_class=HTMLResponse)
def item_split(request: Request, item_id: int, qty1: int = Form(...), qty2: int = Form(...)):
    if qty1 < 0 or qty2 < 0: raise HTTPException(400)
    with Session(engine) as s:
        it = s.get(Item, item_id)
        if not it: raise HTTPException(404)
        if qty1 + qty2 != it.qty: raise HTTPException(400, "qty1 + qty2 must equal original qty")
        it.qty = qty1
        if qty2 > 0:
            s.add(Item(order_id=it.order_id, type=it.type, style=it.style, qty=qty2,
                       width_in=it.width_in, height_in=it.height_in, note=it.note,
                       source_page=it.source_page, hinge=it.hinge))
        s.commit()
        order = s.get(Order, it.order_id)
        return templates.TemplateResponse("_items_table.html", {"request": request, "items": order.items})

# CSV / Excel
@app.get("/orders/{order_id}/items.csv")
def order_csv(order_id: int):
    with Session(engine) as s:
        o = s.get(Order, order_id)
        if not o: raise HTTPException(404, "Order not found")
        rows = o.items
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["order_id","job_id","type","style","qty","width_in","height_in","hinge","note","source_page"])
    for it in rows:
        w.writerow([o.id, o.job_id, it.type, it.style, it.qty, it.width_in, it.height_in, it.hinge or "None", it.note, it.source_page])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="order_{order_id}.csv"'})

@app.get("/orders/{order_id}/export.xlsx")
def export_xlsx(order_id: int):
    with Session(engine) as s:
        o = s.get(Order, order_id)
        if not o: raise HTTPException(404)
        wb = build_order_excel(o, o.items)
    from io import BytesIO
    bio = BytesIO(); wb.save(bio); bio.seek(0)
    return StreamingResponse(bio, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="order_{order_id}.xlsx"'})

# Settings per order
@app.get("/orders/{order_id}/settings", response_class=HTMLResponse)
def order_settings_get(request: Request, order_id: int):
    with Session(engine) as s:
        o = s.get(Order, order_id)
        if not o: raise HTTPException(404)
        return templates.TemplateResponse("settings.html", {"request": request, "order": o})

@app.post("/orders/{order_id}/settings")
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
        if not o: raise HTTPException(404)
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
    return RedirectResponse(f"/orders/{order_id}/settings", status_code=303)