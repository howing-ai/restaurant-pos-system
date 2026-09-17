"""Food-allergy engine.

The safety-critical part is a deterministic rule engine (no AI required, works
offline): a dish is unsafe when it is linked to any allergen in the guest's
profile.  An *optional* LLM assistant can be switched on with environment
variables - if it is unavailable the engine silently falls back to rules, so the
allergy check is never dependent on a network service.

Environment variables (all optional):
    LLM_API_KEY / OPENAI_API_KEY   enable the assistant
    LLM_BASE_URL                   default https://api.openai.com/v1
    LLM_MODEL                      default gpt-4o-mini
"""
import json
import os
import urllib.request

import db


# --------------------------------------------------------------------------- #
# Rule engine
# --------------------------------------------------------------------------- #
def list_allergens(conn):
    rows = conn.execute("SELECT AllergenID, AllergenName FROM Allergen ORDER BY AllergenName").fetchall()
    return [dict(r) for r in rows]


def allergen_names(conn, ids):
    ids = [int(i) for i in ids] or [-1]
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT AllergenName FROM Allergen WHERE AllergenID IN ({placeholders}) ORDER BY AllergenName",
        ids,
    ).fetchall()
    return [r["AllergenName"] for r in rows]


def dish_allergen_map(conn):
    """{LunchID: [{'id', 'name', 'note'}, ...]}"""
    rows = conn.execute("""
        SELECT da.LunchID, a.AllergenID AS id, a.AllergenName AS name, da.RiskNote AS note
        FROM Dish_Allergen da
        JOIN Allergen a ON a.AllergenID = da.AllergenID
        ORDER BY a.AllergenName
    """).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["LunchID"], []).append({"id": r["id"], "name": r["name"], "note": r["note"]})
    return out


def excluded_ids(conn, guest_id):
    """Allergen ids saved on a guest profile."""
    if not guest_id:
        return []
    rows = conn.execute(
        "SELECT AllergenID FROM Guest_Allergy WHERE GuestID = ?", (guest_id,)
    ).fetchall()
    return [r["AllergenID"] for r in rows]


def conflicts_for(conn, lunch_id, excluded):
    """Allergen names of a dish that clash with the guest's profile."""
    excluded = set(int(i) for i in excluded)
    if not excluded:
        return []
    return [
        a["name"]
        for a in dish_allergen_map(conn).get(lunch_id, [])
        if a["id"] in excluded
    ]


def filter_menu(conn, excluded_ids_list=None):
    """Full menu annotated with allergen info and a safe/unsafe verdict."""
    excluded = set(int(i) for i in (excluded_ids_list or []))
    allergens = dish_allergen_map(conn)
    used = db.used_quota(conn)

    dishes = []
    for r in conn.execute("SELECT * FROM Menu ORDER BY LunchID").fetchall():
        dish_allergens = allergens.get(r["LunchID"], [])
        conflicts = [a["name"] for a in dish_allergens if a["id"] in excluded]
        used_qty = used.get(r["LunchID"], 0)
        dishes.append({
            "id": r["LunchID"],
            "name": r["LunchName"],
            "price": round(r["LunchPrice"], 2),
            "quota": r["Quota"],
            "available": max(0, r["Quota"] - used_qty),
            "ingredients": r["Ingredients"],
            "is_vegetarian": bool(r["IsVegetarian"]),
            "allergens": dish_allergens,
            "safe": not conflicts,
            "conflicts": conflicts,
        })
    return dishes


def suggest_alternatives(conn, excluded_ids_list, limit=3, avoid=None):
    """Safe, in-stock dishes, most allergy-friendly (fewest allergens) first."""
    avoid = set(avoid or [])
    safe = [
        d for d in filter_menu(conn, excluded_ids_list)
        if d["safe"] and d["available"] > 0 and d["id"] not in avoid
    ]
    safe.sort(key=lambda d: (len(d["allergens"]), d["price"]))
    return safe[:limit]


# --------------------------------------------------------------------------- #
# Optional LLM assistant
# --------------------------------------------------------------------------- #
def llm_available():
    return bool(os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _ask_llm(prompt, timeout=15):
    key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a restaurant food-allergy assistant. Recommend ONLY dishes "
                    "that contain none of the guest's allergens. Never invent dishes. "
                    "Answer in one or two short friendly sentences."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        # Any problem (no network, bad key, timeout) -> fall back to rules.
        return None


def recommend(conn, excluded_ids_list, question=None):
    """Return {'source', 'message', 'dishes'} for the allergy assistant."""
    excluded = [int(i) for i in (excluded_ids_list or [])]
    names = allergen_names(conn, excluded)
    dishes = filter_menu(conn, excluded)
    safe = [d for d in dishes if d["safe"] and d["available"] > 0]
    safe.sort(key=lambda d: (len(d["allergens"]), d["price"]))

    if llm_available():
        menu_lines = "\n".join(
            f"- {d['name']} (${d['price']:.2f}) allergens: {', '.join(a['name'] for a in d['allergens']) or 'none'}"
            for d in safe
        )
        prompt = (
            f"Guest allergens to avoid: {', '.join(names) or 'none'}.\n"
            f"Safe dishes available: \n{menu_lines or '(none)'}\n"
            f"{('Guest question: ' + question) if question else 'Suggest a safe meal.'}"
        )
        answer = _ask_llm(prompt)
        if answer:
            return {"source": "llm", "message": answer, "dishes": safe[:5]}

    if safe:
        picks = ", ".join(f"{d['name']} (${d['price']:.2f})" for d in safe[:3])
        message = (
            f"Safe choices for you: {picks}. "
            f"All are free of: {', '.join(names) or 'your allergens'}."
        )
    else:
        message = "No dish on the menu is safe for this allergen profile. Please ask our staff for help."
    return {"source": "rule", "message": message, "dishes": safe[:5]}
