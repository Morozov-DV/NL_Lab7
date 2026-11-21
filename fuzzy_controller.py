"""Нечіткий регулятор швидкості вентилятора (система типу Мамдані).

Входи:  температура T (°C), відносна вологість H (%), концентрація CO2 (ppm).
Вихід:  керувальний сигнал U — швидкість вентилятора, % (0...100).

Модуль не залежить від Flask: його можна імпортувати й перевіряти окремо.
"""
import numpy as np

# ---------------------------------------------------------------------------
# Універсуми (діапазони змінних)
# ---------------------------------------------------------------------------
UNIVERSES = {
    "temperature": (10.0, 40.0),     # °C
    "humidity": (0.0, 100.0),        # %
    "co2": (400.0, 2000.0),          # ppm
    "fan": (0.0, 100.0),             # % швидкості вентилятора
}

# ---------------------------------------------------------------------------
# Лінгвістичні терми та параметри функцій належності.
# Трикутна функція задається (a, b, c), трапецієподібна — (a, b, c, d).
# Для зручності всі функції зберігаються як трапеції; трикутник — це
# трапеція з b == c.
# ---------------------------------------------------------------------------
MEMBERSHIPS = {
    "temperature": {
        "Low":  (10, 10, 17, 21),     # низька (холодно)
        "Norm": (18, 23, 23, 28),     # комфортна
        "High": (24, 29, 40, 40),     # висока (спекотно)
    },
    "humidity": {
        "Dry":  (0, 0, 25, 45),       # суха
        "Norm": (30, 50, 50, 70),     # нормальна
        "Wet":  (55, 75, 100, 100),   # волога
    },
    "co2": {
        "Low":  (400, 400, 600, 900),     # низька концентрація
        "Med":  (700, 1000, 1000, 1300),  # середня
        "High": (1100, 1500, 2000, 2000), # висока
    },
    "fan": {
        "VL": (0, 0, 5, 20),          # дуже низька швидкість
        "L":  (10, 25, 25, 40),       # низька
        "M":  (30, 50, 50, 70),       # середня
        "H":  (60, 75, 75, 90),       # висока
        "VH": (80, 95, 100, 100),     # дуже висока
    },
}

# Українські підписи термів (для інтерфейсу та звіту)
TERM_LABELS = {
    "Low": "низька", "Norm": "нормальна", "High": "висока",
    "Dry": "суха", "Wet": "волога", "Med": "середня",
    "VL": "дуже низька", "L": "низька", "M": "середня",
    "H": "висока", "VH": "дуже висока",
}

# ---------------------------------------------------------------------------
# База правил: 3 x 3 x 3 = 27 правил (повне покриття всіх комбінацій).
# Ключ — (терм температури, терм вологості), значення — вихідні терми
# для CO2 = Low, Med, High відповідно.
# База монотонна: чим вища температура, вологість чи CO2, тим швидше
# обертається вентилятор.
# ---------------------------------------------------------------------------
RULE_TABLE = {
    ("Low",  "Dry"):  ("VL", "L",  "M"),
    ("Low",  "Norm"): ("VL", "L",  "M"),
    ("Low",  "Wet"):  ("L",  "M",  "H"),
    ("Norm", "Dry"):  ("VL", "L",  "M"),
    ("Norm", "Norm"): ("VL", "L",  "H"),
    ("Norm", "Wet"):  ("L",  "M",  "H"),
    ("High", "Dry"):  ("M",  "M",  "H"),
    ("High", "Norm"): ("M",  "H",  "VH"),
    ("High", "Wet"):  ("H",  "H",  "VH"),
}
CO2_TERMS = ("Low", "Med", "High")

# Плоский список правил: (T, H, CO2, вихід)
RULES = [
    (t, h, c, out)
    for (t, h), outs in RULE_TABLE.items()
    for c, out in zip(CO2_TERMS, outs)
]


def trapmf(x, a, b, c, d):
    """Трапецієподібна функція належності (трикутна, якщо b == c).

    Коректно обробляє «плечі» (a == b або c == d), де функція дорівнює 1
    на межі універсуму.
    """
    x = np.asarray(x, dtype=float)
    if b > a:
        left = np.clip((x - a) / (b - a), 0.0, 1.0)
    else:
        left = (x >= a).astype(float)
    if d > c:
        right = np.clip((d - x) / (d - c), 0.0, 1.0)
    else:
        right = (x <= d).astype(float)
    return np.minimum(left, right)


class FanFuzzyController:
    """Нечіткий регулятор Мамдані: фазифікація → правила → агрегування →
    дефазифікація методом центра ваги."""

    def __init__(self, resolution=1001):
        lo, hi = UNIVERSES["fan"]
        self.y = np.linspace(lo, hi, resolution)    # дискретний універсум виходу
        # Попередньо обчислені функції належності вихідних термів
        self.out_mf = {
            name: trapmf(self.y, *params)
            for name, params in MEMBERSHIPS["fan"].items()
        }

    # -- Крок 1. Фазифікація ------------------------------------------------
    def fuzzify(self, var, value):
        """Повертає ступені належності значення всім термам змінної."""
        lo, hi = UNIVERSES[var]
        value = float(np.clip(value, lo, hi))        # значення поза межами обрізаємо
        return {
            term: float(trapmf(value, *params))
            for term, params in MEMBERSHIPS[var].items()
        }

    # -- Кроки 2-4. Висновок ------------------------------------------------
    def infer(self, temperature, humidity, co2, details=False):
        """Обчислює швидкість вентилятора (%).

        Якщо details=True, додатково повертає ступені належності входів,
        сили спрацювання вихідних термів і агреговану множину.
        """
        mu_t = self.fuzzify("temperature", temperature)
        mu_h = self.fuzzify("humidity", humidity)
        mu_c = self.fuzzify("co2", co2)

        # Крок 2. Оцінювання умов правил: операція І — мінімум.
        # Крок 3. Агрегування: для кожного вихідного терма беремо максимум
        # сил усіх правил з цим висновком (еквівалентно max по обрізаних
        # функціях, бо min(w, mf) монотонна за w).
        strength = {term: 0.0 for term in MEMBERSHIPS["fan"]}
        fired = []
        for t, h, c, out in RULES:
            w = min(mu_t[t], mu_h[h], mu_c[c])
            if w > 0.0:
                fired.append({"if": [t, h, c], "then": out, "weight": round(w, 4)})
            strength[out] = max(strength[out], w)

        aggregated = np.zeros_like(self.y)
        for term, w in strength.items():
            if w > 0.0:
                aggregated = np.maximum(aggregated, np.minimum(w, self.out_mf[term]))

        # Крок 4. Дефазифікація — центр ваги (centroid)
        area = aggregated.sum()
        if area <= 1e-12:           # не повинно траплятися: правила покривають усе
            speed = 0.0
        else:
            speed = float((self.y * aggregated).sum() / area)

        if not details:
            return speed
        return {
            "fan": speed,
            "memberships": {"temperature": mu_t, "humidity": mu_h, "co2": mu_c},
            "output_strength": strength,
            "fired_rules": fired,
        }

    # -- Допоміжне: дані для графіків функцій належності ---------------------
    def membership_curves(self, points=301):
        """Повертає криві належності всіх змінних для відображення в браузері."""
        curves = {}
        for var, terms in MEMBERSHIPS.items():
            lo, hi = UNIVERSES[var]
            xs = np.linspace(lo, hi, points)
            curves[var] = {
                "x": [round(float(v), 3) for v in xs],
                "terms": {
                    name: [round(float(v), 4) for v in trapmf(xs, *p)]
                    for name, p in terms.items()
                },
            }
        return curves

    @staticmethod
    def rules_table():
        """Список правил у вигляді словників (для таблиці в інтерфейсі)."""
        return [
            {"n": i + 1, "temperature": t, "humidity": h, "co2": c, "fan": out}
            for i, (t, h, c, out) in enumerate(RULES)
        ]


if __name__ == "__main__":
    # Контрольні значення для перевірки висновку
    ctrl = FanFuzzyController()
    tests = [
        (22, 50, 450, "комфортні умови"),
        (22, 50, 1000, "помірно підвищений CO2"),
        (22, 50, 1800, "високий CO2"),
        (32, 50, 500, "спека"),
        (22, 85, 500, "висока вологість"),
        (35, 80, 1800, "найгірші умови"),
        (12, 20, 420, "холодно, сухо, свіже повітря"),
    ]
    for t, h, c, note in tests:
        print(f"T={t:>4} H={h:>4} CO2={c:>5} -> U={ctrl.infer(t, h, c):6.2f} %  ({note})")
