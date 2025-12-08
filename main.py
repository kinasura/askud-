import sqlite3
from datetime import datetime, time
import json
from typing import Optional, List, Dict


class LaboratoryAccessSystem:
    def __init__(self, db_path: str = "laboratory_access.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Таблица сотрудников
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                pin_code TEXT UNIQUE NOT NULL,
                department TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица лабораторий
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS laboratories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')

        # Таблица прав доступа
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS access_rights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                laboratory_id INTEGER,
                schedule_start TIME DEFAULT '08:00',
                schedule_end TIME DEFAULT '18:00',
                FOREIGN KEY (employee_id) REFERENCES employees (id),
                FOREIGN KEY (laboratory_id) REFERENCES laboratories (id)
            )
        ''')

        # Таблица событий доступа
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS access_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER,
                laboratory_id INTEGER,
                event_type TEXT NOT NULL, -- 'entry' или 'exit'
                event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success BOOLEAN NOT NULL,
                reason TEXT, -- Причина отказа (если success=False)
                FOREIGN KEY (employee_id) REFERENCES employees (id),
                FOREIGN KEY (laboratory_id) REFERENCES laboratories (id)
            )
        ''')

        # Таблица текущего присутствия
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS current_presence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER UNIQUE,
                laboratory_id INTEGER,
                entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (employee_id) REFERENCES employees (id),
                FOREIGN KEY (laboratory_id) REFERENCES laboratories (id)
            )
        ''')

        conn.commit()
        conn.close()

    def add_employee(self, full_name: str, pin_code: str, department: str = None) -> bool:
        """Добавление нового сотрудника"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO employees (full_name, pin_code, department) VALUES (?, ?, ?)",
                (full_name, pin_code, department)
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            print(f"Ошибка: PIN-код '{pin_code}' уже существует")
            return False

    def grant_access(self, employee_id: int, laboratory_id: int,
                     schedule_start: str = "08:00", schedule_end: str = "18:00") -> bool:
        """Предоставление прав доступа сотруднику"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO access_rights 
                (employee_id, laboratory_id, schedule_start, schedule_end) 
                VALUES (?, ?, ?, ?)''',
                (employee_id, laboratory_id, schedule_start, schedule_end)
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.Error as e:
            print(f"Ошибка при предоставлении доступа: {e}")
            return False

    def verify_access(self, pin_code: str, laboratory_id: int) -> Dict:
        """Проверка прав доступа и обработка входа/выхода"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Поиск сотрудника по PIN-коду
        cursor.execute(
            "SELECT id, full_name FROM employees WHERE pin_code = ? AND is_active = TRUE",
            (pin_code,)
        )
        employee = cursor.fetchone()

        if not employee:
            conn.close()
            return {
                "success": False,
                "message": "Неверный PIN-код или сотрудник неактивен",
                "action": None
            }

        employee_id, full_name = employee

        # Проверка текущего статуса присутствия
        cursor.execute(
            "SELECT laboratory_id FROM current_presence WHERE employee_id = ?",
            (employee_id,)
        )
        current_presence = cursor.fetchone()

        # Логика входа/выхода
        if current_presence:
            # Сотрудник уже внутри - регистрируем выход
            self._register_exit(employee_id, laboratory_id, conn)
            action = "exit"
            message = f"Выход сотрудника {full_name} зарегистрирован"
        else:
            # Сотрудник снаружи - проверяем права и регистрируем вход
            access_result = self._check_access_rights(employee_id, laboratory_id, conn)
            if access_result["success"]:
                self._register_entry(employee_id, laboratory_id, conn)
                action = "entry"
                message = f"Вход сотрудника {full_name} разрешен"
            else:
                conn.close()
                return {
                    "success": False,
                    "message": access_result["reason"],
                    "action": None
                }

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": message,
            "action": action,
            "employee_name": full_name
        }

    def _check_access_rights(self, employee_id: int, laboratory_id: int, conn) -> Dict:
        """Проверка прав доступа сотрудника"""
        cursor = conn.cursor()

        # Проверка наличия прав доступа
        cursor.execute('''
            SELECT schedule_start, schedule_end 
            FROM access_rights 
            WHERE employee_id = ? AND laboratory_id = ?
        ''', (employee_id, laboratory_id))

        access_right = cursor.fetchone()

        if not access_right:
            return {
                "success": False,
                "reason": "Доступ в эту лабораторию запрещен"
            }

        # Проверка временного расписания
        schedule_start, schedule_end = access_right
        current_time = datetime.now().time()

        start_time = time.fromisoformat(schedule_start)
        end_time = time.fromisoformat(schedule_end)

        if not (start_time <= current_time <= end_time):
            return {
                "success": False,
                "reason": f"Доступ разрешен только с {schedule_start} до {schedule_end}"
            }

        return {"success": True}

    def _register_entry(self, employee_id: int, laboratory_id: int, conn):
        """Регистрация входа сотрудника"""
        cursor = conn.cursor()

        # Добавляем запись о текущем присутствии
        cursor.execute(
            "INSERT INTO current_presence (employee_id, laboratory_id) VALUES (?, ?)",
            (employee_id, laboratory_id)
        )

        # Регистрируем событие входа
        cursor.execute(
            "INSERT INTO access_events (employee_id, laboratory_id, event_type, success) VALUES (?, ?, 'entry', TRUE)",
            (employee_id, laboratory_id)
        )

    def _register_exit(self, employee_id: int, laboratory_id: int, conn):
        """Регистрация выхода сотрудника"""
        cursor = conn.cursor()

        # Удаляем запись о текущем присутствии
        cursor.execute(
            "DELETE FROM current_presence WHERE employee_id = ?",
            (employee_id,)
        )

        # Регистрируем событие выхода
        cursor.execute(
            "INSERT INTO access_events (employee_id, laboratory_id, event_type, success) VALUES (?, ?, 'exit', TRUE)",
            (employee_id, laboratory_id)
        )

    def get_current_presence(self) -> List[Dict]:
        """Получение списка сотрудников, находящихся в лабораториях"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT e.full_name, l.name, cp.entry_time
            FROM current_presence cp
            JOIN employees e ON cp.employee_id = e.id
            JOIN laboratories l ON cp.laboratory_id = l.id
        ''')

        presence_data = []
        for row in cursor.fetchall():
            presence_data.append({
                "employee_name": row[0],
                "laboratory_name": row[1],
                "entry_time": row[2]
            })

        conn.close()
        return presence_data

    def generate_attendance_report(self, start_date: str, end_date: str) -> List[Dict]:
        """Генерация отчета о посещаемости"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT e.full_name, l.name, ae.event_type, ae.event_time
            FROM access_events ae
            JOIN employees e ON ae.employee_id = e.id
            JOIN laboratories l ON ae.laboratory_id = l.id
            WHERE DATE(ae.event_time) BETWEEN ? AND ?
            ORDER BY ae.event_time
        ''', (start_date, end_date))

        report_data = []
        for row in cursor.fetchall():
            report_data.append({
                "employee_name": row[0],
                "laboratory_name": row[1],
                "event_type": "Вход" if row[2] == "entry" else "Выход",
                "event_time": row[3]
            })

        conn.close()
        return report_data


# Демонстрация работы системы
def demo_system():
    system = LaboratoryAccessSystem()

    # Добавляем тестовые данные
    system.add_employee("Иванов Иван Иванович", "1234", "Исследовательская лаборатория")
    system.add_employee("Петров Петр Петрович", "5678", "Аналитическая лаборатория")

    # Создаем лаборатории
    conn = sqlite3.connect(system.db_path)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO laboratories (name, location) VALUES (?, ?)",
                   ("Химическая лаборатория", "Корпус А, этаж 3"))
    cursor.execute("INSERT OR IGNORE INTO laboratories (name, location) VALUES (?, ?)",
                   ("Биологическая лаборатория", "Корпус Б, этаж 2"))
    conn.commit()
    conn.close()

    # Предоставляем права доступа
    system.grant_access(1, 1)  # Иванов - в химическую лабораторию
    system.grant_access(2, 2)  # Петров - в биологическую лабораторию

    print("=== ДЕМОНСТРАЦИЯ СИСТЕМЫ КОНТРОЛЯ ДОСТУПА ===\n")

    # Симуляция работы терминалов
    test_scenarios = [
        ("1234", 1),  # Иванов входит в химическую лабораторию
        ("5678", 2),  # Петров входит в биологическую лабораторию
        ("1234", 1),  # Иванов выходит из химической лаборатории
        ("9999", 1),  # Неверный PIN-код
        ("5678", 1),  # Петров пытается войти в чужую лабораторию
    ]

    for pin, lab_id in test_scenarios:
        result = system.verify_access(pin, lab_id)
        print(f"PIN: {pin}, Лаборатория: {lab_id}")
        print(f"Результат: {result}\n")

    # Показываем текущее присутствие
    print("=== ТЕКУЩЕЕ ПРИСУТСТВИЕ ===")
    presence = system.get_current_presence()
    for person in presence:
        print(f"{person['employee_name']} - {person['laboratory_name']} (с {person['entry_time']})")

    # Генерируем отчет
    print("\n=== ОТЧЕТ ПО ПОСЕЩАЕМОСТИ ===")
    today = datetime.now().strftime("%Y-%m-%d")
    report = system.generate_attendance_report(today, today)
    for event in report:
        print(f"{event['event_time']} - {event['employee_name']} - {event['laboratory_name']} - {event['event_type']}")


if __name__ == "__main__":
    demo_system()