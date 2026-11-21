// Клієнтська частина: запити до Flask API та побудова графіків Chart.js.

const PARAM_IDS = ["temperature0", "humidity0", "co2_0", "duration",
                   "disturbance_time", "disturbance_gain", "tau_fan"];
const COLORS = ["#1f6feb", "#d1242f", "#2da44e", "#bf8700", "#8250df"];
const charts = {};          // створені графіки (щоб оновлювати, а не створювати заново)
let labels = {};            // українські підписи термів

// ---------- допоміжні функції ----------
function showMessage(el, text) {
    el.textContent = text;          // textContent — захист від HTML-ін'єкцій
    el.hidden = !text;
}

function cell(row, text, className) {
    const td = document.createElement("td");
    td.textContent = text;
    if (className) td.className = className;
    row.appendChild(td);
    return td;
}

function fillTable(selector, rows) {
    const tbody = document.querySelector(selector + " tbody");
    tbody.replaceChildren(...rows);
}

// ---------- графіки перехідного процесу ----------
function lineDataset(label, xs, ys, color, options = {}) {
    return Object.assign({
        label, data: xs.map((x, i) => ({x, y: ys[i]})),
        borderColor: color, backgroundColor: color,
        borderWidth: 2, pointRadius: 0, tension: 0.15,
    }, options);
}

function drawChart(id, title, yTitle, datasets, yRange) {
    const options = {
        responsive: true, maintainAspectRatio: false, animation: false,
        parsing: false,
        interaction: {mode: "nearest", intersect: false},
        plugins: {title: {display: true, text: title}, legend: {labels: {boxWidth: 14}}},
        scales: {
            x: {type: "linear", title: {display: true, text: "Час, хв"}},
            y: {title: {display: true, text: yTitle}, ...(yRange || {})},
        },
    };
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), {type: "line", data: {datasets}, options});
}

function zoneLines(xs, lo, hi) {
    const dashed = {borderDash: [6, 4], borderColor: "#8a94a3", borderWidth: 1};
    const lines = [];
    if (lo !== null) lines.push(lineDataset("Межа зони (мін.)", [xs[0], xs.at(-1)], [lo, lo], "#8a94a3", dashed));
    if (hi !== null) lines.push(lineDataset("Межа зони (макс.)", [xs[0], xs.at(-1)], [hi, hi], "#8a94a3", dashed));
    return lines;
}

function renderResult(result) {
    const t = result.time;
    drawChart("chart-temperature", "Температура", "°C",
        [lineDataset("Температура", t, result.temperature, COLORS[1]),
         ...zoneLines(t, result.comfort.temperature[0], result.comfort.temperature[1])]);
    drawChart("chart-humidity", "Відносна вологість", "%",
        [lineDataset("Вологість", t, result.humidity, COLORS[0]),
         ...zoneLines(t, result.comfort.humidity[0], result.comfort.humidity[1])]);
    drawChart("chart-co2", "Концентрація CO₂", "ppm",
        [lineDataset("CO₂", t, result.co2, COLORS[2]),
         ...zoneLines(t, null, result.comfort.co2[1])]);
    drawChart("chart-fan", "Керувальний сигнал і швидкість вентилятора", "%",
        [lineDataset("Команда регулятора", t, result.fan_command, COLORS[3], {borderDash: [4, 3]}),
         lineDataset("Фактична швидкість", t, result.fan_actual, COLORS[4])],
        {min: 0, max: 100});
    renderMetrics(result.metrics);
}

function renderMetrics(m) {
    const names = {temperature: "Температура, °C", humidity: "Вологість, %", co2: "CO₂, ppm"};
    const rows = Object.keys(names).map(key => {
        const tr = document.createElement("tr");
        cell(tr, names[key]);
        cell(tr, m[key].max);
        cell(tr, m[key].min);
        cell(tr, m[key].steady);
        if (m[key].in_zone) cell(tr, m[key].settle_time);
        else cell(tr, "не входить у зону", "not-reached");
        return tr;
    });
    fillTable("#metrics-table", rows);

    const extra = document.getElementById("metrics-extra");
    const items = [
        "Час входу всіх величин у зону: " +
            (m.all_in_zone ? m.settle_time_all + " хв" : "не входить у зону за час експерименту"),
        `Середня / максимальна швидкість вентилятора: ${m.fan_mean} % / ${m.fan_max} %`,
        `Енергетичний індекс (∫U dt): ${m.fan_energy} %·хв`,
        `Сумарна варіація керування: ${m.fan_variation} %`,
        `Інтегральний дискомфорт (IAE): ${m.discomfort_iae}`,
    ];
    extra.replaceChildren(...items.map(text => {
        const li = document.createElement("li");
        li.textContent = text;
        return li;
    }));
}

// ---------- запуск моделювання ----------
async function runSimulation(event) {
    event.preventDefault();
    const message = document.getElementById("message");
    const button = document.getElementById("run-btn");
    showMessage(message, "");
    const payload = {};
    for (const id of PARAM_IDS) payload[id] = Number(document.getElementById(id).value);

    button.disabled = true;
    try {
        const response = await fetch("/api/simulate", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) {
            showMessage(message, result.error || "Помилка моделювання");
            return;
        }
        renderResult(result);
        document.getElementById("csv-link").href = `/api/export/${result.run_id}.csv`;
        document.getElementById("xlsx-link").href = `/api/export/${result.run_id}.xlsx`;
        document.getElementById("export-links").hidden = false;
        loadHistory();
    } catch (err) {
        showMessage(message, "Не вдалося зв'язатися із сервером");
    } finally {
        button.disabled = false;
    }
}

// ---------- функції належності та правила ----------
const MF_TITLES = {
    temperature: ["Температура", "°C"], humidity: ["Вологість", "%"],
    co2: ["CO₂", "ppm"], fan: ["Швидкість вентилятора (вихід)", "%"],
};

async function loadMembership() {
    const response = await fetch("/api/membership");
    const data = await response.json();
    labels = data.labels;
    for (const [variable, curve] of Object.entries(data.curves)) {
        const [title, unit] = MF_TITLES[variable];
        const datasets = Object.entries(curve.terms).map(([term, ys], i) =>
            lineDataset(`${term} — ${labels[term]}`, curve.x, ys, COLORS[i % COLORS.length]));
        drawChart(`mf-${variable}`, title, "μ", datasets, {min: 0, max: 1.05});
        charts[`mf-${variable}`].options.scales.x.title.text = unit;
        charts[`mf-${variable}`].update();
    }
    fillTable("#rules-table", data.rules.map(r => {
        const tr = document.createElement("tr");
        cell(tr, r.n);
        cell(tr, `${r.temperature} (${labels[r.temperature]})`);
        cell(tr, `${r.humidity} (${labels[r.humidity]})`);
        cell(tr, `${r.co2} (${labels[r.co2]})`);
        cell(tr, `${r.fan} (${labels[r.fan]})`);
        return tr;
    }));
}

// ---------- контрольні значення ----------
async function runInfer(event) {
    event.preventDefault();
    const message = document.getElementById("infer-message");
    const out = document.getElementById("infer-result");
    showMessage(message, "");
    const payload = {
        temperature: Number(document.getElementById("in-t").value),
        humidity: Number(document.getElementById("in-h").value),
        co2: Number(document.getElementById("in-c").value),
    };
    const response = await fetch("/api/infer", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
        out.textContent = "";
        showMessage(message, result.error || "Помилка висновку");
        return;
    }
    out.textContent = `Керувальний сигнал: ${result.fan} % (активних правил: ${result.fired_rules.length})`;
}

// ---------- історія ----------
async function loadHistory() {
    const response = await fetch("/api/history");
    const runs = await response.json();
    fillTable("#history-table", runs.map(run => {
        const tr = document.createElement("tr");
        cell(tr, run.id);
        cell(tr, run.created_at);
        cell(tr, run.params.temperature0);
        cell(tr, run.params.humidity0);
        cell(tr, run.params.co2_0);
        cell(tr, `×${run.params.disturbance_gain} з ${run.params.disturbance_time} хв`);
        cell(tr, run.metrics.all_in_zone ? run.metrics.settle_time_all : "не входить");
        const td = document.createElement("td");
        for (const ext of ["csv", "xlsx"]) {
            const a = document.createElement("a");
            a.href = `/api/export/${run.id}.${ext}`;
            a.textContent = ext.toUpperCase() + " ";
            td.appendChild(a);
        }
        tr.appendChild(td);
        return tr;
    }));
}

document.getElementById("sim-form").addEventListener("submit", runSimulation);
document.getElementById("infer-form").addEventListener("submit", runInfer);
loadMembership();
loadHistory();
// Початковий запуск із параметрами за замовчуванням
document.getElementById("sim-form").requestSubmit();
