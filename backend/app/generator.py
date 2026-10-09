"""
Site generator — the "AI Agent" step from the platform's diagram.

This is deliberately implemented as a deterministic, template-based
generator rather than a call to a real LLM: given a business name and a
plain-language description, it picks a category by keyword matching and
fills in a small full-stack app template (FastAPI backend + vanilla-JS
static frontend + its own Postgres schema).

To swap in a real AI model later, replace `generate_site()`'s body with a
call to an LLM (e.g. the Anthropic API) that returns the same file map
{relative_path: file_contents}; nothing else in the deploy pipeline needs
to change.
"""

import re
import uuid

CATEGORIES = {
    "clothing": {
        "keywords": ["cloth", "apparel", "fashion", "boutique", "wear"],
        "tagline": "Everyday style, made simple.",
        "products": [
            ("Classic Tee", 24.00, "A soft, everyday cotton t-shirt.", "\U0001f455"),
            ("Denim Jacket", 89.00, "A timeless jacket for any season.", "\U0001f9e5"),
            ("Wool Sweater", 64.00, "Cozy knit sweater for cooler days.", "\U0001f9f6"),
            ("Canvas Sneakers", 54.00, "Lightweight everyday sneakers.", "\U0001f45f"),
        ],
    },
    "food": {
        "keywords": ["food", "restaurant", "cafe", "coffee", "bakery", "menu", "kitchen"],
        "tagline": "Made fresh, served with care.",
        "products": [
            ("House Blend Coffee", 4.50, "Our signature medium roast.", "\u2615"),
            ("Sourdough Loaf", 7.00, "Baked fresh every morning.", "\U0001f35e"),
            ("Chef's Sandwich", 11.00, "Today's special, made to order.", "\U0001f96a"),
            ("Seasonal Salad", 9.50, "Whatever's freshest this week.", "\U0001f957"),
        ],
    },
    "tech": {
        "keywords": ["tech", "software", "app", "electronics", "gadget", "computer"],
        "tagline": "Tools built for how you work.",
        "products": [
            ("Wireless Mouse", 29.00, "Reliable, precise, all day.", "\U0001f5b1\ufe0f"),
            ("USB-C Hub", 39.00, "One cable, every port you need.", "\U0001f50c"),
            ("Mechanical Keyboard", 89.00, "Satisfying typing, built to last.", "\u2328\ufe0f"),
            ("Laptop Stand", 45.00, "Better posture, better airflow.", "\U0001f4bb"),
        ],
    },
    "services": {
        "keywords": [],  # default/fallback category
        "tagline": "Quality service you can count on.",
        "products": [
            ("Starter Package", 49.00, "A great way to get started with us.", "\u2728"),
            ("Standard Package", 99.00, "Our most popular offering.", "\u2b50"),
            ("Premium Package", 199.00, "The full experience, top to bottom.", "\U0001f451"),
            ("Consultation", 25.00, "A one-on-one session to plan your project.", "\U0001f4dd"),
        ],
    },
}


def detect_category(description: str) -> str:
    text = description.lower()
    for category, info in CATEGORIES.items():
        if any(keyword in text for keyword in info["keywords"]):
            return category
    return "services"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "site"


def make_unique_subdomain(name: str, exists_fn) -> str:
    """exists_fn(candidate) -> bool. Appends a short suffix on collision."""
    base = slugify(name)
    candidate = base
    while exists_fn(candidate):
        candidate = f"{base}-{uuid.uuid4().hex[:4]}"
    return candidate


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------

DOCKERFILE = """\
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

REQUIREMENTS = """\
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
psycopg2-binary==2.9.9
"""

MAIN_PY = '''\
import os
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

app = FastAPI(title="{business_name}")


def get_or_create_cart_id(request: Request, response: Response) -> str:
    cart_id = request.cookies.get("cart_id")
    if not cart_id:
        cart_id = str(uuid.uuid4())
        response.set_cookie("cart_id", cart_id, httponly=True, samesite="lax")
    return cart_id


@app.get("/api/products")
def list_products():
    with SessionLocal() as db:
        rows = db.execute(
            text("SELECT id, name, price, description, emoji FROM products ORDER BY id")
        ).mappings().all()
        return [dict(r) for r in rows]


@app.post("/api/contact")
async def submit_contact(request: Request):
    payload = await request.json()
    with SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO contact_messages (name, email, message) "
                "VALUES (:name, :email, :message)"
            ),
            {{
                "name": payload.get("name", ""),
                "email": payload.get("email", ""),
                "message": payload.get("message", ""),
            }},
        )
        db.commit()
    return {{"ok": True}}


@app.get("/api/cart")
def get_cart(request: Request, response: Response):
    cart_id = get_or_create_cart_id(request, response)
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT p.id, p.name, p.price, p.emoji, c.quantity "
                "FROM cart_items c JOIN products p ON p.id = c.product_id "
                "WHERE c.cart_id = :cart_id"
            ),
            {{"cart_id": cart_id}},
        ).mappings().all()
        items = [dict(r) for r in rows]
        total = sum(item["price"] * item["quantity"] for item in items)
        return {{"items": items, "total": round(total, 2)}}


@app.post("/api/cart/add")
async def add_to_cart(request: Request, response: Response):
    cart_id = get_or_create_cart_id(request, response)
    payload = await request.json()
    product_id = payload["product_id"]
    quantity = int(payload.get("quantity", 1))
    with SessionLocal() as db:
        existing = db.execute(
            text(
                "SELECT id, quantity FROM cart_items "
                "WHERE cart_id = :cart_id AND product_id = :product_id"
            ),
            {{"cart_id": cart_id, "product_id": product_id}},
        ).first()
        if existing:
            db.execute(
                text("UPDATE cart_items SET quantity = :qty WHERE id = :id"),
                {{"qty": existing.quantity + quantity, "id": existing.id}},
            )
        else:
            db.execute(
                text(
                    "INSERT INTO cart_items (cart_id, product_id, quantity) "
                    "VALUES (:cart_id, :product_id, :quantity)"
                ),
                {{"cart_id": cart_id, "product_id": product_id, "quantity": quantity}},
            )
        db.commit()
    return {{"ok": True}}


@app.post("/api/checkout")
def checkout(request: Request, response: Response):
    cart_id = get_or_create_cart_id(request, response)
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT p.price, c.quantity FROM cart_items c "
                "JOIN products p ON p.id = c.product_id WHERE c.cart_id = :cart_id"
            ),
            {{"cart_id": cart_id}},
        ).all()
        total = sum(r.price * r.quantity for r in rows)
        if not rows:
            return {{"ok": False, "error": "Cart is empty"}}
        order = db.execute(
            text(
                "INSERT INTO orders (cart_id, total) VALUES (:cart_id, :total) "
                "RETURNING id"
            ),
            {{"cart_id": cart_id, "total": total}},
        ).first()
        db.execute(text("DELETE FROM cart_items WHERE cart_id = :cart_id"), {{"cart_id": cart_id}})
        db.commit()
        return {{"ok": True, "order_id": order.id, "total": round(total, 2)}}


@app.get("/api/health")
def health():
    return {{"status": "ok", "business": "{business_name}"}}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
'''

STYLE_CSS = """\
:root {
  --brand: #2563eb;
  --bg: #fafafa;
  --card: #ffffff;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: #1a1a1a;
}
nav {
  display: flex;
  gap: 20px;
  padding: 16px 32px;
  background: white;
  border-bottom: 1px solid #eee;
  align-items: center;
}
nav a { text-decoration: none; color: #1a1a1a; font-weight: 500; }
nav .brand { font-weight: 700; font-size: 18px; color: var(--brand); margin-right: auto; }
main { max-width: 900px; margin: 0 auto; padding: 40px 24px; }
.hero { text-align: center; padding: 60px 20px; }
.hero h1 { font-size: 32px; margin-bottom: 8px; }
.hero p { color: #555; font-size: 18px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 20px; }
.card {
  background: var(--card);
  border: 1px solid #eee;
  border-radius: 10px;
  padding: 20px;
  text-align: center;
}
.card .emoji { font-size: 40px; }
.card h3 { margin: 8px 0 4px; }
.card .price { color: var(--brand); font-weight: 700; margin-bottom: 10px; }
button {
  background: var(--brand);
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}
button:hover { opacity: 0.9; }
form { display: flex; flex-direction: column; gap: 12px; max-width: 420px; }
input, textarea {
  padding: 10px 12px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 14px;
  font-family: inherit;
}
.cart-row { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #eee; }
.total-row { display: flex; justify-content: space-between; font-weight: 700; margin-top: 12px; font-size: 18px; }
.msg { padding: 10px; border-radius: 6px; margin-top: 10px; }
.msg.ok { background: #dcfce7; color: #166534; }
.msg.err { background: #fee2e2; color: #991b1b; }
"""

NAV_HTML = """\
<nav>
  <span class="brand">{business_name}</span>
  <a href="/">Home</a>
  <a href="/products.html">Products</a>
  <a href="/cart.html">Cart</a>
  <a href="/contact.html">Contact</a>
</nav>
"""

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{business_name}</title>
  <link rel="stylesheet" href="/style.css" />
</head>
<body>
{nav}
  <main>
    <div class="hero">
      <h1>{business_name}</h1>
      <p>{tagline}</p>
      <p>{description}</p>
      <a href="/products.html"><button>Shop now</button></a>
    </div>
  </main>
</body>
</html>
"""

PRODUCTS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Products - {business_name}</title>
  <link rel="stylesheet" href="/style.css" />
</head>
<body>
{nav}
  <main>
    <h1>Products</h1>
    <div class="grid" id="grid">Loading...</div>
  </main>
  <script>
    fetch('/api/products').then(r => r.json()).then(products => {{
      const grid = document.getElementById('grid');
      grid.innerHTML = '';
      products.forEach(p => {{
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
          <div class="emoji">${{p.emoji}}</div>
          <h3>${{p.name}}</h3>
          <p>${{p.description}}</p>
          <div class="price">$${{p.price.toFixed(2)}}</div>
          <button onclick="addToCart(${{p.id}})">Add to cart</button>
        `;
        grid.appendChild(card);
      }});
    }});

    function addToCart(productId) {{
      fetch('/api/cart/add', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ product_id: productId, quantity: 1 }})
      }}).then(() => alert('Added to cart!'));
    }}
  </script>
</body>
</html>
"""

CART_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cart - {business_name}</title>
  <link rel="stylesheet" href="/style.css" />
</head>
<body>
{nav}
  <main>
    <h1>Your cart</h1>
    <div id="cart">Loading...</div>
    <div id="msg"></div>
  </main>
  <script>
    function loadCart() {{
      fetch('/api/cart').then(r => r.json()).then(data => {{
        const el = document.getElementById('cart');
        if (data.items.length === 0) {{
          el.innerHTML = '<p>Your cart is empty.</p>';
          return;
        }}
        el.innerHTML = data.items.map(i => `
          <div class="cart-row"><span>${{i.emoji}} ${{i.name}} x${{i.quantity}}</span><span>$${{(i.price * i.quantity).toFixed(2)}}</span></div>
        `).join('') + `
          <div class="total-row"><span>Total</span><span>$${{data.total.toFixed(2)}}</span></div>
          <button onclick="checkout()">Checkout</button>
        `;
      }});
    }}

    function checkout() {{
      fetch('/api/checkout', {{ method: 'POST' }}).then(r => r.json()).then(data => {{
        const msg = document.getElementById('msg');
        if (data.ok) {{
          msg.innerHTML = `<div class="msg ok">Order #${{data.order_id}} placed - $${{data.total.toFixed(2)}}</div>`;
          loadCart();
        }} else {{
          msg.innerHTML = `<div class="msg err">${{data.error}}</div>`;
        }}
      }});
    }}

    loadCart();
  </script>
</body>
</html>
"""

CONTACT_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Contact - {business_name}</title>
  <link rel="stylesheet" href="/style.css" />
</head>
<body>
{nav}
  <main>
    <h1>Contact us</h1>
    <form id="contact-form">
      <input type="text" name="name" placeholder="Your name" required />
      <input type="email" name="email" placeholder="Your email" required />
      <textarea name="message" placeholder="Your message" rows="5" required></textarea>
      <button type="submit">Send</button>
    </form>
    <div id="msg"></div>
  </main>
  <script>
    document.getElementById('contact-form').addEventListener('submit', function (e) {{
      e.preventDefault();
      const form = e.target;
      const payload = {{
        name: form.name.value,
        email: form.email.value,
        message: form.message.value,
      }};
      fetch('/api/contact', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload),
      }}).then(() => {{
        document.getElementById('msg').innerHTML = '<div class="msg ok">Message sent - thank you!</div>';
        form.reset();
      }});
    }});
  </script>
</body>
</html>
"""

INIT_SQL = """\
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    description TEXT,
    emoji VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS contact_messages (
    id SERIAL PRIMARY KEY,
    name VARCHAR(150),
    email VARCHAR(255),
    message TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cart_items (
    id SERIAL PRIMARY KEY,
    cart_id VARCHAR(64) NOT NULL,
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    cart_id VARCHAR(64) NOT NULL,
    total NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO products (name, price, description, emoji) VALUES
{seed_rows};
"""


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def generate_site(business_name: str, description: str) -> dict:
    """Returns {relative_path: file_contents} for the generated app, plus
    metadata (category) the caller needs for seeding/labels."""

    category = detect_category(description)
    info = CATEGORIES[category]

    seed_rows = ",\n".join(
        f"('{_sql_escape(n)}', {p}, '{_sql_escape(d)}', '{e}')"
        for (n, p, d, e) in info["products"]
    )

    nav = NAV_HTML.format(business_name=business_name)
    common = dict(
        business_name=business_name,
        description=description,
        tagline=info["tagline"],
        nav=nav,
    )

    files = {
        "Dockerfile": DOCKERFILE,
        "requirements.txt": REQUIREMENTS,
        "main.py": MAIN_PY.format(business_name=business_name),
        "static/style.css": STYLE_CSS,
        "static/index.html": INDEX_HTML.format(**common),
        "static/products.html": PRODUCTS_HTML.format(**common),
        "static/cart.html": CART_HTML.format(**common),
        "static/contact.html": CONTACT_HTML.format(**common),
    }
    init_sql = INIT_SQL.format(seed_rows=seed_rows)

    return {"files": files, "init_sql": init_sql, "category": category}
