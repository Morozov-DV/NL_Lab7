# Нечіткий регулятор швидкості вентилятора (Flask) — ЛР №7, варіант 14

Входи: температура, вологість, CO₂. Вихід: керувальний сигнал (швидкість вентилятора, %).
Нечіткий висновок Мамдані реалізовано на NumPy (без scikit-fuzzy).

## Запуск
    python -m venv .venv
    source .venv/bin/activate        # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python app.py                    # відкрити http://127.0.0.1:5000

## Тести
    python -m unittest -v

## Структура
- app.py — маршрути Flask (HTTP-рівень)
- fuzzy_controller.py — змінні, функції належності, 27 правил, висновок
- simulation.py — модель приміщення, вентилятор, метрики
- export_service.py — експорт CSV / XLSX
- storage.py — історія експериментів у SQLite
- templates/index.html, static/app.js, static/styles.css — інтерфейс (Chart.js з CDN)
