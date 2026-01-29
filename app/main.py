from fastapi import FastAPI, HTTPException, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
import sqlite3
from datetime import datetime
import pandas as pd
import os

DB_NAME = os.getenv("DATABASE_URL", "roperia.db")
app = FastAPI()
templates = Jinja2Templates(directory="templates")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Tabla de Movimientos
    c.execute('''CREATE TABLE IF NOT EXISTS movimientos 
                 (id INTEGER PRIMARY KEY, piso INTEGER, item TEXT, 
                  cantidad INTEGER, fecha TIMESTAMP, tipo TEXT, estado TEXT)''')
    # Tabla de Inventario Central
    c.execute('''CREATE TABLE IF NOT EXISTS inventario 
                 (item TEXT PRIMARY KEY, estado_manual INTEGER DEFAULT 1)''')
    # Tabla de Stock por Piso (Estimado)
    c.execute('''CREATE TABLE IF NOT EXISTS stock_piso 
                 (piso INTEGER, item TEXT, cantidad INTEGER, last_update TIMESTAMP, 
                  PRIMARY KEY (piso, item))''')
    # TABLA CLAVE: Registro de actualizaciones para ALERTAS
    c.execute('''CREATE TABLE IF NOT EXISTS actualizaciones 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, piso INTEGER, item TEXT)''')
    
    items = ["Toalla Corporal", "Toalla Manos", "Toalla Facial", "Tapete", "Sabana King", "Sabana Matrimonial", "Inserto Grande", "Inserto Chico", "Funda"]
    for i in items:
        c.execute("INSERT OR IGNORE INTO inventario (item, estado_manual) VALUES (?, 1)", (i,))
        for p in range(3, 12):
            c.execute("INSERT OR IGNORE INTO stock_piso (piso, item, cantidad, last_update) VALUES (?, ?, 0, ?)", (p, i, datetime.now()))
    conn.commit()
    conn.close()

init_db()

# Modelos para JSON
class ItemPedido(BaseModel):
    item: str
    cantidad: int
class PedidoBatch(BaseModel):
    piso: int
    items: List[ItemPedido]

# --- RUTAS DE ALERTAS ---
@app.get("/check_updates")
def check_updates(last_id: int = 0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT MAX(id) FROM actualizaciones")
    max_id = c.fetchone()[0] or 0
    updates = []
    if max_id > last_id:
        c.execute("SELECT id, tipo, piso, item FROM actualizaciones WHERE id > ?", (last_id,))
        rows = c.fetchall()
        for r in rows:
            updates.append({"id": r[0], "tipo": r[1], "piso": r[2], "item": r[3]})
    conn.close()
    return {"max_id": max_id, "updates": updates}

# --- RUTAS CAMARISTAS ---
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT item, estado_manual FROM inventario", conn)
    conn.close()
    return templates.TemplateResponse("index.html", {"request": request, "inventario": dict(zip(df.item, df.estado_manual))})

@app.get("/piso/{piso_id}/datos")
def get_datos_piso(piso_id: int):
    conn = sqlite3.connect(DB_NAME)
    stock = pd.read_sql_query(f"SELECT item, cantidad, last_update FROM stock_piso WHERE piso={piso_id}", conn).to_dict('records')
    last_up = pd.to_datetime(stock[0]['last_update']).strftime('%H:%M %d/%m') if stock else "--"
    hist = pd.read_sql_query(f"SELECT item, cantidad, fecha, tipo, estado FROM movimientos WHERE piso={piso_id} ORDER BY fecha DESC LIMIT 15", conn)
    if not hist.empty:
        hist['fecha_fmt'] = pd.to_datetime(hist['fecha']).dt.strftime('%H:%M')
    conn.close()
    return {"stock": stock, "ultima_recarga": last_up, "historial": hist.to_dict('records')}

@app.post("/pedir_varios")
async def pedir_varios(pedido: PedidoBatch):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    for it in pedido.items:
        c.execute("INSERT INTO movimientos (piso, item, cantidad, fecha, tipo, estado) VALUES (?, ?, ?, ?, 'PEDIDO', 'PENDIENTE')",
                  (pedido.piso, it.item, it.cantidad, datetime.now()))
        # Notificar al Admin
        c.execute("INSERT INTO actualizaciones (tipo, piso, item) VALUES ('PEDIDO', ?, ?)", (pedido.piso, it.item))
    conn.commit()
    conn.close()
    return {"status": "ok"}

# --- RUTAS ADMIN ---
@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    conn = sqlite3.connect(DB_NAME)
    pendientes = pd.read_sql_query("SELECT piso, item, SUM(cantidad) as total FROM movimientos WHERE estado='PENDIENTE' GROUP BY piso, item", conn)
    totales = pd.read_sql_query("SELECT item, SUM(cantidad) as total FROM movimientos WHERE estado='PENDIENTE' GROUP BY item", conn)
    inv = pd.read_sql_query("SELECT item, estado_manual FROM inventario", conn)
    
    pisos_dict = {}
    for p in pendientes['piso'].unique():
        pisos_dict[p] = pendientes[pendientes['piso'] == p].to_dict('records')
    
    conn.close()
    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "pisos_pendientes": pisos_dict, 
        "totales": totales.to_dict('records'),
        "inventario": inv.to_dict('records')
    })

@app.post("/admin/surtir_stock")
def surtir_stock(piso: str = Form(...)):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    ahora = datetime.now()
    
    # Marcar como surtido en movimientos
    if piso == "TODOS":
        c.execute("UPDATE movimientos SET estado='SURTIDO' WHERE estado='PENDIENTE'")
        for p in range(3, 12):
            c.execute("UPDATE stock_piso SET cantidad=5, last_update=? WHERE piso=?", (ahora, p))
            c.execute("INSERT INTO actualizaciones (tipo, piso) VALUES ('SURTIDO', ?)", (p,))
    else:
        c.execute("UPDATE movimientos SET estado='SURTIDO' WHERE piso=? AND estado='PENDIENTE'", (piso,))
        c.execute("UPDATE stock_piso SET cantidad=5, last_update=? WHERE piso=?", (ahora, piso))
        c.execute("INSERT INTO actualizaciones (tipo, piso) VALUES ('SURTIDO', ?)", (piso,))
        
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/limpiar")
def limpiar_todo():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE movimientos SET estado='SURTIDO' WHERE estado='PENDIENTE'")
    c.execute("INSERT INTO actualizaciones (tipo) VALUES ('LIMPIAR')")
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/set_status")
def set_status(item: str = Form(...), estado: int = Form(...)):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE inventario SET estado_manual=? WHERE item=?", (estado, item))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)