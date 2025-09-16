import os
from typing import Optional, Dict, Any, List
import sqlite3

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  type TEXT NOT NULL,            -- Door | Drawer Front | Panel
  style TEXT,
  qty INTEGER NOT NULL DEFAULT 1,
  width_in REAL NOT NULL,
  height_in REAL NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS settings(
  order_id INTEGER PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
  dealer_code TEXT,
  job_name TEXT,
  finish TEXT,
  door_sfp_code TEXT,
  door_flat_code TEXT,
  drawer_sfp_code TEXT,
  drawer_flat_code TEXT,
  panel_code TEXT,
  hinge_top_offset_in REAL,
  hinge_bottom_offset_in REAL,
  hinge_size_in REAL
);
"""

def get_engine(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True) if os.path.dirname(db_path) else None
    return db_path

def ensure_schema(engine: str):
    with sqlite3.connect(engine) as con:
        con.executescript(SCHEMA)

# ---------------- Orders ----------------
def create_order(engine: str, job_id: str) -> int:
    from datetime import datetime
    with sqlite3.connect(engine) as con:
        cur = con.execute("INSERT INTO orders(job_id, created_at) VALUES(?,?)",
                          (job_id, datetime.utcnow().isoformat()+"Z"))
        return cur.lastrowid

def delete_order(engine: str, order_id: int):
    with sqlite3.connect(engine) as con:
        con.execute("DELETE FROM orders WHERE id=?", (order_id,))

def get_order(engine: str, order_id: int) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(engine) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        row = cur.fetchone()
        return dict(row) if row else None

def list_orders(engine: str, q: Optional[str] = None, page: int = 1, page_size: int = 50) -> List[Dict[str, Any]]:
    with sqlite3.connect(engine) as con:
        con.row_factory = sqlite3.Row
        sql = "SELECT * FROM orders"
        params = []
        if q:
            sql += " WHERE job_id LIKE ?"
            params.append(f"%{q}%")
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([page_size, (page-1)*page_size])
        cur = con.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

# ---------------- Items ----------------
def add_item_to_order(engine: str, order_id: int, type: str, style: str, qty: int,
                      width_in: float, height_in: float, note: str):
    with sqlite3.connect(engine) as con:
        con.execute("""
            INSERT INTO items(order_id,type,style,qty,width_in,height_in,note)
            VALUES(?,?,?,?,?,?,?)
        """, (order_id, type, style, qty, width_in, height_in, note))

def list_items_for_order(engine: str, order_id: int) -> List[Dict[str, Any]]:
    with sqlite3.connect(engine) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM items WHERE order_id=? ORDER BY id", (order_id,))
        return [dict(r) for r in cur.fetchall()]

# ---------------- Settings -------------
def get_settings_for_order(engine: str, order_id: int) -> Optional[Dict[str, Any]]:
    with sqlite3.connect(engine) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM settings WHERE order_id=?", (order_id,))
        r = cur.fetchone()
        return dict(r) if r else None

def upsert_settings_for_order(engine: str, order_id: int, payload: Dict[str, Any]):
    keys = [
        "dealer_code","job_name","finish",
        "door_sfp_code","door_flat_code","drawer_sfp_code","drawer_flat_code",
        "panel_code","hinge_top_offset_in","hinge_bottom_offset_in","hinge_size_in"
    ]
    vals = [payload.get(k) for k in keys]
    with sqlite3.connect(engine) as con:
        # upsert
        if get_settings_for_order(engine, order_id):
            con.execute(f"""
              UPDATE settings SET
                dealer_code=?, job_name=?, finish=?,
                door_sfp_code=?, door_flat_code=?, drawer_sfp_code=?, drawer_flat_code=?,
                panel_code=?, hinge_top_offset_in=?, hinge_bottom_offset_in=?, hinge_size_in=?
              WHERE order_id=?""", (*vals, order_id))
        else:
            con.execute(f"""
              INSERT INTO settings(order_id, dealer_code, job_name, finish,
                door_sfp_code, door_flat_code, drawer_sfp_code, drawer_flat_code,
                panel_code, hinge_top_offset_in, hinge_bottom_offset_in, hinge_size_in)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
              (order_id, *vals))