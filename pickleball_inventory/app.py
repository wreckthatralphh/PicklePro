"""PicklePro - Pickleball Paddle Inventory, a small Flask + SQLite web app.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:3000 in your browser.
"""

import os
import sqlite3
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = os.environ.get("PADDLE_DB", str(BASE_DIR / "inventory.db"))
LOW_STOCK_THRESHOLD = 5

CORE_MATERIALS = ["Polymer", "Nomex", "Aluminum", "Foam"]
FACE_MATERIALS = ["Carbon Fiber", "Fiberglass", "Graphite", "Kevlar", "Composite"]
GRIP_SIZES = ['4"', '4.125"', '4.25"', '4.375"', '4.5"']

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")

SEED_PADDLES = [
    ("JOOLA", "Ben Johns Hyperion CFS 16", "JOO-HYP-16", 8.0, '4.25"', "Polymer", "Carbon Fiber", "Black", 249.95, 12),
    ("Selkirk", "Vanguard Power Air Invikta", "SEL-VPA-INV", 7.9, '4.25"', "Polymer", "Composite", "Red", 249.99, 4),
    ("CRBN", "CRBN 1X Power Series", "CRB-1X-PWR", 8.0, '4.125"', "Polymer", "Carbon Fiber", "White", 219.99, 9),
    ("Franklin", "Signature Pro", "FRA-SIG-PRO", 7.8, '4.25"', "Polymer", "Fiberglass", "Blue", 89.99, 22),
    ("Paddletek", "Bantam TS-5", "PTK-BAN-TS5", 7.6, '4.25"', "Polymer", "Graphite", "Green", 129.99, 0),
    ("Onix", "Z5 Graphite", "ONX-Z5-GRA", 7.9, '4.375"', "Nomex", "Graphite", "Yellow", 79.99, 3),
    ("Engage", "Pursuit MX 6.0", "ENG-PUR-MX6", 8.1, '4.25"', "Polymer", "Composite", "Orange", 199.99, 7),
    ("Gearbox", "CX14E Ultimate Power", "GBX-CX14E", 8.2, '4"', "Foam", "Carbon Fiber", "Black", 179.99, 15),
]


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = sqlite3.connect(DATABASE)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS paddles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            sku TEXT NOT NULL UNIQUE,
            weight_oz REAL NOT NULL,
            grip_size TEXT NOT NULL,
            core_material TEXT NOT NULL,
            face_material TEXT NOT NULL,
            color TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paddle_id INTEGER,
            brand TEXT NOT NULL,
            model TEXT NOT NULL,
            sku TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_price REAL NOT NULL,
            total REAL NOT NULL,
            customer TEXT NOT NULL DEFAULT '',
            sold_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    if db.execute("SELECT COUNT(*) FROM paddles").fetchone()[0] == 0:
        db.executemany(
            """INSERT INTO paddles
               (brand, model, sku, weight_oz, grip_size, core_material, face_material, color, price, quantity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            SEED_PADDLES,
        )
    db.commit()
    db.close()


def parse_paddle_form(form) -> tuple[dict, list[str]]:
    errors: list[str] = []
    data = {
        "brand": form.get("brand", "").strip(),
        "model": form.get("model", "").strip(),
        "sku": form.get("sku", "").strip().upper(),
        "grip_size": form.get("grip_size", ""),
        "core_material": form.get("core_material", ""),
        "face_material": form.get("face_material", ""),
        "color": form.get("color", "").strip(),
        "weight_oz": form.get("weight_oz", "").strip(),
        "price": form.get("price", "").strip(),
        "quantity": form.get("quantity", "").strip(),
    }

    for field in ("brand", "model", "sku", "color"):
        if not data[field]:
            errors.append(f"{field.capitalize()} is required.")
        elif len(data[field]) > 80:
            errors.append(f"{field.capitalize()} must be 80 characters or fewer.")

    if data["grip_size"] not in GRIP_SIZES:
        errors.append("Choose a valid grip size.")
    if data["core_material"] not in CORE_MATERIALS:
        errors.append("Choose a valid core material.")
    if data["face_material"] not in FACE_MATERIALS:
        errors.append("Choose a valid face material.")

    try:
        data["weight_oz"] = float(data["weight_oz"])
        if not 6.0 <= data["weight_oz"] <= 10.0:
            errors.append("Weight must be between 6.0 and 10.0 oz.")
    except ValueError:
        errors.append("Weight must be a number.")

    try:
        data["price"] = round(float(data["price"]), 2)
        if data["price"] < 0:
            errors.append("Price cannot be negative.")
    except ValueError:
        errors.append("Price must be a number.")

    try:
        data["quantity"] = int(data["quantity"])
        if data["quantity"] < 0:
            errors.append("Quantity cannot be negative.")
    except ValueError:
        errors.append("Quantity must be a whole number.")

    return data, errors


def get_paddle_or_404(paddle_id: int) -> sqlite3.Row:
    paddle = get_db().execute("SELECT * FROM paddles WHERE id = ?", (paddle_id,)).fetchone()
    if paddle is None:
        abort(404)
    return paddle


def form_context(**extra):
    return {
        "grip_sizes": GRIP_SIZES,
        "core_materials": CORE_MATERIALS,
        "face_materials": FACE_MATERIALS,
        **extra,
    }


@app.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    brand = request.args.get("brand", "")
    stock = request.args.get("stock", "")
    sort = request.args.get("sort", "brand")

    sort_columns = {
        "brand": "brand, model",
        "price_asc": "price ASC",
        "price_desc": "price DESC",
        "qty_asc": "quantity ASC",
        "qty_desc": "quantity DESC",
        "weight": "weight_oz ASC",
    }
    order_by = sort_columns.get(sort, sort_columns["brand"])

    clauses, params = [], []
    if q:
        clauses.append("(brand LIKE ? OR model LIKE ? OR sku LIKE ? OR color LIKE ?)")
        params.extend([f"%{q}%"] * 4)
    if brand:
        clauses.append("brand = ?")
        params.append(brand)
    if stock == "low":
        clauses.append("quantity > 0 AND quantity <= ?")
        params.append(LOW_STOCK_THRESHOLD)
    elif stock == "out":
        clauses.append("quantity = 0")
    elif stock == "in":
        clauses.append("quantity > ?")
        params.append(LOW_STOCK_THRESHOLD)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    paddles = db.execute(f"SELECT * FROM paddles {where} ORDER BY {order_by}", params).fetchall()

    stats = db.execute(
        """SELECT COUNT(*) AS models,
                  COALESCE(SUM(quantity), 0) AS units,
                  COALESCE(SUM(quantity * price), 0) AS value,
                  COALESCE(SUM(CASE WHEN quantity <= ? THEN 1 ELSE 0 END), 0) AS low
           FROM paddles""",
        (LOW_STOCK_THRESHOLD,),
    ).fetchone()
    brands = [r["brand"] for r in db.execute("SELECT DISTINCT brand FROM paddles ORDER BY brand")]
    sales_stats = get_sales_stats(db)

    return render_template(
        "index.html",
        paddles=paddles,
        stats=stats,
        sales_stats=sales_stats,
        brands=brands,
        filters={"q": q, "brand": brand, "stock": stock, "sort": sort},
        low_threshold=LOW_STOCK_THRESHOLD,
    )


@app.route("/paddles/new", methods=["GET", "POST"])
def create_paddle():
    if request.method == "POST":
        data, errors = parse_paddle_form(request.form)
        if not errors:
            try:
                get_db().execute(
                    """INSERT INTO paddles
                       (brand, model, sku, weight_oz, grip_size, core_material, face_material, color, price, quantity)
                       VALUES (:brand, :model, :sku, :weight_oz, :grip_size, :core_material, :face_material, :color, :price, :quantity)""",
                    data,
                )
                get_db().commit()
                flash(f"Added {data['brand']} {data['model']}.", "success")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                errors.append(f"SKU {data['sku']} already exists.")
        return render_template("form.html", **form_context(paddle=data, errors=errors, mode="new")), 400
    return render_template("form.html", **form_context(paddle={}, errors=[], mode="new"))


@app.route("/paddles/<int:paddle_id>/edit", methods=["GET", "POST"])
def edit_paddle(paddle_id: int):
    paddle = get_paddle_or_404(paddle_id)
    if request.method == "POST":
        data, errors = parse_paddle_form(request.form)
        if not errors:
            try:
                get_db().execute(
                    """UPDATE paddles SET brand=:brand, model=:model, sku=:sku, weight_oz=:weight_oz,
                       grip_size=:grip_size, core_material=:core_material, face_material=:face_material,
                       color=:color, price=:price, quantity=:quantity WHERE id=:id""",
                    {**data, "id": paddle_id},
                )
                get_db().commit()
                flash(f"Updated {data['brand']} {data['model']}.", "success")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                errors.append(f"SKU {data['sku']} already exists.")
        data["id"] = paddle_id
        return render_template("form.html", **form_context(paddle=data, errors=errors, mode="edit")), 400
    return render_template("form.html", **form_context(paddle=dict(paddle), errors=[], mode="edit"))


@app.post("/paddles/<int:paddle_id>/adjust")
def adjust_stock(paddle_id: int):
    paddle = get_paddle_or_404(paddle_id)
    try:
        delta = int(request.form.get("delta", "0"))
    except ValueError:
        delta = 0
    new_qty = max(0, paddle["quantity"] + delta)
    get_db().execute("UPDATE paddles SET quantity = ? WHERE id = ?", (new_qty, paddle_id))
    get_db().commit()
    return redirect(request.referrer or url_for("index"))


@app.post("/paddles/<int:paddle_id>/delete")
def delete_paddle(paddle_id: int):
    paddle = get_paddle_or_404(paddle_id)
    get_db().execute("UPDATE sales SET paddle_id = NULL WHERE paddle_id = ?", (paddle_id,))
    get_db().execute("DELETE FROM paddles WHERE id = ?", (paddle_id,))
    get_db().commit()
    flash(f"Deleted {paddle['brand']} {paddle['model']}.", "info")
    return redirect(url_for("index"))


MAX_SALE_QUANTITY = 500


def get_sales_stats(db: sqlite3.Connection) -> sqlite3.Row:
    return db.execute(
        """SELECT COUNT(*) AS transactions,
                  COALESCE(SUM(quantity), 0) AS units,
                  COALESCE(SUM(total), 0) AS revenue
           FROM sales"""
    ).fetchone()


@app.route("/sales", methods=["GET", "POST"])
def sales():
    db = get_db()
    errors: list[str] = []
    form = {"paddle_id": request.args.get("paddle", ""), "quantity": "1", "customer": ""}

    if request.method == "POST":
        form = {
            "paddle_id": request.form.get("paddle_id", ""),
            "quantity": request.form.get("quantity", "").strip(),
            "customer": request.form.get("customer", "").strip(),
        }
        paddle = None
        try:
            paddle = db.execute("SELECT * FROM paddles WHERE id = ?", (int(form["paddle_id"]),)).fetchone()
        except ValueError:
            pass
        if paddle is None:
            errors.append("Choose a paddle to sell.")

        try:
            qty = int(form["quantity"])
            if qty <= 0:
                errors.append("Quantity must be at least 1.")
            elif qty > MAX_SALE_QUANTITY:
                errors.append(f"Quantity cannot exceed {MAX_SALE_QUANTITY} per sale.")
        except ValueError:
            qty = 0
            errors.append("Quantity must be a whole number.")

        if len(form["customer"]) > 80:
            errors.append("Customer name must be 80 characters or fewer.")

        if not errors:
            updated = db.execute(
                "UPDATE paddles SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
                (qty, paddle["id"], qty),
            )
            if updated.rowcount == 0:
                errors.append(f"Only {paddle['quantity']} {paddle['model']} left in stock.")
            else:
                unit_price = paddle["price"]
                db.execute(
                    """INSERT INTO sales (paddle_id, brand, model, sku, quantity, unit_price, total, customer)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (paddle["id"], paddle["brand"], paddle["model"], paddle["sku"], qty,
                     unit_price, round(unit_price * qty, 2), form["customer"]),
                )
                db.commit()
                flash(f"Sold {qty} × {paddle['brand']} {paddle['model']} for {money(unit_price * qty)}.", "success")
                return redirect(url_for("sales"))

    paddles = db.execute("SELECT * FROM paddles ORDER BY brand, model").fetchall()
    top_sellers = db.execute(
        """SELECT brand, model, sku, SUM(quantity) AS units, SUM(total) AS revenue, COUNT(*) AS orders
           FROM sales GROUP BY sku, brand, model ORDER BY units DESC, revenue DESC"""
    ).fetchall()
    recent = db.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 50").fetchall()

    return render_template(
        "sales.html",
        paddles=paddles,
        stats=get_sales_stats(db),
        top_sellers=top_sellers,
        recent=recent,
        form=form,
        errors=errors,
        max_qty=MAX_SALE_QUANTITY,
    ), (400 if errors else 200)


@app.post("/sales/<int:sale_id>/void")
def void_sale(sale_id: int):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale is None:
        abort(404)
    if sale["paddle_id"] is not None:
        db.execute("UPDATE paddles SET quantity = quantity + ? WHERE id = ?", (sale["quantity"], sale["paddle_id"]))
    db.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
    db.commit()
    flash(f"Voided sale of {sale['quantity']} × {sale['model']}; stock restored.", "info")
    return redirect(url_for("sales"))


@app.template_filter("money")
def money(value) -> str:
    return f"₱{value:,.2f}"


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    app.run(host="0.0.0.0", port=port, debug=True)
