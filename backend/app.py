"""ABC Dim Sum Restaurant - POS REST API.

Run:
    python app.py          # serves the API *and* the frontend on http://127.0.0.1:5000

Endpoints
---------
Auth      POST /api/auth/login | POST /api/auth/logout | GET /api/auth/me
Allergens GET  /api/allergens
Menu      GET  /api/menu                        (public, allergen annotated)
          POST /api/menu                        (Manager)
          PUT  /api/menu/<lunch_id>             (Manager)
          DELETE /api/menu/<lunch_id>           (Manager)
Guests    POST /api/guests | GET /api/guests/<id>
Tables    GET  /api/tables
          POST /api/tables                      (Manager)
          PUT  /api/tables/<table_id>           (Waiter, Manager)
Orders    POST /api/orders                      (Diner self-order, Waiter, Manager)
          GET  /api/orders[?guest_id=&status=]
          GET  /api/orders/<id>
          POST /api/orders/<id>/pay             (Waiter, Manager)
          POST /api/orders/<id>/cancel          (Waiter, Manager)
Reports   GET  /api/reports/<name>              (Waiter, Manager)  SBA 4.6 SQL
Assistant POST /api/assistant/recommend         (rule engine + optional LLM)
"""
import os

from flask import Flask, jsonify, request, send_from_directory

import allergy
import db
from auth import current_user, issue_token, require_role, revoke_current_token, verify_password

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
db.init_db()  # make sure tables + demo data exist before the first request


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def bad(message, code=400, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), code


def payload():
    return request.get_json(silent=True) or {}


def parse_ids(raw):
    if not raw:
        return []
    return [int(part) for part in str(raw).split(",") if part.strip().isdigit()]


def clean_items(raw):
    """Turn {'L1': '2'} into {'L1': 2}, dropping invalid entries."""
    items = {}
    for lunch_id, quantity in (raw or {}).items():
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            continue
        if quantity > 0:
            items[str(lunch_id)] = quantity
    return items


def order_detail(conn, order_id):
    order = conn.execute("""
        SELECT o.OrderID, o.TableID, o.GuestID, o.Bill, o.Status, o.Created_At,
               g.GuestName
        FROM Order_Form o
        LEFT JOIN Guest g ON g.GuestID = o.GuestID
        WHERE o.OrderID = ?
    """, (order_id,)).fetchone()
    if not order:
        return None

    items = conn.execute("""
        SELECT r.LunchID AS id, m.LunchName AS name, r.Set_Quantity AS quantity,
               m.LunchPrice AS price, ROUND(m.LunchPrice * r.Set_Quantity, 2) AS subtotal
        FROM Order_Record r
        JOIN Menu m ON m.LunchID = r.LunchID
        WHERE r.OrderID = ?
        ORDER BY r.LunchID
    """, (order_id,)).fetchall()

    allergies = conn.execute("""
        SELECT a.AllergenName FROM Guest_Allergy ga
        JOIN Allergen a ON a.AllergenID = ga.AllergenID
        WHERE ga.GuestID = ? ORDER BY a.AllergenName
    """, (order["GuestID"],)).fetchall() if order["GuestID"] else []

    table = conn.execute(
        "SELECT Num_of_Diners FROM Dining_Table WHERE TableID = ?", (order["TableID"],)
    ).fetchone()

    diners = table["Num_of_Diners"] if table else 0
    bill = round(order["Bill"], 2)
    return {
        "id": order["OrderID"],
        "table_id": order["TableID"],
        "guest_id": order["GuestID"],
        "guest_name": order["GuestName"] or "Guest",
        "bill": bill,
        "status": order["Status"],
        "created_at": order["Created_At"],
        "items": [dict(i) for i in items],
        "allergies": [a["AllergenName"] for a in allergies],
        "num_diners": diners,
        "split_bill": round(bill / diners, 2) if diners else None,
    }


def set_dish_allergens(conn, lunch_id, allergens):
    """Replace the allergen links of a dish. Skips when `allergens` is None."""
    if allergens is None:
        return
    conn.execute("DELETE FROM Dish_Allergen WHERE LunchID = ?", (lunch_id,))
    for entry in allergens:
        if isinstance(entry, dict):
            allergen_id, note = entry.get("id"), (entry.get("note") or "").strip()
        else:
            allergen_id, note = entry, ""
        if allergen_id:
            conn.execute(
                "INSERT OR IGNORE INTO Dish_Allergen (LunchID, AllergenID, RiskNote) VALUES (?, ?, ?)",
                (lunch_id, int(allergen_id), note),
            )


def find_dish(conn, lunch_id):
    return next((d for d in allergy.filter_menu(conn, []) if d["id"] == lunch_id), None)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@app.post("/api/auth/login")
def login():
    data = payload()
    conn = db.get_db()
    user = conn.execute(
        "SELECT * FROM Users WHERE Username = ?", (data.get("username", ""),)
    ).fetchone()
    conn.close()
    if not user or not verify_password(user["PasswordHash"], data.get("password", "")):
        return bad("Invalid username or password", 401)
    return jsonify({
        "token": issue_token(user),
        "role": user["Role"],
        "username": user["Username"],
    })


@app.post("/api/auth/logout")
def logout():
    revoke_current_token()
    return jsonify({"status": "logged out"})


@app.get("/api/auth/me")
def me():
    user = current_user()
    return jsonify(user) if user else bad("Not logged in", 401)


# --------------------------------------------------------------------------- #
# Allergens + guest profiles
# --------------------------------------------------------------------------- #
@app.get("/api/allergens")
def get_allergens():
    conn = db.get_db()
    rows = allergy.list_allergens(conn)
    conn.close()
    return jsonify(rows)


@app.post("/api/guests")
def create_guest():
    data = payload()
    name = (data.get("name") or "Guest").strip() or "Guest"
    conn = db.get_db()
    guest_id = conn.execute("INSERT INTO Guest (GuestName) VALUES (?)", (name,)).lastrowid
    for allergen_id in data.get("allergens") or []:
        if str(allergen_id).isdigit():
            conn.execute(
                "INSERT OR IGNORE INTO Guest_Allergy (GuestID, AllergenID) VALUES (?, ?)",
                (guest_id, int(allergen_id)),
            )
    conn.commit()
    names = allergy.allergen_names(conn, allergy.excluded_ids(conn, guest_id))
    conn.close()
    return jsonify({"guest_id": guest_id, "name": name, "allergies": names}), 201


@app.get("/api/guests/<int:guest_id>")
def get_guest(guest_id):
    conn = db.get_db()
    guest = conn.execute("SELECT * FROM Guest WHERE GuestID = ?", (guest_id,)).fetchone()
    if not guest:
        conn.close()
        return bad("Guest not found", 404)
    names = allergy.allergen_names(conn, allergy.excluded_ids(conn, guest_id))
    conn.close()
    return jsonify({
        "guest_id": guest_id,
        "name": guest["GuestName"],
        "allergies": names,
    })


# --------------------------------------------------------------------------- #
# Menu
# --------------------------------------------------------------------------- #
@app.get("/api/menu")
def get_menu():
    conn = db.get_db()
    dishes = allergy.filter_menu(conn, parse_ids(request.args.get("exclude")))
    conn.close()
    return jsonify(dishes)


@app.post("/api/menu")
@require_role("Manager")
def create_menu():
    data = payload()
    lunch_id = (data.get("lunch_id") or "").strip()
    name = (data.get("name") or "").strip()
    try:
        price = float(data.get("price"))
        quota = max(0, int(data.get("quota") or 0))
    except (TypeError, ValueError):
        return bad("price and quota must be numbers")
    if not lunch_id or not name or price <= 0:
        return bad("lunch_id, name and a positive price are required")

    conn = db.get_db()
    if conn.execute("SELECT 1 FROM Menu WHERE LunchID = ?", (lunch_id,)).fetchone():
        conn.close()
        return bad(f"Menu item {lunch_id} already exists", 409)

    conn.execute(
        "INSERT INTO Menu (LunchID, LunchName, LunchPrice, Quota, Ingredients, IsVegetarian)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (lunch_id, name, price, quota, (data.get("ingredients") or "").strip(),
         1 if data.get("is_vegetarian") else 0),
    )
    set_dish_allergens(conn, lunch_id, data.get("allergens"))
    conn.commit()
    dish = find_dish(conn, lunch_id)
    conn.close()
    return jsonify(dish), 201


@app.put("/api/menu/<lunch_id>")
@require_role("Manager")
def update_menu(lunch_id):
    data = payload()
    conn = db.get_db()
    if not conn.execute("SELECT 1 FROM Menu WHERE LunchID = ?", (lunch_id,)).fetchone():
        conn.close()
        return bad("Menu item not found", 404)

    fields, values = [], []
    if "name" in data:
        fields.append("LunchName = ?")
        values.append(str(data["name"]).strip())
    if "price" in data:
        try:
            price = float(data["price"])
        except (TypeError, ValueError):
            conn.close()
            return bad("price must be a number")
        if price <= 0:
            conn.close()
            return bad("price must be positive")
        fields.append("LunchPrice = ?")
        values.append(price)
    if "quota" in data:
        fields.append("Quota = ?")
        values.append(max(0, int(data["quota"])))
    if "ingredients" in data:
        fields.append("Ingredients = ?")
        values.append(str(data["ingredients"]).strip())
    if "is_vegetarian" in data:
        fields.append("IsVegetarian = ?")
        values.append(1 if data["is_vegetarian"] else 0)

    if fields:
        conn.execute(f"UPDATE Menu SET {', '.join(fields)} WHERE LunchID = ?", values + [lunch_id])
    set_dish_allergens(conn, lunch_id, data.get("allergens"))
    conn.commit()
    dish = find_dish(conn, lunch_id)
    conn.close()
    return jsonify(dish)


@app.delete("/api/menu/<lunch_id>")
@require_role("Manager")
def delete_menu(lunch_id):
    conn = db.get_db()
    used = conn.execute(
        "SELECT 1 FROM Order_Record WHERE LunchID = ? LIMIT 1", (lunch_id,)
    ).fetchone()
    if used:
        conn.close()
        return bad("This dish appears in past orders, so it cannot be deleted. "
                   "Set its quota to 0 to stop selling it.", 409)
    conn.execute("DELETE FROM Menu WHERE LunchID = ?", (lunch_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted", "id": lunch_id})


# --------------------------------------------------------------------------- #
# Dining tables
# --------------------------------------------------------------------------- #
@app.get("/api/tables")
def get_tables():
    conn = db.get_db()
    rows = conn.execute("""
        SELECT t.TableID, t.Availability, t.Num_of_Diners, t.Capacity,
               (SELECT COUNT(*) FROM Order_Form o
                 WHERE o.TableID = t.TableID AND o.Status = 'Pending') AS Open_Orders
        FROM Dining_Table t
        ORDER BY t.TableID
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/tables")
@require_role("Manager")
def create_table():
    data = payload()
    table_id = (data.get("table_id") or "").strip().upper()
    try:
        capacity = max(1, int(data.get("capacity") or 4))
    except (TypeError, ValueError):
        return bad("capacity must be a number")
    if not table_id:
        return bad("table_id is required")

    conn = db.get_db()
    if conn.execute("SELECT 1 FROM Dining_Table WHERE TableID = ?", (table_id,)).fetchone():
        conn.close()
        return bad(f"Table {table_id} already exists", 409)
    conn.execute("INSERT INTO Dining_Table (TableID, Capacity) VALUES (?, ?)", (table_id, capacity))
    conn.commit()
    conn.close()
    return jsonify({"table_id": table_id, "capacity": capacity}), 201


@app.put("/api/tables/<table_id>")
@require_role("Waiter", "Manager")
def update_table(table_id):
    data = payload()
    conn = db.get_db()
    table = conn.execute("SELECT * FROM Dining_Table WHERE TableID = ?", (table_id,)).fetchone()
    if not table:
        conn.close()
        return bad("Table not found", 404)

    availability = table["Availability"]
    if "availability" in data:
        availability = 1 if data["availability"] else 0

    diners = table["Num_of_Diners"]
    if "num_of_diners" in data:
        try:
            diners = int(data["num_of_diners"])
        except (TypeError, ValueError):
            conn.close()
            return bad("num_of_diners must be a number")
        if diners < 0:
            conn.close()
            return bad("num_of_diners cannot be negative")
        if diners > table["Capacity"]:
            conn.close()
            return bad(f"Table {table_id} seats at most {table['Capacity']} diners")

    conn.execute(
        "UPDATE Dining_Table SET Availability = ?, Num_of_Diners = ? WHERE TableID = ?",
        (availability, diners, table_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM Dining_Table WHERE TableID = ?", (table_id,)).fetchone()
    conn.close()
    return jsonify(dict(row))


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #
@app.post("/api/orders")
def create_order():
    data = payload()
    table_id = (data.get("table_id") or "").strip()
    items = clean_items(data.get("items"))
    guest_id = data.get("guest_id")
    force = bool(data.get("force"))
    user = current_user()

    if not table_id:
        return bad("table_id is required")
    if not items:
        return bad("Order must contain at least one item")

    conn = db.get_db()
    table = conn.execute("SELECT * FROM Dining_Table WHERE TableID = ?", (table_id,)).fetchone()
    if not table:
        conn.close()
        return bad(f"Unknown table {table_id}", 404)

    # ---- quota check -------------------------------------------------------
    used = db.used_quota(conn)
    problems = []
    for lunch_id, quantity in items.items():
        dish = conn.execute("SELECT * FROM Menu WHERE LunchID = ?", (lunch_id,)).fetchone()
        if not dish:
            conn.close()
            return bad(f"Unknown menu item {lunch_id}", 400)
        remaining = dish["Quota"] - used.get(lunch_id, 0)
        if quantity > remaining:
            problems.append({
                "lunch_id": lunch_id, "name": dish["LunchName"],
                "requested": quantity, "available": max(0, remaining),
            })
    if problems:
        conn.close()
        return bad("Not enough quota for some items", 409, quota=problems)

    # ---- allergy check (authoritative, never trust the browser) ------------
    conflicts, excluded = [], []
    if guest_id:
        excluded = allergy.excluded_ids(conn, guest_id)
        for lunch_id in items:
            hits = allergy.conflicts_for(conn, lunch_id, excluded)
            if hits:
                conflicts.append({
                    "lunch_id": lunch_id,
                    "name": conn.execute(
                        "SELECT LunchName FROM Menu WHERE LunchID = ?", (lunch_id,)
                    ).fetchone()["LunchName"],
                    "allergens": hits,
                })

    staff_override = force and user and user["role"] in ("Waiter", "Manager")
    if conflicts and not staff_override:
        alternatives = allergy.suggest_alternatives(
            conn, excluded, limit=3, avoid={c["lunch_id"] for c in conflicts}
        )
        conn.close()
        return bad("Allergy conflict detected", 409,
                   conflicts=conflicts, alternatives=alternatives)

    # ---- create the order --------------------------------------------------
    bill = 0.0
    for lunch_id, quantity in items.items():
        price = conn.execute(
            "SELECT LunchPrice FROM Menu WHERE LunchID = ?", (lunch_id,)
        ).fetchone()["LunchPrice"]
        bill += price * quantity

    order_id = conn.execute(
        "INSERT INTO Order_Form (TableID, GuestID, Bill, Status) VALUES (?, ?, ?, 'Pending')",
        (table_id, guest_id, round(bill, 2)),
    ).lastrowid
    for lunch_id, quantity in items.items():
        conn.execute(
            "INSERT INTO Order_Record (OrderID, LunchID, Set_Quantity) VALUES (?, ?, ?)",
            (order_id, lunch_id, quantity),
        )

    if "num_diners" in data:
        try:
            diners = max(0, int(data["num_diners"]))
        except (TypeError, ValueError):
            diners = table["Num_of_Diners"]
    else:
        diners = table["Num_of_Diners"]
    conn.execute(
        "UPDATE Dining_Table SET Availability = 0, Num_of_Diners = ? WHERE TableID = ?",
        (diners, table_id),
    )
    conn.commit()

    detail = order_detail(conn, order_id)
    conn.close()
    detail["warnings"] = conflicts
    return jsonify(detail), 201


@app.get("/api/orders")
def list_orders():
    user = current_user()
    guest_id = request.args.get("guest_id")
    status = request.args.get("status")

    conditions, values = [], []
    if guest_id and str(guest_id).isdigit():
        conditions.append("GuestID = ?")
        values.append(int(guest_id))
    elif not user:
        return bad("guest_id is required for guests", 400)
    if status:
        conditions.append("Status = ?")
        values.append(status)

    sql = "SELECT OrderID FROM Order_Form"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY OrderID DESC"

    conn = db.get_db()
    orders = [order_detail(conn, row["OrderID"]) for row in conn.execute(sql, values).fetchall()]
    conn.close()
    return jsonify(orders)


@app.get("/api/orders/<int:order_id>")
def get_order(order_id):
    conn = db.get_db()
    detail = order_detail(conn, order_id)
    conn.close()
    return jsonify(detail) if detail else bad("Order not found", 404)


@app.post("/api/orders/<int:order_id>/pay")
@require_role("Waiter", "Manager")
def pay_order(order_id):
    conn = db.get_db()
    order = conn.execute("SELECT * FROM Order_Form WHERE OrderID = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return bad("Order not found", 404)
    if order["Status"] != "Pending":
        conn.close()
        return bad(f"Order is already {order['Status']}", 409)

    conn.execute("UPDATE Order_Form SET Status = 'Paid' WHERE OrderID = ?", (order_id,))
    # the table becomes free again once the bill is settled
    conn.execute("UPDATE Dining_Table SET Availability = 1 WHERE TableID = ?", (order["TableID"],))
    conn.commit()
    detail = order_detail(conn, order_id)
    conn.close()
    return jsonify(detail)


@app.post("/api/orders/<int:order_id>/cancel")
@require_role("Waiter", "Manager")
def cancel_order(order_id):
    conn = db.get_db()
    order = conn.execute("SELECT * FROM Order_Form WHERE OrderID = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return bad("Order not found", 404)
    if order["Status"] != "Pending":
        conn.close()
        return bad(f"Order is already {order['Status']}", 409)

    conn.execute("UPDATE Order_Form SET Status = 'Cancelled' WHERE OrderID = ?", (order_id,))
    conn.execute("UPDATE Dining_Table SET Availability = 1 WHERE TableID = ?", (order["TableID"],))
    conn.commit()
    detail = order_detail(conn, order_id)
    conn.close()
    return jsonify(detail)


# --------------------------------------------------------------------------- #
# Reports - the SQL commands required by SBA Task 1 (section 4.6)
# --------------------------------------------------------------------------- #
REPORTS = {
    "available-tables": (
        "Number of available dining tables (SBA 4.6 Q1)",
        "SELECT COUNT(*) AS NUMBER_OF_AVAILABLE_TABLE FROM Dining_Table WHERE Availability = 1",
    ),
    "split-bill": (
        "Split the bill equally among diners (SBA 4.6 Q2)",
        """SELECT Dining_Table.TableID,
                  ROUND(Order_Form.Bill / Dining_Table.Num_of_Diners, 2) AS SPLIT_THE_BILL
           FROM Order_Form
           INNER JOIN Dining_Table ON Order_Form.TableID = Dining_Table.TableID
           WHERE Order_Form.Status <> 'Cancelled' AND Dining_Table.Num_of_Diners > 0""",
    ),
    "discount": (
        "Dim sum price after a 10% discount (SBA 4.6 Q3)",
        """SELECT LunchID,
                  ROUND(LunchPrice * 0.9, 2) AS SPECIAL_OFFER_ON_DIM_SUM,
                  LunchName
           FROM Menu""",
    ),
    "quota": (
        "Remaining quota of each lunch set (SBA reference)",
        """SELECT Menu.LunchID,
                  Menu.LunchName,
                  Menu.Quota,
                  Menu.Quota - IFNULL(SUM(CASE WHEN Order_Form.Status <> 'Cancelled'
                                               THEN Order_Record.Set_Quantity ELSE 0 END), 0)
                      AS AVAILABLE_DIM_SUM
           FROM Menu
           LEFT JOIN Order_Record ON Order_Record.LunchID = Menu.LunchID
           LEFT JOIN Order_Form   ON Order_Form.OrderID   = Order_Record.OrderID
           GROUP BY Menu.LunchID, Menu.LunchName, Menu.Quota
           ORDER BY Menu.LunchID""",
    ),
    "sales": (
        "Total sales of paid orders",
        """SELECT IFNULL(ROUND(SUM(Bill), 2), 0) AS TOTAL_SALES,
                  COUNT(*) AS PAID_ORDERS
           FROM Order_Form WHERE Status = 'Paid'""",
    ),
}


@app.get("/api/reports/<name>")
@require_role("Waiter", "Manager")
def run_report(name):
    if name not in REPORTS:
        return bad("Unknown report", 404)
    title, sql = REPORTS[name]
    conn = db.get_db()
    rows = [dict(r) for r in conn.execute(sql).fetchall()]
    conn.close()
    return jsonify({
        "name": name,
        "title": title,
        "sql": " ".join(sql.split()),  # one-line version for display
        "rows": rows,
    })


# --------------------------------------------------------------------------- #
# Allergy assistant (rule engine, optionally upgraded by an LLM)
# --------------------------------------------------------------------------- #
@app.post("/api/assistant/recommend")
def assistant():
    data = payload()
    excluded = parse_ids(",".join(str(i) for i in data.get("exclude") or []))
    guest_id = data.get("guest_id")

    conn = db.get_db()
    if guest_id and str(guest_id).isdigit():
        excluded = sorted(set(excluded) | set(allergy.excluded_ids(conn, int(guest_id))))
    result = allergy.recommend(conn, excluded, data.get("question"))
    conn.close()
    return jsonify(result)


# --------------------------------------------------------------------------- #
# Frontend + entry point
# --------------------------------------------------------------------------- #
@app.route("/favicon.ico")
def favicon():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<text y="80" font-size="80">🥟</text></svg>')
    return app.response_class(svg, mimetype="image/svg+xml")


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
