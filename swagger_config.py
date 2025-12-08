"""
Swagger/OpenAPI конфигурация для системы контроля доступа
"""

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec',
            "route": '/apispec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
    "title": "Система контроля доступа в лаборатории",
    "version": "2.0",
    "description": """
    ## API для управления доступом в лаборатории

    ### Основные возможности:
    - Управление сотрудниками и их правами доступа
    - Контроль посещения лабораторий
    - Генерация отчетов
    - Статистика и мониторинг

    ### Авторизация:
    Большинство endpoints требуют авторизации.
    Используйте Basic Auth или сессионные куки.

    ### Коды ответов:
    - 200: Успех
    - 400: Неверный запрос
    - 401: Неавторизован
    - 403: Доступ запрещен
    - 404: Не найдено
    - 500: Ошибка сервера
    """
}

# OpenAPI спецификация
OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "Система контроля доступа в лаборатории",
        "description": "API для управления доступом сотрудников в лаборатории",
        "contact": {
            "name": "Администратор системы",
            "email": "admin@lab-access.local"
        },
        "version": "2.0"
    },
    "servers": [
        {
            "url": "http://localhost:5000",
            "description": "Локальный сервер разработки"
        }
    ],
    "tags": [
        {"name": "Аутентификация", "description": "Вход и управление сессиями"},
        {"name": "Сотрудники", "description": "Управление сотрудниками"},
        {"name": "Лаборатории", "description": "Управление лабораториями"},
        {"name": "Доступ", "description": "Контроль доступа и события"},
        {"name": "Отчеты", "description": "Генерация отчетов"},
        {"name": "Статистика", "description": "Статистика системы"}
    ],
    "components": {
        "schemas": {
            "Employee": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 1},
                    "login": {"type": "string", "example": "ivanov"},
                    "full_name": {"type": "string", "example": "Иванов Иван Иванович"},
                    "department": {"type": "string", "example": "Химическая лаборатория"},
                    "position": {"type": "string", "example": "Инженер-химик"},
                    "pin_code": {"type": "string", "example": "1234"},
                    "is_active": {"type": "boolean", "example": True}
                }
            },
            "Laboratory": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 1},
                    "name": {"type": "string", "example": "Химическая лаборатория"},
                    "code": {"type": "string", "example": "CHEM-001"},
                    "location": {"type": "string", "example": "Корпус А, этаж 3"},
                    "capacity": {"type": "integer", "example": 15},
                    "is_active": {"type": "boolean", "example": True}
                }
            },
            "AccessEvent": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "example": 1},
                    "employee_id": {"type": "integer", "example": 1},
                    "laboratory_id": {"type": "integer", "example": 1},
                    "event_type": {"type": "string", "enum": ["entry", "exit"], "example": "entry"},
                    "event_time": {"type": "string", "format": "date-time"},
                    "success": {"type": "boolean", "example": True},
                    "method": {"type": "string", "enum": ["pin", "login", "card"], "example": "pin"}
                }
            },
            "Statistics": {
                "type": "object",
                "properties": {
                    "employees_count": {"type": "integer", "example": 45},
                    "labs_count": {"type": "integer", "example": 8},
                    "active_count": {"type": "integer", "example": 12},
                    "today_events": {"type": "integer", "example": 47}
                }
            },
            "Error": {
                "type": "object",
                "properties": {
                    "error": {"type": "string", "example": "Not Found"},
                    "message": {"type": "string", "example": "Ресурс не найден"},
                    "status_code": {"type": "integer", "example": 404}
                }
            }
        },
        "securitySchemes": {
            "session_auth": {
                "type": "apiKey",
                "in": "cookie",
                "name": "session",
                "description": "Сессионная авторизация"
            },
            "basic_auth": {
                "type": "http",
                "scheme": "basic",
                "description": "Базовая HTTP аутентификация"
            }
        }
    }
}