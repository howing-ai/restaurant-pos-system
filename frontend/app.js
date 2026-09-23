/* ABC Dim Sum Restaurant - POS front-end (vanilla JS, no build step)
 *
 * Views:  home | diner (self-order) | login | staff (waiter/manager dashboard)
 * Reports: the SBA Task-1 SQL queries (available tables, split bill, 90%
 *          discount, quota, sales) are surfaced in the staff "Reports" tab
 *          through GET /api/reports/<name>.
 */
const API_BASE = (location.protocol === "file:" ? "http://127.0.0.1:5000" : "") + "/api";

const REPORT_LABELS = {
    "available-tables": "Available tables",
    "split-bill": "Split the bill",
    "discount": "90% price (10% off)",
    "quota": "Dim sum quota left",
    "sales": "Paid sales",
};

const state = {
    view: "home",                 // home | diner | login | staff
    token: null, role: null, username: null,
    allergens: [],                // [{AllergenID, AllergenName}]
    menu: [],                     // dishes from GET /api/menu
    tables: [],
    orders: [],
    // diner self-order
    dinerExcluded: [], guestId: null,
    // staff new-order
    staffExcluded: [], staffGuestId: null,
    cart: {},                     // LunchID -> quantity
    selectedTableId: null, numDiners: 2,
    hideUnsafe: true,
    staffTab: "tables",
    report: null,                 // last report {name, title, sql, rows}
};

/* ------------------------------------------------------------------ utils */
function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function fmt(value) {
    return typeof value === "number" ? (Number.isInteger(value) ? value : value.toFixed(2)) : esc(value);
}

async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (state.token) headers.Authorization = state.token;
    const res = await fetch(API_BASE + path, { ...options, headers });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { error: text }; }
    if (!res.ok) {
        const err = new Error((data && data.error) || "HTTP " + res.status);
        err.data = data;
        err.status = res.status;
        throw err;
    }
    return data;
}

function toast(message, kind = "info") {
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.textContent = message;
    document.getElementById("toast").appendChild(el);
    setTimeout(() => el.remove(), 3500);
}

function showModal(html) {
    document.getElementById("modalBody").innerHTML = html;
    document.getElementById("modal").classList.remove("hidden");
}

function closeModal() { document.getElementById("modal").classList.add("hidden"); }

/* ------------------------------------------------------------- data load */
const loadAllergens = async () => { state.allergens = await api("/allergens"); };
const loadMenu = async () => { state.menu = await api("/menu"); };
const loadTables = async () => { state.tables = await api("/tables"); };

async function loadOrders() {
    // anonymous diner with no saved profile yet -> simply nothing to list
    if (!state.token && !state.guestId) { state.orders = []; return; }
    const query = state.token ? "" : "?guest_id=" + state.guestId;
    state.orders = await api("/orders" + query);
}

async function loadEverything() {
    await Promise.all([loadAllergens(), loadMenu(), loadTables()]);
    await loadOrders();
}

/* ----------------------------------------------------------- menu pieces */
const dishById = id => state.menu.find(d => d.id === id);
const isSafe = (dish, excluded) => !dish.allergens.some(a => excluded.includes(a.id));
const cartTotal = () => Object.entries(state.cart)
    .reduce((sum, [id, qty]) => sum + dishById(id).price * qty, 0);

function allergenChipsHTML(excluded, action) {
    return state.allergens.map(a => `
        <button class="chip ${excluded.includes(a.AllergenID) ? "on" : ""}"
                data-action="${action}" data-id="${a.AllergenID}">${esc(a.AllergenName)}</button>`).join("");
}

function dishCardHTML(dish, excluded) {
    const safe = isSafe(dish, excluded);
    const qty = state.cart[dish.id] || 0;
    const soldOut = dish.available <= 0;
    const badges = dish.allergens.length
        ? dish.allergens.map(a => `<span class="badge" title="${esc(a.note)}">${esc(a.name)}</span>`).join("")
        : '<span class="badge ok">No major allergen</span>';
    const conflicts = dish.allergens.filter(a => excluded.includes(a.id)).map(a => a.name);
    return `
    <div class="dish ${safe ? "" : "unsafe"} ${soldOut ? "soldout" : ""}">
        <div class="dish-head"><h4>${esc(dish.name)}</h4><span class="price">$${dish.price.toFixed(2)}</span></div>
        <p class="ing">${esc(dish.ingredients) || "—"}</p>
        <div class="badges">${badges}</div>
        <div class="quota">Left today: ${dish.available} / ${dish.quota}</div>
        ${safe
            ? (soldOut
                ? '<p class="warn-text">Sold out</p>'
                : `<div class="qty">
                     <button data-action="dec" data-id="${dish.id}">−</button>
                     <span>${qty}</span>
                     <button data-action="inc" data-id="${dish.id}">+</button>
                   </div>`)
            : `<p class="warn-text">Not safe for you: ${conflicts.map(esc).join(", ")}</p>`}
    </div>`;
}

function cartHTML(excluded) {
    const lines = Object.entries(state.cart).map(([id, qty]) => {
        const d = dishById(id);
        return `<li><span>${esc(d.name)} × ${qty}</span><span>$${(d.price * qty).toFixed(2)}</span></li>`;
    });
    const total = cartTotal();
    return `
    <h3>Your order</h3>
    ${lines.length
        ? `<ul>${lines.join("")}</ul>
           <div class="total"><span>Total</span><span>$${total.toFixed(2)}</span></div>
           ${state.numDiners > 1 ? `<p class="muted">Split per diner (×${state.numDiners}): $${(total / state.numDiners).toFixed(2)}</p>` : ""}`
        : '<p class="muted">Nothing selected yet. Pick dishes from the menu.</p>'}
    <div class="row" style="margin-top:12px;">
        <button class="btn primary" data-action="submit-order" ${(!state.selectedTableId || !lines.length) ? "disabled" : ""}>Place order</button>
        <button class="btn ghost" data-action="ai-suggest" ${!excluded.length ? "disabled" : ""}>Ask for safe choices</button>
    </div>`;
}

function tablePickerHTML(onlyAvailable) {
    const list = state.tables.filter(t => !onlyAvailable || t.Availability);
    if (!list.length) return '<p class="muted">No table available right now, please wait.</p>';
    return `<div class="table-grid">${list.map(t => `
        <button class="table-card ${t.Availability ? "free" : "busy"}"
                data-action="select-table" data-id="${t.TableID}"
                style="${state.selectedTableId === t.TableID ? "outline:3px solid var(--primary)" : ""}">
            <div class="tc-head"><b>${t.TableID}</b><span class="seat">${t.Num_of_Diners}/${t.Capacity}</span></div>
            <p>${t.Availability ? "Available" : "Occupied"}</p>
        </button>`).join("")}</div>`;
}

function ordersHTML(isStaff) {
    if (!state.orders.length) return '<p class="muted">No orders yet.</p>';
    return state.orders.map(o => `
    <div class="order ${o.status.toLowerCase()}">
        <div class="order-head">
            <b>Order #${o.id}</b>
            <span class="pill ${o.status.toLowerCase()}">${o.status}</span>
            <span class="muted">Table ${esc(o.table_id)} · ${esc(o.guest_name)}</span>
        </div>
        ${o.allergies.length ? `<div class="allergy-line">Guest allergies: ${o.allergies.map(esc).join(", ")}</div>` : ""}
        <table class="mini">
            ${o.items.map(i => `<tr><td>${esc(i.name)}</td><td>× ${i.quantity}</td><td>$${i.price.toFixed(2)}</td><td>$${i.subtotal.toFixed(2)}</td></tr>`).join("")}
        </table>
        <div class="order-foot">
            <b>Bill $${o.bill.toFixed(2)}</b>
            ${o.split_bill ? `<span class="muted">Split (${o.num_diners} diners): $${o.split_bill.toFixed(2)} each</span>` : ""}
            <button class="btn small" data-action="view-bill" data-id="${o.id}">Bill</button>
            ${isStaff && o.status === "Pending" ? `
                <button class="btn small primary" data-action="pay-order" data-id="${o.id}">Mark paid</button>
                <button class="btn small danger" data-action="cancel-order" data-id="${o.id}">Cancel</button>` : ""}
        </div>
    </div>`).join("");
}

/* --------------------------------------------------------------- reports */
function reportTableHTML(rows) {
    if (!rows.length) return '<p class="muted">No rows returned.</p>';
    const cols = Object.keys(rows[0]);
    return `<table class="data-table">
        <thead><tr>${cols.map(esc).join("")}</tr></thead>
        <tbody>${rows.map(r => `<tr>${cols.map(c => `<td>${fmt(r[c])}</td>`).join("")}</tr>`).join("")}</tbody>
    </table>`;
}

function reportResultHTML(rep) {
    return `
    <h4>${esc(rep.title)}</h4>
    <div class="sql-box">SQL&gt; ${esc(rep.sql)}</div>
    ${reportTableHTML(rep.rows)}`;
}

function viewReports() {
    const rep = state.report;
    return `
    <section class="card">
        <h3>Reports — useful information (SBA Task 1, section 4.6)</h3>
        <p class="muted">Each button runs one SQL command against the live database.</p>
        <div class="row">
            ${Object.keys(REPORT_LABELS).map(name => `
                <button class="btn ${rep && rep.name === name ? "primary" : ""}"
                        data-action="run-report" data-id="${name}">${REPORT_LABELS[name]}</button>`).join("")}
        </div>
        <div id="reportOut" style="margin-top:10px;">
            ${rep ? reportResultHTML(rep) : '<p class="muted">Pick a report to run.</p>'}
        </div>
    </section>`;
}

/* --------------------------------------------------------------din views */
function viewHome() {
    return `
    <section class="card hero">
        <h2>Dim sum, made safe.</h2>
        <p>Tell us your allergies and the menu will only let you order dishes that are
           safe for you — with hidden allergens like sauce and oil clearly marked.</p>
        <div class="row" style="justify-content:center;">
            <button class="btn primary lg" data-action="go-diner">I'm a Diner — order now</button>
            <button class="btn lg" data-action="go-login">Staff login</button>
        </div>
    </section>`;
}

function viewLogin() {
    return `
    <section class="card" style="max-width:430px;margin:40px auto;">
        <h3>Staff login</h3>
        <p class="muted">Demo accounts — manager / manager123 · waiter / waiter123</p>
        <p><label>Username <input id="loginUser" autocomplete="username"></label></p>
        <p><label>Password <input id="loginPass" type="password" autocomplete="current-password"></label></p>
        <div class="row">
            <button class="btn primary" data-action="do-login">Login</button>
            <button class="btn" data-action="go-home">Back</button>
        </div>
    </section>`;
}

function viewDiner() {
    const excluded = state.dinerExcluded;
    const visible = state.menu.filter(d => !state.hideUnsafe || isSafe(d, excluded));
    return `
    <section class="card">
        <h3>Step 1 · Your allergies</h3>
        <p class="muted">Select everything you must avoid. Dishes containing these allergens will be blocked.</p>
        <div class="chips">${allergenChipsHTML(excluded, "toggle-allergen")}</div>
        <div class="row">
            <button class="btn primary" data-action="save-guest">Save my allergy profile</button>
            ${state.guestId ? `<span class="pill ok">Profile #${state.guestId} saved — orders will be checked</span>` : '<span class="muted">Save before ordering so we can double-check your food.</span>'}
        </div>
    </section>

    <section class="card">
        <h3>Step 2 · Table &amp; diners</h3>
        ${tablePickerHTML(true)}
        <p><label>Number of diners
            <input type="number" min="1" value="${state.numDiners}" data-action="num-diners">
        </label></p>
    </section>

    <div class="layout">
        <section class="card">
            <h3>Step 3 · Menu <span class="muted">(${visible.filter(d => isSafe(d, excluded)).length} safe dishes)</span></h3>
            <label class="switch"><input type="checkbox" data-action="hide-unsafe" ${state.hideUnsafe ? "checked" : ""}> Hide unsafe dishes</label>
            <div class="dish-grid">${visible.map(d => dishCardHTML(d, excluded)).join("")}</div>
        </section>
        <aside class="card cart">${cartHTML(excluded)}</aside>
    </div>

    <section class="card">
        <h3>My orders &amp; bills</h3>
        ${ordersHTML(false)}
    </section>`;
}

/* ------------------------------------------------------------- staff view */
function staffTablesHTML() {
    return state.tables.map(t => `
    <div class="table-card ${t.Availability ? "free" : "busy"}">
        <div class="tc-head"><b>${t.TableID}</b><span class="seat">${t.Num_of_Diners}/${t.Capacity}</span></div>
        <p>${t.Availability ? "Available" : "Occupied"}${t.Open_Orders ? ` · ${t.Open_Orders} open order(s)` : ""}</p>
        <div class="row">
            <input type="number" min="0" max="${t.Capacity}" value="${t.Num_of_Diners}" data-diners="${t.TableID}">
            <button class="btn small" data-action="save-diners" data-id="${t.TableID}">Save diners</button>
            <button class="btn small ${t.Availability ? "warn" : ""}" data-action="toggle-table" data-id="${t.TableID}">
                ${t.Availability ? "Seat" : "Free"}
            </button>
        </div>
    </div>`).join("");
}

function staffMenuHTML() {
    return `
    <section class="card">
        <h3>Add a dish (Manager)</h3>
        <div class="row">
            <input id="m-id" placeholder="LunchID e.g. L9" style="width:120px;">
            <input id="m-name" placeholder="Dish name" style="width:220px;">
            <input id="m-price" type="number" step="0.1" placeholder="Price" style="width:90px;">
            <input id="m-quota" type="number" placeholder="Quota" style="width:90px;">
            <input id="m-ing" placeholder="Ingredients" style="width:260px;">
            <label class="switch"><input id="m-veg" type="checkbox"> Vegetarian</label>
        </div>
        <div class="chips">${state.allergens.map(a => `
            <label class="chip" style="cursor:pointer;">
                <input type="checkbox" class="m-alg" value="${a.AllergenID}"> ${esc(a.AllergenName)}
            </label>`).join("")}</div>
        <button class="btn primary" data-action="add-menu">Add dish</button>
    </section>
    <section class="card">
        <h3>Menu</h3>
        <table class="data-table">
            <thead><tr><th>ID</th><th>Name</th><th>Price</th><th>Quota</th><th>Allergens</th><th></th></tr></thead>
            <tbody>${state.menu.map(d => `
                <tr>
                    <td>${d.id}</td>
                    <td>${esc(d.name)}<br><span class="muted">${esc(d.ingredients)}</span></td>
                    <td><input type="number" step="0.1" value="${d.price}" data-price="${d.id}"></td>
                    <td><input type="number" value="${d.quota}" data-quota="${d.id}"></td>
                    <td>${d.allergens.map(a => `<span class="badge" title="${esc(a.note)}">${esc(a.name)}</span>`).join(" ") || '<span class="badge ok">none</span>'}</td>
                    <td>
                        <button class="btn small primary" data-action="save-menu-item" data-id="${d.id}">Save</button>
                        <button class="btn small danger" data-action="delete-menu" data-id="${d.id}">Delete</button>
                    </td>
                </tr>`).join("")}</tbody>
        </table>
    </section>`;
}

function staffNewOrderHTML() {
    const excluded = state.staffExcluded;
    const visible = state.menu.filter(d => !state.hideUnsafe || isSafe(d, excluded));
    return `
    <section class="card">
        <h3>Guest allergies (optional)</h3>
        <p class="muted">Pick the diner's allergens — unsafe dishes will be blocked, and the kitchen ticket notes the allergy.</p>
        <div class="chips">${allergenChipsHTML(excluded, "toggle-staff-allergen")}</div>
    </section>
    <section class="card">
        <h3>Table &amp; diners</h3>
        ${tablePickerHTML(false)}
        <p><label>Number of diners
            <input type="number" min="1" value="${state.numDiners}" data-action="num-diners">
        </label></p>
        <label class="switch"><input type="checkbox" data-action="hide-unsafe" ${state.hideUnsafe ? "checked" : ""}> Hide unsafe dishes</label>
    </section>
    <div class="layout">
        <section class="card">
            <h3>Menu</h3>
            <div class="dish-grid">${visible.map(d => dishCardHTML(d, excluded)).join("")}</div>
        </section>
        <aside class="card cart">${cartHTML(excluded)}</aside>
    </div>`;
}

function viewStaff() {
    const body = {
        tables: `<section class="card"><h3>Dining tables</h3>
                   <p class="muted">Green = available, red = occupied. Click Seat/Free to change availability.</p>
                   <div class="table-grid">${staffTablesHTML()}</div></section>`,
        order: staffNewOrderHTML(),
        orders: `<section class="card"><h3>All orders</h3>${ordersHTML(true)}</section>`,
        menu: state.role === "Manager" ? staffMenuHTML() : "",
        reports: viewReports(),
    }[state.staffTab] || "";
    return body;
}

/* ----------------------------------------------------------------- render */
function tabsHTML() {
    if (state.view !== "staff") return "";
    const tabs = [
        { id: "tables", label: "Tables" },
        { id: "order", label: "New Order" },
        { id: "orders", label: "Orders" },
    ];
    if (state.role === "Manager") tabs.push({ id: "menu", label: "Menu" });
    tabs.push({ id: "reports", label: "Reports" });
    return tabs.map(t =>
        `<button class="tab ${state.staffTab === t.id ? "active" : ""}"
                 data-action="staff-tab" data-id="${t.id}">${t.label}</button>`).join("");
}

function userAreaHTML() {
    if (state.token) {
        return `<span class="pill ok">${esc(state.role)}</span><span>${esc(state.username)}</span>
                <button class="btn small" data-action="logout">Logout</button>`;
    }
    if (state.view === "diner") {
        return `<span class="pill pending">Diner · guest</span><button class="btn small" data-action="go-home">Exit</button>`;
    }
    return "";
}

function render() {
    document.getElementById("tabs").innerHTML = tabsHTML();
    document.getElementById("userArea").innerHTML = userAreaHTML();
    const app = document.getElementById("app");
    app.innerHTML = state.view === "diner" ? viewDiner()
        : state.view === "login" ? viewLogin()
        : state.view === "staff" ? viewStaff()
        : viewHome();
}

/* -------------------------------------------------------------- actions */
async function submitOrder(force) {
    const staffOrder = state.view === "staff";
    const excluded = staffOrder ? state.staffExcluded : state.dinerExcluded;
    let guestId = staffOrder ? state.staffGuestId : state.guestId;

    if (excluded.length && !guestId) {
        const guest = await api("/guests", {
            method: "POST",
            body: JSON.stringify({ name: staffOrder ? "Table guest" : "Guest", allergens: excluded }),
        });
        guestId = guest.guest_id;
        if (staffOrder) state.staffGuestId = guestId; else state.guestId = guestId;
    }

    try {
        const order = await api("/orders", {
            method: "POST",
            body: JSON.stringify({
                table_id: state.selectedTableId,
                guest_id: guestId,
                items: state.cart,
                num_diners: state.numDiners,
                force,
            }),
        });
        state.cart = {};
        state.selectedTableId = null;
        await Promise.all([loadMenu(), loadTables(), loadOrders()]);
        render();
        showBill(order, "Order placed");
        if (order.warnings && order.warnings.length) {
            toast("Staff override: contains " + order.warnings.map(w => w.allergens.join("/")).join(", "), "err");
        }
    } catch (err) {
        if (err.status === 409 && err.data && err.data.conflicts) {
            showConflict(err.data);
        } else if (err.status === 409 && err.data && err.data.quota) {
            toast(err.data.quota.map(q => `${q.name}: only ${q.available} left`).join("; "), "err");
        } else {
            toast(err.message, "err");
        }
    }
}

function showConflict(data) {
    const conflicts = data.conflicts.map(c =>
        `<li><b>${esc(c.name)}</b> — contains ${c.allergens.map(esc).join(", ")}</li>`).join("");
    const alts = (data.alternatives || []).map(d =>
        `<li>${esc(d.name)} — $${d.price.toFixed(2)} <button class="btn tiny" data-action="add-alt" data-id="${d.id}">Add</button></li>`).join("")
        || '<li class="muted">No safe alternative found — please ask our staff.</li>';
    showModal(`
        <h3 class="danger-text">Allergy warning</h3>
        <p>These dishes are <b>not safe</b> for this guest and were not ordered:</p>
        <ul>${conflicts}</ul>
        <h4>Suggested safe alternatives</h4>
        <ul class="alt-list">${alts}</ul>
        ${state.token
            ? '<button class="btn danger" data-action="force-order">Override &amp; place order anyway (staff)</button>'
            : '<p class="muted">Staff can override after verbally confirming with the guest.</p>'}
        <button class="btn" data-action="close-modal">Close</button>`);
}

function showBill(order, title = "Bill") {
    showModal(`
        <h3>${esc(title)} · Order #${order.id}</h3>
        <p class="muted">Table ${esc(order.table_id)} · ${esc(order.guest_name)} · ${order.status}</p>
        ${order.allergies.length ? `<div class="allergy-line">Guest allergies: ${order.allergies.map(esc).join(", ")}</div>` : ""}
        <table class="mini">
            ${order.items.map(i => `<tr><td>${esc(i.name)}</td><td>× ${i.quantity}</td><td>$${i.price.toFixed(2)}</td><td>$${i.subtotal.toFixed(2)}</td></tr>`).join("")}
        </table>
        <div class="order-foot"><b>Total $${order.bill.toFixed(2)}</b>
            ${order.split_bill ? `<span class="muted">Split per diner ($${order.num_diners}): $${order.split_bill.toFixed(2)}</span>` : ""}
        </div>
        <button class="btn" data-action="close-modal">Close</button>`);
}

async function aiSuggest() {
    const staffOrder = state.view === "staff";
    const excluded = staffOrder ? state.staffExcluded : state.dinerExcluded;
    if (!excluded.length) { toast("Select at least one allergen first", "err"); return; }
    try {
        const res = await api("/assistant/recommend", {
            method: "POST",
            body: JSON.stringify({ exclude: excluded, guest_id: staffOrder ? state.staffGuestId : state.guestId }),
        });
        showModal(`
            <h3>Allergy assistant</h3>
            <p class="muted">Answer provided by: ${res.source === "llm" ? "AI model (LLM)" : "built-in rule engine"}</p>
            <p>${esc(res.message)}</p>
            <ul class="alt-list">${res.dishes.map(d =>
                `<li>${esc(d.name)} — $${d.price.toFixed(2)} <button class="btn tiny" data-action="add-alt" data-id="${d.id}">Add</button></li>`).join("")}</ul>
            <button class="btn" data-action="close-modal">Close</button>`);
    } catch (err) {
        toast(err.message, "err");
    }
}

/* ------------------------------------------------------- event listeners */
document.addEventListener("click", async e => {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const action = el.dataset.action;
    const id = el.dataset.id;
    try {
        switch (action) {
            case "go-diner":
                await loadEverything();
                state.view = "diner";
                render();
                break;

            case "go-login":
                state.view = "login";
                render();
                break;

            case "go-home":
                state.view = "home";
                render();
                break;

            case "do-login": {
                const username = document.getElementById("loginUser").value.trim();
                const password = document.getElementById("loginPass").value;
                const res = await api("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
                state.token = res.token;
                state.role = res.role;
                state.username = res.username;
                state.view = "staff";
                state.staffTab = "tables";
                await loadEverything();
                render();
                toast(`Welcome back, ${res.username} (${res.role})`, "ok");
                break;
            }

            case "logout":
                try { await api("/auth/logout", { method: "POST" }); } catch { /* ignore */ }
                state.token = state.role = state.username = null;
                state.staffExcluded = [];
                state.staffGuestId = null;
                state.report = null;
                state.view = "home";
                render();
                break;

            case "toggle-allergen": {
                const i = state.dinerExcluded.indexOf(+id);
                i >= 0 ? state.dinerExcluded.splice(i, 1) : state.dinerExcluded.push(+id);
                state.guestId = null;  // profile changed, needs saving again
                render();
                break;
            }

            case "toggle-staff-allergen": {
                const i = state.staffExcluded.indexOf(+id);
                i >= 0 ? state.staffExcluded.splice(i, 1) : state.staffExcluded.push(+id);
                state.staffGuestId = null;
                render();
                break;
            }

            case "save-guest": {
                const guest = await api("/guests", {
                    method: "POST",
                    body: JSON.stringify({ name: "Guest", allergens: state.dinerExcluded }),
                });
                state.guestId = guest.guest_id;
                await loadOrders();
                render();
                toast("Allergy profile saved — your order will be double-checked", "ok");
                break;
            }

            case "select-table":
                state.selectedTableId = id;
                render();
                break;

            case "inc":
                state.cart[id] = (state.cart[id] || 0) + 1;
                render();
                break;

            case "dec":
                if (--state.cart[id] <= 0) delete state.cart[id];
                render();
                break;

            case "add-alt":
                state.cart[id] = (state.cart[id] || 0) + 1;
                closeModal();
                render();
                break;

            case "submit-order":
                await submitOrder(false);
                break;

            case "force-order":
                await submitOrder(true);
                break;

            case "ai-suggest":
                await aiSuggest();
                break;

            case "staff-tab":
                state.staffTab = id;
                if (id === "orders") await loadOrders();
                if (id === "tables") await loadTables();
                if (id === "menu") await loadMenu();
                render();
                break;

            case "toggle-table": {
                const table = state.tables.find(t => t.TableID === id);
                await api(`/tables/${id}`, {
                    method: "PUT",
                    body: JSON.stringify({ availability: table.Availability ? 0 : 1 }),
                });
                await loadTables();
                render();
                break;
            }

            case "save-diners": {
                const value = document.querySelector(`input[data-diners="${id}"]`).value;
                await api(`/tables/${id}`, { method: "PUT", body: JSON.stringify({ num_of_diners: +value }) });
                await loadTables();
                render();
                break;
            }

            case "pay-order":
                await api(`/orders/${id}/pay`, { method: "POST" });
                await Promise.all([loadOrders(), loadTables(), loadMenu()]);
                render();
                toast(`Order #${id} marked paid`, "ok");
                break;

            case "cancel-order":
                await api(`/orders/${id}/cancel`, { method: "POST" });
                await Promise.all([loadOrders(), loadTables(), loadMenu()]);
                render();
                toast(`Order #${id} cancelled`, "info");
                break;

            case "view-bill": {
                const order = await api(`/orders/${id}`);
                showBill(order);
                break;
            }

            case "add-menu": {
                const allergens = [...document.querySelectorAll(".m-alg:checked")].map(c => +c.value);
                await api("/menu", {
                    method: "POST",
                    body: JSON.stringify({
                        lunch_id: document.getElementById("m-id").value.trim(),
                        name: document.getElementById("m-name").value.trim(),
                        price: +document.getElementById("m-price").value,
                        quota: +document.getElementById("m-quota").value,
                        ingredients: document.getElementById("m-ing").value.trim(),
                        is_vegetarian: document.getElementById("m-veg").checked,
                        allergens,
                    }),
                });
                await loadMenu();
                render();
                toast("Dish added", "ok");
                break;
            }

            case "save-menu-item": {
                const price = document.querySelector(`input[data-price="${id}"]`).value;
                const quota = document.querySelector(`input[data-quota="${id}"]`).value;
                await api(`/menu/${id}`, { method: "PUT", body: JSON.stringify({ price: +price, quota: +quota }) });
                await loadMenu();
                render();
                toast(`${id} updated`, "ok");
                break;
            }

            case "delete-menu":
                try {
                    await api(`/menu/${id}`, { method: "DELETE" });
                    toast(`${id} deleted`, "ok");
                } catch (err) {
                    toast(err.message, "err");
                }
                await loadMenu();
                render();
                break;

            case "run-report":
                state.report = await api(`/reports/${id}`);
                render();
                break;

            case "close-modal":
                closeModal();
                break;
        }
    } catch (err) {
        toast(err.message, "err");
    }
});

// close the modal when clicking the dark overlay
document.getElementById("modal").addEventListener("click", e => {
    if (e.target.id === "modal") closeModal();
});

// text/checkbox inputs
document.addEventListener("change", e => {
    if (e.target.dataset.action === "hide-unsafe") {
        state.hideUnsafe = e.target.checked;
        render();
    }
});

document.addEventListener("input", e => {
    if (e.target.dataset.action === "num-diners") {
        const value = parseInt(e.target.value, 10);
        if (value > 0) state.numDiners = value;
    }
});

/* first paint */
render();
