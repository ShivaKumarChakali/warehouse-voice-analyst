// Warehouse Voice Analyst front end.
// Plain vanilla JavaScript. Talks to POST /api/ask, draws the returned
// chart as inline SVG, and can speak the answer with the browser's
// built in speech synthesis (a simulation of the Alexa+ voice reply).

const chatLog = document.getElementById("chatLog");
const form = document.getElementById("askForm");
const input = document.getElementById("questionInput");
const chartPanel = document.getElementById("chartPanel");
const chartBox = document.getElementById("chartBox");
const sqlPanel = document.getElementById("sqlPanel");
const sqlBox = document.getElementById("sqlBox");
const explainBox = document.getElementById("explainBox");
const voiceToggle = document.getElementById("voiceToggle");

function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = "msg " + who;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function shortLabel(label) {
  return label.length > 22 ? label.slice(0, 21) + "..." : label;
}

function drawChart(chart) {
  chartBox.innerHTML = "";
  if (!chart || chart.type === "none" || !chart.labels.length) {
    chartPanel.hidden = true;
    return;
  }
  const width = 760, height = 300, padL = 70, padB = 64, padT = 16, padR = 12;
  const plotW = width - padL - padR, plotH = height - padT - padB;
  const max = Math.max(...chart.values) * 1.1 || 1;
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  svg.setAttribute("width", "100%");

  function el(name, attrs) {
    const e = document.createElementNS(svgNS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // Axis lines
  svg.appendChild(el("line", {x1: padL, y1: padT, x2: padL, y2: padT + plotH, stroke: "#8895a1"}));
  svg.appendChild(el("line", {x1: padL, y1: padT + plotH, x2: padL + plotW, y2: padT + plotH, stroke: "#8895a1"}));
  // Y axis max label
  const maxText = el("text", {x: padL - 6, y: padT + 12, "text-anchor": "end", "font-size": "11", fill: "#44515c"});
  maxText.textContent = Number(max).toLocaleString(undefined, {maximumFractionDigits: 1});
  svg.appendChild(maxText);

  if (chart.type === "line") {
    const stepX = chart.values.length > 1 ? plotW / (chart.values.length - 1) : plotW;
    let points = "";
    chart.values.forEach(function (v, i) {
      const x = padL + i * stepX, y = padT + plotH - (v / max) * plotH;
      points += x + "," + y + " ";
      svg.appendChild(el("circle", {cx: x, cy: y, r: 3.5, fill: "#146eb4"}));
      const t = el("text", {x: x, y: padT + plotH + 16, "text-anchor": "middle", "font-size": "11", fill: "#44515c"});
      t.textContent = shortLabel(chart.labels[i]);
      svg.appendChild(t);
    });
    svg.appendChild(el("polyline", {points: points.trim(), fill: "none", stroke: "#146eb4", "stroke-width": 2.5}));
  } else {
    const slot = plotW / chart.values.length;
    const barW = Math.min(90, slot * 0.62);
    chart.values.forEach(function (v, i) {
      const h = (v / max) * plotH;
      const x = padL + i * slot + (slot - barW) / 2;
      const y = padT + plotH - h;
      svg.appendChild(el("rect", {x: x, y: y, width: barW, height: h, fill: "#146eb4", rx: 3}));
      const val = el("text", {x: x + barW / 2, y: y - 5, "text-anchor": "middle", "font-size": "11", fill: "#1c2733"});
      val.textContent = Number(v).toLocaleString(undefined, {maximumFractionDigits: 2});
      svg.appendChild(val);
      const lab = el("text", {x: x + barW / 2, y: padT + plotH + 15, "text-anchor": "middle", "font-size": "10.5", fill: "#44515c"});
      lab.textContent = shortLabel(chart.labels[i]);
      svg.appendChild(lab);
    });
  }
  chartBox.appendChild(svg);
  chartPanel.hidden = false;
}

function speak(text) {
  if (!voiceToggle.checked || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = 1.0;
  window.speechSynthesis.speak(utter);
}

async function ask(question) {
  addMessage(question, "user");
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question: question})
    });
    const data = await res.json();
    if (!res.ok) {
      addMessage(data.error || "Something went wrong.", "bot");
      return;
    }
    addMessage(data.answer_text, "bot");
    drawChart(data.chart);
    if (data.sql_like) {
      sqlBox.textContent = data.sql_like;
      explainBox.textContent = data.explanation || "";
      sqlPanel.hidden = false;
    }
    speak(data.answer_text);
  } catch (err) {
    addMessage("I could not reach the server. Is server.py still running?", "bot");
  }
}

form.addEventListener("submit", function (e) {
  e.preventDefault();
  const q = input.value.trim();
  if (!q) return;
  input.value = "";
  ask(q);
});

document.querySelectorAll(".chip").forEach(function (chip) {
  chip.addEventListener("click", function () { ask(chip.getAttribute("data-q")); });
});

addMessage("Hello. I am your warehouse voice analyst, running on sample data. Ask me about top products, sales by region, the monthly trend, low stock, or return rates.", "bot");
