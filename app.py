import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Custom filter for currency formatting
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    user_id = session["user_id"]

    # Retrieve user's stock holdings, grouped by symbol
    stocks = db.execute(
        "SELECT symbol, SUM(shares) as total_shares FROM transactions WHERE user_id = ? GROUP BY symbol HAVING total_shares > 0",
        user_id,
    )

    # Retrieve current cash balance for user
    cash_db = db.execute("SELECT cash FROM users WHERE id = ?", user_id)
    cash = cash_db[0]["cash"]

    grand_total = cash

    # Update current stock prices and calculate total portfolio value
    for stock in stocks:
        quote = lookup(stock["symbol"])
        stock["name"] = quote["name"]
        stock["price"] = quote["price"]
        stock["total"] = stock["price"] * stock["total_shares"]
        grand_total += stock["total"]

    return render_template("index.html", stocks=stocks, cash=cash, grand_total=grand_total)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        # Validate inputs
        if not symbol:
            return apology("must provide symbol", 400)

        quote = lookup(symbol)
        if quote is None:
            return apology("invalid symbol", 400)

        try:
            shares = int(shares)
            if shares <= 0:
                return apology("shares must be a positive integer", 400)
        except ValueError:
            return apology("shares must be a positive integer", 400)

        user_id = session["user_id"]
        cost = quote["price"] * shares

        # Check user cash
        cash_db = db.execute("SELECT cash FROM users WHERE id = ?", user_id)
        user_cash = cash_db[0]["cash"]

        if user_cash < cost:
            return apology("cannot afford purchase", 400)

        # Update cash and record transaction
        db.execute("UPDATE users SET cash = cash - ? WHERE id = ?", cost, user_id)
        db.execute(
            "INSERT INTO transactions (user_id, symbol, shares, price, type) VALUES (?, ?, ?, ?, ?)",
            user_id,
            quote["symbol"],
            shares,
            quote["price"],
            "BUY",
        )

        flash("Bought successfully!")
        return redirect("/")
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    user_id = session["user_id"]
    transactions = db.execute(
        "SELECT symbol, shares, price, timestamp, type FROM transactions WHERE user_id = ? ORDER BY timestamp DESC",
        user_id,
    )
    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""
    session.clear()

    if request.method == "POST":
        if not request.form.get("username"):
            return apology("must provide username", 403)
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        session["user_id"] = rows[0]["id"]
        return redirect("/")
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""
    session.clear()
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        symbol = request.form.get("symbol")
        if not symbol:
            return apology("must provide symbol", 400)

        item = lookup(symbol)
        if item is None:
            return apology("invalid symbol", 400)

        return render_template("quoted.html", item=item)
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username:
            return apology("must provide username", 400)
        elif not password or not confirmation:
            return apology("must provide password and confirmation", 400)
        elif password != confirmation:
            return apology("passwords must match", 400)

        # Hash password and insert user into database
        hash_pass = generate_password_hash(password)
        try:
            db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, hash_pass)
        except ValueError:
            return apology("username already exists", 400)

        # Log in newly registered user automatically
        rows = db.execute("SELECT * FROM users WHERE username = ?", username)
        session["user_id"] = rows[0]["id"]

        flash("Registered successfully!")
        return redirect("/")
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    user_id = session["user_id"]

    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares = request.form.get("shares")

        if not symbol:
            return apology("must select symbol", 400)

        try:
            shares = int(shares)
            if shares <= 0:
                return apology("shares must be positive integer", 400)
        except ValueError:
            return apology("shares must be positive integer", 400)

        # Check total owned shares of selected symbol
        user_shares = db.execute(
            "SELECT SUM(shares) as total FROM transactions WHERE user_id = ? AND symbol = ? GROUP BY symbol",
            user_id,
            symbol,
        )

        if not user_shares or user_shares[0]["total"] < shares:
            return apology("too many shares", 400)

        quote = lookup(symbol)
        revenue = quote["price"] * shares

        # Update cash balance and record transaction (negative shares for selling)
        db.execute("UPDATE users SET cash = cash + ? WHERE id = ?", revenue, user_id)
        db.execute(
            "INSERT INTO transactions (user_id, symbol, shares, price, type) VALUES (?, ?, ?, ?, ?)",
            user_id,
            quote["symbol"],
            -shares,
            quote["price"],
            "SELL",
        )

        flash("Sold successfully!")
        return redirect("/")
    else:
        # Get user owned stocks for dropdown selection
        stocks = db.execute(
            "SELECT symbol FROM transactions WHERE user_id = ? GROUP BY symbol HAVING SUM(shares) > 0",
            user_id,
        )
        return render_template("sell.html", stocks=stocks)
