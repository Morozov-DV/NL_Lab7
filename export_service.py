"""Формування файлів експорту (CSV та XLSX) за результатами експерименту."""
import csv
import io

import pandas as pd

# Назви параметрів і метрик для файлів
PARAM_NAMES = {
    "temperature0": "Початкова температура, °C",
    "humidity0": "Початкова вологість, %",
    "co2_0": "Початковий CO2, ppm",
    "duration": "Тривалість, хв",
    "disturbance_time": "Момент збурення, хв",
    "disturbance_gain": "Множник збурення",
    "tau_fan": "Стала часу вентилятора, хв",
}

COLUMNS = {
    "time": "Час, хв",
    "temperature": "Температура, °C",
    "humidity": "Вологість, %",
    "co2": "CO2, ppm",
    "fan_command": "Керувальний сигнал (команда), %",
    "fan_actual": "Швидкість вентилятора (факт), %",
    "discomfort": "Показник дискомфорту",
    "disturbance": "Множник збурення",
}


def _metrics_rows(metrics):
    """Перетворює вкладені метрики на плоский список (назва, значення)."""
    labels = {"max": "максимум", "min": "мінімум", "steady": "усталене значення",
              "settle_time": "час входу в зону, хв", "in_zone": "входить у зону"}
    names = {"temperature": "Температура", "humidity": "Вологість", "co2": "CO2"}
    rows = []
    for key in ("temperature", "humidity", "co2"):
        for field, label in labels.items():
            value = metrics[key][field]
            if field == "settle_time" and value is None:
                value = "не входить у зону"
            rows.append((f"{names[key]}: {label}", value))
    rows += [
        ("Час входу всіх величин у зону, хв",
         metrics["settle_time_all"] if metrics["all_in_zone"] else "не входить у зону"),
        ("Середня швидкість вентилятора, %", metrics["fan_mean"]),
        ("Максимальна швидкість вентилятора, %", metrics["fan_max"]),
        ("Енергетичний індекс (∫U dt), %·хв", metrics["fan_energy"]),
        ("Сумарна варіація керування, %", metrics["fan_variation"]),
        ("Інтегральний дискомфорт (IAE)", metrics["discomfort_iae"]),
    ]
    return rows


def export_csv(result):
    """CSV (роздільник «;», кодування UTF-8 з BOM — коректно відкривається в Excel).

    Спочатку йдуть службові рядки з параметрами та метриками (починаються
    з «#»), потім таблиця перехідного процесу.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["# Параметри експерименту"])
    for key, label in PARAM_NAMES.items():
        writer.writerow([f"# {label}", result["params"][key]])
    writer.writerow(["# Метрики якості"])
    for label, value in _metrics_rows(result["metrics"]):
        writer.writerow([f"# {label}", value])
    writer.writerow(list(COLUMNS.values()))
    for i in range(len(result["time"])):
        writer.writerow([result[key][i] for key in COLUMNS])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def export_xlsx(result):
    """XLSX з трьома аркушами: перехідний процес, параметри, метрики."""
    frame = pd.DataFrame({label: result[key] for key, label in COLUMNS.items()})
    params = pd.DataFrame(
        [(label, result["params"][key]) for key, label in PARAM_NAMES.items()],
        columns=["Параметр", "Значення"])
    metrics = pd.DataFrame(_metrics_rows(result["metrics"]),
                           columns=["Показник", "Значення"])
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Перехідний процес", index=False)
        params.to_excel(writer, sheet_name="Параметри", index=False)
        metrics.to_excel(writer, sheet_name="Метрики", index=False)
        for sheet in writer.sheets.values():          # ширина стовпців
            for col in sheet.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                sheet.column_dimensions[col[0].column_letter].width = min(width + 2, 48)
    return out.getvalue()
