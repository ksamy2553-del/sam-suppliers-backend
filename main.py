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
    
    for col, definition in [
        ("address", "TEXT DEFAULT 'Walk-in'"),
        ("opening_credit", "REAL DEFAULT 0.0"),
        ("discount", "REAL DEFAULT 0.0"),
        ("payment_status", "TEXT DEFAULT 'Cash'"),
        ("delivery_option", "TEXT DEFAULT 'Pick up'"),
        ("sale_date", "TEXT")
    ]:
        try:
            target_table = "sales" if col in ["discount", "payment_status", "delivery_option", "sale_date"] else "customers"
            cursor.execute(f"ALTER TABLE {target_table} ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass
    
    # Seed default Admin worker if table is empty
    cursor.execute("SELECT COUNT(*) FROM workers")
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
    base_unit_name: Optional[str] = "piece"
    pieces_per_box: int
    wholesale_price_per_box: float
    retail_price_per_box: float
    wholesale_price_per_base: float
    retail_price_per_base: float
    boxes_in_stock: int = 0
    pieces_in_stock: int = 0

class RestockRequest(BaseModel):
    boxes_to_add: int = 0
    pieces_to_add: int = 0

class StockUpdateSchema(BaseModel):
    total_base_stock: int

class CustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    address: Optional[str] = "Walk-in"
    opening_credit: Optional[float] = 0.0

class CreditPaymentRequest(BaseModel):
    amount_cleared: float

class ExpenseCreate(BaseModel):
    worker_name: str
    reason: str
    amount: float

class CartItem(BaseModel):
    product_id: int
    unit_type: str
    quantity: int
    price_type: str

class CheckoutRequest(BaseModel):
    customer_id: Optional[int] = None
    items: List[CartItem]
    discount: float = 0.0
    amount_paid: float
    payment_status: str
    delivery_option: str

@app.post("/worker/login")
def worker_login(creds: WorkerLogin, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM workers WHERE phone = ? AND password = ?", (creds.phone, creds.password))
    worker = cursor.fetchone()
    if not worker:
        raise HTTPException(status_code=401, detail="Invalid telephone number or password")
    return {
        "message": "Login successful",
        "worker_name": worker["name"],
        "role": worker["role"]
    }

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
        p_dict["is_low_stock"] = boxes < 2
        p_dict["box_pricing"] = {
            "retail_price_per_box": p_dict["retail_price_per_box"],
            "wholesale_price_per_box": p_dict["wholesale_price_per_box"]
        }
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

@app.post("/products/{product_id}/restock")
def restock_product(product_id: int, restock: RestockRequest, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    pieces_per_box = product["pieces_per_box"]
    current_stock = product["total_base_stock"]
    added_base = (restock.boxes_to_add * pieces_per_box) + restock.pieces_to_add
    
    cursor.execute("UPDATE products SET total_base_stock = ? WHERE id = ?", (current_stock + added_base, product_id))
    db.commit()
    return {"message": "Stock updated successfully"}

@app.get("/customers")
def get_customers(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        SELECT c.*, 
        COALESCE((SELECT SUM(s.total_price - s.discount - s.amount_paid) FROM sales s WHERE s.customer_id = c.id), 0.0) as sales_credit
        FROM customers c
    """)
    rows = cursor.fetchall()
    customers = []
    for r in rows:
        d = dict(r)
        d["total_credit_owed"] = d.get("opening_credit", 0.0) + d.get("sales_credit", 0.0)
        customers.append(d)
    return customers

@app.post("/customers")
def create_customer(cust: CustomerCreate, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO customers (name, phone, address, opening_credit) VALUES (?, ?, ?, ?)",
        (cust.name, cust.phone, cust.address, cust.opening_credit or 0.0)
    )
    db.commit()
    return {"message": "Customer created successfully"}

@app.post("/customers/{customer_id}/clear-credit")
def clear_customer_credit(customer_id: int, payload: CreditPaymentRequest, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    cust = cursor.fetchone()
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    opening = cust["opening_credit"]
    if opening >= payload.amount_cleared:
        new_opening = opening - payload.amount_cleared
        cursor.execute("UPDATE customers SET opening_credit = ? WHERE id = ?", (new_opening, customer_id))
    else:
        remainder = payload.amount_cleared - opening
        cursor.execute("UPDATE customers SET opening_credit = 0.0 WHERE id = ?", (customer_id,))
        cursor.execute("SELECT * FROM sales WHERE customer_id = ? ORDER BY id ASC", (customer_id,))
        sales_rows = cursor.fetchall()
        for s in sales_rows:
            due = (s["total_price"] - s["discount"]) - s["amount_paid"]
            if due > 0 and remainder > 0:
                pay_add = min(due, remainder)
                new_paid = s["amount_paid"] + pay_add
                cursor.execute("UPDATE sales SET amount_paid = ? WHERE id = ?", (new_paid, s["id"]))
                remainder -= pay_add
    db.commit()
    return {"message": "Credit payment recorded successfully"}

@app.post("/checkout")
def process_checkout(checkout: CheckoutRequest, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    sale_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    computed_subtotal = 0.0
    item_details = []
    
    for item in checkout.items:
        cursor.execute("SELECT * FROM products WHERE id = ?", (item.product_id,))
        product = cursor.fetchone()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product ID {item.product_id} not found")
        
        pieces_per_box = product["pieces_per_box"]
        if item.unit_type == "box":
            qty_in_base = item.quantity * pieces_per_box
            unit_price = product["wholesale_price_per_box"] if item.price_type == "wholesale" else product["retail_price_per_box"]
        else:
            qty_in_base = item.quantity
            unit_price = product["wholesale_price_per_base"] if item.price_type == "wholesale" else product["retail_price_per_base"]
            
        if product["total_base_stock"] < qty_in_base:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {product['name']}!")
            
        line_total = unit_price * item.quantity
        computed_subtotal += line_total
        item_details.append({
            "product_id": item.product_id,
            "unit_type": item.unit_type,
            "quantity": item.quantity,
            "price_type": item.price_type,
            "line_total": line_total,
            "qty_in_base": qty_in_base
        })

    final_total = max(0.0, computed_subtotal - checkout.discount)
    
    for detail in item_details:
        cursor.execute("SELECT total_base_stock FROM products WHERE id = ?", (detail["product_id"],))
        curr_stock = cursor.fetchone()["total_base_stock"]
        new_stock = curr_stock - detail["qty_in_base"]
        cursor.execute("UPDATE products SET total_base_stock = ? WHERE id = ?", (new_stock, detail["product_id"]))
        
        item_proportion = detail["line_total"] / computed_subtotal if computed_subtotal > 0 else 0
        item_paid = checkout.amount_paid * item_proportion
        item_disc = checkout.discount * item_proportion
        
        cursor.execute("""
            INSERT INTO sales (product_id, unit_sold, quantity_sold, price_type, total_price, discount, amount_paid, payment_status, delivery_option, customer_id, sale_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            detail["product_id"], detail["unit_type"], detail["quantity"], detail["price_type"],
            detail["line_total"], item_disc, item_paid, checkout.payment_status, checkout.delivery_option,
            checkout.customer_id, sale_timestamp
        ))
        
    db.commit()
    return {"message": "Checkout completed successfully", "total_price": final_total}

@app.get("/sales")
def get_sales(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        SELECT s.*, p.name as product_name, c.name as customer_name, c.address as customer_address, c.phone as customer_phone
        FROM sales s
        LEFT JOIN products p ON s.product_id = p.id
        LEFT JOIN customers c ON s.customer_id = c.id
        ORDER BY s.id DESC
    """)
    rows = cursor.fetchall()
    
    sales_list = []
    for r in rows:
        d = dict(r)
        if not d.get("customer_name"):
            d["customer_name"] = "Walk-in Customer"
        if not d.get("customer_address"):
            d["customer_address"] = "Walk-in"
        if not d.get("sale_date"):
            d["sale_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        sales_list.append(d)
    return sales_list

@app.delete("/sales/{sale_id}")
def delete_sale(sale_id: int, role: str = "Staff", db: sqlite3.Connection = Depends(get_db)):
    if role != "Admin":
        raise HTTPException(status_code=403, detail="Unauthorized: Only admin can delete orders.")
        
    cursor = db.cursor()
    cursor.execute("SELECT * FROM sales WHERE id = ?", (sale_id,))
    sale = cursor.fetchone()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
        
    product_id = sale["product_id"]
    unit_sold = sale["unit_sold"]
    qty_sold = sale["quantity_sold"]
    
    cursor.execute("SELECT pieces_per_box, total_base_stock FROM products WHERE id = ?", (product_id,))
    prod = cursor.fetchone()
    if prod:
        pieces_per_box = prod["pieces_per_box"]
        current_stock = prod["total_base_stock"]
        revert_qty = (qty_sold * pieces_per_box) if unit_sold == "box" else qty_sold
        cursor.execute("UPDATE products SET total_base_stock = ? WHERE id = ?", (current_stock + revert_qty, product_id))
        
    cursor.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
    db.commit()
    return {"message": "Sale deleted and stock restored"}

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

@app.get("/dashboard")
def get_dashboard(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT SUM(total_price - discount) FROM sales")
    total_sales_res = cursor.fetchone()[0]
    todays_sales = total_sales_res if total_sales_res else 0.0
    
    cursor.execute("SELECT SUM((total_price - discount) - amount_paid) FROM sales")
    sales_credit_res = cursor.fetchone()[0]
    sales_credit = sales_credit_res if sales_credit_res else 0.0
    
    cursor.execute("SELECT SUM(opening_credit) FROM customers")
    opening_credit_res = cursor.fetchone()[0]
    opening_credit = opening_credit_res if opening_credit_res else 0.0
    
    cursor.execute("SELECT SUM(amount) FROM expenses")
    expenses_res = cursor.fetchone()[0]
    total_expenses = expenses_res if expenses_res else 0.0
    
    return {
        "todays_sales": todays_sales,
        "credit_owed_by_customers": sales_credit + opening_credit,
        "total_expenses": total_expenses
    }