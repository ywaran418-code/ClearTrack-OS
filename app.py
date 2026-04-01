import os
import sqlite3
import io
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from flask import send_file

app = Flask(__name__)
app.secret_key = 'super_secret_payroll_key'

# Change it to look like this:
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static/uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Change your get_db function to look like this:
def get_db():
    db_path = os.path.join(BASE_DIR, 'database.db')
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT, full_name TEXT, job_title TEXT, profile_pic TEXT, managed_by INTEGER, base_salary REAL DEFAULT 15000, monthly_target INTEGER DEFAULT 20)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT, assigned_to TEXT, assigned_by TEXT, status TEXT, start_time TEXT, end_time TEXT, proof_file TEXT, salary REAL, tl_remark TEXT, bonus_amount REAL DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS leaves (id INTEGER PRIMARY KEY, username TEXT, leave_date TEXT, reason TEXT, status TEXT, leave_type TEXT, tl_message TEXT, hr_message TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY, username TEXT, punch_time TEXT, status TEXT)''')

        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            for i in range(1, 4):
                cursor.execute("INSERT INTO users (id, username, password, role, full_name, job_title, base_salary, monthly_target) VALUES (?, ?, '123', 'HR', ?, 'HR Manager', 50000, 0)", (i, f'hr{i}', f'HR Executive {i}'))
            for i in range(1, 6):
                tl_id = i + 3
                cursor.execute("INSERT INTO users (id, username, password, role, full_name, job_title, base_salary, monthly_target) VALUES (?, ?, '123', 'TL', ?, 'Team Lead', 25000, 15)", (tl_id, f'tl{i}', f'Team Lead {i}'))
            emp_id = 9
            emp_number = 1
            for tl_num in range(1, 6):
                tl_id = tl_num + 3
                for e in range(1, 11):
                    cursor.execute("INSERT INTO users (id, username, password, role, full_name, job_title, base_salary, monthly_target, managed_by) VALUES (?, ?, '123', 'Employee', ?, 'Developer', 15000, 20, ?)", (emp_id, f'emp{emp_number}', f'Employee {emp_number}', tl_id))
                    emp_id += 1
                    emp_number += 1
            db.commit()

init_db()

def get_current_user():
    if 'user' in session:
        cursor = get_db().cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (session['user'],))
        return cursor.fetchone()
    return None

# --- AUTH & PROFILE ---
@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        cursor = get_db().cursor()
        cursor.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = cursor.fetchone()
        if user:
            session['user'] = user['username']
            if user['role'] == 'HR': return redirect(url_for('hr'))
            if user['role'] == 'TL': return redirect(url_for('tl'))
            return redirect(url_for('employee'))
        return render_template('login.html', error="Invalid Credentials")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user = get_current_user()
    if not user: return redirect(url_for('home'))
    if request.method == 'POST':
        full_name = request.form['full_name']
        password = request.form['password']
        db = get_db()
        db.execute("UPDATE users SET full_name=?, password=? WHERE id=?", (full_name, password, user['id']))
        db.commit()
        return render_template('profile.html', user=user, success="Profile updated successfully!")
    return render_template('profile.html', user=user)

@app.route('/punch_biometric')
def punch_biometric():
    if 'user' not in session: return "Error", 403
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO attendance (username, punch_time, status) SELECT ?, ?, 'Present' WHERE NOT EXISTS (SELECT 1 FROM attendance WHERE username=? AND punch_time LIKE ?)", (session['user'], now, session['user'], f'{today}%'))
    db.commit()
    return "Success", 200

# --- EMPLOYEE ROUTES ---
@app.route('/employee')
def employee():
    user = get_current_user()
    if not user or user['role'] != 'Employee': return redirect(url_for('home'))
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("SELECT * FROM tasks WHERE assigned_to=?", (user['username'],))
    tasks = cursor.fetchall()
    
    pending_count = sum(1 for t in tasks if t['status'] == 'Pending' or t['status'] == 'In Progress')
    submitted_count = sum(1 for t in tasks if t['status'] == 'Submitted')
    done_count = sum(1 for t in tasks if t['status'] == 'Completed')
    
    cursor.execute("SELECT * FROM leaves WHERE username=?", (user['username'],))
    my_leaves = cursor.fetchall()
    
    return render_template('employee.html', user=user, tasks=tasks, my_leaves=my_leaves, 
                           pending_count=pending_count, submitted_count=submitted_count, done_count=done_count)

@app.route('/start_task/<int:task_id>')
def start_task(task_id):
    db = get_db()
    db.execute("UPDATE tasks SET status='In Progress', start_time=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id))
    db.commit()
    return redirect('https://docs.google.com/spreadsheets/')

@app.route('/submit_task/<int:task_id>', methods=['POST'])
def submit_task(task_id):
    file = request.files.get('proof')
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        db = get_db()
        db.execute("UPDATE tasks SET status='Submitted', end_time=?, proof_file=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), filename, task_id))
        db.commit()
    return redirect(url_for('employee'))

@app.route('/apply_leave', methods=['POST'])
def apply_leave():
    db = get_db()
    db.execute("INSERT INTO leaves (username, leave_date, reason, status, leave_type) VALUES (?, ?, ?, 'Pending TL', ?)", (session['user'], request.form['date'], request.form['reason'], 'Emergency' if 'is_emergency' in request.form else 'Normal'))
    db.commit()
    return redirect(url_for('employee'))

# --- TL DASHBOARD ---
@app.route('/tl')
def tl():
    user = get_current_user()
    if not user or user['role'] != 'TL': return redirect(url_for('home'))
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("SELECT * FROM users WHERE managed_by=?", (user['id'],))
    my_employees = cursor.fetchall()
    
    emp_stats = []
    chart_labels = []
    chart_data = []
    
    for emp in my_employees:
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status='Completed'", (emp['username'],))
        done = cursor.fetchone()[0]
        emp_stats.append({'name': emp['full_name'], 'username': emp['username'], 'done': done, 'target': emp['monthly_target']})
        chart_labels.append(emp['full_name'])
        chart_data.append(done)
        
    cursor.execute("SELECT * FROM tasks WHERE assigned_by=? AND status != 'Completed'", (user['username'],))
    tasks = cursor.fetchall()
    
    cursor.execute("SELECT * FROM tasks WHERE assigned_by=? AND status='Completed'", (user['username'],))
    task_history = cursor.fetchall()
    
    cursor.execute("SELECT * FROM leaves WHERE status='Pending TL'")
    leave_requests = cursor.fetchall()
    
    emp_usernames = [e['username'] for e in my_employees]
    leave_history = []
    if emp_usernames:
        placeholders = ','.join(['?'] * len(emp_usernames))
        cursor.execute(f"SELECT * FROM leaves WHERE username IN ({placeholders}) AND status != 'Pending TL'", emp_usernames)
        leave_history = cursor.fetchall()
        
    return render_template('tl.html', user=user, employees=my_employees, tasks=tasks, task_history=task_history, 
                           leave_requests=leave_requests, leave_history=leave_history, emp_stats=emp_stats,
                           chart_labels=json.dumps(chart_labels), chart_data=json.dumps(chart_data))

@app.route('/assign_task', methods=['POST'])
def assign_task():
    db = get_db()
    db.execute("INSERT INTO tasks (title, assigned_to, assigned_by, status, bonus_amount) VALUES (?, ?, ?, 'Pending', 0)", (request.form['title'], request.form['assigned_to'], session['user']))
    db.commit()
    return redirect(url_for('tl'))

@app.route('/task_action/<int:task_id>/<action>', methods=['POST'])
def task_action(task_id, action):
    remark = request.form.get('remark', '') 
    db = get_db()
    cursor = db.cursor()
    if action == 'reject':
        # BUG FIX: Sets status back to Pending so the employee can start it again
        db.execute("UPDATE tasks SET status='Pending', end_time=NULL, tl_remark=? WHERE id=?", (f"REJECTED: {remark}", task_id))
    elif action == 'approve':
        cursor.execute("SELECT start_time, end_time FROM tasks WHERE id=?", (task_id,))
        times = cursor.fetchone()
        bonus = 0
        if times and times[0] and times[1]:
            try:
                start = datetime.strptime(times[0], "%Y-%m-%d %H:%M:%S")
                end = datetime.strptime(times[1], "%Y-%m-%d %H:%M:%S")
                bonus = (12.0 - ((end - start).total_seconds() / 3600)) * 50 
            except: pass
        db.execute("UPDATE tasks SET status='Completed', salary=0, bonus_amount=?, tl_remark=? WHERE id=?", (bonus, f"APPROVED: {remark}", task_id))
    db.commit()
    return redirect(url_for('tl'))

@app.route('/tl_leave_action/<int:leave_id>/<action>', methods=['POST'])
def tl_leave_action(leave_id, action):
    status = 'Forwarded to HR' if action == 'approve' else 'Rejected by TL'
    db = get_db()
    db.execute("UPDATE leaves SET status=?, tl_message=? WHERE id=?", (status, request.form.get('msg', ''), leave_id))
    db.commit()
    return redirect(url_for('tl'))

# --- HR DASHBOARD ---
@app.route('/hr')
def hr():
    user = get_current_user()
    if not user or user['role'] != 'HR': return redirect(url_for('home'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE role='TL'")
    tls = cursor.fetchall()
    
    hierarchy_data = []
    hr_chart_labels = []
    hr_chart_data = []
    
    for tl in tls:
        cursor.execute("SELECT * FROM users WHERE managed_by=?", (tl['id'],))
        emps = cursor.fetchall()
        emp_data = []
        team_total_tasks = 0
        for emp in emps:
            base_salary = emp['base_salary'] if emp['base_salary'] else 15000 
            target = emp['monthly_target'] if emp['monthly_target'] else 20   
            cursor.execute("SELECT COUNT(*), SUM(bonus_amount) FROM tasks WHERE assigned_to=? AND status='Completed'", (emp['username'],))
            stats = cursor.fetchone()
            count = stats[0] or 0
            team_total_tasks += count
            bonus = max(0, stats[1] or 0)
            earned = (count / target) * base_salary if target > 0 else base_salary
            if earned > base_salary: earned = base_salary
            emp_data.append({'id': emp['id'], 'name': emp['full_name'], 'role': emp['job_title'], 'salary': round(earned + bonus, 2), 'tasks_done': f"{count}/{target}", 'bonus': round(bonus, 2)})
            
        hierarchy_data.append({'tl_name': tl['full_name'], 'employees': emp_data})
        hr_chart_labels.append(tl['full_name'])
        hr_chart_data.append(team_total_tasks)
        
    cursor.execute("SELECT * FROM leaves WHERE status='Forwarded to HR'")
    hr_leaves = cursor.fetchall()
    
    return render_template('hr.html', user=user, hierarchy=hierarchy_data, hr_leaves=hr_leaves,
                           chart_labels=json.dumps(hr_chart_labels), chart_data=json.dumps(hr_chart_data))

@app.route('/hr_leave_action/<int:leave_id>/<action>', methods=['POST'])
def hr_leave_action(leave_id, action):
    status = 'Approved' if action == 'approve' else 'Rejected by HR'
    db = get_db()
    db.execute("UPDATE leaves SET status=?, hr_message=? WHERE id=?", (status, request.form.get('msg', ''), leave_id))
    db.commit()
    return redirect(url  _for('hr'))

@app.route('/download_payslip/<int:emp_id>')
def download_payslip(emp_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id=?", (emp_id,))
    emp = cursor.fetchone()
    base_salary = emp['base_salary'] if emp['base_salary'] else 15000 
    target = emp['monthly_target'] if emp['monthly_target'] else 20
    cursor.execute("SELECT COUNT(*), SUM(bonus_amount) FROM tasks WHERE assigned_to=? AND status='Completed'", (emp['username'],))
    stats = cursor.fetchone()
    count = stats[0] or 0
    bonus = max(0, stats[1] or 0)
    earned = (count / target) * base_salary if target > 0 else base_salary
    if earned > base_salary: earned = base_salary
    
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 20)
    p.drawString(200, 750, "OFFICIAL SALARY SLIP")
    p.setFont("Helvetica", 12)
    p.drawString(50, 700, "-"*90)
    p.drawString(50, 680, f"Employee Name: {emp['full_name']}")
    p.drawString(50, 660, f"Job Title:     {emp['job_title']}")
    p.drawString(50, 640, f"Employee ID:   {emp['id']}")
    p.drawString(50, 620, "-"*90)
    p.drawString(50, 580, "EARNINGS:")
    p.drawString(50, 560, f"Base Salary Earned: Rs. {round(earned, 2)} ({count}/{target} Tasks)")
    p.drawString(50, 540, f"Performance Bonus:  Rs. {round(bonus, 2)}")
    p.drawString(50, 520, "-"*90)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, 480, f"NET PAYABLE:   Rs. {round(earned + bonus, 2)}")
    p.setFont("Helvetica-Oblique", 10)
    p.drawString(50, 400, "* Computer-generated document. No signature required.")
    p.showPage()
    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Payslip_{emp['username']}.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True)