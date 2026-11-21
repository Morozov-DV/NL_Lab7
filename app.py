"""Flask-застосунок: HTTP-рівень (маршрути). Уся прикладна логіка — в окремих модулях."""
import io

from flask import Flask, render_template, request, jsonify, send_file

import storage
from export_service import export_csv, export_xlsx
from fuzzy_controller import FanFuzzyController, TERM_LABELS, UNIVERSES
from simulation import PARAM_LIMITS, validate_params, run_simulation

app = Flask(__name__)
controller = FanFuzzyController()      # один екземпляр: функції належності обчислюються раз
storage.init_db()


@app.get("/")
def index():
    defaults = {k: v[2] for k, v in PARAM_LIMITS.items()}
    limits = {k: {"min": v[0], "max": v[1]} for k, v in PARAM_LIMITS.items()}
    return render_template("index.html", defaults=defaults, limits=limits,
                           universes=UNIVERSES)


@app.get("/api/membership")
def membership():
    """Функції належності, підписи термів і база правил."""
    return jsonify({
        "curves": controller.membership_curves(),
        "labels": TERM_LABELS,
        "rules": controller.rules_table(),
    })


@app.post("/api/infer")
def infer():
    """Нечіткий висновок для однієї точки (контрольні значення)."""
    data = request.get_json(silent=True) or {}
    try:
        values = {}
        for key in ("temperature", "humidity", "co2"):
            lo, hi = UNIVERSES[key]
            value = float(data[key])
            if not lo <= value <= hi:
                return jsonify({"error": f"«{key}» має бути в діапазоні {lo}…{hi}"}), 400
            values[key] = value
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Потрібні числові поля temperature, humidity, co2"}), 400
    details = controller.infer(values["temperature"], values["humidity"],
                               values["co2"], details=True)
    details["fan"] = round(details["fan"], 2)
    return jsonify(details)


@app.post("/api/simulate")
def simulate():
    """Запуск експерименту. Параметри перевіряються на сервері."""
    data = request.get_json(silent=True)
    if data is not None and not isinstance(data, dict):
        return jsonify({"error": "Очікується JSON-об'єкт"}), 400
    try:
        params = validate_params(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    result = run_simulation(params, controller)
    result["run_id"] = storage.save_run(result)
    return jsonify(result)


@app.get("/api/history")
def history():
    return jsonify(storage.list_runs())


def _load_or_404(run_id):
    result = storage.get_run(run_id)
    if result is None:
        return None, (jsonify({"error": "Експеримент не знайдено"}), 404)
    return result, None


@app.get("/api/export/<int:run_id>.csv")
def download_csv(run_id):
    result, error = _load_or_404(run_id)
    if error:
        return error
    return send_file(io.BytesIO(export_csv(result)), mimetype="text/csv",
                     as_attachment=True, download_name=f"fan_experiment_{run_id}.csv")


@app.get("/api/export/<int:run_id>.xlsx")
def download_xlsx(run_id):
    result, error = _load_or_404(run_id)
    if error:
        return error
    return send_file(
        io.BytesIO(export_xlsx(result)),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name=f"fan_experiment_{run_id}.xlsx")


if __name__ == "__main__":
    app.run(debug=True)
