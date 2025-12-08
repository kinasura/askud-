# Разработка системы контроля доступа

## Запуск тестов

```bash
# Установить зависимости разработки
pip install -r requirements_dev.txt

# Запустить все тесты
pytest tests/ -v

# Запустить тесты с покрытием
pytest tests/ --cov=app --cov-report=html

# Запустить конкретный тест
pytest tests/test_system.py::test_get_statistics -v