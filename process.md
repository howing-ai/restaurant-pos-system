# Development Process Log — Restaurant POS + Food Allergy Integration

This file records every step taken during development, plus important decisions,
so both you and I can pick the work back up without confusion.

---

## 1. Project understanding

### Sources analysed
1. **`backend/app.py` + `frontend/index.html`** — the existing prototype:
   Flask + SQLite + vanilla JS. Tables `users / menu / orders / order_items`,
   a single admin login, menu CRUD, simple orders and a "pay" button.
2. **`53082085_Li Ho Wing ICT SBA.pdf`** — HKDSE ICT SBA "Point-of-Sale System"
   for **ABC Dim Sum Restaurant**. Key requirements extracted:
   - Users: **Waiter** (order food, check quota, manage tables),
     **Diner** (self-order, view menu), **Manager** (modify price,
     create/delete menu, manage tables).
   - 3NF schema: `Dining_Table(TableID, Availability, Num_of_Diners)`,
     `Order_Form(OrderID, TableID, Bill)`,
     `Order_Record(OrderID, LunchID, Set_Quantity)`,
     `Menu(LunchID, LunchName, LunchPrice, Quota)`.
   - Data integrity: entity / referential / domain integrity (PKs, FKs,
     CHECK, DEFAULT).
   - Access rights per user per table (data privacy).
   - At least 3 useful SQL commands: count available tables, split the bill
     (`Bill / Num_of_Diners`), 90% discount price (`LunchPrice * 0.9`);
     the reference also lists remaining quota (`Quota - SUM(Set_Quantity)`).
   - Task 2: testing, plus "one major change in the database design" or a
     scope extension.
3. **`53082085_Li Ho Wing.pdf`** — the **food allergy project**:
   - Guests select/enter their allergens (e.g. seafood, nuts, dairy).
   - Every dish is labelled with ingredients, **especially potential
     allergens**; "sauce" and "oil" type hidden allergens must be marked.
   - The system filters out dishes containing allergens, and after a dish is
     selected it confirms it meets the allergy requirement — if not, it
     **recommends alternatives** ("AI-powered dish selection").
   - Staff training aspects (EpiPen, labelling) are outside software scope.

### Decisions confirmed with the user (2026-09-17)
| Question | Decision |
|---|---|
| Database | Rebuild to the **SBA 3NF schema + allergy tables** |
| Allergy "AI" | **Rule engine first** (deterministic, offline, safe) + **optional LLM** assistant behind env vars |
| Roles | **Diner / Waiter / Manager** with permissions |
| UI language | **English** |

---

## 2. Architecture

```
restaurant-pos-system/
├── backend/
│   ├── app.py          # Flask REST API + serves the frontend
│   ├── db.py           # SQLite connection, seed data, helpers
│   ├── auth.py         # login tokens, hashed passwords, role guards
│   ├── allergy.py      # allergen rule engine + optional LLM
│   ├── schema.sql      # full CREATE TABLE script + SBA queries documented
│   ├── requirements.txt
│   └── pos.db          # generated SQLite database (git-ignored ideally)
└── frontend/
    ├── index.html      # single page shell
    ├── styles.css      # all styling
    └── app.js          # all logic (views + event delegation)
```

Run with **one command**: `python app.py` → open http://127.0.0.1:5000
(Flask serves the API *and* the frontend, so no CORS pain).

---

## 3. Steps taken (chronological)

1. **Extracted both PDFs** with `pypdf` (temp files deleted afterwards).
2. **Read the existing prototype** code to understand what already worked.
3. **Deleted `backend/pos.db`** — the old DB used tables (`menu`, `orders`,
   `order_items`, `users`) that collide case-insensitively with the new SBA
   tables (`Menu`, …), so a clean rebuild was required. It is regenerated
   automatically with demo data on the first run (or `python db.py`).
4. **`schema.sql`** — created the SBA 3NF tables + allergy layer:
   - SBA: `Dining_Table`, `Order_Form`, `Order_Record`, `Menu`
   - New: `Allergen`, `Dish_Allergen` (with `RiskNote` for hidden allergens
     like oyster sauce / sesame oil), `Guest`, `Guest_Allergy`
   - `Users` is staff-only (`Waiter`/`Manager`); diners are `Guest` sessions
     (kiosk-style self-order, no account needed).
5. **`db.py`** — connection helper (`PRAGMA foreign_keys = ON`), seed data:
   10 allergens, 8 dim-sum dishes (each with realistic allergen links +
   risk notes), tables T1–T8 with capacities, staff accounts
   `manager/manager123`, `waiter/waiter123` (passwords hashed).
   Helper `used_quota()` computes remaining quota excluding cancelled orders.
6. **`auth.py`** — Werkzeug password hashing, random URL-safe tokens
   (in-memory → restart logs everyone out, fine for a prototype),
   `require_role()` decorator for access rights.
7. **`allergy.py`** — the rule engine:
   `filter_menu()` annotates every dish with allergens + safe/unsafe verdict
   against a guest profile; `suggest_alternatives()` ranks safe, in-stock
   dishes by fewest allergens; `recommend()` calls the optional LLM if
   `LLM_API_KEY`/`OPENAI_API_KEY` is set, otherwise falls back to rules
   (via `urllib`, no extra dependency, silent failure → never blocks ordering).
8. **`app.py`** — REST API (see the endpoint table below). Notable behaviour:
   - **Authoritative allergy check on the server**: even if the browser is
     modified, `POST /api/orders` re-validates every dish against the guest
     profile and returns **409 + conflicts + alternatives**; only staff
     (`force`) can override after verbal confirmation.
   - **Quota check** (`Quota - SUM(non-cancelled Set_Quantity)`) → 409.
   - Creating an order seats the table (`Availability=0`); paying/cancelling
     frees it.
   - **Reports** expose the exact SBA SQL, and the SQL text is returned with
     the rows so it can be displayed for marking.
9. **`frontend/`** — single-page app:
   - **Diner flow**: Step 1 pick allergens (chips) → save profile;
     Step 2 pick table + number of diners; Step 3 menu where unsafe dishes
     are visually blocked (red, allergens listed, cannot be added), with a
     "hide unsafe" toggle; cart with running total + split-bill preview;
     "Ask for safe choices" assistant button; "My orders & bills".
   - **Staff app**: tabs Tables (seat/free, set diners), New Order (allergy
     chips for the guest, same guarded menu), Orders (pay / cancel / bill),
     Menu (Manager only: add dish with allergen checkboxes, edit price &
     quota inline, delete), **Reports** (the SBA queries).
   - Conflict modal lists blocked dishes + safe alternatives (Add buttons),
     and offers a staff-only override.
10. **`requirements.txt`** — added `flask-cors` (the old file listed Flask's
    transitive deps but not `flask-cors`, which `app.py` imported).

---

## 4. SBA requirements → where they live

| SBA requirement | Implementation |
|---|---|
| 3NF schema (4 tables) | `schema.sql` — unchanged names/columns |
| Entity integrity | PK on every table |
| Referential integrity | FKs + `PRAGMA foreign_keys = ON` on every connection |
| Domain integrity | `CHECK`/`DEFAULT` constraints (price > 0, quota >= 0, roles, statuses, availability ∈ {0,1}) |
| Data privacy / access rights | `auth.py` + `@require_role(...)` on every write endpoint; guests can only read the menu, create their own order and see their own bills (`?guest_id=` required, no token ⇒ no access to others' orders) |
| SQL command 1 — available tables | `GET /api/reports/available-tables` |
| SQL command 2 — split the bill | `GET /api/reports/split-bill` |
| SQL command 3 — 90% discount | `GET /api/reports/discount` |
| Reference query — remaining quota | `GET /api/reports/quota` (+ used by ordering logic) |
| Task 2 "major design change" | `OrderID` is now an auto-increment key **separate from `TableID`** (the SBA sample data re-used table IDs as order IDs, so a table could never have a second order). Also `Status` + `GuestID` were added to `Order_Form` |
| Task 2 "scope extension" | The food-allergy layer (`Allergen`, `Dish_Allergen`, `Guest`, `Guest_Allergy`) |
| Rollback concept | SQLite transactions: any failed validation aborts before `commit()`, so no partial order is written |

## 5. Food-allergy project → where it lives

| Allergy-project requirement | Implementation |
|---|---|
| Guest selects/enters allergens | Diner Step 1 chips → `Guest` + `Guest_Allergy` |
| Every dish labelled with ingredients | `Menu.Ingredients` shown on every card |
| Hidden allergens (sauce/oil) marked | `Dish_Allergen.RiskNote` (e.g. "Oyster sauce") shown as tooltip on each badge |
| Filter out dishes containing allergens | `allergy.filter_menu()` + disabled cards in UI + server-side 409 |
| Confirm selection meets requirements | Re-checked at `POST /api/orders` |
| Recommend alternatives | `suggest_alternatives()` in the 409 response + conflict modal + assistant |
| "AI-powered" selection | Optional LLM via env vars (`LLM_API_KEY`/`OPENAI_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`); rule engine answers when absent |

---

## 6. API summary

| Method & path | Who | Purpose |
|---|---|---|
| `POST /api/auth/login` `logout` `GET me` | staff | authentication |
| `GET /api/allergens` | public | allergen master list |
| `POST /api/guests`, `GET /api/guests/<id>` | public | guest allergy profiles |
| `GET /api/menu` | public | menu + allergen/safety info |
| `POST/PUT/DELETE /api/menu[/id]` | Manager | menu CRUD (price/quota/ingredients/allergens) |
| `GET /api/tables`, `POST /api/tables` | public / Manager | table list & creation |
| `PUT /api/tables/<id>` | Waiter+Manager | availability & diners (capacity validated) |
| `POST /api/orders` | guest / staff | allergy + quota validated order |
| `GET /api/orders[?guest_id=&status=]` | staff or own guest | order list |
| `GET /api/orders/<id>` | public by id | full bill |
| `POST /api/orders/<id>/pay` `/cancel` | Waiter+Manager | settle orders |
| `GET /api/reports/<name>` | Waiter+Manager | 5 SBA queries (+ SQL text) |
| `POST /api/assistant/recommend` | public | rule engine / LLM suggestions |

---

## 7. Verification performed

A temporary smoke-test script (Flask `test_client`, since deleted) exercised
the whole API end-to-end — **20/20 checks passed**, covering:

- `GET /api/menu` returns 8 dishes with allergen info; `/api/allergens` returns 10.
- Manager login; `report available-tables` = 8; `report discount` = 8 rows with
  `SPECIAL_OFFER_ON_DIM_SUM`.
- Guest profile with Shellfish + Dairy → ordering **L1 Har Gow is blocked with
  409 + alternatives** (L4/L6/L7 suggested); ordering **L7 succeeds**
  (bill 26.00, split 13.00 for 2 diners); table T1 becomes occupied.
- `report split-bill` shows T1 = 13.00; `report quota` shows L7 = 48/50.
- Guests can list only their own orders (`?guest_id=` enforced).
- Access control: menu write requires login (401) and Manager role
  (waiter gets 403).
- Staff `force` override of an allergy conflict returns 201 with warnings.
- Paying the order frees the table; `report sales` counts paid orders.
- Assistant falls back to the rule engine when no `LLM_API_KEY` is set
  (`source: "rule"`), suggesting safe dishes.
- `GET /` serves the frontend page.

After testing, `pos.db` was reset to a clean seed (`python db.py`) so the
demo starts fresh.

---

## 8. Known limitations / future work

- Tokens are in-memory (restart = logout); fine for a demo, use sessions/JWT for production.
- Plain HTTP on localhost; real deployment needs HTTPS.
- Demo passwords are documented in the UI for convenience.
- The LLM assistant is optional and off by default; the rule engine is the
  safety-critical path and never depends on the network.
- Inventory/CRM/social-media extensions listed in SBA 5.2 are not implemented.

---

## 9. Incident log (2026-09-17): files reverted, recovered from git stash

**What happened.** After the GUI editor (GitHub Desktop) was used, most of our
work disappeared from the working tree: `app.py` reverted to the old 13-line
stub ("Restaurant POS backend is running"), `auth.py` / `allergy.py` /
`db.py` / `app.js` / `index.html` / `styles.css` / `process.md` were deleted,
`schema.sql` / `requirements.txt` were emptied, and a stray empty
`frontend/later` file plus an empty `backend/venv/` appeared. Root cause:
GitHub Desktop stashed the local changes (`stash@{0}`) while the branch held
older commits.

**Recovery (all steps verified).**

1. `git stash show --stat stash@{0}` confirmed the stash contained the full
   versions of every missing file (2529 insertions).
2. Deleted the empty on-disk `schema.sql` (it blocked the stash restore).
3. `git stash pop` — restored everything except `app.py`, which hit a merge
   conflict with the old stub commit.
4. Resolved with `git checkout stash@{0} -- backend/app.py`
   (24,244 bytes, the complete version).
5. Cleaned up: removed the empty `venv/`, `__pycache__/`, `frontend/later`
   and the old `pos.db` so `db.init_db()` re-seeds a fresh database.
6. Restarted the server and re-verified: `GET /` = 200,
   `GET /api/menu` = 200, `GET /api/allergens` = 200,
   `GET /favicon.ico` = 200 (SVG), manager login returns role `Manager`.

**Lesson.** If files ever vanish after using GitHub Desktop, check
`git stash list` before panicking — it usually stashed them. Nothing is
committed yet; when we do commit, this whole state will be safe from
future reverts.
