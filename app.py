import io
import os
from datetime import datetime
from pathlib import Path

import pdfplumber
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, create_engine, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# -------------------------------
# Paths
# -------------------------------
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# -------------------------------
# FastAPI setup
# -------------------------------
app = FastAPI()

# Only mount static if it exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# -------------------------------
# Database setup
# -------------------------------
DATABASE_URL = f"sqlite:///{BASE_DIR}/doorapp.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)
Base = declarative_base()

# -------------------------------
# Models
# -------------------------------
class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    job_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    settings = relationship("OrderSettings", uselist=False, back_populates="order")
    items = relationship("Item", back_populates="order", cascade="all, delete-orphan")

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    type = Column(String)      # Door, Drawer Front, Panel
    style = Column(String)     # SFP, Flat, etc.
    qty = Column(Integer)
    width_in = Column(String)
    height_in = Column(String)
    note = Column(Text)
    source_page = Column(Integer)
    order = relationship("Order", back_populates="items")

class OrderSettings(Base):
    __tablename__ = "order_settings"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    dealer_code = Column(String)
    job_name = Column(String)
    finish = Column(String)

    door_sfp_code = Column(String)
    door_flat_code = Column(String)
    drawer_sfp_code = Column(String)
    drawer_flat_code = Column(String)
    panel_code = Column(String)

    hinge_top_offset = Column(Integer)
    hinge_bottom_offset = Column(Integer)
    hinge_size = Column(Integer)

    order = relationship("Order", back_populates="settings")

Base.metadata.create_all(engine)

# -------------------------------
# PDF Parsing Stub
# -------------------------------
def parse_pdf_bytes(pdf_bytes: bytes):
    rows = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                for line in text.splitlines():
                    if "Door" in line or "Drawer" in line or "Panel" in line:
                        rows.append({
                            "type": "Door" if "Door" in line else "Drawer Front",
                            "style": "SFP" if "SFP" in line else "Flat",
                            "qty": 1,
                            "width_in": "10.0",
                            "height_in": "20.0",
                            "note": line.strip(),
                            "source_page": i
                        })
    except Exception as e:
        print("PDF parse error:", e)
    return rows

# -------------------------------
# Routes
# -------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with Session() as s:
        orders = s.query(Order).order_by(Order.id.desc()).all()
    return templates.TemplateResponse(
        "orders_list.html",
        {"request": request, "orders": orders, "page": 1, "page_count": 1}
    )

@app.post("/upload")
async def upload(file: UploadFile, job_id: str = Form(None)):
    pdf_bytes = await file.read()
    rows = parse_pdf_bytes(pdf_bytes)

    with Session() as s:
        order = Order(job_id=job_id or f"job-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
        s.add(order)
        s.commit()

        for r in rows:
            item = Item(
                order_id=order.id,
                type=r["type"],
                style=r["style"],
                qty=r["qty"],
                width_in=r["width_in"],
                height_in=r["height_in"],
                note=r["note"],
                source_page=r["source_page"],
            )
            s.add(item)
        s.commit()

    return RedirectResponse(url=f"/orders/{order.id}", status_code=303)

@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(request: Request, order_id: int):
    with Session() as s:
        order = s.query(Order).get(order_id)
        if not order:
            return HTMLResponse("Order not found", status_code=404)
    return templates.TemplateResponse("order_detail.html", {"request": request, "order": order})

@app.get("/orders/{order_id}/settings", response_class=HTMLResponse)
def order_settings_get(request: Request, order_id: int):
    with Session() as s:
        order = s.query(Order).get(order_id)
        if not order:
            return HTMLResponse("Order not found", status_code=404)
        settings = order.settings or OrderSettings(order_id=order.id)
        if not order.settings:
            s.add(settings)
            s.commit()
    return templates.TemplateResponse("settings.html", {"request": request, "order": order, "settings": settings})

@app.post("/orders/{order_id}/settings")
async def order_settings_post(
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
    hinge_top_offset: int = Form(3),
    hinge_bottom_offset: int = Form(3),
    hinge_size: int = Form(5),
):
    with Session() as s:
        order = s.query(Order).get(order_id)
        if not order:
            return HTMLResponse("Order not found", status_code=404)

        if not order.settings:
            settings = OrderSettings(order_id=order.id)
            s.add(settings)
        else:
            settings = order.settings

        settings.dealer_code = dealer_code
        settings.job_name = job_name
        settings.finish = finish
        settings.door_sfp_code = door_sfp_code
        settings.door_flat_code = door_flat_code
        settings.drawer_sfp_code = drawer_sfp_code
        settings.drawer_flat_code = drawer_flat_code
        settings.panel_code = panel_code
        settings.hinge_top_offset = hinge_top_offset
        settings.hinge_bottom_offset = hinge_bottom_offset
        settings.hinge_size = hinge_size

        s.commit()

    return RedirectResponse(url=f"/orders/{order_id}/settings", status_code=303)