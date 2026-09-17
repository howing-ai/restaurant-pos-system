"""SQLite access layer: connection, schema creation and demo seed data.

Schema: see schema.sql (HKDSE ICT SBA 3NF design + food-allergy tables).
Run `python db.py` to (re)create and seed the database from scratch.
"""
import os
import sqlite3

from auth import hash_password

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pos.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --------------------------------------------------------------------------- #
# Seed data
# --------------------------------------------------------------------------- #
ALLERGENS = [
    "Seafood", "Shellfish", "Peanuts", "Tree nuts", "Dairy",
    "Egg", "Gluten", "Soy", "Beef", "Sesame",
]

# (LunchID, Name, Price, Quota, Ingredients, IsVegetarian, [(AllergenName, RiskNote)])
MENU = [
    ("L1", "Har Gow (Shrimp Dumpling)", 12.0, 50,
     "Shrimp, wheat starch, bamboo shoot, sesame oil", 0,
     [("Shellfish", "Shrimp"), ("Sesame", "Sesame oil in the filling")]),
    ("L2", "Siu Mai (Pork & Shrimp)", 12.0, 50,
     "Pork, shrimp, mushroom, wheat wrapper, soy sauce", 0,
     [("Shellfish", "Shrimp"), ("Gluten", "Wheat wrapper"), ("Soy", "Soy sauce")]),
    ("L3", "Char Siu Bao (BBQ Pork Bun)", 12.0, 50,
     "Pork, wheat flour, sugar, oyster sauce", 0,
     [("Gluten", "Wheat flour"), ("Shellfish", "Oyster sauce"), ("Soy", "Oyster sauce seasoning")]),
    ("L4", "Vegetable Spring Roll", 10.0, 50,
     "Cabbage, carrot, wheat wrapper, soy oil", 1,
     [("Gluten", "Wheat wrapper"), ("Soy", "Fried in soy oil")]),
    ("L5", "Egg Tart", 9.0, 50,
     "Egg, milk, butter, wheat pastry", 1,
     [("Egg", "Egg custard"), ("Dairy", "Milk & butter"), ("Gluten", "Wheat pastry")]),
    ("L6", "Peanut Glutinous Rice Ball", 11.0, 50,
     "Glutinous rice, peanut, sugar, soy oil", 1,
     [("Peanuts", "Peanut filling"), ("Soy", "Soy oil")]),
    ("L7", "Steamed Beef Ball", 13.0, 50,
     "Beef, coriander, soy sauce", 0,
     [("Beef", "Beef"), ("Soy", "Soy sauce")]),
    ("L8", "Mango Pudding", 8.0, 50,
     "Mango, milk, cream, sugar", 1,
     [("Dairy", "Milk & cream")]),
]

TABLES = [("T1", 2), ("T2", 4), ("T3", 4), ("T4", 6),
          ("T5", 6), ("T6", 8), ("T7", 2), ("T8", 4)]

# (Username, Password, Role)
USERS = [("manager", "manager123", "Manager"),
         ("waiter", "waiter123", "Waiter")]


def _seed(conn):
    if conn.execute("SELECT COUNT(*) AS n FROM Allergen").fetchone()["n"] == 0:
        conn.executemany("INSERT INTO Allergen (AllergenName) VALUES (?)",
                         [(a,) for a in ALLERGENS])

    allergen_id = {
        r["AllergenName"]: r["AllergenID"]
        for r in conn.execute("SELECT AllergenName, AllergenID FROM Allergen")
    }

    if conn.execute("SELECT COUNT(*) AS n FROM Menu").fetchone()["n"] == 0:
        for lunch_id, name, price, quota, ingredients, vegetarian, allergens in MENU:
            conn.execute(
                "INSERT INTO Menu (LunchID, LunchName, LunchPrice, Quota, Ingredients, IsVegetarian)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (lunch_id, name, price, quota, ingredients, vegetarian),
            )
            for allergen_name, note in allergens:
                conn.execute(
                    "INSERT OR IGNORE INTO Dish_Allergen (LunchID, AllergenID, RiskNote) VALUES (?, ?, ?)",
                    (lunch_id, allergen_id[allergen_name], note),
                )

    if conn.execute("SELECT COUNT(*) AS n FROM Dining_Table").fetchone()["n"] == 0:
        conn.executemany("INSERT INTO Dining_Table (TableID, Capacity) VALUES (?, ?)", TABLES)

    if conn.execute("SELECT COUNT(*) AS n FROM Users").fetchone()["n"] == 0:
        conn.executemany(
            "INSERT INTO Users (Username, PasswordHash, Role) VALUES (?, ?, ?)",
            [(u, hash_password(p), r) for u, p, r in USERS],
        )


def init_db():
    """Create every table and insert demo data if the database is empty."""
    conn = get_db()
    try:
        with open(SCHEMA_PATH, encoding="utf-8") as schema_file:
            conn.executescript(schema_file.read())
        _seed(conn)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def used_quota(conn):
    """{LunchID: quantity ordered so far} - cancelled orders are ignored."""
    rows = conn.execute("""
        SELECT r.LunchID AS LunchID, SUM(r.Set_Quantity) AS Used
        FROM Order_Record r
        JOIN Order_Form o ON o.OrderID = r.OrderID
        WHERE o.Status <> 'Cancelled'
        GROUP BY r.LunchID
    """).fetchall()
    return {r["LunchID"]: r["Used"] for r in rows}


def reset_db():
    """Delete the database file so the next init_db() rebuilds it."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


if __name__ == "__main__":
    reset_db()
    init_db()
    print("Rebuilt", DB_PATH)
