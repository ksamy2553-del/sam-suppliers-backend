from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
from datetime import datetime

app = FastAPI(title="SAM SUPPLIERS POS API")

DB_FILE = "shop.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            pieces_per_box INTEGER NOT NULL,
            total_base_stock INTEGER NOT NULL,
            retail_price_per_base REAL NOT NULL,
            wholesale_price_per_base REAL NOT NULL,
            retail_price_per_box REAL NOT NULL,
            wholesale_price_per_box REAL NOT NULL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT DEFAULT 'Walk-in',
            opening_credit REAL DEFAULT 0.0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'Staff'
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            unit_sold TEXT,
            quantity_sold INTEGER,
            price_type TEXT,
            total_price REAL,
            discount REAL DEFAULT 0.0,
            amount_paid REAL,
            payment_status TEXT DEFAULT 'Cash',
            delivery_option TEXT DEFAULT 'Pick up',
            customer_id INTEGER,
            sale_date TEXT,
            FOREIGN KEY(product_id) REFERENCES products(id),
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_date TEXT,
            worker_name TEXT NOT NULL,
            reason TEXT NOT NULL,
            amount REAL NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deletion_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT,
            item_identifier TEXT,
            reason TEXT,
            deleted_at TEXT
        )
    """)
    
    # Ensure default admin always exists even if other workers are in the db
    cursor.execute("SELECT COUNT(*) FROM workers WHERE phone = '0700000000'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO workers (name, phone, password, role)
            VALUES (?, ?, ?, ?)
        """, ("System Admin", "0700000000", "admin123", "Admin"))

    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO products (name, pieces_per_box, total_base_stock, retail_price_per_base, wholesale_price_per_base, retail_price_per_box, wholesale_price_per_box)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("Kopiko", 48, 70, 200, 180, 4800, 4500))
        
    conn.commit()
    conn.close()

init_db()

class WorkerLogin(BaseModel):
    phone: str
    password: str

class WorkerCreate(BaseModel):
    name: str
    phone: str
    password: str
    role: str = "Staff"

class ProductCreate(BaseModel):
    name: str
    pieces_per_box: int
    wholesale_price_per_box: float
    retail_price_per_box: float
    wholesale_price_per_base: float
    retail_price_per_base: float
    boxes_in_stock: int = 0
    pieces_in_stock: int = 0

class CustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    address: Optional[str] = "Walk-in"
    opening_credit: Optional[float] = 0.0

class SaleCreate(BaseModel):
    product_id: int
    unit_sold: str
    quantity_sold: int
    price_type: str
    total_price: float
    discount: float = 0.0
    amount_paid: float
    payment_status: str = "Cash"
    delivery_option: str = "Pick up"
    customer_id: Optional[int] = None

class ExpenseCreate(BaseModel):
    worker_name: str
    reason: str
    amount: float

# --- WORKERS ROUTES ---
@app.get("/workers")
def get_workers(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id, name, phone, role FROM workers")
    return [dict(row) for row in cursor.fetchall()]

@app.post("/workers")
def create_worker(worker: WorkerCreate, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO workers (name, phone, password, role) VALUES (?, ?, ?, ?)",
            (worker.name, worker.phone, worker.password, worker.role)
        )
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Worker with this phone number already exists.")
    return {"message": "Worker created successfully"}

@app.post("/workers/login")
def login_worker(cred: WorkerLogin, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM workers WHERE phone = ? AND password = ?", (cred.phone, cred.password))
    worker = cursor.fetchone()
    if not worker:
        raise HTTPException(status_code=401, detail="Invalid phone number or password")
    return dict(worker)

# --- PRODUCTS ROUTES ---
@app.get("/products")
def get_products(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM products")
    rows = cursor.fetchall()
    products = []
    for r in rows:
        p_dict = dict(r)
        boxes = p_dict["total_base_stock"] // p_dict["pieces_per_box"]
        pieces = p_dict["total_base_stock"] % p_dict["pieces_per_box"]
        p_dict["stock_display"] = f"{boxes} Box(es), {pieces} Piece(s)"
        products.append(p_dict)
    return products

@app.post("/products")
def create_product(prod: ProductCreate, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    total_base_stock = (prod.boxes_in_stock * prod.pieces_per_box) + prod.pieces_in_stock
    cursor.execute("""
        INSERT INTO products (name, pieces_per_box, total_base_stock, retail_price_per_base, wholesale_price_per_base, retail_price_per_box, wholesale_price_per_box)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        prod.name, prod.pieces_per_box, total_base_stock,
        prod.retail_price_per_base, prod.wholesale_price_per_base,
        prod.retail_price_per_box, prod.wholesale_price_per_box
    ))
    db.commit()
    return {"message": "Product created successfully"}

@app.delete("/products/{product_id}")
def delete_product(product_id: int, reason: str = "No reason provided", db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    prod = cursor.fetchone()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    
    deleted_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        "INSERT INTO deletion_logs (item_type, item_identifier, reason, deleted_at) VALUES (?, ?, ?, ?)",
        ("Product", prod["name"], reason, deleted_at)
    )
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    return {"message": "Product deleted successfully"}

# --- CUSTOMERS ROUTES ---
@app.get("/customers")
def get_customers(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM customers")
    return [dict(row) for row in cursor.fetchall()]

@app.post("/customers")
def create_customer(cust: CustomerCreate, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO customers (name, phone, address, opening_credit) VALUES (?, ?, ?, ?)",
        (cust.name, cust.phone, cust.address, cust.opening_credit or 0.0)
    )
    db.commit()
    return {"message": "Customer created successfully"}

@app.delete("/customers/{customer_id}")
def delete_customer(customer_id: int, reason: str = "No reason provided", db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    cust = cursor.fetchone()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    deleted_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        "INSERT INTO deletion_logs (item_type, item_identifier, reason, deleted_at) VALUES (?, ?, ?, ?)",
        ("Customer", cust["name"], reason, deleted_at)
    )
    cursor.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    db.commit()
    return {"message": "Customer deleted successfully"}

# --- SALES ROUTES ---
@app.get("/sales")
def get_sales(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT s.*, p.name as product_name, c.name as customer_name FROM sales s LEFT JOIN products p ON s.product_id = p.id LEFT JOIN customers c ON s.customer_id = c.id ORDER BY s.id DESC")
    return [dict(row) for row in cursor.fetchall()]

@app.post("/sales")
def create_sale(sale: SaleCreate, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    sale_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute("""
        INSERT INTO sales (product_id, unit_sold, quantity_sold, price_type, total_price, discount, amount_paid, payment_status, delivery_option, customer_id, sale_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sale.product_id, sale.unit_sold, sale.quantity_sold, sale.price_type,
        sale.total_price, sale.discount, sale.amount_paid, sale.payment_status,
        sale.delivery_option, sale.customer_id, sale_date
    ))
    db.commit()
    return {"message": "Sale recorded successfully"}

@app.delete("/sales/{sale_id}")
def delete_sale(sale_id: int, reason: str = "No reason provided", db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT s.*, p.name as product_name FROM sales s LEFT JOIN products p ON s.product_id = p.id WHERE s.id = ?", (sale_id,))
    sale = cursor.fetchone()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    deleted_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    item_desc = f"Sale #{sale['id']} ({sale['product_name'] or 'Product'})"
    cursor.execute(
        "INSERT INTO deletion_logs (item_type, item_identifier, reason, deleted_at) VALUES (?, ?, ?, ?)",
        ("Sale", item_desc, reason, deleted_at)
    )
    cursor.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
    db.commit()
    return {"message": "Sale deleted successfully"}

# --- EXPENSES ROUTES ---
@app.get("/expenses")
def get_expenses(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM expenses ORDER BY id DESC")
    return [dict(row) for row in cursor.fetchall()]

@app.post("/expenses")
def create_expense(exp: ExpenseCreate, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    expense_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        "INSERT INTO expenses (expense_date, worker_name, reason, amount) VALUES (?, ?, ?, ?)",
        (expense_date, exp.worker_name, exp.reason, exp.amount)
    )
    db.commit()
    return {"message": "Expense recorded successfully"}

# --- AUDIT LOGS ROUTE ---
@app.get("/audit-logs")
def get_audit_logs(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM deletion_logs ORDER BY id DESC")
    return [dict(row) for row in cursor.fetchall()]
