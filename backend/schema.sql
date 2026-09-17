-- ===========================================================================
-- ABC Dim Sum Restaurant - Point-of-Sale database (SQLite)
--
-- Core schema follows the HKDSE ICT SBA 3NF design:
--   Dining_Table / Order_Form / Order_Record / Menu
-- Food-allergy layer added on top:
--   Allergen / Dish_Allergen / Guest / Guest_Allergy
--
-- Notes on the SBA -> implementation mapping (see process.md):
--   * Order_Form gains an auto-increment OrderID (+ TableID, Status, GuestID).
--     In the SBA the OrderID was re-used as the TableID ('T2'), which could not
--     represent more than one order per table; separating them is the
--     "database design improvement" required by SBA Task 2.
--   * Passwords are stored as hashes, never plain text (data privacy).
-- ===========================================================================

PRAGMA foreign_keys = ON;

-- ------------------------------ Staff users ------------------------------
CREATE TABLE IF NOT EXISTS Users (
    UserID       INTEGER PRIMARY KEY AUTOINCREMENT,
    Username     TEXT    NOT NULL UNIQUE,
    PasswordHash TEXT    NOT NULL,
    Role         TEXT    NOT NULL CHECK (Role IN ('Waiter', 'Manager'))
);

-- ------------------------------ Dining_Table -----------------------------
CREATE TABLE IF NOT EXISTS Dining_Table (
    TableID       TEXT    PRIMARY KEY,
    Availability  INTEGER NOT NULL DEFAULT 1 CHECK (Availability IN (0, 1)),
    Num_of_Diners INTEGER NOT NULL DEFAULT 0 CHECK (Num_of_Diners >= 0),
    Capacity      INTEGER NOT NULL DEFAULT 4 CHECK (Capacity > 0)
);

-- ------------------------------ Menu -------------------------------------
CREATE TABLE IF NOT EXISTS Menu (
    LunchID      TEXT    PRIMARY KEY,
    LunchName    TEXT    NOT NULL,
    LunchPrice   REAL    NOT NULL CHECK (LunchPrice > 0),
    Quota        INTEGER NOT NULL DEFAULT 0 CHECK (Quota >= 0),
    Ingredients  TEXT    NOT NULL DEFAULT '',
    IsVegetarian INTEGER NOT NULL DEFAULT 0 CHECK (IsVegetarian IN (0, 1))
);

-- ------------------------------ Allergen master --------------------------
CREATE TABLE IF NOT EXISTS Allergen (
    AllergenID   INTEGER PRIMARY KEY AUTOINCREMENT,
    AllergenName TEXT    NOT NULL UNIQUE
);

-- ------------------------------ Dish <-> Allergen ------------------------
-- RiskNote records hidden allergens (e.g. allergens inside "sauce" or "oil"),
-- exactly as requested by the food-allergy project.
CREATE TABLE IF NOT EXISTS Dish_Allergen (
    LunchID    TEXT    NOT NULL,
    AllergenID INTEGER NOT NULL,
    RiskNote   TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (LunchID, AllergenID),
    FOREIGN KEY (LunchID)    REFERENCES Menu(LunchID)        ON DELETE CASCADE,
    FOREIGN KEY (AllergenID) REFERENCES Allergen(AllergenID) ON DELETE CASCADE
);

-- ------------------------------ Guest (diner session) --------------------
CREATE TABLE IF NOT EXISTS Guest (
    GuestID    INTEGER PRIMARY KEY AUTOINCREMENT,
    GuestName  TEXT    NOT NULL DEFAULT 'Guest',
    Created_At TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Guest_Allergy (
    GuestID    INTEGER NOT NULL,
    AllergenID INTEGER NOT NULL,
    PRIMARY KEY (GuestID, AllergenID),
    FOREIGN KEY (GuestID)    REFERENCES Guest(GuestID)       ON DELETE CASCADE,
    FOREIGN KEY (AllergenID) REFERENCES Allergen(AllergenID) ON DELETE CASCADE
);

-- ------------------------------ Order_Form -------------------------------
CREATE TABLE IF NOT EXISTS Order_Form (
    OrderID    INTEGER PRIMARY KEY AUTOINCREMENT,
    TableID    TEXT    NOT NULL,
    GuestID    INTEGER,
    Bill       REAL    NOT NULL DEFAULT 0 CHECK (Bill >= 0),
    Status     TEXT    NOT NULL DEFAULT 'Pending'
                       CHECK (Status IN ('Pending', 'Paid', 'Cancelled')),
    Created_At TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (TableID) REFERENCES Dining_Table(TableID),
    FOREIGN KEY (GuestID) REFERENCES Guest(GuestID)
);

-- ------------------------------ Order_Record -----------------------------
CREATE TABLE IF NOT EXISTS Order_Record (
    OrderID      INTEGER NOT NULL,
    LunchID      TEXT    NOT NULL,
    Set_Quantity INTEGER NOT NULL CHECK (Set_Quantity > 0),
    PRIMARY KEY (OrderID, LunchID),
    FOREIGN KEY (OrderID) REFERENCES Order_Form(OrderID) ON DELETE CASCADE,
    FOREIGN KEY (LunchID) REFERENCES Menu(LunchID)
);

CREATE INDEX IF NOT EXISTS idx_order_record_lunch ON Order_Record(LunchID);
CREATE INDEX IF NOT EXISTS idx_order_form_table   ON Order_Form(TableID);

-- ===========================================================================
-- Required "useful information" queries (SBA Task 1, section 4.6 / Reference).
-- They are executed by /api/reports/<name>; the SQL text is also returned to
-- the client so the marker can see the commands in action.
-- ===========================================================================
-- 1) Number of available tables
--    SELECT COUNT(*) AS NUMBER_OF_AVAILABLE_TABLE
--    FROM Dining_Table WHERE Availability = 1;
--
-- 2) Split the bill equally among the diners of a table
--    SELECT Dining_Table.TableID, ROUND(Order_Form.Bill / Dining_Table.Num_of_Diners, 2) AS SPLIT_THE_BILL
--    FROM Order_Form
--    INNER JOIN Dining_Table ON Order_Form.TableID = Dining_Table.TableID
--    WHERE Order_Form.Status <> 'Cancelled' AND Dining_Table.Num_of_Diners > 0;
--
-- 3) Price of every dim sum after a 10% discount (i.e. 90% of the price)
--    SELECT LunchID, ROUND(LunchPrice * 0.9, 2) AS SPECIAL_OFFER_ON_DIM_SUM, LunchName
--    FROM Menu;
--
-- 4) Remaining quota of each lunch set (SBA reference query)
--    SELECT Menu.LunchID, Menu.LunchName, Menu.Quota,
--           Menu.Quota - IFNULL(SUM(CASE WHEN Order_Form.Status <> 'Cancelled'
--                                        THEN Order_Record.Set_Quantity ELSE 0 END), 0) AS AVAILABLE_DIM_SUM
--    FROM Menu
--    LEFT JOIN Order_Record ON Order_Record.LunchID = Menu.LunchID
--    LEFT JOIN Order_Form   ON Order_Form.OrderID   = Order_Record.OrderID
--    GROUP BY Menu.LunchID, Menu.LunchName, Menu.Quota;
