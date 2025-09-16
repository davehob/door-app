from pathlib import Path
from sqlalchemy import create_engine, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent / "door_orders.db"
engine = create_engine(f"sqlite:///{DB_PATH}", future=True, echo=False)

class Base(DeclarativeBase):
    pass

class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    value: Mapped[str] = mapped_column(Text)

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # per-order metadata
    dealer_code: Mapped[str | None] = mapped_column(String(120), default=None)
    job_name:   Mapped[str | None] = mapped_column(String(200), default=None)
    finish:     Mapped[str | None] = mapped_column(String(120), default=None)

    # per-order style codes
    style_door_sfp:    Mapped[str | None] = mapped_column(String(120), default=None)
    style_door_flat:   Mapped[str | None] = mapped_column(String(120), default=None)
    style_drawer_sfp:  Mapped[str | None] = mapped_column(String(120), default=None)
    style_drawer_flat: Mapped[str | None] = mapped_column(String(120), default=None)
    style_panel_code:  Mapped[str | None] = mapped_column(String(120), default=None)  # one code for all panels

    # door specs
    hinge_top_offset_in:    Mapped[str | None] = mapped_column(String(20), default=None)
    hinge_bottom_offset_in: Mapped[str | None] = mapped_column(String(20), default=None)
    hinge_size_in:          Mapped[str | None] = mapped_column(String(20), default=None)

    items: Mapped[list["Item"]] = relationship(back_populates="order", cascade="all, delete-orphan")

class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    type: Mapped[str] = mapped_column(String(20))     # Door | Drawer Front | Panel
    style: Mapped[str] = mapped_column(String(20))    # SFP | Flat | Panel (for panels)
    qty: Mapped[int] = mapped_column(Integer)
    width_in:  Mapped[str] = mapped_column(String(12))  # 3-dec strings
    height_in: Mapped[str] = mapped_column(String(12))
    note: Mapped[str] = mapped_column(Text)
    source_page: Mapped[int] = mapped_column(Integer)
    hinge: Mapped[str | None] = mapped_column(String(8), default=None)  # 'L' | 'R' | None

    order: Mapped[Order] = relationship(back_populates="items")

def init_db():
    Base.metadata.create_all(engine)
    # keep legacy defaults so old pages work if referenced
    with Session(engine) as s:
        defaults = {
            "decimal_precision": "3",
            "note_joiner": " | ",
            "style_door_sfp": "SFP",
            "style_door_flat": "Flat",
            "style_drawer_sfp": "SFP",
            "style_drawer_flat": "Flat",
        }
        for k, v in defaults.items():
            if not s.query(Setting).filter_by(key=k).first():
                from sqlalchemy.exc import IntegrityError
                try:
                    s.add(Setting(key=k, value=v))
                    s.commit()
                except IntegrityError:
                    s.rollback()