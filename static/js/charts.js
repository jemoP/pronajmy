// Grafy přehledů (Chart.js). Data čte z <script type="application/json"> (json_script),
// barvy z CSS tokenů v assets/css/input.css (ověřená paleta pro světlý povrch).
(function () {
  "use strict";
  const number = new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 0 });
  const compact = new Intl.NumberFormat("cs-CZ", { notation: "compact", maximumFractionDigits: 1 });

  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  }

  function colorFor(series) {
    if (series.color === "diverging") {
      return series.values.map((v) => token(v < 0 ? "diverge-neg" : "diverge-pos"));
    }
    return token(series.color === "ink" ? "chart-ink" : series.color);
  }

  function dataset(spec, series) {
    const color = colorFor(series);
    if (spec.type === "line") {
      return {
        type: "line", label: series.name, data: series.values,
        borderColor: color, backgroundColor: color,
        borderWidth: series.color === "ink" ? 3 : 2, borderCapStyle: "round", borderJoinStyle: "round",
        pointRadius: 0, pointHoverRadius: 5, pointHoverBorderWidth: 2,
        pointHoverBorderColor: token("chart-surface"), pointStyle: "line", order: series.color === "ink" ? 0 : 1,
      };
    }
    return {
      type: "bar", label: series.name, data: series.values, backgroundColor: color,
      borderRadius: 4, borderSkipped: "start", maxBarThickness: 24,
      categoryPercentage: 0.8, barPercentage: 0.9, pointStyle: "rect",
    };
  }

  function build(canvas) {
    const source = document.getElementById(canvas.dataset.chart);
    if (!source || typeof Chart === "undefined") return;
    const spec = JSON.parse(source.textContent);
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    const horizontal = spec.type === "hbar";
    const datasets = spec.series.map((s) => dataset(spec, s));
    const valueAxis = {
      grid: { color: token("chart-grid"), drawTicks: false },
      border: { display: false },
      ticks: { color: token("chart-muted"), padding: 6, callback: (v) => compact.format(v) },
    };
    const categoryAxis = {
      grid: { display: false },
      border: { color: token("chart-axis") },
      ticks: { color: token("chart-muted"), autoSkip: true, maxRotation: 0, maxTicksLimit: horizontal ? undefined : 14 },
    };
    const links = spec.links || null;
    new Chart(canvas, {
      data: { labels: spec.labels, datasets },
      options: {
        indexAxis: horizontal ? "y" : "x",
        maintainAspectRatio: false,
        animation: false,
        interaction: horizontal ? { mode: "nearest", axis: "y", intersect: false } : { mode: "index", intersect: false },
        scales: horizontal ? { x: valueAxis, y: categoryAxis } : { x: categoryAxis, y: valueAxis },
        plugins: {
          legend: {
            display: datasets.length > 1, position: "top", align: "start",
            labels: { color: token("chart-text"), usePointStyle: true, boxWidth: 14, padding: 14 },
          },
          tooltip: {
            backgroundColor: token("chart-surface"), borderColor: token("chart-axis"), borderWidth: 1,
            titleColor: token("chart-text"), bodyColor: token("chart-ink"), usePointStyle: true,
            callbacks: {
              // Hodnota první, název řady za ní.
              label: (ctx) => ` ${number.format(ctx.parsed[horizontal ? "x" : "y"])} Kč  ${ctx.dataset.label}`,
            },
          },
        },
        onClick: links ? (_event, elements) => {
          const url = elements.length ? links[elements[0].index] : null;
          if (url) window.location.href = url;
        } : undefined,
        onHover: links ? (event, elements) => {
          const clickable = elements.length && links[elements[0].index];
          event.native.target.style.cursor = clickable ? "pointer" : "default";
        } : undefined,
      },
    });
  }

  function init(root) {
    root.querySelectorAll("canvas[data-chart]").forEach(build);
  }

  document.addEventListener("DOMContentLoaded", () => init(document));
  document.addEventListener("htmx:load", (event) => init(event.detail.elt));
})();
