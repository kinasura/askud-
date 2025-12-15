from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file
import sqlite3
from datetime import datetime, time, timedelta
import os
import csv
import zipfile
import io
import traceback
from functools import wraps

# Дополнительные импорты
try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False
try:
    import pandas as pd
    HAS_PANDAS = True
    print("Pandas установлен. Экспорт в Excel будет доступен.")
except ImportError:
    HAS_PANDAS = False
    print("⚠️ Pandas не установлен. Экспорт в Excel будет недоступен.")
    print(" Установите: pip install pandas openpyxl")
app = Flask(__name__)
app.secret_key = 'askud_secret_key_2025'

# Конфигурация системы
MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 8
MIN_PASSWORD_LENGTH = 6

# Типы пользователей
USER_TYPE_EMPLOYEE = 'employee'
USER_TYPE_ADMIN = 'admin'


def init_database():
    """Инициализация базы данных с расширенной структурой"""
    conn = None
    cursor = None

    try:
        if os.path.exists('access_system.db'):
            # Не удаляем базу для сохранения данных
            print("📁 Используется существующая база данных")
            conn = sqlite3.connect('access_system.db')
            cursor = conn.cursor()

            # Проверяем наличие необходимых таблиц
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reports'")
            if not cursor.fetchone():
                print("⚠️  Таблица reports не найдена, создаём...")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        report_type TEXT NOT NULL,
                        period_start DATE,
                        period_end DATE,
                        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        file_path TEXT,
                        created_by INTEGER,
                        FOREIGN KEY (created_by) REFERENCES employees (id)
                    )
                ''')
                conn.commit()
                print("✅ Таблица reports создана")

            # Проверяем другие таблицы на случай, если база повреждена
            tables = ['employees', 'laboratories', 'access_events', 'current_presence']
            for table in tables:
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
                if not cursor.fetchone():
                    print(f"⚠️  Таблица {table} отсутствует! Возможно, база повреждена.")

            conn.close()
            return

        # Если базы нет - создаём новую
        conn = sqlite3.connect('access_system.db')
        cursor = conn.cursor()

        # Улучшенная таблица сотрудников с логинами и паролями
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                pin_code TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                department TEXT,
                position TEXT,
                phone TEXT,
                email TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                user_type TEXT DEFAULT 'employee',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS laboratories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                location TEXT,
                description TEXT,
                capacity INTEGER,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS access_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                laboratory_id INTEGER,
                days_of_week TEXT,
                time_start TIME,
                time_end TIME,
                FOREIGN KEY (employee_id) REFERENCES employees (id),
                FOREIGN KEY (laboratory_id) REFERENCES laboratories (id),
                UNIQUE(employee_id, laboratory_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS access_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                laboratory_id INTEGER,
                event_type TEXT NOT NULL,
                event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success BOOLEAN NOT NULL,
                reason TEXT,
                method TEXT DEFAULT 'pin',
                FOREIGN KEY (employee_id) REFERENCES employees (id),
                FOREIGN KEY (laboratory_id) REFERENCES laboratories (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS current_presence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER UNIQUE,
                laboratory_id INTEGER,
                entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expected_exit_time TIMESTAMP,
                FOREIGN KEY (employee_id) REFERENCES employees (id),
                FOREIGN KEY (laboratory_id) REFERENCES laboratories (id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                report_type TEXT NOT NULL,
                period_start DATE,
                period_end DATE,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                file_path TEXT,
                created_by INTEGER,
                FOREIGN KEY (created_by) REFERENCES employees (id)
            )
        ''')

        # Добавляем лаборатории
        laboratories = [
            ("Химическая лаборатория", "CHEM-001", "Корпус А, этаж 3, комн. 301",
             "Лаборатория химического анализа", 15, True),
            ("Биологическая лаборатория", "BIO-002", "Корпус Б, этаж 2, комн. 215",
             "Лаборатория биологических исследований", 10, True),
            ("Физическая лаборатория", "PHYS-003", "Корпус В, этаж 1, комн. 105",
             "Лаборатория физических измерений", 20, True),
            ("Компьютерный класс", "COMP-004", "Корпус Г, этаж 4, комн. 401",
             "Лаборатория программирования", 25, True),
            ("Серверная", "SERV-005", "Корпус А, цокольный этаж",
             "Помещение серверного оборудования", 5, True)
        ]

        cursor.executemany(
            "INSERT INTO laboratories (name, code, location, description, capacity, is_active) VALUES (?, ?, ?, ?, ?, ?)",
            laboratories
        )

        # Добавляем администратора по умолчанию
        cursor.execute(
            "INSERT INTO employees (login, password, pin_code, full_name, department, position, user_type, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("admin", "admin123", "0000", "Администратор Системы", "ИТ-отдел",
             "Системный администратор", "admin", True)
        )

        # Добавляем тестовых сотрудников
        employees = [
            ("ivanov", "ivanov123", "1234", "Иванов Иван Иванович",
             "Химическая лаборатория", "Инженер-химик", "employee", True),
            ("petrov", "petrov123", "5678", "Петров Петр Петрович",
             "Биологическая лаборатория", "Биолог", "employee", True),
            ("sidorova", "sidorova123", "9999", "Сидорова Анна Сергеевна",
             "Физическая лаборатория", "Физик-исследователь", "employee", True),
            ("smirnov", "smirnov123", "1111", "Смирнов Алексей Владимирович",
             "Компьютерный класс", "Программист", "employee", True)
        ]

        cursor.executemany(
            "INSERT INTO employees (login, password, pin_code, full_name, department, position, user_type, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            employees
        )

        # Назначаем права доступа
        access_schedules = [
            (2, 1, '0,1,2,3,4', '08:00', '20:00'),  # Сотрудник 2, лаборатория 1, пн-пт
            (3, 2, '0,1,2,3,4', '09:00', '18:00'),  # Сотрудник 3, лаборатория 2, пн-пт
            (4, 3, '0,2,4', '08:30', '17:30'),  # Сотрудник 4, лаборатория 3, пн, ср, пт
            (5, 4, '0,1,2,3,4', '10:00', '22:00'),  # Сотрудник 5, лаборатория 4, пн-пт
        ]

        cursor.executemany(
            "INSERT INTO access_schedules (employee_id, laboratory_id, days_of_week, time_start, time_end) VALUES (?, ?, ?, ?, ?)",
            access_schedules
        )

        conn.commit()
        print("✅ База данных инициализирована с расширенной структурой")

    except Exception as e:
        print(f"❌ Ошибка при инициализации базы данных: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


# Добавьте этот фильтр для Jinja2
@app.template_filter('split')
def split_filter(s, delimiter=','):
    """Разделение строки по разделителю"""
    if not s:
        return []
    return s.split(delimiter)


# Декоратор для проверки аутентификации
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


# Декоратор для проверки прав администратора
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_type' not in session or session['user_type'] != 'admin':
            flash('Требуются права администратора', 'danger')
            return redirect(url_for('index'))  # Или 'employee_dashboard'
        return f(*args, **kwargs)
    return decorated_function


# Функции работы с базой данных
def get_db_connection():
    conn = sqlite3.connect('access_system.db')
    conn.row_factory = sqlite3.Row
    return conn


def validate_credentials(login, password):
    """Проверка логина и пароля"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, full_name, user_type FROM employees WHERE login = ? AND password = ? AND is_active = TRUE",
        (login, password)
    )

    user = cursor.fetchone()
    conn.close()

    return dict(user) if user else None


def verify_access(employee_id, laboratory_id, method='pin'):
    """Проверка доступа сотрудника в лабораторию"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем текущее время и день недели
    now = datetime.now()
    current_time = now.time()
    day_of_week = now.weekday()  # 0 = понедельник

    # Проверяем расписание доступа
    cursor.execute('''
        SELECT time_start, time_end, days_of_week 
        FROM access_schedules 
        WHERE employee_id = ? AND laboratory_id = ?
    ''', (employee_id, laboratory_id))

    schedule = cursor.fetchone()

    if not schedule:
        # Логируем отказ в доступе
        cursor.execute(
            "INSERT INTO access_events (employee_id, laboratory_id, event_type, success, reason, method) VALUES (?, ?, 'entry', FALSE, 'Нет расписания доступа', ?)",
            (employee_id, laboratory_id, method)
        )
        conn.commit()
        conn.close()
        return False, "Доступ в эту лабораторию не разрешён"

    # Проверяем, разрешен ли доступ в текущий день недели
    days_allowed = schedule['days_of_week']
    if days_allowed:
        # Преобразуем строку дней в список
        allowed_days = [int(d) for d in days_allowed.split(',') if d.isdigit()]
        if day_of_week not in allowed_days:
            cursor.execute(
                "INSERT INTO access_events (employee_id, laboratory_id, event_type, success, reason, method) VALUES (?, ?, 'entry', FALSE, 'День недели не разрешен', ?)",
                (employee_id, laboratory_id, method)
            )
            conn.commit()
            conn.close()
            return False, f"Доступ в этот день недели не разрешен"

    time_start = time.fromisoformat(schedule['time_start'])
    time_end = time.fromisoformat(schedule['time_end'])

    # Проверяем временной интервал
    if not (time_start <= current_time <= time_end):
        cursor.execute(
            "INSERT INTO access_events (employee_id, laboratory_id, event_type, success, reason, method) VALUES (?, ?, 'entry', FALSE, 'Вне времени доступа', ?)",
            (employee_id, laboratory_id, method)
        )
        conn.commit()
        conn.close()
        return False, f"Доступ разрешён с {time_start.strftime('%H:%M')} до {time_end.strftime('%H:%M')}"

    # Проверяем, находится ли сотрудник уже внутри
    cursor.execute("SELECT id FROM current_presence WHERE employee_id = ?", (employee_id,))
    current_presence = cursor.fetchone()

    event_type = 'exit' if current_presence else 'entry'
    success = True
    message = "Выход выполнен" if current_presence else "Вход разрешён"

    if current_presence:
        # Выход из лаборатории
        cursor.execute("DELETE FROM current_presence WHERE employee_id = ?", (employee_id,))
    else:
        # Вход в лабораторию
        expected_exit = datetime.combine(now.date(), time_end)
        cursor.execute(
            "INSERT INTO current_presence (employee_id, laboratory_id, expected_exit_time) VALUES (?, ?, ?)",
            (employee_id, laboratory_id, expected_exit)
        )

    # Логируем событие
    cursor.execute(
        "INSERT INTO access_events (employee_id, laboratory_id, event_type, success, method) VALUES (?, ?, ?, ?, ?)",
        (employee_id, laboratory_id, event_type, success, method)
    )

    conn.commit()
    conn.close()
    return True, message


def get_statistics():
    """Получение статистики для дашборда"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Количество сотрудников
    cursor.execute("SELECT COUNT(*) FROM employees WHERE is_active = TRUE")
    employees_count = cursor.fetchone()[0]

    # Количество лабораторий
    cursor.execute("SELECT COUNT(*) FROM laboratories WHERE is_active = TRUE")
    labs_count = cursor.fetchone()[0]

    # Сейчас в лабораториях
    cursor.execute("SELECT COUNT(*) FROM current_presence")
    active_count = cursor.fetchone()[0]

    # Событий сегодня
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT COUNT(*) FROM access_events 
        WHERE DATE(event_time) = DATE(?)
    """, (today,))
    today_events = cursor.fetchone()[0]

    conn.close()

    return {
        'employees_count': employees_count,
        'labs_count': labs_count,
        'active_count': active_count,
        'today_events': today_events
    }


def migrate_old_data():
    """Миграция старых данных из старого формата в новый"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Проверяем, существует ли столбец day_of_week
        cursor.execute("PRAGMA table_info(access_schedules)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'day_of_week' in columns and 'days_of_week' not in columns:
            print("🔄 Обнаружена старая структура данных, начинаю миграцию...")

            # Создаем временную таблицу для группировки данных
            cursor.execute('''
                SELECT employee_id, laboratory_id, 
                       GROUP_CONCAT(day_of_week) as days_of_week,
                       time_start, time_end
                FROM access_schedules
                GROUP BY employee_id, laboratory_id, time_start, time_end
            ''')

            grouped_data = cursor.fetchall()

            # Создаем новую таблицу
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS access_schedules_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER,
                    laboratory_id INTEGER,
                    days_of_week TEXT,
                    time_start TIME,
                    time_end TIME,
                    FOREIGN KEY (employee_id) REFERENCES employees (id),
                    FOREIGN KEY (laboratory_id) REFERENCES laboratories (id),
                    UNIQUE(employee_id, laboratory_id)
                )
            ''')

            # Вставляем новые данные
            for row in grouped_data:
                cursor.execute('''
                    INSERT INTO access_schedules_new 
                    (employee_id, laboratory_id, days_of_week, time_start, time_end)
                    VALUES (?, ?, ?, ?, ?)
                ''', (row[0], row[1], row[2], row[3], row[4]))

            # Удаляем старую таблицу и переименовываем новую
            cursor.execute("DROP TABLE access_schedules")
            cursor.execute("ALTER TABLE access_schedules_new RENAME TO access_schedules")

            conn.commit()
            print("✅ Миграция данных завершена успешно")
        else:
            print("✅ Структура данных уже обновлена")

    except Exception as e:
        print(f"❌ Ошибка миграции данных: {e}")
        conn.rollback()
    finally:
        conn.close()


# Маршруты приложения
@app.route('/')
def index():
    return render_template('index.html',
                           MIN_PIN_LENGTH=MIN_PIN_LENGTH,
                           MAX_PIN_LENGTH=MAX_PIN_LENGTH)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = validate_credentials(login, password)

        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['full_name']
            session['user_type'] = user['user_type']

            if user['user_type'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('employee_dashboard'))
        else:
            flash('Неверный логин или пароль', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/terminal')
def terminal():
    return render_template('terminal.html',
                           min_pin_length=MIN_PIN_LENGTH,
                           max_pin_length=MAX_PIN_LENGTH)


@app.route('/employee/dashboard')
@login_required
def employee_dashboard():
    if session.get('user_type') == 'admin':
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()

    # Получаем информацию о сотруднике
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees WHERE id = ?", (session['user_id'],))
    employee = dict(cursor.fetchone())

    # Получаем последние события сотрудника
    cursor.execute('''
        SELECT ae.event_time, l.name, ae.event_type, ae.success
        FROM access_events ae
        JOIN laboratories l ON ae.laboratory_id = l.id
        WHERE ae.employee_id = ?
        ORDER BY ae.event_time DESC
        LIMIT 10
    ''', (session['user_id'],))

    recent_events = [dict(row) for row in cursor.fetchall()]

    # Получаем доступные лаборатории
    cursor.execute('''
        SELECT DISTINCT l.* 
        FROM access_schedules a
        JOIN laboratories l ON a.laboratory_id = l.id
        WHERE a.employee_id = ? AND l.is_active = TRUE
    ''', (session['user_id'],))

    accessible_labs = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template('employee_dashboard.html',
                           employee=employee,
                           recent_events=recent_events,
                           accessible_labs=accessible_labs)


# Админ-маршруты
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    stats = get_statistics()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем последние события
    cursor.execute('''
        SELECT ae.event_time, e.full_name, l.name, ae.event_type, ae.success, ae.reason
        FROM access_events ae
        JOIN employees e ON ae.employee_id = e.id
        JOIN laboratories l ON ae.laboratory_id = l.id
        ORDER BY ae.event_time DESC
        LIMIT 20
    ''')

    recent_events = [dict(row) for row in cursor.fetchall()]

    # Получаем сотрудников в лабораториях
    cursor.execute('''
        SELECT cp.entry_time, e.full_name, l.name, l.location
        FROM current_presence cp
        JOIN employees e ON cp.employee_id = e.id
        JOIN laboratories l ON cp.laboratory_id = l.id
        ORDER BY cp.entry_time DESC
    ''')

    current_presence = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template('admin_dashboard.html',
                           stats=stats,
                           recent_events=recent_events,
                           current_presence=current_presence,
                           now=datetime.now())


@app.route('/admin/employees')
@login_required
@admin_required
def admin_employees():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем сотрудников
    cursor.execute('''
        SELECT e.*, 
               GROUP_CONCAT(DISTINCT l.name) as accessible_labs
        FROM employees e
        LEFT JOIN access_schedules a ON e.id = a.employee_id
        LEFT JOIN laboratories l ON a.laboratory_id = l.id
        GROUP BY e.id
        ORDER BY e.created_at DESC
    ''')

    employees = [dict(row) for row in cursor.fetchall()]

    # Получаем список лабораторий для выпадающего списка
    cursor.execute('''
        SELECT id, name, code 
        FROM laboratories 
        WHERE is_active = TRUE
        ORDER BY name
    ''')

    laboratories = [dict(row) for row in cursor.fetchall()]

    conn.close()

    # Дни недели для отображения
    days_of_week = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

    return render_template('admin_employees.html',
                           employees=employees,
                           laboratories=laboratories,
                           days_of_week=days_of_week,
                           min_pin_length=MIN_PIN_LENGTH,
                           max_pin_length=MAX_PIN_LENGTH)


@app.route('/admin/laboratories')
@login_required
@admin_required
def admin_laboratories():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT l.*, 
               COUNT(DISTINCT a.employee_id) as employee_count,
               COUNT(DISTINCT cp.employee_id) as current_count
        FROM laboratories l
        LEFT JOIN access_schedules a ON l.id = a.laboratory_id
        LEFT JOIN current_presence cp ON l.id = cp.laboratory_id
        GROUP BY l.id
        ORDER BY l.name
    ''')

    laboratories = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('admin_laboratories.html', laboratories=laboratories)


@app.route('/admin/reports')
@login_required
@admin_required
def admin_reports():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем доступные отчеты
    cursor.execute('''
        SELECT r.*, e.full_name as created_by_name
        FROM reports r
        LEFT JOIN employees e ON r.created_by = e.id
        ORDER BY r.generated_at DESC
    ''')

    reports = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('admin_reports.html', reports=reports)


@app.route('/admin/access_rights')
@login_required
@admin_required
def admin_access_rights():
    """Страница управления правами доступа"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем всех сотрудников с количеством доступных лабораторий
    cursor.execute('''
        SELECT e.*, 
               COUNT(DISTINCT a.id) as accessible_labs_count
        FROM employees e
        LEFT JOIN access_schedules a ON e.id = a.employee_id
        GROUP BY e.id
        ORDER BY e.full_name
    ''')

    employees = [dict(row) for row in cursor.fetchall()]

    # Получаем все активные лаборатории
    cursor.execute('''
        SELECT id, name, code 
        FROM laboratories 
        WHERE is_active = TRUE
        ORDER BY name
    ''')

    laboratories = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template('admin_access_rights.html',
                           employees=employees,
                           laboratories=laboratories)


@app.route('/admin/import_export')
@login_required
@admin_required
def admin_import_export():
    """Страница импорта/экспорта данных"""
    return render_template('admin_import_export.html')


@app.route('/admin/statistics')
@login_required
@admin_required
def admin_statistics():
    """Страница статистики с графиками"""
    return render_template('admin_statistics.html')


# API маршруты
@app.route('/api/verify_access', methods=['POST'])
def api_verify_access():
    """API для проверки доступа через терминал"""
    try:
        data = request.get_json()

        # Поддержка разных методов аутентификации
        if 'pin_code' in data:
            # Аутентификация по PIN-коду
            pin_code = str(data.get('pin_code', '')).strip()
            laboratory_id = int(data.get('laboratory_id', 1))

            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id FROM employees WHERE pin_code = ? AND is_active = TRUE",
                (pin_code,)
            )

            employee = cursor.fetchone()
            conn.close()

            if not employee:
                return jsonify({
                    'success': False,
                    'message': 'Неверный PIN-код'
                })

            employee_id = employee['id']
            success, message = verify_access(employee_id, laboratory_id, 'pin')

        elif 'login' in data and 'password' in data:
            # Аутентификация по логину/паролю
            login = data.get('login', '').strip()
            password = data.get('password', '').strip()
            laboratory_id = int(data.get('laboratory_id', 1))

            user = validate_credentials(login, password)

            if not user:
                return jsonify({
                    'success': False,
                    'message': 'Неверный логин или пароль'
                })

            success, message = verify_access(user['id'], laboratory_id, 'login')
        else:
            return jsonify({
                'success': False,
                'message': 'Неверный формат запроса'
            })

        return jsonify({
            'success': success,
            'message': message
        })

    except Exception as e:
        print(f"Ошибка API: {e}")
        return jsonify({
            'success': False,
            'message': 'Внутренняя ошибка сервера'
        }), 500


@app.route('/api/admin/export/pdf/pdfkit', methods=['POST'])
@login_required
@admin_required
def api_export_pdf_pdfkit():
    """Экспорт в PDF с использованием pdfkit и wkhtmltopdf"""
    try:
        import pdfkit
        import tempfile
        import os
    except ImportError:
        return jsonify({
            'success': False,
            'message': 'Для экспорта в PDF требуется установить библиотеку pdfkit: pip install pdfkit'
        }), 500

    # Проверяем наличие wkhtmltopdf
    try:
        # Пробуем найти wkhtmltopdf в системе
        wkhtmltopdf_path = None
        possible_paths = [
            '/usr/bin/wkhtmltopdf',
            '/usr/local/bin/wkhtmltopdf',
            'C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe',
            'wkhtmltopdf'  # Если в PATH
        ]

        for path in possible_paths:
            if os.path.exists(path):
                wkhtmltopdf_path = path
                break

        if not wkhtmltopdf_path:
            return jsonify({
                'success': False,
                'message': 'Не найден wkhtmltopdf. Установите его с https://wkhtmltopdf.org/'
            }), 500
    except:
        return jsonify({
            'success': False,
            'message': 'Не удалось найти wkhtmltopdf. Установите его с https://wkhtmltopdf.org/'
        }), 500

    data = request.get_json()
    report_type = data.get('type', 'daily')
    report_name = data.get('name', 'Отчет АСКУД')
    date_start = data.get('period_start')
    date_end = data.get('period_end')

    conn = get_db_connection()
    cursor = conn.cursor()

    # Определяем период
    if report_type == 'daily':
        date_start = date_end = datetime.now().strftime('%Y-%m-%d')
    elif report_type == 'weekly':
        date_end = datetime.now().strftime('%Y-%m-%d')
        date_start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    elif report_type == 'monthly':
        date_end = datetime.now().strftime('%Y-%m-%d')
        date_start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    # Получаем данные
    query = '''
        SELECT 
            ae.event_time,
            e.full_name,
            e.department,
            l.name as laboratory,
            ae.event_type,
            ae.success,
            ae.reason
        FROM access_events ae
        JOIN employees e ON ae.employee_id = e.id
        JOIN laboratories l ON ae.laboratory_id = l.id
        WHERE DATE(ae.event_time) BETWEEN ? AND ?
        ORDER BY ae.event_time DESC
        LIMIT 200
    '''

    cursor.execute(query, (date_start, date_end))
    events = [dict(row) for row in cursor.fetchall()]

    conn.close()

    # Создаем HTML
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>{report_name}</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; }}
            h1 {{ text-align: center; color: #333; }}
            .header {{ text-align: center; margin-bottom: 30px; color: #666; }}
            .stats {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th {{ background-color: #4a6fa5; color: white; padding: 12px; text-align: left; }}
            td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
            .success {{ color: green; }}
            .failure {{ color: red; }}
            .footer {{ margin-top: 40px; text-align: center; color: #888; font-style: italic; }}
        </style>
    </head>
    <body>
        <h1>{report_name}</h1>
        <div class="header">
            <p>Период: {date_start} - {date_end}</p>
            <p>Дата генерации: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>

        <h3>События доступа:</h3>
    """

    if events:
        html_content += """
        <table>
            <tr>
                <th>Дата/Время</th>
                <th>Сотрудник</th>
                <th>Лаборатория</th>
                <th>Тип</th>
                <th>Статус</th>
                <th>Причина</th>
            </tr>
        """

        for event in events:
            event_time = event['event_time'][:16]
            full_name = event['full_name']
            laboratory = event['laboratory']
            event_type = 'Вход' if event['event_type'] == 'entry' else 'Выход'
            status_class = 'success' if event['success'] else 'failure'
            status_text = '✓ Успех' if event['success'] else '✗ Отказ'
            reason = event['reason'] or ''

            html_content += f"""
            <tr>
                <td>{event_time}</td>
                <td>{full_name}</td>
                <td>{laboratory}</td>
                <td>{event_type}</td>
                <td class="{status_class}">{status_text}</td>
                <td>{reason[:50]}{'...' if len(reason) > 50 else ''}</td>
            </tr>
            """

        html_content += """
        </table>
        """
    else:
        html_content += "<p>Нет данных за указанный период</p>"

    html_content += f"""
        <div class="footer">
            <p>Сгенерировано системой контроля доступа АСКУД</p>
            <p>Всего записей: {len(events)}</p>
        </div>
    </body>
    </html>
    """

    # Конвертируем HTML в PDF
    try:
        options = {
            'page-size': 'A4',
            'margin-top': '0.75in',
            'margin-right': '0.75in',
            'margin-bottom': '0.75in',
            'margin-left': '0.75in',
            'encoding': "UTF-8",
            'no-outline': None,
            'quiet': ''
        }

        # Создаем временный файл для PDF
        pdf_buffer = io.BytesIO()

        # Используем pdfkit с путем к wkhtmltopdf
        config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
        pdf = pdfkit.from_string(html_content, False, options=options, configuration=config)

        pdf_buffer.write(pdf)
        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'{report_name}_{datetime.now().strftime("%Y%m%d")}.pdf'
        )

    except Exception as e:
        print(f"Ошибка при создании PDF с pdfkit: {e}")
        return jsonify({
            'success': False,
            'message': f'Ошибка при создании PDF: {str(e)}'
        }), 500

@app.route('/api/admin/statistics/charts')
@login_required
@admin_required
def api_statistics_charts():
    """API для получения данных для графиков статистики"""
    try:
        period = int(request.args.get('period', 30))
        group_by = request.args.get('group_by', 'day')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Определяем дату начала периода
        date_from = (datetime.now() - timedelta(days=period)).strftime('%Y-%m-%d')
        date_to = datetime.now().strftime('%Y-%m-%d')

        # 1. Быстрая статистика
        cursor.execute('''
            SELECT 
                COUNT(*) as total_events,
                SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as successful_entries,
                SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) as denials
            FROM access_events
            WHERE DATE(event_time) BETWEEN ? AND ?
        ''', (date_from, date_to))

        total_stats = cursor.fetchone()

        # Рассчитываем процент успешных входов
        success_rate = 0
        if total_stats['total_events'] and total_stats['total_events'] > 0:
            success_rate = round((total_stats['successful_entries'] or 0) / total_stats['total_events'] * 100)

        # Находим пиковый час
        cursor.execute('''
            SELECT 
                strftime('%H', event_time) as hour,
                COUNT(*) as count
            FROM access_events
            WHERE DATE(event_time) BETWEEN ? AND ?
            GROUP BY strftime('%H', event_time)
            ORDER BY count DESC
            LIMIT 1
        ''', (date_from, date_to))

        peak_hour_data = cursor.fetchone()
        peak_hour = f"{peak_hour_data['hour']}:00" if peak_hour_data else "-"

        # 2. Данные для графика посещаемости
        if group_by == 'day':
            cursor.execute('''
                SELECT 
                    DATE(event_time) as date,
                    SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as entries,
                    SUM(CASE WHEN event_type = 'exit' AND success = TRUE THEN 1 ELSE 0 END) as exits
                FROM access_events
                WHERE DATE(event_time) BETWEEN ? AND ?
                GROUP BY DATE(event_time)
                ORDER BY date
            ''', (date_from, date_to))

            attendance_data = cursor.fetchall()
            labels = [row['date'] for row in attendance_data]
            entries = [row['entries'] for row in attendance_data]
            exits = [row['exits'] for row in attendance_data]

        elif group_by == 'week':
            cursor.execute('''
                SELECT 
                    strftime('%Y-%W', event_time) as week,
                    SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as entries,
                    SUM(CASE WHEN event_type = 'exit' AND success = TRUE THEN 1 ELSE 0 END) as exits
                FROM access_events
                WHERE DATE(event_time) BETWEEN ? AND ?
                GROUP BY strftime('%Y-%W', event_time)
                ORDER BY week
            ''', (date_from, date_to))

            attendance_data = cursor.fetchall()
            labels = [f"Неделя {row['week'].split('-')[1]}" for row in attendance_data]
            entries = [row['entries'] for row in attendance_data]
            exits = [row['exits'] for row in attendance_data]

        else:  # month
            cursor.execute('''
                SELECT 
                    strftime('%Y-%m', event_time) as month,
                    SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as entries,
                    SUM(CASE WHEN event_type = 'exit' AND success = TRUE THEN 1 ELSE 0 END) as exits
                FROM access_events
                WHERE DATE(event_time) BETWEEN ? AND ?
                GROUP BY strftime('%Y-%m', event_time)
                ORDER BY month
            ''', (date_from, date_to))

            attendance_data = cursor.fetchall()
            month_names = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
            labels = []
            for row in attendance_data:
                year, month = row['month'].split('-')
                labels.append(f"{month_names[int(month) - 1]} {year}")
            entries = [row['entries'] for row in attendance_data]
            exits = [row['exits'] for row in attendance_data]

        # 3. Данные по лабораториям (для круговой диаграммы)
        cursor.execute('''
            SELECT 
                l.name,
                COUNT(ae.id) as count
            FROM access_events ae
            JOIN laboratories l ON ae.laboratory_id = l.id
            WHERE ae.success = TRUE 
                AND ae.event_type = 'entry'
                AND DATE(ae.event_time) BETWEEN ? AND ?
            GROUP BY l.id
            ORDER BY count DESC
            LIMIT 8
        ''', (date_from, date_to))

        labs_data = cursor.fetchall()
        labs_labels = [row['name'][:20] + ('...' if len(row['name']) > 20 else '') for row in labs_data]
        labs_values = [row['count'] for row in labs_data]

        # 4. Данные по часам
        cursor.execute('''
            SELECT 
                strftime('%H', event_time) as hour,
                COUNT(*) as count
            FROM access_events
            WHERE DATE(event_time) BETWEEN ? AND ?
            GROUP BY strftime('%H', event_time)
            ORDER BY hour
        ''', (date_from, date_to))

        hourly_data = cursor.fetchall()

        # Создаем полный список часов (0-23)
        hourly_labels = []
        hourly_values = []
        hourly_dict = {row['hour']: row['count'] for row in hourly_data}

        for i in range(24):
            hour_key = str(i).zfill(2)
            hourly_labels.append(f"{hour_key}:00")
            hourly_values.append(hourly_dict.get(hour_key, 0))

        # 5. Данные об отказах
        cursor.execute('''
            SELECT 
                COALESCE(reason, 'Не указана') as reason,
                COUNT(*) as count
            FROM access_events
            WHERE success = FALSE 
                AND DATE(event_time) BETWEEN ? AND ?
            GROUP BY reason
            ORDER BY count DESC
            LIMIT 10
        ''', (date_from, date_to))

        denials_data = cursor.fetchall()
        denials_labels = [row['reason'] for row in denials_data]
        denials_values = [row['count'] for row in denials_data]

        # 6. Среднее время в лаборатории (приблизительно)
        cursor.execute('''
            SELECT 
                AVG(
                    CAST(
                        (strftime('%s', cp.expected_exit_time) - strftime('%s', cp.entry_time)) / 3600.0 
                        AS REAL
                    )
                ) as avg_hours
            FROM current_presence cp
            WHERE DATE(cp.entry_time) BETWEEN ? AND ?
        ''', (date_from, date_to))

        avg_hours_result = cursor.fetchone()
        avg_time_in_lab = round(avg_hours_result['avg_hours'] or 0, 1)

        # 7. Статистика для предыдущего периода (для сравнения)
        prev_date_from = (datetime.strptime(date_from, '%Y-%m-%d') - timedelta(days=period)).strftime('%Y-%m-%d')
        prev_date_to = date_from

        cursor.execute('''
            SELECT 
                COUNT(*) as prev_events,
                SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as prev_entries,
                SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) as prev_denials
            FROM access_events
            WHERE DATE(event_time) BETWEEN ? AND ?
        ''', (prev_date_from, prev_date_to))

        prev_stats = cursor.fetchone()

        # Вычисляем изменения в процентах
        def calculate_change(current, previous):
            if previous and previous > 0:
                return round(((current - previous) / previous) * 100, 1)
            return 0

        conn.close()

        # Формируем ответ
        return jsonify({
            'success': True,
            'quick_stats': {
                'total_events': total_stats['total_events'] or 0,
                'success_rate': success_rate,
                'avg_time': f"{avg_time_in_lab}ч",
                'peak_hour': peak_hour
            },
            'attendance_data': {
                'labels': labels,
                'entries': entries,
                'exits': exits
            },
            'labs_data': {
                'labels': labs_labels,
                'values': labs_values
            },
            'hourly_data': {
                'labels': hourly_labels,
                'values': hourly_values
            },
            'denials_data': {
                'labels': denials_labels,
                'values': denials_values
            },
            'detailed_stats': {
                'total_events': total_stats['total_events'] or 0,
                'successful_entries': total_stats['successful_entries'] or 0,
                'denials': total_stats['denials'] or 0,
                'total_employees': get_statistics()['employees_count'],
                'active_labs': get_statistics()['labs_count'],
                'avg_time_in_lab': f"{avg_time_in_lab} часов",
                'events_change': calculate_change(total_stats['total_events'] or 0, prev_stats['prev_events'] or 0),
                'entries_change': calculate_change(total_stats['successful_entries'] or 0,
                                                   prev_stats['prev_entries'] or 0),
                'denials_change': calculate_change(total_stats['denials'] or 0, prev_stats['prev_denials'] or 0),
                'time_change': 0,  # Для простоты
                'events_trend': 'up' if (total_stats['total_events'] or 0) > (
                        prev_stats['prev_events'] or 0) else 'down',
                'time_trend': 'up'
            }
        })

    except Exception as e:
        print(f"Ошибка при получении статистики для графиков: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/employee/schedule')
@login_required
def api_employee_schedule():
    """API для получения расписания текущего сотрудника"""
    try:
        employee_id = session['user_id']

        conn = get_db_connection()
        cursor = conn.cursor()

        # Получаем расписание сотрудника
        cursor.execute('''
            SELECT 
                a.id,
                l.name as laboratory_name,
                l.code as laboratory_code,
                a.days_of_week,
                a.time_start,
                a.time_end
            FROM access_schedules a
            JOIN laboratories l ON a.laboratory_id = l.id
            WHERE a.employee_id = ?
            ORDER BY l.name
        ''', (employee_id,))

        schedule_data = []
        for row in cursor.fetchall():
            item = dict(row)

            # Преобразуем строку дней в список названий
            days_list = []
            if item['days_of_week']:
                try:
                    # Парсим строку типа "0,1,2,3,4"
                    day_numbers = [int(d.strip()) for d in item['days_of_week'].split(',') if d.strip().isdigit()]
                    day_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
                    days_list = [day_names[day_num] for day_num in day_numbers if 0 <= day_num < 7]
                except Exception as e:
                    print(f"Ошибка парсинга дней недели: {e}")
                    days_list = []

            item['days_list'] = days_list
            item['days_text'] = ', '.join(days_list) if days_list else 'Не указаны'
            schedule_data.append(item)

        conn.close()

        return jsonify({
            'success': True,
            'schedule': schedule_data
        })

    except Exception as e:
        print(f"Ошибка при получении расписания сотрудника: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
@app.route('/api/current_presence')
def api_current_presence():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT e.full_name, l.name, cp.entry_time
        FROM current_presence cp
        JOIN employees e ON cp.employee_id = e.id
        JOIN laboratories l ON cp.laboratory_id = l.id
    ''')

    presence = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return jsonify({
        'count': len(presence),
        'people': presence
    })


@app.route('/api/laboratories')
def api_laboratories():
    """API для получения списка лабораторий с текущей загрузкой"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT 
                l.id,
                l.name,
                l.code,
                l.location,
                l.description,
                l.capacity,
                l.is_active,
                COALESCE(cp.current_count, 0) as current_count
            FROM laboratories l
            LEFT JOIN (
                SELECT laboratory_id, COUNT(DISTINCT employee_id) as current_count
                FROM current_presence 
                GROUP BY laboratory_id
            ) cp ON l.id = cp.laboratory_id
            WHERE l.is_active = TRUE
            ORDER BY l.name
        ''')

        laboratories = []
        for row in cursor.fetchall():
            lab = dict(row)
            # Рассчитываем процент заполненности
            lab['occupancy_percent'] = round((lab['current_count'] / lab['capacity']) * 100) if lab['capacity'] and lab[
                'capacity'] > 0 else 0
            laboratories.append(lab)

        conn.close()

        return jsonify({
            'success': True,
            'laboratories': laboratories
        })

    except Exception as e:
        print(f"Ошибка при получении лабораторий: {e}")
        return jsonify({
            'success': False,
            'message': 'Ошибка при получении списка лабораторий'
        }), 500


@app.route('/api/laboratory_presence')
def api_laboratory_presence():
    """API для получения сотрудников в конкретной лаборатории"""
    try:
        lab_id = request.args.get('lab_id', type=int)

        if not lab_id:
            return jsonify({
                'success': False,
                'message': 'Не указан ID лаборатории'
            }), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT 
                cp.entry_time,
                e.full_name,
                e.department,
                e.position
            FROM current_presence cp
            JOIN employees e ON cp.employee_id = e.id
            WHERE cp.laboratory_id = ?
            ORDER BY cp.entry_time
        ''', (lab_id,))

        people = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify({
            'success': True,
            'people': people
        })

    except Exception as e:
        print(f"Ошибка при получении присутствия: {e}")
        return jsonify({
            'success': False,
            'message': 'Ошибка при получении данных о присутствии'
        }), 500


# API для работы с отдельными правилами доступа
@app.route('/api/admin/access_rule', methods=['POST'])
@login_required
@admin_required
def api_add_access_rule():
    """Добавление нового правила доступа"""
    try:
        data = request.get_json()

        # Проверка обязательных полей
        required_fields = ['laboratory_id', 'days_of_week', 'time_start', 'time_end']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'message': f'Не указано поле: {field}'}), 400

        # Проверяем, есть ли employee_id в данных или он должен быть в URL
        if 'employee_id' not in data:
            return jsonify({'success': False, 'message': 'Не указан ID сотрудника'}), 400

        employee_id = data['employee_id']
        laboratory_id = data['laboratory_id']

        conn = get_db_connection()
        cursor = conn.cursor()

        # Проверяем существование сотрудника
        cursor.execute("SELECT id FROM employees WHERE id = ?", (employee_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Сотрудник не найден'}), 404

        # Проверяем существование лаборатории
        cursor.execute("SELECT id FROM laboratories WHERE id = ?", (laboratory_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Лаборатория не найдена'}), 404

        # Преобразуем список дней в строку
        days_str = ','.join(map(str, data['days_of_week']))

        # Проверяем, существует ли уже запись для этого сотрудника и лаборатории
        cursor.execute('''
            SELECT id FROM access_schedules 
            WHERE employee_id = ? AND laboratory_id = ?
        ''', (employee_id, laboratory_id))

        existing = cursor.fetchone()

        if existing:
            # Обновляем существующую запись
            cursor.execute('''
                UPDATE access_schedules 
                SET days_of_week = ?, time_start = ?, time_end = ?
                WHERE id = ?
            ''', (days_str, data['time_start'], data['time_end'], existing['id']))
        else:
            # Добавляем новую запись
            cursor.execute('''
                INSERT INTO access_schedules (employee_id, laboratory_id, days_of_week, time_start, time_end)
                VALUES (?, ?, ?, ?, ?)
            ''', (employee_id, laboratory_id, days_str,
                  data['time_start'], data['time_end']))

        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Правило доступа обновлено'})

    except Exception as e:
        print(f"Ошибка при добавлении правила доступа: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.context_processor
def inject_theme():
    """Инжектирует настройки темы во все шаблоны"""
    return {
        'theme': request.cookies.get('theme', 'light'),
        'MIN_PIN_LENGTH': MIN_PIN_LENGTH,
        'MAX_PIN_LENGTH': MAX_PIN_LENGTH
    }


@app.route('/api/theme', methods=['POST'])
def set_theme():
    """Установить тему"""
    data = request.get_json()
    theme = data.get('theme', 'light')

    response = jsonify({'success': True, 'theme': theme})
    response.set_cookie('theme', theme, max_age=365 * 24 * 60 * 60)
    return response
@app.route('/api/admin/access_rule/<int:rule_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@admin_required
def api_access_rule_detail(rule_id):
    """Получение, обновление или удаление правила доступа"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if request.method == 'GET':
            # Получение информации о правиле
            cursor.execute('''
                SELECT asch.*, e.full_name, l.name as laboratory_name
                FROM access_schedules asch
                JOIN employees e ON asch.employee_id = e.id
                JOIN laboratories l ON asch.laboratory_id = l.id
                WHERE asch.id = ?
            ''', (rule_id,))

            rule = cursor.fetchone()

            if not rule:
                conn.close()
                return jsonify({'success': False, 'message': 'Правило не найдено'}), 404

            # Преобразуем строку дней в список
            days_list = []
            if rule['days_of_week']:
                days_list = [int(d) for d in rule['days_of_week'].split(',') if d.isdigit()]

            rule_data = dict(rule)
            rule_data['days_of_week'] = days_list

            conn.close()
            return jsonify({'success': True, 'rule': rule_data})

        elif request.method == 'PUT':
            # Обновление правила
            data = request.get_json()

            # Проверяем существование правила
            cursor.execute("SELECT id FROM access_schedules WHERE id = ?", (rule_id,))
            if not cursor.fetchone():
                conn.close()
                return jsonify({'success': False, 'message': 'Правило не найдено'}), 404

            # Преобразуем список дней в строку
            days_str = ','.join(map(str, data.get('days_of_week', [])))

            # Обновляем запись
            cursor.execute('''
                UPDATE access_schedules 
                SET days_of_week = ?, time_start = ?, time_end = ?
                WHERE id = ?
            ''', (days_str, data['time_start'], data['time_end'], rule_id))

            conn.commit()
            conn.close()

            return jsonify({'success': True, 'message': 'Правило обновлено'})

        elif request.method == 'DELETE':
            # Удаление правила
            cursor.execute("DELETE FROM access_schedules WHERE id = ?", (rule_id,))
            conn.commit()
            conn.close()

            return jsonify({'success': True, 'message': 'Правило удалено'})

    except Exception as e:
        print(f"Ошибка при работе с правилом доступа: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# API для получения всех правил доступа сотрудника
@app.route('/api/admin/employees/<int:employee_id>/access', methods=['GET'])
@login_required
@admin_required
def api_employee_access_rules(employee_id):
    """Получение всех правил доступа сотрудника с группировкой"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Проверяем существование сотрудника
        cursor.execute("SELECT id FROM employees WHERE id = ?", (employee_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Сотрудник не найден'}), 404

        # Получаем правила доступа с группировкой по лабораториям и времени
        cursor.execute('''
            SELECT 
                asch.id,
                asch.laboratory_id,
                l.name as laboratory_name,
                l.code as laboratory_code,
                asch.time_start,
                asch.time_end,
                asch.days_of_week
            FROM access_schedules asch
            JOIN laboratories l ON asch.laboratory_id = l.id
            WHERE asch.employee_id = ?
            ORDER BY l.name
        ''', (employee_id,))

        access_rules = []
        for row in cursor.fetchall():
            rule = dict(row)
            # Преобразуем строку дней в список чисел
            if rule['days_of_week']:
                try:
                    # Ожидаем формат "0,1,2,3,4"
                    days_list = rule['days_of_week'].split(',')
                    rule['days_of_week'] = [int(day.strip()) for day in days_list if day.strip().isdigit()]
                except (ValueError, AttributeError):
                    rule['days_of_week'] = []
            else:
                rule['days_of_week'] = []
            access_rules.append(rule)

        conn.close()

        return jsonify({
            'success': True,
            'access_rights': access_rules
        })

    except Exception as e:
        print(f"Ошибка при получении правил доступа: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
@app.route('/api/admin/add_employee', methods=['POST'])
@login_required
@admin_required
def api_add_employee():
    try:
        data = request.get_json()

        # Валидация данных
        required_fields = ['login', 'password', 'pin_code', 'full_name']
        for field in required_fields:
            if field not in data or not data[field].strip():
                return jsonify({'success': False, 'message': f'Поле {field} обязательно'})

        # Проверка длины PIN-кода
        pin_code = data['pin_code'].strip()
        if len(pin_code) < MIN_PIN_LENGTH or len(pin_code) > MAX_PIN_LENGTH:
            return jsonify({
                'success': False,
                'message': f'PIN-код должен содержать от {MIN_PIN_LENGTH} до {MAX_PIN_LENGTH} цифр'
            })

        if not pin_code.isdigit():
            return jsonify({'success': False, 'message': 'PIN-код должен содержать только цифры'})

        # Проверка уникальности логина и PIN-кода
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM employees WHERE login = ?", (data['login'],))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Логин уже существует'})

        cursor.execute("SELECT id FROM employees WHERE pin_code = ?", (pin_code,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'PIN-код уже существует'})

        # Добавление сотрудника
        cursor.execute('''
            INSERT INTO employees (login, password, pin_code, full_name, department, position, phone, email, is_active, user_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['login'],
            data['password'],
            pin_code,
            data['full_name'],
            data.get('department', ''),
            data.get('position', ''),
            data.get('phone', ''),
            data.get('email', ''),
            data.get('is_active', True),
            data.get('user_type', 'employee')
        ))

        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Сотрудник добавлен'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/admin/statistics')
@login_required
@admin_required
def api_statistics():
    """API для получения данных для графиков статистики"""
    try:
        period = request.args.get('period', '30')
        chart_type = request.args.get('type', 'daily')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Определяем период для фильтрации
        if period == 'custom':
            date_from = request.args.get('date_from')
            date_to = request.args.get('date_to')
            if not date_from or not date_to:
                date_from = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                date_to = datetime.now().strftime('%Y-%m-%d')
        else:
            days = int(period)
            date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            date_to = datetime.now().strftime('%Y-%m-%d')

        # 1. Данные посещаемости по дням
        if chart_type == 'daily':
            cursor.execute('''
                SELECT 
                    DATE(event_time) as date,
                    SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as entries,
                    SUM(CASE WHEN event_type = 'exit' AND success = TRUE THEN 1 ELSE 0 END) as exits
                FROM access_events
                WHERE DATE(event_time) BETWEEN ? AND ?
                GROUP BY DATE(event_time)
                ORDER BY date
            ''', (date_from, date_to))

            daily_data = cursor.fetchall()

            # Формируем данные для графика
            labels = []
            entries = []
            exits = []

            for row in daily_data:
                labels.append(row['date'])
                entries.append(row['entries'])
                exits.append(row['exits'])

            visits_data = {
                'labels': labels,
                'entries': entries,
                'exits': exits,
                'total_entries': sum(entries),
                'total_exits': sum(exits),
                'avg_daily': sum(entries) / len(entries) if entries else 0
            }

        elif chart_type == 'weekly':
            # Аналогично для недель
            visits_data = get_weekly_data(cursor, date_from, date_to)
        else:  # monthly
            visits_data = get_monthly_data(cursor, date_from, date_to)

        # 2. Данные по лабораториям
        cursor.execute('''
            SELECT 
                l.name,
                COUNT(ae.id) as visit_count
            FROM access_events ae
            JOIN laboratories l ON ae.laboratory_id = l.id
            WHERE ae.success = TRUE 
                AND ae.event_type = 'entry'
                AND DATE(ae.event_time) BETWEEN ? AND ?
            GROUP BY l.id
            ORDER BY visit_count DESC
            LIMIT 10
        ''', (date_from, date_to))

        labs_data = cursor.fetchall()

        labs_labels = []
        labs_values = []

        for row in labs_data:
            labs_labels.append(row['name'])
            labs_values.append(row['visit_count'])

        # 3. Данные об отказах
        cursor.execute('''
            SELECT 
                reason,
                COUNT(*) as count
            FROM access_events
            WHERE success = FALSE 
                AND DATE(event_time) BETWEEN ? AND ?
                AND reason IS NOT NULL
            GROUP BY reason
            ORDER BY count DESC
            LIMIT 5
        ''', (date_from, date_to))

        denials_data = cursor.fetchall()

        denial_labels = []
        denial_values = []
        denial_reasons = []

        for row in denials_data:
            reason = row['reason'] or 'Не указана'
            denial_labels.append(reason)
            denial_values.append(row['count'])
            denial_reasons.append({
                'reason': reason,
                'count': row['count']
            })

        # 4. Данные по часам
        cursor.execute('''
            SELECT 
                strftime('%H', event_time) as hour,
                COUNT(*) as count
            FROM access_events
            WHERE DATE(event_time) BETWEEN ? AND ?
            GROUP BY strftime('%H', event_time)
            ORDER BY hour
        ''', (date_from, date_to))

        hourly_data = cursor.fetchall()

        hourly_labels = []
        hourly_values = []

        # Создаем все часы (0-23)
        all_hours = [f"{str(i).zfill(2)}:00" for i in range(24)]
        hourly_counts = {row['hour']: row['count'] for row in hourly_data}

        for i in range(24):
            hour_key = str(i).zfill(2)
            hourly_labels.append(all_hours[i])
            hourly_values.append(hourly_counts.get(hour_key, 0))

        # 5. Общая статистика
        cursor.execute('''
            SELECT 
                COUNT(*) as total_events,
                SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as successful_entries,
                SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) as denials
            FROM access_events
            WHERE DATE(event_time) BETWEEN ? AND ?
        ''', (date_from, date_to))

        total_stats = cursor.fetchone()

        # Получаем статистику за предыдущий период для сравнения
        prev_date_from = (datetime.strptime(date_from, '%Y-%m-%d') - timedelta(days=int(period))).strftime('%Y-%m-%d')
        prev_date_to = date_from

        cursor.execute('''
            SELECT 
                COUNT(*) as prev_events,
                SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as prev_entries,
                SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) as prev_denials
            FROM access_events
            WHERE DATE(event_time) BETWEEN ? AND ?
        ''', (prev_date_from, prev_date_to))

        prev_stats = cursor.fetchone()

        # Вычисляем изменения в процентах
        def calculate_change(current, previous):
            if previous and previous > 0:
                return round(((current - previous) / previous) * 100, 1)
            return 0

        conn.close()

        return jsonify({
            'success': True,
            'visits': visits_data,
            'labs': {
                'labels': labs_labels,
                'values': labs_values,
                'total_labs': len(labs_labels),
                'avg_occupancy': round((sum(labs_values) / max(len(labs_values), 1)) / 10, 1)  # Примерный расчет
            },
            'denials': {
                'labels': denial_labels,
                'values': denial_values,
                'reasons': denial_reasons
            },
            'hourly': {
                'labels': hourly_labels,
                'values': hourly_values
            },
            'stats': {
                'total_events': total_stats['total_events'] or 0,
                'successful_entries': total_stats['successful_entries'] or 0,
                'denials': total_stats['denials'] or 0,
                'total_employees': get_statistics()['employees_count'],
                'active_labs': get_statistics()['labs_count'],
                'avg_time_in_lab': 2.5,  # Заглушка - нужно реализовать расчет
                'events_change': calculate_change(total_stats['total_events'] or 0, prev_stats['prev_events'] or 0),
                'entries_change': calculate_change(total_stats['successful_entries'] or 0,
                                                   prev_stats['prev_entries'] or 0),
                'denials_change': calculate_change(total_stats['denials'] or 0, prev_stats['prev_denials'] or 0),
                'employees_change': 0,
                'labs_change': 0,
                'time_change': 0,
                'events_trend': 'up' if (total_stats['total_events'] or 0) > (
                        prev_stats['prev_events'] or 0) else 'down',
                'time_trend': 'up'
            }
        })

    except Exception as e:
        print(f"Ошибка при получении статистики: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# Вспомогательные функции для обработки данных
def get_weekly_data(cursor, date_from, date_to):
    """Получение данных по неделям"""
    cursor.execute('''
        SELECT 
            strftime('%Y-%W', event_time) as week,
            SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as entries,
            SUM(CASE WHEN event_type = 'exit' AND success = TRUE THEN 1 ELSE 0 END) as exits
        FROM access_events
        WHERE DATE(event_time) BETWEEN ? AND ?
        GROUP BY strftime('%Y-%W', event_time)
        ORDER BY week
    ''', (date_from, date_to))

    weekly_data = cursor.fetchall()

    labels = []
    entries = []
    exits = []

    for row in weekly_data:
        # Преобразуем номер недели в читаемый формат
        year, week = row['week'].split('-')
        labels.append(f"Неделя {week}, {year}")
        entries.append(row['entries'])
        exits.append(row['exits'])

    return {
        'labels': labels,
        'entries': entries,
        'exits': exits,
        'total_entries': sum(entries),
        'total_exits': sum(exits),
        'avg_daily': sum(entries) / (len(entries) * 7) if entries else 0
    }


def get_monthly_data(cursor, date_from, date_to):
    """Получение данных по месяцам"""
    cursor.execute('''
        SELECT 
            strftime('%Y-%m', event_time) as month,
            SUM(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 ELSE 0 END) as entries,
            SUM(CASE WHEN event_type = 'exit' AND success = TRUE THEN 1 ELSE 0 END) as exits
        FROM access_events
        WHERE DATE(event_time) BETWEEN ? AND ?
        GROUP BY strftime('%Y-%m', event_time)
        ORDER BY month
    ''', (date_from, date_to))

    monthly_data = cursor.fetchall()

    labels = []
    entries = []
    exits = []

    for row in monthly_data:
        # Преобразуем месяц в читаемый формат
        year, month = row['month'].split('-')
        month_names = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
                       'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
        labels.append(f"{month_names[int(month) - 1]} {year}")
        entries.append(row['entries'])
        exits.append(row['exits'])

    return {
        'labels': labels,
        'entries': entries,
        'exits': exits,
        'total_entries': sum(entries),
        'total_exits': sum(exits),
        'avg_daily': sum(entries) / (len(entries) * 30) if entries else 0
    }


@app.route('/api/admin/laboratories', methods=['GET', 'POST'])
@login_required
@admin_required
def api_admin_laboratories():
    """API для получения списка лабораторий или добавления новой (админ)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if request.method == 'GET':
            # Получение списка лабораторий с расширенной информацией
            cursor.execute('''
                SELECT 
                    l.*,
                    COUNT(DISTINCT a.employee_id) as employee_count,
                    COUNT(DISTINCT cp.employee_id) as current_count,
                    GROUP_CONCAT(DISTINCT e.full_name) as current_employees
                FROM laboratories l
                LEFT JOIN access_schedules a ON l.id = a.laboratory_id
                LEFT JOIN current_presence cp ON l.id = cp.laboratory_id
                LEFT JOIN employees e ON cp.employee_id = e.id
                GROUP BY l.id
                ORDER BY l.name
            ''')

            laboratories = []
            for row in cursor.fetchall():
                lab = dict(row)
                # Рассчитываем статистику
                lab['occupancy_percent'] = round((lab['current_count'] / lab['capacity']) * 100) if lab[
                                                                                                        'capacity'] > 0 else 0

                # Форматируем список сотрудников
                if lab['current_employees']:
                    lab['current_employees'] = lab['current_employees'].split(',')
                else:
                    lab['current_employees'] = []

                laboratories.append(lab)

            conn.close()
            return jsonify({'success': True, 'laboratories': laboratories})

        elif request.method == 'POST':
            # Добавление новой лаборатории
            data = request.get_json()

            required_fields = ['name', 'code', 'location', 'capacity']
            for field in required_fields:
                if field not in data or not str(data[field]).strip():
                    conn.close()
                    return jsonify({'success': False, 'message': f'Поле {field} обязательно'}), 400

            # Проверяем уникальность кода лаборатории
            cursor.execute(
                "SELECT id FROM laboratories WHERE code = ?",
                (data['code'].strip(),)
            )
            if cursor.fetchone():
                conn.close()
                return jsonify({'success': False, 'message': 'Лаборатория с таким кодом уже существует'}), 400

            # Добавляем лабораторию
            cursor.execute('''
                INSERT INTO laboratories (name, code, location, description, capacity, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                data['name'].strip(),
                data['code'].strip(),
                data['location'].strip(),
                data.get('description', ''),
                int(data['capacity']),
                data.get('is_active', True)
            ))

            conn.commit()
            lab_id = cursor.lastrowid
            conn.close()

            return jsonify({
                'success': True,
                'message': 'Лаборатория добавлена',
                'laboratory_id': lab_id
            })

    except Exception as e:
        print(f"Ошибка при работе с лабораториями: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/laboratories/<int:laboratory_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@admin_required
def api_admin_laboratory_detail(laboratory_id):
    """API для получения, обновления или удаления лаборатории (админ)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if request.method == 'GET':
            # Получение подробной информации о лаборатории
            cursor.execute('''
                SELECT 
                    l.*,
                    COUNT(DISTINCT a.employee_id) as total_employees,
                    COUNT(DISTINCT cp.employee_id) as current_employees_count
                FROM laboratories l
                LEFT JOIN access_schedules a ON l.id = a.laboratory_id
                LEFT JOIN current_presence cp ON l.id = cp.laboratory_id
                WHERE l.id = ?
                GROUP BY l.id
            ''', (laboratory_id,))

            laboratory = cursor.fetchone()

            if not laboratory:
                conn.close()
                return jsonify({'success': False, 'message': 'Лаборатория не найдена'}), 404

            # Получаем список сотрудников с доступом к лаборатории
            cursor.execute('''
                SELECT 
                    e.id,
                    e.full_name,
                    e.department,
                    e.position,
                    a.days_of_week as days,
                    a.time_start as earliest_start,
                    a.time_end as latest_end
                FROM employees e
                JOIN access_schedules a ON e.id = a.employee_id
                WHERE a.laboratory_id = ?
                GROUP BY e.id
                ORDER BY e.full_name
            ''', (laboratory_id,))

            employees_with_access = [dict(row) for row in cursor.fetchall()]

            # Получаем текущих сотрудников в лаборатории
            cursor.execute('''
                SELECT 
                    e.full_name,
                    e.department,
                    cp.entry_time
                FROM current_presence cp
                JOIN employees e ON cp.employee_id = e.id
                WHERE cp.laboratory_id = ?
                ORDER BY cp.entry_time
            ''', (laboratory_id,))

            current_presence = [dict(row) for row in cursor.fetchall()]

            laboratory_data = dict(laboratory)
            laboratory_data['employees_with_access'] = employees_with_access
            laboratory_data['current_presence'] = current_presence

            conn.close()
            return jsonify({'success': True, 'laboratory': laboratory_data})

        elif request.method == 'PUT':
            # Обновление информации о лаборатории
            data = request.get_json()

            # Проверяем существование лаборатории
            cursor.execute("SELECT id FROM laboratories WHERE id = ?", (laboratory_id,))
            if not cursor.fetchone():
                conn.close()
                return jsonify({'success': False, 'message': 'Лаборатория не найдена'}), 404

            # Проверяем уникальность кода, если он изменен
            if 'code' in data:
                cursor.execute(
                    "SELECT id FROM laboratories WHERE code = ? AND id != ?",
                    (data['code'].strip(), laboratory_id)
                )
                if cursor.fetchone():
                    conn.close()
                    return jsonify({'success': False, 'message': 'Код лаборатории уже используется'}), 400

            # Подготавливаем поля для обновления
            update_fields = []
            update_values = []

            allowed_fields = ['name', 'code', 'location', 'description', 'capacity', 'is_active']

            for field in allowed_fields:
                if field in data:
                    update_fields.append(f"{field} = ?")
                    if field in ['capacity', 'is_active']:
                        update_values.append(int(data[field]) if field == 'capacity' else bool(data[field]))
                    else:
                        update_values.append(str(data[field]).strip())

            if not update_fields:
                conn.close()
                return jsonify({'success': False, 'message': 'Нет данных для обновления'}), 400

            # Выполняем обновление
            update_values.append(laboratory_id)
            update_query = f"UPDATE laboratories SET {', '.join(update_fields)} WHERE id = ?"

            cursor.execute(update_query, update_values)
            conn.commit()
            conn.close()

            return jsonify({'success': True, 'message': 'Данные лаборатории обновлены'})

        elif request.method == 'DELETE':
            # Удаление лаборатории
            # Проверяем, есть ли в лаборатории сотрудники
            cursor.execute(
                "SELECT id FROM current_presence WHERE laboratory_id = ?",
                (laboratory_id,)
            )
            if cursor.fetchone():
                conn.close()
                return jsonify({
                    'success': False,
                    'message': 'Нельзя удалить лабораторию, в которой находятся сотрудники'
                }), 400

            # Проверяем, есть ли связанные права доступа
            cursor.execute(
                "SELECT id FROM access_schedules WHERE laboratory_id = ?",
                (laboratory_id,)
            )
            if cursor.fetchone():
                # Вместо удаления деактивируем лабораторию
                cursor.execute(
                    "UPDATE laboratories SET is_active = FALSE WHERE id = ?",
                    (laboratory_id,)
                )
                conn.commit()
                conn.close()
                return jsonify({
                    'success': True,
                    'message': 'Лаборатория деактивирована (есть связанные права доступа)'
                })

            # Удаляем лабораторию
            cursor.execute("DELETE FROM laboratories WHERE id = ?", (laboratory_id,))
            conn.commit()
            conn.close()

            return jsonify({'success': True, 'message': 'Лаборатория удалена'})

    except Exception as e:
        print(f"Ошибка при работе с лабораторией: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/employees/<int:employee_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@admin_required
def api_employee_detail(employee_id):
    """API для получения, обновления или удаления конкретного сотрудника"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if request.method == 'GET':
            # Получение информации о сотруднике
            cursor.execute('''
                SELECT 
                    e.*,
                    GROUP_CONCAT(DISTINCT l.name) as accessible_labs,
                    GROUP_CONCAT(DISTINCT l.id) as accessible_lab_ids
                FROM employees e
                LEFT JOIN access_schedules a ON e.id = a.employee_id
                LEFT JOIN laboratories l ON a.laboratory_id = l.id
                WHERE e.id = ?
                GROUP BY e.id
            ''', (employee_id,))

            employee = cursor.fetchone()

            if not employee:
                conn.close()
                return jsonify({'success': False, 'message': 'Сотрудник не найден'}), 404

            # Получаем расписание доступа сотрудника
            cursor.execute('''
                SELECT 
                    a.laboratory_id,
                    l.name as laboratory_name,
                    a.days_of_week,
                    a.time_start,
                    a.time_end
                FROM access_schedules a
                JOIN laboratories l ON a.laboratory_id = l.id
                WHERE a.employee_id = ?
                ORDER BY l.name
            ''', (employee_id,))

            schedule = []
            for row in cursor.fetchall():
                schedule_item = dict(row)
                # Преобразуем дни недели в список
                if schedule_item['days_of_week']:
                    schedule_item['days_of_week'] = schedule_item['days_of_week'].split(',')
                else:
                    schedule_item['days_of_week'] = []
                schedule.append(schedule_item)

            employee_data = dict(employee)
            employee_data['access_schedule'] = schedule

            # Также получаем список ID лабораторий для удобства
            cursor.execute('''
                SELECT DISTINCT laboratory_id 
                FROM access_schedules 
                WHERE employee_id = ?
            ''', (employee_id,))

            lab_ids = [row['laboratory_id'] for row in cursor.fetchall()]
            employee_data['laboratory_ids'] = lab_ids

            conn.close()
            return jsonify({'success': True, 'employee': employee_data})

        elif request.method == 'PUT':
            # Обновление информации о сотруднике
            data = request.get_json()

            # Проверяем существование сотрудника
            cursor.execute("SELECT id FROM employees WHERE id = ?", (employee_id,))
            if not cursor.fetchone():
                conn.close()
                return jsonify({'success': False, 'message': 'Сотрудник не найден'}), 404

            # Подготавливаем поля для обновления
            update_fields = []
            update_values = []

            allowed_fields = ['full_name', 'department', 'position', 'phone', 'email', 'is_active', 'user_type']

            for field in allowed_fields:
                if field in data:
                    update_fields.append(f"{field} = ?")
                    update_values.append(data[field])

            # Проверяем PIN-код, если он указан
            if 'pin_code' in data:
                pin_code = str(data['pin_code']).strip()

                # Проверка длины PIN-кода
                if len(pin_code) < MIN_PIN_LENGTH or len(pin_code) > MAX_PIN_LENGTH:
                    conn.close()
                    return jsonify({
                        'success': False,
                        'message': f'PIN-код должен содержать от {MIN_PIN_LENGTH} до {MAX_PIN_LENGTH} цифр'
                    }), 400

                if not pin_code.isdigit():
                    conn.close()
                    return jsonify({'success': False, 'message': 'PIN-код должен содержать только цифры'}), 400

                # Проверка уникальности PIN-кода
                cursor.execute(
                    "SELECT id FROM employees WHERE pin_code = ? AND id != ?",
                    (pin_code, employee_id)
                )
                if cursor.fetchone():
                    conn.close()
                    return jsonify({'success': False, 'message': 'PIN-код уже используется другим сотрудником'}), 400

                update_fields.append("pin_code = ?")
                update_values.append(pin_code)

            # Обновляем пароль, если он указан и не пустой
            if 'password' in data and data['password'].strip():
                password = data['password'].strip()
                if len(password) < MIN_PASSWORD_LENGTH:
                    conn.close()
                    return jsonify({
                        'success': False,
                        'message': f'Пароль должен содержать не менее {MIN_PASSWORD_LENGTH} символов'
                    }), 400

                update_fields.append("password = ?")
                update_values.append(password)

            if not update_fields:
                conn.close()
                return jsonify({'success': False, 'message': 'Нет данных для обновления'}), 400

            # Выполняем обновление
            update_values.append(employee_id)
            update_query = f"UPDATE employees SET {', '.join(update_fields)} WHERE id = ?"

            cursor.execute(update_query, update_values)
            conn.commit()
            conn.close()

            return jsonify({'success': True, 'message': 'Данные сотрудника обновлены'})

        elif request.method == 'DELETE':
            # Удаление сотрудника
            # Проверяем, есть ли у сотрудника активные сессии
            cursor.execute(
                "SELECT id FROM current_presence WHERE employee_id = ?",
                (employee_id,)
            )
            if cursor.fetchone():
                conn.close()
                return jsonify({
                    'success': False,
                    'message': 'Нельзя удалить сотрудника, который находится в лаборатории'
                }), 400

            # Удаляем расписание доступа
            cursor.execute("DELETE FROM access_schedules WHERE employee_id = ?", (employee_id,))

            # Удаляем сотрудника
            cursor.execute("DELETE FROM employees WHERE id = ?", (employee_id,))

            conn.commit()
            conn.close()

            return jsonify({'success': True, 'message': 'Сотрудник удален'})

    except Exception as e:
        print(f"Ошибка при работе с сотрудником: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/employees/<int:employee_id>/access', methods=['GET', 'POST'])
@login_required
@admin_required
def api_employee_access(employee_id):
    """API для управления правами доступа сотрудника"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Проверяем существование сотрудника
        cursor.execute("SELECT id FROM employees WHERE id = ?", (employee_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Сотрудник не найден'}), 404

        if request.method == 'GET':
            # Получение текущих прав доступа
            cursor.execute('''
                SELECT 
                    a.*,
                    l.name as laboratory_name,
                    l.code as laboratory_code
                FROM access_schedules a
                JOIN laboratories l ON a.laboratory_id = l.id
                WHERE a.employee_id = ?
                ORDER BY l.name
            ''', (employee_id,))

            access_rights = [dict(row) for row in cursor.fetchall()]

            # Получаем все лаборатории для выпадающего списка
            cursor.execute('''
                SELECT id, name, code 
                FROM laboratories 
                WHERE is_active = TRUE
                ORDER BY name
            ''')

            all_labs = [dict(row) for row in cursor.fetchall()]

            conn.close()

            return jsonify({
                'success': True,
                'access_rights': access_rights,
                'all_laboratories': all_labs
            })

        elif request.method == 'POST':
            # Добавление/обновление прав доступа
            data = request.get_json()

            required_fields = ['laboratory_id', 'days_of_week', 'time_start', 'time_end']
            for field in required_fields:
                if field not in data:
                    conn.close()
                    return jsonify({'success': False, 'message': f'Не указано поле: {field}'}), 400

            # Проверяем существование лаборатории
            cursor.execute(
                "SELECT id FROM laboratories WHERE id = ? AND is_active = TRUE",
                (data['laboratory_id'],)
            )
            if not cursor.fetchone():
                conn.close()
                return jsonify({'success': False, 'message': 'Лаборатория не найдена'}), 404

            # Преобразуем список дней в строку
            days_str = ','.join(map(str, data['days_of_week']))

            # Проверяем, существует ли уже запись для этого сотрудника и лаборатории
            cursor.execute('''
                SELECT id FROM access_schedules 
                WHERE employee_id = ? AND laboratory_id = ?
            ''', (employee_id, data['laboratory_id']))

            existing = cursor.fetchone()

            if existing:
                # Обновляем существующую запись
                cursor.execute('''
                    UPDATE access_schedules 
                    SET days_of_week = ?, time_start = ?, time_end = ?
                    WHERE id = ?
                ''', (days_str, data['time_start'], data['time_end'], existing['id']))
            else:
                # Добавляем новую запись
                cursor.execute('''
                    INSERT INTO access_schedules (employee_id, laboratory_id, days_of_week, time_start, time_end)
                    VALUES (?, ?, ?, ?, ?)
                ''', (employee_id, data['laboratory_id'], days_str,
                      data['time_start'], data['time_end']))

            conn.commit()
            conn.close()

            return jsonify({'success': True, 'message': 'Права доступа обновлены'})

    except Exception as e:
        print(f"Ошибка при работе с правами доступа: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/employees/<int:employee_id>/access/<int:schedule_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_access_schedule(employee_id, schedule_id):
    """API для удаления расписания доступа"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Проверяем, что расписание принадлежит сотруднику
        cursor.execute('''
            SELECT id FROM access_schedules 
            WHERE id = ? AND employee_id = ?
        ''', (schedule_id, employee_id))

        if not cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Расписание не найдено'}), 404

        cursor.execute("DELETE FROM access_schedules WHERE id = ?", (schedule_id,))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Расписание удалено'})

    except Exception as e:
        print(f"Ошибка при удалении расписания: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/generate_report', methods=['POST'])
@login_required
@admin_required
def api_generate_report():
    try:
        data = request.get_json()
        report_type = data.get('type', 'daily')
        report_name = data.get('name', 'Отчет АСКУД')
        period_start = data.get('period_start')
        period_end = data.get('period_end')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Определяем период и SQL-запрос в зависимости от типа отчета
        if report_type == 'daily':
            # Отчет за день
            query = '''
                SELECT DATE(ae.event_time) as date,
                       e.full_name,
                       l.name as laboratory,
                       ae.event_type,
                       COUNT(*) as count
                FROM access_events ae
                JOIN employees e ON ae.employee_id = e.id
                JOIN laboratories l ON ae.laboratory_id = l.id
                WHERE DATE(ae.event_time) = DATE('now')
                GROUP BY DATE(ae.event_time), e.full_name, l.name, ae.event_type
                ORDER BY date, e.full_name
            '''
            params = ()
            filename = f'report_daily_{datetime.now().strftime("%Y%m%d")}.csv'

        elif report_type == 'weekly':
            # Отчет за неделю
            week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            today = datetime.now().strftime('%Y-%m-%d')
            query = '''
                SELECT ae.event_time,
                       e.full_name,
                       e.department,
                       l.name as laboratory,
                       ae.event_type,
                       ae.success,
                       ae.reason
                FROM access_events ae
                JOIN employees e ON ae.employee_id = e.id
                JOIN laboratories l ON ae.laboratory_id = l.id
                WHERE DATE(ae.event_time) BETWEEN ? AND ?
                ORDER BY ae.event_time
            '''
            params = (week_ago, today)
            filename = f'report_weekly_{week_ago}_to_{today}.csv'

        elif report_type == 'monthly':
            # Отчет за месяц
            month_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            today = datetime.now().strftime('%Y-%m-%d')
            query = '''
                SELECT ae.event_time,
                       e.full_name,
                       e.department,
                       l.name as laboratory,
                       ae.event_type,
                       ae.success,
                       ae.reason
                FROM access_events ae
                JOIN employees e ON ae.employee_id = e.id
                JOIN laboratories l ON ae.laboratory_id = l.id
                WHERE DATE(ae.event_time) BETWEEN ? AND ?
                ORDER BY ae.event_time
            '''
            params = (month_ago, today)
            filename = f'report_monthly_{datetime.now().strftime("%Y%m")}.csv'

        elif report_type == 'custom':
            # Пользовательский отчет
            if not period_start or not period_end:
                return jsonify({'success': False, 'message': 'Укажите период для отчета'}), 400

            query = '''
                SELECT ae.event_time,
                       e.full_name,
                       e.department,
                       l.name as laboratory,
                       ae.event_type,
                       ae.success,
                       ae.reason
                FROM access_events ae
                JOIN employees e ON ae.employee_id = e.id
                JOIN laboratories l ON ae.laboratory_id = l.id
                WHERE DATE(ae.event_time) BETWEEN ? AND ?
                ORDER BY ae.event_time
            '''
            params = (period_start, period_end)
            filename = f'report_custom_{period_start}_to_{period_end}.csv'
        else:
            # Для других типов используем дневной отчет
            query = '''
                SELECT ae.event_time,
                       e.full_name,
                       e.department,
                       l.name as laboratory,
                       ae.event_type,
                       ae.success,
                       ae.reason
                FROM access_events ae
                JOIN employees e ON ae.employee_id = e.id
                JOIN laboratories l ON ae.laboratory_id = l.id
                WHERE DATE(ae.event_time) = DATE('now')
                ORDER BY ae.event_time
            '''
            params = ()
            filename = f'report_{report_type}_{datetime.now().strftime("%Y%m%d")}.csv'

        # Выполняем запрос с параметрами
        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Создаем CSV в памяти
        output = io.StringIO()
        writer = csv.writer(output)

        # Если есть данные, получаем заголовки из первой строки
        if rows:
            # Получаем ключи из первого ряда
            keys = rows[0].keys()
            writer.writerow(keys)

            # Записываем данные
            for row in rows:
                writer.writerow([row[key] for key in keys])
        else:
            # Если данных нет, создаем заголовки по умолчанию
            if report_type in ['daily', 'weekly', 'monthly', 'custom']:
                headers = ['Дата и время', 'Сотрудник', 'Отдел', 'Лаборатория', 'Событие', 'Статус', 'Причина']
            else:
                headers = ['date', 'full_name', 'laboratory', 'event_type', 'count']
            writer.writerow(headers)
            writer.writerow(['Нет данных за выбранный период'])

        # Сохраняем отчет в базе
        cursor.execute('''
            INSERT INTO reports (name, report_type, period_start, period_end, created_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (filename, report_type, period_start or datetime.now().strftime('%Y-%m-%d'),
              period_end or datetime.now().strftime('%Y-%m-%d'), session['user_id']))

        conn.commit()
        conn.close()

        output.seek(0)

        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        print(f"Ошибка при генерации отчета: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/admin/export/excel')
@login_required
@admin_required
def api_export_excel():
    """Экспорт данных в Excel формате"""
    try:
        if not HAS_PANDAS:
            return jsonify({
                'success': False,
                'message': 'Для экспорта в Excel требуется установить библиотеки pandas и openpyxl'
            }), 500

        import pandas as pd
        import io

        conn = get_db_connection()

        # 1. Сотрудники
        employees_df = pd.read_sql_query('SELECT * FROM employees', conn)

        # 2. Лаборатории
        labs_df = pd.read_sql_query('SELECT * FROM laboratories', conn)

        # 3. События за последние 30 дней
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        events_df = pd.read_sql_query(
            'SELECT * FROM access_events WHERE DATE(event_time) >= ? ORDER BY event_time',
            conn, params=(thirty_days_ago,)
        )

        # 4. Расписание доступа
        schedule_df = pd.read_sql_query('SELECT * FROM access_schedules', conn)

        conn.close()

        # Создаем Excel файл в памяти
        output = io.BytesIO()

        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            employees_df.to_excel(writer, sheet_name='Сотрудники', index=False)
            labs_df.to_excel(writer, sheet_name='Лаборатории', index=False)
            events_df.to_excel(writer, sheet_name='События', index=False)
            schedule_df.to_excel(writer, sheet_name='Расписание', index=False)

        output.seek(0)

        # Сохраняем информацию об экспорте
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reports (name, report_type, period_start, period_end, created_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            f'excel_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
            'export',
            datetime.now().strftime('%Y-%m-%d'),
            datetime.now().strftime('%Y-%m-%d'),
            session['user_id']
        ))
        conn.commit()
        conn.close()

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'askud_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )

    except ImportError:
        return jsonify({
            'success': False,
            'message': 'Для экспорта в Excel требуется установить библиотеки pandas и openpyxl'
        }), 500
    except Exception as e:
        print(f"Ошибка при экспорте в Excel: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/admin/reports/<int:report_id>/download')
@login_required
@admin_required
def api_download_report(report_id):
    """Скачивание отчёта"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM reports WHERE id = ?', (report_id,))
        report = cursor.fetchone()
        conn.close()

        if not report:
            return jsonify({'success': False, 'message': 'Отчёт не найден'}), 404

        report_dict = dict(report)

        # Генерируем отчет на лету
        return generate_report_file(report_dict)

    except Exception as e:
        print(f"Ошибка при скачивании отчёта: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def generate_report_file(report):
    """Генерация файла отчёта"""
    import csv
    import io

    conn = get_db_connection()
    cursor = conn.cursor()

    # Определяем запрос и параметры в зависимости от типа отчета
    query = ''
    params = ()

    if report['report_type'] == 'daily':
        date_filter = datetime.now().strftime('%Y-%m-%d')
        query = '''
            SELECT ae.event_time, e.full_name, l.name, ae.event_type, ae.success, ae.reason
            FROM access_events ae
            JOIN employees e ON ae.employee_id = e.id
            JOIN laboratories l ON ae.laboratory_id = l.id
            WHERE DATE(ae.event_time) = ?
            ORDER BY ae.event_time
        '''
        params = (date_filter,)

    elif report['report_type'] == 'weekly':
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')
        query = '''
            SELECT ae.event_time, e.full_name, l.name, ae.event_type, ae.success, ae.reason
            FROM access_events ae
            JOIN employees e ON ae.employee_id = e.id
            JOIN laboratories l ON ae.laboratory_id = l.id
            WHERE DATE(ae.event_time) BETWEEN ? AND ?
            ORDER BY ae.event_time
        '''
        params = (week_ago, today)

    elif report['report_type'] == 'monthly':
        month_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')
        query = '''
            SELECT ae.event_time, e.full_name, l.name, ae.event_type, ae.success, ae.reason
            FROM access_events ae
            JOIN employees e ON ae.employee_id = e.id
            JOIN laboratories l ON ae.laboratory_id = l.id
            WHERE DATE(ae.event_time) BETWEEN ? AND ?
            ORDER BY ae.event_time
        '''
        params = (month_ago, today)

    elif report['report_type'] == 'custom':
        if not report['period_start'] or not report['period_end']:
            report['period_start'] = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            report['period_end'] = datetime.now().strftime('%Y-%m-%d')

        query = '''
            SELECT ae.event_time, e.full_name, l.name, ae.event_type, ae.success, ae.reason
            FROM access_events ae
            JOIN employees e ON ae.employee_id = e.id
            JOIN laboratories l ON ae.laboratory_id = l.id
            WHERE DATE(ae.event_time) BETWEEN ? AND ?
            ORDER BY ae.event_time
        '''
        params = (report['period_start'], report['period_end'])
    else:
        # По умолчанию дневной отчет
        date_filter = datetime.now().strftime('%Y-%m-%d')
        query = '''
            SELECT ae.event_time, e.full_name, l.name, ae.event_type, ae.success, ae.reason
            FROM access_events ae
            JOIN employees e ON ae.employee_id = e.id
            JOIN laboratories l ON ae.laboratory_id = l.id
            WHERE DATE(ae.event_time) = ?
            ORDER BY ae.event_time
        '''
        params = (date_filter,)

    # Выполняем запрос
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    # Создаем CSV в памяти
    output = io.StringIO()
    writer = csv.writer(output)

    # Заголовки
    headers = ['Дата и время', 'Сотрудник', 'Лаборатория', 'Событие', 'Статус', 'Причина']
    writer.writerow(headers)

    # Данные
    if rows:
        for row in rows:
            row_dict = dict(row)
            writer.writerow([
                row_dict['event_time'],
                row_dict['full_name'],
                row_dict['name'],
                'Вход' if row_dict['event_type'] == 'entry' else 'Выход',
                'Успешно' if row_dict['success'] else 'Отказ',
                row_dict['reason'] or ''
            ])
    else:
        writer.writerow(['Нет данных за выбранный период'])

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"{report['name'] or 'report'}.csv"
    )


@app.route('/api/admin/export/csv')
@login_required
@admin_required
def api_export_csv():
    """Экспорт всех данных в CSV файлы (ZIP архив)"""
    try:
        import zipfile
        import io
        import csv

        # Создаем ZIP архив в памяти
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 1. Экспорт сотрудников
            cursor.execute('''
                SELECT id, login, password, pin_code, full_name, department, 
                       position, phone, email, is_active, user_type, created_at
                FROM employees
                ORDER BY id
            ''')

            employees_data = io.StringIO()
            writer = csv.writer(employees_data)

            # Заголовки
            writer.writerow(['id', 'login', 'password', 'pin_code', 'full_name', 'department',
                             'position', 'phone', 'email', 'is_active', 'user_type', 'created_at'])

            # Данные
            for row in cursor.fetchall():
                writer.writerow(row)

            zip_file.writestr('employees.csv', employees_data.getvalue())

            # 2. Экспорт лабораторий
            cursor.execute('''
                SELECT id, name, code, location, description, capacity, is_active, created_at
                FROM laboratories
                ORDER BY id
            ''')

            labs_data = io.StringIO()
            writer = csv.writer(labs_data)
            writer.writerow(['id', 'name', 'code', 'location', 'description', 'capacity', 'is_active', 'created_at'])

            for row in cursor.fetchall():
                writer.writerow(row)

            zip_file.writestr('laboratories.csv', labs_data.getvalue())

            # 3. Экспорт прав доступа
            cursor.execute('''
                SELECT id, employee_id, laboratory_id, days_of_week, time_start, time_end
                FROM access_schedules
                ORDER BY id
            ''')

            access_data = io.StringIO()
            writer = csv.writer(access_data)
            writer.writerow(['id', 'employee_id', 'laboratory_id', 'days_of_week', 'time_start', 'time_end'])

            for row in cursor.fetchall():
                writer.writerow(row)

            zip_file.writestr('access_schedules.csv', access_data.getvalue())

            # 4. Экспорт событий доступа (за последние 30 дней)
            thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

            cursor.execute('''
                SELECT id, employee_id, laboratory_id, event_type, event_time, success, reason, method
                FROM access_events
                WHERE DATE(event_time) >= ?
                ORDER BY event_time
            ''', (thirty_days_ago,))

            events_data = io.StringIO()
            writer = csv.writer(events_data)
            writer.writerow(
                ['id', 'employee_id', 'laboratory_id', 'event_type', 'event_time', 'success', 'reason', 'method'])

            for row in cursor.fetchall():
                writer.writerow(row)

            zip_file.writestr('access_events_last_30_days.csv', events_data.getvalue())

            conn.close()

        zip_buffer.seek(0)

        # Сохраняем информацию об экспорте в базу
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reports (name, report_type, period_start, period_end, created_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            f'export_full_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip',
            'export',
            datetime.now().strftime('%Y-%m-%d'),
            datetime.now().strftime('%Y-%m-%d'),
            session['user_id']
        ))
        conn.commit()
        conn.close()

        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'askud_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
        )

    except Exception as e:
        print(f"Ошибка при экспорте данных: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/import/csv', methods=['POST'])
@login_required
@admin_required
def api_import_csv():
    """Импорт данных из CSV файла"""
    try:
        if 'csv_file' not in request.files:
            return jsonify({'success': False, 'message': 'Файл не выбран'}), 400

        file = request.files['csv_file']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'Файл не выбран'}), 400

        if not file.filename.endswith('.csv'):
            return jsonify({'success': False, 'message': 'Требуется CSV файл'}), 400

        # Читаем CSV файл
        import io
        import csv

        stream = io.TextIOWrapper(file.stream, encoding='utf-8-sig')
        csv_reader = csv.DictReader(stream)

        filename = file.filename.lower()
        conn = get_db_connection()
        cursor = conn.cursor()

        records_imported = 0
        records_skipped = 0

        if 'employees' in filename:
            # Импорт сотрудников
            for row in csv_reader:
                try:
                    # Проверяем обязательные поля
                    if not all(k in row for k in ['login', 'pin_code', 'full_name']):
                        records_skipped += 1
                        continue

                    # Проверяем уникальность логина
                    cursor.execute("SELECT id FROM employees WHERE login = ?", (row['login'],))
                    if cursor.fetchone():
                        records_skipped += 1
                        continue

                    # Проверяем уникальность PIN-кода
                    cursor.execute("SELECT id FROM employees WHERE pin_code = ?", (row['pin_code'],))
                    if cursor.fetchone():
                        records_skipped += 1
                        continue

                    # Добавляем сотрудника
                    cursor.execute('''
                        INSERT INTO employees (login, password, pin_code, full_name, department, 
                                              position, phone, email, is_active, user_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        row.get('login', ''),
                        row.get('password', '123456'),  # Пароль по умолчанию
                        row.get('pin_code', ''),
                        row.get('full_name', ''),
                        row.get('department', ''),
                        row.get('position', ''),
                        row.get('phone', ''),
                        row.get('email', ''),
                        bool(int(row.get('is_active', 1))),
                        row.get('user_type', 'employee')
                    ))

                    records_imported += 1
                except Exception as e:
                    print(f"Ошибка при импорте строки сотрудника: {e}")
                    records_skipped += 1

        elif 'laboratories' in filename:
            # Импорт лабораторий
            for row in csv_reader:
                try:
                    # Проверяем обязательные поля
                    if not all(k in row for k in ['name', 'code', 'location']):
                        records_skipped += 1
                        continue

                    # Проверяем уникальность кода
                    cursor.execute("SELECT id FROM laboratories WHERE code = ?", (row['code'],))
                    if cursor.fetchone():
                        records_skipped += 1
                        continue

                    # Добавляем лабораторию
                    cursor.execute('''
                        INSERT INTO laboratories (name, code, location, description, capacity, is_active)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        row.get('name', ''),
                        row.get('code', ''),
                        row.get('location', ''),
                        row.get('description', ''),
                        int(row.get('capacity', 10)),
                        bool(int(row.get('is_active', 1)))
                    ))

                    records_imported += 1
                except Exception as e:
                    print(f"Ошибка при импорте строки лаборатории: {e}")
                    records_skipped += 1

        elif 'access' in filename:
            # Импорт прав доступа
            for row in csv_reader:
                try:
                    # Проверяем обязательные поля
                    if not all(k in row for k in ['employee_id', 'laboratory_id']):
                        records_skipped += 1
                        continue

                    # Проверяем существование сотрудника и лаборатории
                    cursor.execute("SELECT id FROM employees WHERE id = ?", (row['employee_id'],))
                    if not cursor.fetchone():
                        records_skipped += 1
                        continue

                    cursor.execute("SELECT id FROM laboratories WHERE id = ?", (row['laboratory_id'],))
                    if not cursor.fetchone():
                        records_skipped += 1
                        continue

                    # Добавляем право доступа
                    cursor.execute('''
                        INSERT INTO access_schedules (employee_id, laboratory_id, days_of_week, time_start, time_end)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        int(row['employee_id']),
                        int(row['laboratory_id']),
                        row.get('days_of_week', '0,1,2,3,4'),
                        row.get('time_start', '08:00'),
                        row.get('time_end', '18:00')
                    ))

                    records_imported += 1
                except Exception as e:
                    print(f"Ошибка при импорте строки прав доступа: {e}")
                    records_skipped += 1
        else:
            conn.close()
            return jsonify({'success': False, 'message': 'Неизвестный тип файла'}), 400

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': f'Импорт завершен: {records_imported} записей импортировано, {records_skipped} пропущено'
        })

    except Exception as e:
        print(f"Ошибка при импорте данных: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/reports/list')
@login_required
@admin_required
def api_reports_list():
    """Получение списка всех отчетов"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT 
                r.*,
                e.full_name as created_by_name
            FROM reports r
            LEFT JOIN employees e ON r.created_by = e.id
            ORDER BY r.generated_at DESC
            LIMIT 50
        ''')

        reports = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return jsonify({'success': True, 'reports': reports})

    except Exception as e:
        print(f"Ошибка при получении списка отчетов: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/reports/<int:report_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_report(report_id):
    """Удаление отчета"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM reports WHERE id = ?", (report_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Отчет не найден'}), 404

        cursor.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Отчет удален'})

    except Exception as e:
        print(f"Ошибка при удалении отчета: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/dashboard_stats')
@login_required
@admin_required
def api_dashboard_stats():
    """Расширенная статистика для дашборда"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Базовая статистика
        stats = get_statistics()

        # Статистика по дням за последние 7 дней
        cursor.execute('''
            SELECT 
                DATE(event_time) as date,
                COUNT(CASE WHEN event_type = 'entry' AND success = TRUE THEN 1 END) as entries,
                COUNT(CASE WHEN event_type = 'exit' AND success = TRUE THEN 1 END) as exits,
                COUNT(CASE WHEN success = FALSE THEN 1 END) as denied
            FROM access_events
            WHERE DATE(event_time) >= DATE('now', '-7 days')
            GROUP BY DATE(event_time)
            ORDER BY date
        ''')

        daily_stats = [dict(row) for row in cursor.fetchall()]

        # Самые активные лаборатории
        cursor.execute('''
            SELECT 
                l.name,
                COUNT(ae.id) as events_count
            FROM access_events ae
            JOIN laboratories l ON ae.laboratory_id = l.id
            WHERE DATE(ae.event_time) = DATE('now')
            GROUP BY l.id
            ORDER BY events_count DESC
            LIMIT 5
        ''')

        top_labs = [dict(row) for row in cursor.fetchall()]

        # Сотрудники с наибольшим количеством событий
        cursor.execute('''
            SELECT 
                e.full_name,
                COUNT(ae.id) as events_count
            FROM access_events ae
            JOIN employees e ON ae.employee_id = e.id
            WHERE DATE(ae.event_time) = DATE('now')
            GROUP BY e.id
            ORDER BY events_count DESC
            LIMIT 10
        ''')

        top_employees = [dict(row) for row in cursor.fetchall()]

        # Среднее время пребывания (примерно)
        cursor.execute('''
            SELECT 
                AVG(
                    CAST(
                        (strftime('%s', cp.expected_exit_time) - strftime('%s', cp.entry_time)) / 3600.0 
                        AS REAL
                    )
                ) as avg_hours
            FROM current_presence cp
        ''')

        avg_hours = cursor.fetchone()[0] or 0

        conn.close()

        return jsonify({
            'success': True,
            'stats': stats,
            'daily_stats': daily_stats,
            'top_labs': top_labs,
            'top_employees': top_employees,
            'avg_hours': round(avg_hours, 2)
        })

    except Exception as e:
        print(f"Ошибка при получении статистики: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/search')
@login_required
def api_search():
    """Поиск по системе"""
    try:
        query = request.args.get('q', '').strip()
        if len(query) < 2:
            return jsonify({'success': False, 'message': 'Слишком короткий запрос'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        results = {
            'employees': [],
            'laboratories': [],
            'events': []
        }

        # Поиск сотрудников
        cursor.execute('''
            SELECT id, full_name, department, position
            FROM employees
            WHERE full_name LIKE ? OR department LIKE ? OR position LIKE ?
            LIMIT 10
        ''', (f'%{query}%', f'%{query}%', f'%{query}%'))

        results['employees'] = [dict(row) for row in cursor.fetchall()]

        # Поиск лабораторий
        cursor.execute('''
            SELECT id, name, code, location
            FROM laboratories
            WHERE name LIKE ? OR code LIKE ? OR location LIKE ?
            LIMIT 10
        ''', (f'%{query}%', f'%{query}%', f'%{query}%'))

        results['laboratories'] = [dict(row) for row in cursor.fetchall()]

        # Поиск событий (только для администраторов)
        if session.get('user_type') == 'admin':
            cursor.execute('''
                SELECT ae.id, e.full_name, l.name as laboratory, ae.event_type, ae.event_time
                FROM access_events ae
                JOIN employees e ON ae.employee_id = e.id
                JOIN laboratories l ON ae.laboratory_id = l.id
                WHERE e.full_name LIKE ? OR l.name LIKE ?
                ORDER BY ae.event_time DESC
                LIMIT 10
            ''', (f'%{query}%', f'%{query}%'))

            results['events'] = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return jsonify({
            'success': True,
            'query': query,
            'results': results
        })

    except Exception as e:
        print(f"Ошибка при поиске: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/system_info')
@login_required
@admin_required
def api_system_info():
    """Информация о системе"""
    import sqlite3
    import platform
    from datetime import datetime

    conn = get_db_connection()
    cursor = conn.cursor()

    # Статистика базы данных
    cursor.execute("SELECT COUNT(*) FROM employees")
    employees_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM laboratories")
    labs_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM access_events")
    events_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM access_schedules")
    schedules_count = cursor.fetchone()[0]

    # Размер базы данных
    import os
    db_size = os.path.getsize('access_system.db') if os.path.exists('access_system.db') else 0

    conn.close()

    info = {
        'system': {
            'python_version': platform.python_version(),
            'platform': platform.platform(),
            'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'database_size': f"{db_size / 1024 / 1024:.2f} MB"
        },
        'database': {
            'employees': employees_count,
            'laboratories': labs_count,
            'events': events_count,
            'schedules': schedules_count
        },
        'config': {
            'min_pin_length': MIN_PIN_LENGTH,
            'max_pin_length': MAX_PIN_LENGTH,
            'min_password_length': MIN_PASSWORD_LENGTH
        }
    }

    return jsonify({'success': True, 'info': info})


@app.route('/api/statistics', methods=['GET'])
def api_get_statistics():
    """
    Получение статистики системы
    """
    try:
        stats = get_statistics()
        return jsonify(stats)
    except Exception as e:
        return jsonify({
            "error": "Internal Server Error",
            "message": str(e),
            "status_code": 500
        }), 500


@app.route('/api/admin/employees', methods=['POST'])
@login_required
@admin_required
def api_admin_employees_post():
    """API для добавления сотрудника (админ)"""
    try:
        data = request.get_json()

        # Валидация данных
        required_fields = ['login', 'password', 'pin_code', 'full_name']
        for field in required_fields:
            if field not in data or not str(data.get(field, '')).strip():
                return jsonify({'success': False, 'message': f'Поле {field} обязательно'}), 400

        # Проверка длины PIN-кода
        pin_code = str(data['pin_code']).strip()
        if len(pin_code) < MIN_PIN_LENGTH or len(pin_code) > MAX_PIN_LENGTH:
            return jsonify({
                'success': False,
                'message': f'PIN-код должен содержать от {MIN_PIN_LENGTH} до {MAX_PIN_LENGTH} цифр'
            }), 400

        if not pin_code.isdigit():
            return jsonify({'success': False, 'message': 'PIN-код должен содержать только цифры'}), 400

        # Проверка уникальности логина и PIN-кода
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM employees WHERE login = ?", (data['login'].strip(),))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Логин уже существует'}), 400

        cursor.execute("SELECT id FROM employees WHERE pin_code = ?", (pin_code,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'PIN-код уже используется'}), 400

        # Добавление сотрудника
        cursor.execute('''
            INSERT INTO employees (login, password, pin_code, full_name, department, 
                                  position, phone, email, is_active, user_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['login'].strip(),
            data['password'].strip(),
            pin_code,
            data['full_name'].strip(),
            data.get('department', '').strip(),
            data.get('position', '').strip(),
            data.get('phone', '').strip(),
            data.get('email', '').strip(),
            data.get('is_active', True),
            data.get('user_type', 'employee')
        ))

        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Сотрудник добавлен'})

    except Exception as e:
        print(f"Ошибка при добавлении сотрудника: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/employees', methods=['GET'])
def api_get_employees():
    """
    Получение списка сотрудников
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем параметры запроса
    active_only = request.args.get('active_only', 'true').lower() == 'true'
    limit = request.args.get('limit', default=50, type=int)

    query = "SELECT * FROM employees"
    params = []

    if active_only:
        query += " WHERE is_active = TRUE"

    query += " ORDER BY id LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    employees = [dict(row) for row in cursor.fetchall()]

    conn.close()

    # Убираем пароли из ответа
    for emp in employees:
        emp.pop('password', None)

    return jsonify(employees)


@app.route('/api/laboratories', methods=['GET'])
def api_get_laboratories():
    """
    Получение списка лабораторий
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM laboratories WHERE is_active = TRUE ORDER BY id")
    laboratories = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return jsonify(laboratories)


@app.route('/api/access_events', methods=['GET'])
def api_get_access_events():
    """
    Получение событий доступа
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    limit = request.args.get('limit', default=50, type=int)
    date_filter = request.args.get('date')

    query = """
        SELECT ae.*, e.full_name, l.name as lab_name
        FROM access_events ae
        JOIN employees e ON ae.employee_id = e.id
        JOIN laboratories l ON ae.laboratory_id = l.id
    """

    params = []

    if date_filter:
        query += " WHERE DATE(ae.event_time) = DATE(?)"
        params.append(date_filter)

    query += " ORDER BY ae.event_time DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    events = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return jsonify(events)


@app.route('/api/current_presence', methods=['GET'])
def api_get_current_presence():
    """
    Получение списка сотрудников в лабораториях
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT cp.employee_id, e.full_name, l.name as lab_name, cp.entry_time
        FROM current_presence cp
        JOIN employees e ON cp.employee_id = e.id
        JOIN laboratories l ON cp.laboratory_id = l.id
        ORDER BY cp.entry_time DESC
    ''')

    presence = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return jsonify({
        "count": len(presence),
        "employees": presence
    })


# Эндпоинт для проверки PIN-кода (имитация терминала)
@app.route('/api/check_access', methods=['POST'])
def api_check_access():
    """
    Проверка доступа по PIN-коду
    """
    data = request.get_json()

    if not data or 'pin_code' not in data or 'laboratory_id' not in data:
        return jsonify({
            "success": False,
            "message": "Требуются pin_code и laboratory_id"
        }), 400

    pin_code = data['pin_code']
    lab_id = data['laboratory_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Поиск сотрудника по PIN-коду
    cursor.execute('''
        SELECT e.* 
        FROM employees e 
        WHERE e.pin_code = ? AND e.is_active = TRUE
    ''', (pin_code,))

    employee = cursor.fetchone()

    if not employee:
        conn.close()
        return jsonify({
            "success": False,
            "message": "Неверный PIN-код или сотрудник неактивен"
        }), 403

    employee_dict = dict(employee)

    # Проверка прав доступа
    day_of_week = datetime.now().weekday()  # 0-понедельник, 6-воскресенье
    current_time = datetime.now().strftime('%H:%M')

    cursor.execute('''
        SELECT * FROM access_schedules 
        WHERE employee_id = ? 
        AND laboratory_id = ? 
        AND days_of_week LIKE ?
        AND time_start <= ? 
        AND time_end >= ?
    ''', (employee_dict['id'], lab_id, f'%{day_of_week}%', current_time, current_time))

    has_access = cursor.fetchone() is not None

    # Запись события
    cursor.execute('''
        INSERT INTO access_events 
        (employee_id, laboratory_id, event_type, success, reason, method)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        employee_dict['id'],
        lab_id,
        'entry' if has_access else 'entry_denied',
        has_access,
        'По расписанию' if has_access else 'Нет доступа в это время',
        'pin'
    ))

    conn.commit()
    conn.close()

    if has_access:
        # Убираем пароль из ответа
        employee_dict.pop('password', None)

        return jsonify({
            "success": True,
            "message": "Доступ разрешен",
            "employee": employee_dict
        })
    else:
        return jsonify({
            "success": False,
            "message": "Доступ запрещен: вне расписания"
        }), 403


# Health check endpoint
@app.route('/api/health', methods=['GET'])
def api_health():
    """
    Проверка здоровья системы
    """
    try:
        # Проверка подключения к БД
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        db_status = "connected"
        conn.close()
    except:
        db_status = "disconnected"

    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "database": db_status,
        "version": "2.0"
    })


if __name__ == '__main__':
    # Инициализируем базу данных
    init_database()

    # Запускаем миграцию старых данных
    migrate_old_data()

    print(f"\n🚀 Запуск АСКУД версии 2.0")
    print("📍 Главная страница: http://localhost:5000")
    print("📍 Терминал доступа: http://localhost:5000/terminal")
    print("📍 Панель управления: http://localhost:5000/admin")
    print(f"📍 Тестовый администратор: логин 'admin', пароль 'admin123', PIN '0000'")
    app.run(debug=True, host='0.0.0.0', port=5000)