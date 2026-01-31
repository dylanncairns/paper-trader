import sqlite3
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from market import lookup


# Configure application
app = Flask(__name__)

# Configure session to use filesystem instead of signed cookies - server side session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Format currency as USD
@app.template_filter("usd")
def usd(value):
    return f"${value:,.2f}"

# Connect to SQLite database
def get_connection():
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    return conn

# Ensure responses are not cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Decorator to require login for route access
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

# Error message
def error(message):
    return render_template("error.html", message=(message))



# Register new user
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return error("must provide username")

        # Ensure password was submitted
        elif not request.form.get("password"):
            return error("must provide password")

        elif not request.form.get("confirmation"):
            return error("must confirm password")

        elif not (request.form.get("confirmation") == (request.form.get("password"))):
            return error("passwords must match")

        # Ensure username is not taken
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (request.form.get("username"),)
            ).fetchall()
            if len(rows) != 0:
                return error("username is taken")
        
        # Insert new user into database
        with get_connection() as conn:
            rows = conn.execute(
                "INSERT INTO users (username, hash) VALUES (?, ?)",
                (request.form.get("username"), generate_password_hash(request.form.get("password")))
            )
            flash("Registration successful!")
            return redirect("/login")

    # User reached via GET
    else:
        return render_template("register.html")


# User login
@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()
    # If user submitted form to log in
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return error("must provide username")

        # Ensure password was submitted
        elif not request.form.get("password"):
            return error("must provide password")

        # Query database for username
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (request.form.get("username"),)
            ).fetchone()

        # Ensure username exists and password is correct
        if row is None or not check_password_hash(row["hash"], request.form.get("password")):
            return error("invalid username and/or password")

        # Remember which user is logged in
        session["user_id"] = row["id"]

        # Redirect to home page
        return redirect("/")

    # If user just viewing page
    else:
        return render_template("login.html")


# Log user out and return to login display
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# Home page portfolio display
@app.route("/")
@login_required
def index():
    with get_connection() as conn:
        row = conn.execute(
            "SELECT cash FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()
        cash = row["cash"]
        rows = conn.execute(
            "SELECT stocksymbol, SUM(numshares) AS numshares FROM transactions WHERE user_id = ? GROUP BY stocksymbol HAVING SUM(numshares) > 0 ORDER BY stocksymbol;",
            (session["user_id"],)
        ).fetchall()
        owned = []
        total = 0.0
        for r in rows:
            updated = lookup(r["stocksymbol"])
            if updated is None:
                continue
            currentprice = updated["price"]
            value = currentprice * r["numshares"]
            total += value
            owned.append(
                {"stocksymbol": r["stocksymbol"],
                 "numshares": r["numshares"],
                 "currentprice": currentprice,
                 "value": value
                 }
            )
        total += cash
        return render_template("index.html", cash=cash, owned=owned, total=total)
    

# Get a quote for a stock symbol
@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    # If form submitted then validate and return info associated with ticker
    if request.method == "POST":
        if not request.form.get("symbol"):
            return error("must provide symbol")
        stock = lookup(request.form.get("symbol"))
        if stock == None:
            return error("invalid symbol")
        return render_template("quoted.html", name=stock["name"], symbol=stock["symbol"], price=stock["price"])
    else:
        return render_template("quote.html")
    

# Purchase shares of stock via search
@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    if request.method == "POST":
        # Ensure symbol was provided
        if not request.form.get("symbol"):
            return error("must provide symbol")
        if not request.form.get("shares") or not request.form.get("shares").isdigit():
            return error("enter a valid number of shares")

        # Look up stock and validate input 
        stock = lookup(request.form.get("symbol"))
        sharess = int(float(request.form.get("shares")))
        if stock == None:
            return error("invalid symbol")
        if (sharess <= 0):
            return error("enter a valid number of shares")
        
        # If proper input then buy shares and update user cash
        with get_connection() as conn:
            row = conn.execute(
                "SELECT cash FROM users WHERE id = ?",
                (session["user_id"],)
            ).fetchone()
            usercash = row["cash"]
            purchaseprice = stock["price"] * sharess
            if (usercash < purchaseprice):
                return error("price exceeds current cash amount")
            conn.execute(
                "INSERT INTO transactions (user_id, stocksymbol, numshares, price_cents) VALUES (?, ?, ?, ?)",
                (session["user_id"], stock["symbol"], sharess, (stock["price"] * 100))
                )
            conn.execute(
                "UPDATE users SET cash = ? WHERE ID = ?",
                ((usercash - purchaseprice), session["user_id"])
            )
            flash("Bought!")
            return redirect("/")
    else:
        return render_template("buy.html")


# Sell shares of a stock from list of owned stocks
@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    # Populate dropdown
    with get_connection() as conn:
        row = conn.execute(
            "SELECT cash FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()
        cash = row["cash"]
        rows = conn.execute(
            "SELECT stocksymbol, SUM(numshares) AS numshares FROM transactions WHERE user_id = ? GROUP BY stocksymbol HAVING SUM(numshares) > 0 ORDER BY stocksymbol;",
            (session["user_id"],)
        ).fetchall()
        owned = []
        for r in rows:
            updated = lookup(r["stocksymbol"])
            if updated is None:
                continue
            currentprice = updated["price"]
            value = currentprice * r["numshares"]
            owned.append({"stocksymbol": r["stocksymbol"], "numshares": r["numshares"], "currentprice": currentprice, "value": value})

    # Validate input and process sale of shares
    if request.method == "POST":
        # Ensure symbol was provided
        if not request.form.get("symbol"):
            return error("must provide symbol")
        if not request.form.get("shares"):
            return error("enter a valid number of shares")
        stock = lookup(request.form.get("symbol"))
        sharess = int(request.form.get("shares"))
        if stock == None:
            return error("invalid symbol")
        if (sharess <= 0):
            return error("enter a valid number of shares")

        usersharesowned = 0
        for item in owned:
            if item["stocksymbol"].upper() == request.form.get("symbol"):
                usersharesowned = item["numshares"]
                break
        sellprice = stock["price"] * sharess
        if (usersharesowned < sharess):
            return error("number exceeds currently owned shares")
        
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO transactions (user_id, stocksymbol, numshares, price_cents) VALUES (?, ?, ?, ?)",
                (session["user_id"], stock["symbol"], (sharess * -1), (stock["price"] * 100))
            )
            conn.execute(
                "UPDATE users SET cash = ? WHERE ID = ?",
                (cash + sellprice, session["user_id"])
            )
        flash("Sold!")
        return redirect("/")
    else:
        return render_template("sell.html", owned=owned)


# User transaction history display
@app.route("/history")
@login_required
def history():
    with get_connection() as conn:
        history = []
        rows = conn.execute(
            "SELECT stocksymbol, numshares, price_cents, transacted_at FROM transactions WHERE user_id = ? ORDER BY id;",
            (session["user_id"],)
        ).fetchall()
        for r in rows:
            history.append(
                {"stocksymbol": r["stocksymbol"],
                 "numshares": r["numshares"],
                 "price": r["price_cents"] / 100,
                 "time": r["transacted_at"]
                }
            )
        return render_template("history.html", history=history)


# Add money to portifolio cash balance
@app.route("/addcash", methods=["GET", "POST"])
@login_required
def addcash():
    if request.method == "POST":
        if not (request.form.get("option") == 'yes'):
            return error("must fill out form correctly")
        with get_connection() as conn:
            row = conn.execute(
                "SELECT cash FROM users WHERE id = ?",
                (session["user_id"],)
            ).fetchone()
            cash = row["cash"]
            cash += 1
            conn.execute(
                "UPDATE users SET cash = ? WHERE ID = ?",
                (cash, session["user_id"])
            )
            flash("Redeemed!")
            return redirect("/")
    else:
        return render_template("addcash.html")


if __name__ == "__main__":
    app.run(debug=True)