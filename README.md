# ABC Dim Sum Restaurant — POS + Allergy-Safe Ordering

A point-of-sale system for ABC Dim Sum Restaurant, rebuilt from the HKDSE ICT
SBA database design and integrated with a food-allergy safety layer: guests
declare their allergens, the menu blocks unsafe dishes, and every order is
re-validated on the server before it reaches the kitchen.

## Quick start

```bash
cd backend
pip install -r requirements.txt
python app.py            # rebuilds/uses pos.db, serves API + UI
```

Open **http://127.0.0.1:5000**

Demo accounts: `manager / manager123` (Manager) · `waiter / waiter123` (Waiter).
Diners need no account — just pick your allergens and order.

## Roles

| Role | Can do |
|---|---|
| **Diner** (guest) | declare allergens, browse the safety-filtered menu, self-order, view own bill |
| **Waiter** | manage tables (availability, diners), take allergy-checked orders, pay/cancel orders, run reports |
| **Manager** | everything a waiter can, plus create/edit/delete menu (price, quota, ingredients, allergens) |

## Optional AI assistant

The allergy filter is a deterministic rule engine (safe, offline). To add an
LLM-powered recommendation layer, set environment variables before starting:

```bash
set LLM_API_KEY=sk-...        # or OPENAI_API_KEY
set LLM_BASE_URL=https://api.openai.com/v1   # any OpenAI-compatible endpoint
set LLM_MODEL=gpt-4o-mini
```

Without a key, the "Ask for safe choices" button falls back to the rule engine.

## Project layout

```
backend/    app.py (API) · db.py · auth.py · allergy.py · schema.sql
frontend/   index.html · styles.css · app.js  (vanilla JS, no build step)
process.md  full development log & design rationale
```

See `process.md` for the mapping between the SBA/allergy-project requirements
and the implementation.
