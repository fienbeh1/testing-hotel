from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
import sqlite3
from datetime import datetime, timedelta
import pandas as pd

app = FastAPI()
templates = Jinja2Templates(directory="templates")
DB_NAME = "roperia.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS movimientos 
                 (id INTEGER PRIMARY KEY, piso INTEGER, item TEXT, 
                  cantidad INTEGER, fecha TIMESTAMP, tipo TEXT, estado TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventario 
                 (item TEXT PRIMARY KEY, estado_manual INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS stock_piso 
                 (piso INTEGER, item TEXT, cantidad INTEGER, last_update TIMESTAMP, 
                  PRIMARY KEY (piso, item))''')
    items = ["Toalla Corporal", "Toalla Manos", "Toalla Facial", "Tapete", "Sabana King", "Sabana Matrimonial", "Inserto Grande", "Inserto Chico", "Funda"]
    for i in items:
        c.execute("INSERT OR IGNORE INTO inventario (item, estado_manual) VALUES (?, 1)", (i,))
        for p in range(3, 12):
            c.execute("INSERT OR IGNORE INTO stock_piso (piso, item, cantidad, last_update) VALUES (?, ?, 0, ?)", (p, i, datetime.now()))
    conn.commit()
    conn.close()

init_db()

class ItemPedido(BaseModel):
    item: str
    cantidad: int
class PedidoBatch(BaseModel):
    piso: int
    items: List[ItemPedido]
class ReporteVacio(BaseModel):
    piso: int

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT item, estado_manual FROM inventario", conn)
    conn.close()
    return templates.TemplateResponse("index.html", {"request": request, "inventario": dict(zip(df.item, df.estado_manual))})

@app.get("/piso/{piso_id}/datos")
def get_datos_piso(piso_id: int):
    conn = sqlite3.connect(DB_NAME)
    # Stock Visual
    stock = pd.read_sql_query(f"SELECT item, cantidad, last_update FROM stock_piso WHERE piso={piso_id}", conn).to_dict('records')
    last_up = "Sin datos"
    if stock and stock[0]['last_update']:
        # Formato solicitado: HH:MM DD/MM/YYYY
        last_up = pd.to_datetime(stock[0]['last_update']).strftime('%H:%M %d/%m/%Y')
    
    # Historial completo del piso
    hist = pd.read_sql_query(f"SELECT item, cantidad, fecha, tipo, estado FROM movimientos WHERE piso={piso_id} ORDER BY fecha DESC LIMIT 50", conn)
    if not hist.empty:
        # Formato solicitado: HH:MM DD/MM/YYYY
        hist['fecha_fmt'] = pd.to_datetime(hist['fecha']).dt.strftime('%H:%M %d/%m/%Y')
    else:
        hist['fecha_fmt'] = ""
    
    conn.close()
    return {"stock": stock, "ultima_recarga": last_up, "historial": hist.to_dict('records')}

@app.post("/pedir_varios")
def crear_pedido(batch: PedidoBatch):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    fecha = datetime.now()
    res = []
    for p in batch.items:
        c.execute("SELECT estado_manual FROM inventario WHERE item=?", (p.item,))
        status = c.fetchone()
        if status and status[0]==0:
            conn.close()
            raise HTTPException(status_code=400, detail=f"{p.item} AGOTADO")
        c.execute("INSERT INTO movimientos (piso, item, cantidad, fecha, tipo, estado) VALUES (?, ?, ?, ?, 'PEDIDO', 'PENDIENTE')", (batch.piso, p.item, p.cantidad, fecha))
        res.append(f"{p.cantidad} {p.item}")
    conn.commit()
    conn.close()
    return {"msg":"OK", "resumen":", ".join(res)}

@app.post("/reportar_vacio")
def reportar_vacio_endpoint(data: ReporteVacio):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    ahora = datetime.now()
    c.execute("INSERT INTO movimientos (piso, item, cantidad, fecha, tipo, estado) VALUES (?, 'TODO', 0, ?, 'VACIO', 'ALERT')", (data.piso, ahora))
    c.execute("UPDATE stock_piso SET cantidad=0, last_update=? WHERE piso=?", (ahora, data.piso))
    conn.commit()
    conn.close()
    return {"msg": "OK"}

# --- ADMIN & REPORTES ---
@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    conn = sqlite3.connect(DB_NAME)
    tot = pd.read_sql_query("SELECT item, SUM(cantidad) as total FROM movimientos WHERE tipo='PEDIDO' AND estado='PENDIENTE' GROUP BY item", conn).to_dict('records')
    
    df_pisos = pd.read_sql_query("SELECT piso, item, SUM(cantidad) as total FROM movimientos WHERE tipo='PEDIDO' AND estado='PENDIENTE' GROUP BY piso, item ORDER BY piso DESC", conn)
    pisos_dict = {}
    if not df_pisos.empty:
        for piso, grupo in df_pisos.groupby('piso'):
            pisos_dict[piso] = grupo[['item', 'total']].to_dict('records')

    inv = pd.read_sql_query("SELECT * FROM inventario", conn).to_dict('records')
    conn.close()
    return templates.TemplateResponse("admin.html", {
        "request": request, "totales": tot, "pisos_pendientes": pisos_dict, "inventario": inv
    })

@app.get("/reporte/{tipo}", response_class=HTMLResponse)
def generar_reporte(request: Request, tipo: str):
    conn = sqlite3.connect(DB_NAME)
    now = datetime.now()
    
    if tipo == "hoy":
        fecha = now.strftime('%Y-%m-%d')
        titulo = f"Reporte Diario ({fecha})"
        filtro = f"date(fecha) = '{fecha}'"
    elif tipo == "semana":
        fecha = (now - timedelta(days=7)).strftime('%Y-%m-%d')
        titulo = f"Reporte Semanal (Desde {fecha})"
        filtro = f"date(fecha) >= '{fecha}'"
    elif tipo == "mes":
        fecha = (now - timedelta(days=30)).strftime('%Y-%m-%d')
        titulo = f"Reporte Mensual (Desde {fecha})"
        filtro = f"date(fecha) >= '{fecha}'"

    # Consultas
    q1 = f"SELECT item, SUM(cantidad) as total FROM movimientos WHERE {filtro} AND tipo='PEDIDO' GROUP BY item ORDER BY total DESC"
    q2 = f"SELECT piso, SUM(cantidad) as total FROM movimientos WHERE {filtro} AND tipo='PEDIDO' GROUP BY piso ORDER BY total DESC"
    
    stats = pd.read_sql_query(q1, conn).to_dict('records')
    detalle = pd.read_sql_query(q2, conn).to_dict('records')
    total_piezas = sum(r['total'] for r in stats) if stats else 0
    
    conn.close()
    return templates.TemplateResponse("reporte.html", {"request": request, "titulo": titulo, "stats": stats, "detalle": detalle, "tipo": tipo, "total_piezas": total_piezas})

# --- ACCIONES ADMIN ---
@app.post("/admin/surtir_stock")
def surtir_stock(piso: str = Form(...)):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    ahora = datetime.now()
    targets = range(3, 12) if piso == "TODOS" else [int(piso)]
    
    for p in targets:
        c.execute("UPDATE stock_piso SET cantidad=5, last_update=? WHERE piso=?", (ahora, p))
        c.execute("UPDATE movimientos SET estado='SURTIDO' WHERE piso=? AND tipo='PEDIDO' AND estado='PENDIENTE'", (p,))
    
    # Log solo una vez para evitar spam
    log_piso = 0 if piso == "TODOS" else int(piso)
    log_txt = "SURTIDO HOTEL" if piso == "TODOS" else "SURTIDO PISO"
    c.execute("INSERT INTO movimientos (piso, item, cantidad, fecha, tipo, estado) VALUES (?, ?, 5, ?, 'SURTIDO', 'OK')", (log_piso, log_txt, ahora))

    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/set_status")
async def set_status(item: str = Form(...), estado: int = Form(...)):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE inventario SET estado_manual = ? WHERE item = ?", (estado, item))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/limpiar")
async def limpiar_pedidos():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE movimientos SET estado='ENTREGADO' WHERE estado='PENDIENTE'")
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin", status_code=303)
