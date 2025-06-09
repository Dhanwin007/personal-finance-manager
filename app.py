from decimal import Decimal
import math
from flask import Flask, render_template, request, redirect, session, flash
from flask_mysqldb import MySQL
import MySQLdb.cursors
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# ---------- MySQL Config ----------
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Dhanu@2005'
app.config['MYSQL_DB'] = 'findb'

mysql = MySQL(app)

# ---------- AUTH ----------
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect('/dashboard')
        flash("Invalid credentials", "danger")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm = request.form['confirm_password']
        if password != confirm:
            flash("Passwords do not match", "danger")
            return redirect('/register')
        hashed_pw = generate_password_hash(password)
        cursor = mysql.connection.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_pw))
            mysql.connection.commit()
            flash("Account created. Please login.", "success")
            return redirect('/login')
        except:
            flash("Username already exists", "danger")
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully", "info")
    return redirect('/login')

# ---------- DASHBOARD ----------
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Income & Expense totals
    cursor.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM income WHERE user_id=%s", (user_id,))
    total_income = cursor.fetchone()['total']

    cursor.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE user_id=%s", (user_id,))
    total_expense = cursor.fetchone()['total']

    savings = total_income - total_expense

    # Expense by category
    cursor.execute("SELECT category, SUM(amount) AS total FROM expenses WHERE user_id=%s GROUP BY category", (user_id,))
    expense_categories = cursor.fetchall()

    # Budgets
    cursor.execute("SELECT * FROM budget WHERE user_id=%s", (user_id,))
    budgets = cursor.fetchall()

    # Budget Warnings
    budget_warnings = []
    for b in budgets:
        for e in expense_categories:
            if b['category'] == e['category'] and float(e['total']) > float(b['limit_amount']):
                budget_warnings.append(f"{b['category']} exceeded its budget of ₹{b['limit_amount']}")

    # Reminders
    cursor.execute("SELECT * FROM reminders WHERE user_id=%s AND is_completed=0 ORDER BY remind_date ASC", (user_id,))
    reminders = cursor.fetchall()

    # Savings Goals
    cursor.execute("SELECT * FROM savings WHERE user_id=%s", (user_id,))
    savings_goals = cursor.fetchall()

    # Monthly Income vs Expenses
    cursor.execute("""
        SELECT DATE_FORMAT(date, '%%b %%Y') AS month,
               SUM(CASE WHEN t = 'income' THEN amount ELSE 0 END) AS income,
               SUM(CASE WHEN t = 'expense' THEN amount ELSE 0 END) AS expense
        FROM (
            SELECT 'income' AS t, amount, date FROM income WHERE user_id = %s
            UNION ALL
            SELECT 'expense', amount, date FROM expenses WHERE user_id = %s
        ) AS combined
        GROUP BY month
        ORDER BY STR_TO_DATE(month, '%%b %%Y') ASC
    """, (user_id, user_id))
    monthly_trends = cursor.fetchall()

    # Monthly Expense Growth (cumulative sum by date)
    cursor.execute("""
        SELECT date,
               SUM(amount) AS daily_expense,
               (SELECT SUM(amount) FROM expenses e2 WHERE e2.user_id = %s AND e2.date <= e1.date) AS cumulative_expense
        FROM expenses e1
        WHERE user_id = %s
        GROUP BY date
        ORDER BY date ASC
    """, (user_id, user_id))
    expense_growth = cursor.fetchall()

    # Fetch individual expenses for listing
    cursor.execute("""
        SELECT id, category, description, amount, date
        FROM expenses
        WHERE user_id = %s
        ORDER BY date DESC
    """, (user_id,))
    expenses = cursor.fetchall()

    return render_template('dashboard.html',
                           total_income=total_income,
                           total_expense=total_expense,
                           savings=savings,
                           expense_categories=expense_categories,
                           budgets=budgets,
                           reminders=reminders,
                           savings_goals=savings_goals,
                           budget_warnings=budget_warnings,
                           current_month=datetime.now().strftime('%B %Y'),
                           monthly_trends=monthly_trends,
                           datetime=datetime,
                           expenses=expenses)

# ---------- FORM HANDLERS ----------
@app.route('/add_income', methods=['POST'])
def add_income():
    if 'user_id' not in session:
        return redirect('/')
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO income (user_id, source, amount, date, notes) VALUES (%s, %s, %s, %s, %s)", (
        session['user_id'], request.form['source'], request.form['amount'], request.form['date'], request.form.get('notes')
    ))
    mysql.connection.commit()
    return redirect('/dashboard')

from decimal import Decimal

@app.route('/add_expense', methods=['POST'])
def add_expense():
    if 'user_id' not in session:
        return redirect('/')
    user_id = session['user_id']
    category = request.form['category']
    description = request.form.get('description', '')
    amount_str = request.form['amount']
    date_str = request.form['date']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        amount = Decimal(amount_str)
    except:
        flash("Invalid amount value.", "danger")
        return redirect('/dashboard')

    # Get current total expense for the category
    cursor.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE user_id=%s AND category=%s", (user_id, category))
    current_total = cursor.fetchone()['total']

    # Ensure current_total is Decimal
    if not isinstance(current_total, Decimal):
        current_total = Decimal(current_total)

    # Get budget limit for the category
    cursor.execute("SELECT limit_amount FROM budget WHERE user_id=%s AND category=%s", (user_id, category))
    budget = cursor.fetchone()

    if budget:
        limit_amount = Decimal(budget['limit_amount'])
        if (current_total + amount) > limit_amount:
            flash(f"Expense exceeds the budget limit of ₹{budget['limit_amount']} for category {category}. Expense not added.", "danger")
            return redirect('/dashboard')

    # Insert expense if within budget
    try:
        cursor.execute("INSERT INTO expenses (user_id, category, description, amount, date) VALUES (%s, %s, %s, %s, %s)", (
            user_id, category, description, amount, date_str
        ))
        mysql.connection.commit()
    except Exception as e:
        flash(f"Error adding expense: {str(e)}", "danger")
        return redirect('/dashboard')

    return redirect('/dashboard')


@app.route('/add_budget', methods=['POST'])
def add_budget():
    if 'user_id' not in session:
        return redirect('/')
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO budget (user_id, category, limit_amount) VALUES (%s, %s, %s)", (
        session['user_id'], request.form['category'], request.form['limit_amount']
    ))
    mysql.connection.commit()
    return redirect('/dashboard')

@app.route('/add_reminder', methods=['POST'])
def add_reminder():
    if 'user_id' not in session:
        return redirect('/')
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO reminders (user_id, note, remind_date) VALUES (%s, %s, %s)", (
        session['user_id'], request.form['note'], request.form['remind_date']
    ))
    mysql.connection.commit()
    return redirect('/dashboard')

@app.route('/complete_reminder/<int:id>', methods=['POST'])
def complete_reminder(id):
    if 'user_id' not in session:
        return redirect('/')
    cursor = mysql.connection.cursor()
    cursor.execute("UPDATE reminders SET is_completed=1 WHERE id=%s AND user_id=%s", (id, session['user_id']))
    mysql.connection.commit()
    return redirect('/dashboard')

@app.route('/delete_reminder/<int:id>', methods=['POST'])
def delete_reminder(id):
    if 'user_id' not in session:
        return redirect('/')
    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM reminders WHERE id=%s AND user_id=%s", (id, session['user_id']))
    mysql.connection.commit()
    return redirect('/dashboard')

@app.route('/add_savings_goal', methods=['POST'])
def add_savings_goal():
    if 'user_id' not in session:
        return redirect('/')
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO savings (user_id, goal, target_amount, target_date) VALUES (%s, %s, %s, %s)", (
        session['user_id'], request.form['goal'], request.form['target_amount'], request.form['target_date']
    ))
    mysql.connection.commit()
    return redirect('/dashboard')

@app.route('/update_savings/<int:id>', methods=['POST'])
def update_savings(id):
    if 'user_id' not in session:
        return redirect('/')
    cursor = mysql.connection.cursor()
    cursor.execute("UPDATE savings SET current_amount = current_amount + %s WHERE id = %s AND user_id = %s", (
        request.form['amount'], id, session['user_id']
    ))
    mysql.connection.commit()
    return redirect('/dashboard')

import pdfkit
from flask import make_response

@app.route('/report')
def report():
    if 'user_id' not in session:
        return redirect('/login')
    user_id = session['user_id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch monthly income and expenses for the report
    cursor.execute("""
        SELECT DATE_FORMAT(date, '%%b %%Y') AS month,
               SUM(CASE WHEN t = 'income' THEN amount ELSE 0 END) AS income,
               SUM(CASE WHEN t = 'expense' THEN amount ELSE 0 END) AS expense
        FROM (
            SELECT 'income' AS t, amount, date FROM income WHERE user_id = %s
            UNION ALL
            SELECT 'expense', amount, date FROM expenses WHERE user_id = %s
        ) AS combined
        GROUP BY month
        ORDER BY STR_TO_DATE(month, '%%b %%Y') ASC
    """, (user_id, user_id))
    monthly_report = cursor.fetchall()

    return render_template('report.html', monthly_report=monthly_report)

@app.route('/report/pdf')
def report_pdf():
    if 'user_id' not in session:
        return redirect('/login')
    user_id = session['user_id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch monthly income and expenses for the report
    cursor.execute("""
        SELECT DATE_FORMAT(date, '%%b %%Y') AS month,
               SUM(CASE WHEN t = 'income' THEN amount ELSE 0 END) AS income,
               SUM(CASE WHEN t = 'expense' THEN amount ELSE 0 END) AS expense
        FROM (
            SELECT 'income' AS t, amount, date FROM income WHERE user_id = %s
            UNION ALL
            SELECT 'expense', amount, date FROM expenses WHERE user_id = %s
        ) AS combined
        GROUP BY month
        ORDER BY STR_TO_DATE(month, '%%b %%Y') ASC
    """, (user_id, user_id))
    monthly_report = cursor.fetchall()

    rendered = render_template('report.html', monthly_report=monthly_report, pdf=True)
    # Configure pdfkit options
    options = {
        'page-size': 'A4',
        'encoding': 'UTF-8',
        'no-outline': None
    }
    pdf = pdfkit.from_string(rendered, False, options=options)

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=monthly_report.pdf'
    return response

from flask import render_template

@app.route('/settings')
def settings():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('settings.html')

@app.route('/delete_budget/<int:id>', methods=['POST'])
def delete_budget(id):
    if 'user_id' not in session:
        return redirect('/login')
    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM budget WHERE id=%s AND user_id=%s", (id, session['user_id']))
    mysql.connection.commit()
    return redirect('/dashboard')

@app.route('/delete_expense/<int:id>', methods=['POST'])
def delete_expense(id):
    if 'user_id' not in session:
        return redirect('/login')
    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM expenses WHERE id=%s AND user_id=%s", (id, session['user_id']))
    mysql.connection.commit()
    return redirect('/dashboard')

if __name__ == '__main__':
    app.run(debug=True)

