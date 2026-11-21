"""Імітаційна модель приміщення з вентилятором і розрахунок показників якості.

Модель — три незалежні дискретні рівняння першого порядку (температура,
вологість, CO2), кожне з яких залежить від швидкості вентилятора:

    X[k+1] = X[k] + dt * ( (X_зовн - X[k]) * (a + b * v[k]) + q * g[k] )

де v = U_факт/100 — відносна швидкість вентилятора, a — природний обмін
(інфільтрація), b — ефективність вентиляції, q — внутрішнє виділення
(тепло, вологість, CO2 від людей і обладнання), g — коефіцієнт збурення.
Сам вентилятор — інерційна ланка: U_факт прямує до команди регулятора
зі сталою часу tau_fan.

Це навчальна модель, а не модель реального обладнання.
"""
from fuzzy_controller import FanFuzzyController

DT = 1.0  # крок моделювання, хв

# Постійні параметри моделі (мають бути вказані у звіті)
MODEL = {
    "temperature": {"outside": 20.0, "leak": 0.010, "vent": 0.080, "gain": 0.15},   # gain, °C/хв
    "humidity":    {"outside": 45.0, "leak": 0.010, "vent": 0.060, "gain": 0.35},   # gain, %/хв
    "co2":         {"outside": 420.0, "leak": 0.010, "vent": 0.100, "gain": 12.0},  # gain, ppm/хв
}

# Зони комфорту (використовуються для метрик)
COMFORT = {
    "temperature": (20.0, 26.0),
    "humidity": (40.0, 60.0),
    "co2": (400.0, 1000.0),
}

# Допустимі діапазони параметрів: (мін, макс, значення за замовчуванням)
PARAM_LIMITS = {
    "temperature0": (10.0, 40.0, 30.0),    # початкова температура, °C
    "humidity0": (0.0, 100.0, 70.0),       # початкова вологість, %
    "co2_0": (400.0, 2000.0, 1500.0),      # початкова концентрація CO2, ppm
    "duration": (10, 480, 180),            # тривалість експерименту, хв
    "disturbance_time": (0, 480, 90),      # момент збурення, хв
    "disturbance_gain": (0.0, 3.0, 1.3),   # множник внутрішніх виділень після збурення
    "tau_fan": (1.0, 10.0, 2.0),           # стала часу вентилятора, хв
}
INT_PARAMS = {"duration", "disturbance_time"}


def validate_params(data):
    """Перевіряє параметри на сервері; повертає очищений словник.

    Некоректні значення спричиняють ValueError з поясненням українською.
    """
    data = data or {}
    params = {}
    for name, (lo, hi, default) in PARAM_LIMITS.items():
        raw = data.get(name, default)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"Параметр «{name}» має бути числом")
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"Параметр «{name}» має скінченне значення")
        if not lo <= value <= hi:
            raise ValueError(f"Параметр «{name}» має бути в діапазоні {lo}…{hi}")
        params[name] = int(value) if name in INT_PARAMS else value
    return params


def _first_stable_entry(times, values, lo, hi):
    """Час, після якого величина назавжди залишається в зоні [lo, hi].

    Повертає None, якщо в кінці експерименту величина поза зоною.
    """
    entry = None
    for t, v in zip(times, values):
        if lo <= v <= hi:
            if entry is None:
                entry = t
        else:
            entry = None
    return entry


def compute_metrics(result):
    """Показники якості перехідного процесу."""
    t = result["time"]
    fan = result["fan_actual"]
    n = len(t)
    tail = max(1, n // 10)               # останні 10 % точок — «усталений режим»
    metrics = {}
    entries = []
    for key in ("temperature", "humidity", "co2"):
        series = result[key]
        lo, hi = COMFORT[key]
        entry = _first_stable_entry(t, series, lo, hi)
        entries.append(entry)
        metrics[key] = {
            "max": round(max(series), 2),
            "min": round(min(series), 2),
            "steady": round(sum(series[-tail:]) / tail, 2),
            "settle_time": entry,                    # None — не входить у зону
            "in_zone": entry is not None,
        }
    all_in = None not in entries
    metrics["settle_time_all"] = max(entries) if all_in else None
    metrics["all_in_zone"] = all_in
    metrics["fan_mean"] = round(sum(fan) / n, 2)
    metrics["fan_max"] = round(max(fan), 2)
    # Енергетичний індекс: інтеграл швидкості вентилятора, %·хв
    metrics["fan_energy"] = round(sum(fan) * DT, 1)
    # Сумарна варіація керування — показує плавність роботи
    metrics["fan_variation"] = round(
        sum(abs(fan[i + 1] - fan[i]) for i in range(n - 1)), 1)
    # Інтегральний показник дискомфорту (IAE нормованих виходів за зону)
    metrics["discomfort_iae"] = round(sum(result["discomfort"]) * DT, 3)
    return metrics


def run_simulation(params, controller=None):
    """Запускає експеримент: нечіткий регулятор + модель приміщення."""
    controller = controller or FanFuzzyController()
    steps = int(params["duration"] / DT)

    x = {
        "temperature": params["temperature0"],
        "humidity": params["humidity0"],
        "co2": params["co2_0"],
    }
    u_actual = 0.0                          # вентилятор спочатку вимкнений
    tau = params["tau_fan"]

    result = {k: [] for k in (
        "time", "temperature", "humidity", "co2",
        "fan_command", "fan_actual", "discomfort", "disturbance")}

    for k in range(steps + 1):
        time = k * DT
        # Регулятор отримує поточні виміри та формує керувальний сигнал
        u_cmd = controller.infer(x["temperature"], x["humidity"], x["co2"])

        # Збурення: після заданого моменту внутрішні виділення зростають
        g = params["disturbance_gain"] if time >= params["disturbance_time"] else 1.0

        # Нормований показник виходу за межі зон комфорту
        d = 0.0
        for key, scale in (("temperature", 6.0), ("humidity", 20.0), ("co2", 1000.0)):
            lo, hi = COMFORT[key]
            d += max(0.0, x[key] - hi, lo - x[key]) / scale

        # Запис поточного стану
        result["time"].append(time)
        for key in ("temperature", "humidity", "co2"):
            result[key].append(round(x[key], 3))
        result["fan_command"].append(round(u_cmd, 3))
        result["fan_actual"].append(round(u_actual, 3))
        result["discomfort"].append(round(d, 5))
        result["disturbance"].append(g)

        # Крок моделі об'єкта
        v = u_actual / 100.0
        for key, m in MODEL.items():
            dx = (m["outside"] - x[key]) * (m["leak"] + m["vent"] * v) + m["gain"] * g
            x[key] += DT * dx
        x["humidity"] = min(max(x["humidity"], 0.0), 100.0)
        x["co2"] = max(x["co2"], 400.0)
        # Інерційність вентилятора
        u_actual += DT / tau * (u_cmd - u_actual)
        u_actual = min(max(u_actual, 0.0), 100.0)

    result["metrics"] = compute_metrics(result)
    result["params"] = params
    result["comfort"] = {k: list(v) for k, v in COMFORT.items()}
    return result


if __name__ == "__main__":
    res = run_simulation(validate_params({}))
    import json
    print(json.dumps(res["metrics"], ensure_ascii=False, indent=2))
