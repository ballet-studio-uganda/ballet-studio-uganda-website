/* ==========================================================================
   Ballet Dance Studio UG — dashboard behaviour and charts
   Chart.js is loaded from the CDN by dashboard/base.html.
   ========================================================================== */
(function () {
  'use strict';

  const $  = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

  const BRAND = {
    pink: '#EE2A7B',
    pinkSoft: '#f4679c',
    plum: '#701344',
    plumLight: '#8a1a55',
    gold: '#c9a84c',
    ink: '#1a0a12',
    success: '#1f8a5f',
    danger: '#b3261e',
    warning: '#c9821a',
    line: '#ece2e7',
    text: '#6b5a62',
  };

  const PALETTE = [
    BRAND.pink, BRAND.plum, BRAND.gold, BRAND.plumLight,
    BRAND.pinkSoft, '#4d0a2e', '#e8d5a3', '#9c8b94',
  ];

  const ugx = (n) => 'UGX ' + Math.round(Number(n) || 0).toLocaleString();

  /* --------------------------------------------------------- sidebar shell */
  function initShell() {
    const sidebar = $('.dash-sidebar');
    const toggle = $('.sidebar-toggle');
    const scrim = $('.dash-scrim');
    if (!sidebar || !toggle) return;

    const setOpen = (open) => {
      sidebar.classList.toggle('is-open', open);
      if (scrim) scrim.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', String(open));
      document.body.style.overflow = open ? 'hidden' : '';
    };

    toggle.addEventListener('click', () => setOpen(!sidebar.classList.contains('is-open')));
    if (scrim) scrim.addEventListener('click', () => setOpen(false));
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') setOpen(false);
    });
  }

  /* ------------------------------------------------------------- dropdowns */
  function initDropdowns() {
    $$('[data-dropdown]').forEach((trigger) => {
      const panel = $('#' + trigger.dataset.dropdown);
      if (!panel) return;
      panel.hidden = true;

      trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        const show = panel.hidden;
        $$('.dropdown-panel').forEach((p) => { p.hidden = true; });
        panel.hidden = !show;
        trigger.setAttribute('aria-expanded', String(show));
      });

      panel.addEventListener('click', (e) => e.stopPropagation());
    });

    document.addEventListener('click', () => {
      $$('.dropdown-panel').forEach((p) => { p.hidden = true; });
    });
  }

  /* ----------------------------------------------------------- the register */
  function initRegister() {
    const form = $('#register-form');
    if (!form) return;

    const tally = () => {
      const counts = { present: 0, late: 0, excused: 0, absent: 0 };
      $$('input[type=radio]:checked', form).forEach((input) => {
        if (counts[input.value] !== undefined) counts[input.value] += 1;
      });
      Object.entries(counts).forEach(([key, value]) => {
        const node = $(`[data-tally="${key}"]`);
        if (node) node.textContent = String(value);
      });
      const unmarked = $('[data-tally="unmarked"]');
      if (unmarked) {
        const rows = $$('.register-row', form).length;
        const marked = Object.values(counts).reduce((a, b) => a + b, 0);
        unmarked.textContent = String(rows - marked);
      }
    };

    // "Mark everyone present", then correct the exceptions — how a register
    // actually gets taken in a studio.
    $$('[data-mark-all]').forEach((button) => {
      button.addEventListener('click', () => {
        const status = button.dataset.markAll;
        $$(`input[type=radio][value="${status}"]`, form).forEach((input) => {
          input.checked = true;
        });
        tally();
      });
    });

    form.addEventListener('change', tally);
    tally();

    let dirty = false;
    form.addEventListener('change', () => { dirty = true; });
    form.addEventListener('submit', () => { dirty = false; });
    window.addEventListener('beforeunload', (e) => {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = '';
    });
  }

  /* ------------------------------------------------- payment method hinting */
  function initPaymentForm() {
    const method = $('#id_method');
    const reference = $('#id_transaction_id');
    if (!method || !reference) return;

    const needsRef = (method.dataset.referenced || '').split(',').filter(Boolean);
    const field = reference.closest('.field') || reference.parentElement;
    let hint = $('.ref-hint', field);
    if (!hint) {
      hint = document.createElement('small');
      hint.className = 'helptext ref-hint';
      field.appendChild(hint);
    }

    const sync = () => {
      const required = needsRef.includes(method.value);
      reference.required = required;
      field.classList.toggle('is-required', required);
      hint.textContent = required
        ? 'Required — copy the reference from the SMS, slip or statement.'
        : 'Optional for this payment method.';
      hint.style.color = required ? 'var(--warning)' : 'var(--text-faint)';
    };

    method.addEventListener('change', sync);
    sync();
  }

  /* ------------------------------------------------------------ chart setup */
  function chartDefaults() {
    if (!window.Chart) return false;
    Chart.defaults.font.family =
      "'Montserrat', 'Segoe UI', system-ui, sans-serif";
    Chart.defaults.font.size = 12;
    Chart.defaults.color = BRAND.text;
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.plugins.tooltip.backgroundColor = BRAND.ink;
    Chart.defaults.plugins.tooltip.padding = 12;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.plugins.tooltip.titleFont = { weight: '700', size: 12 };
    Chart.defaults.plugins.tooltip.displayColors = true;
    Chart.defaults.plugins.tooltip.boxPadding = 4;
    Chart.defaults.maintainAspectRatio = false;
    return true;
  }

  const moneyAxis = {
    beginAtZero: true,
    border: { display: false },
    grid: { color: BRAND.line, drawTicks: false },
    ticks: {
      padding: 10,
      callback: (value) => {
        const n = Number(value);
        if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
        if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(0) + 'K';
        return n;
      },
    },
  };

  const categoryAxis = {
    border: { display: false },
    grid: { display: false },
    ticks: { padding: 8, maxRotation: 0, autoSkipPadding: 16 },
  };

  function readData(id) {
    const node = document.getElementById(id);
    if (!node) return null;
    try { return JSON.parse(node.textContent); } catch (_) { return null; }
  }

  const registry = {};

  function destroy(key) {
    if (registry[key]) { registry[key].destroy(); delete registry[key]; }
  }

  /* Income vs expenses over the period */
  function incomeExpenseChart(canvas, series) {
    if (!canvas || !series || !series.labels || !series.labels.length) {
      showEmpty(canvas, 'No transactions in this period yet.');
      return;
    }
    const ctx = canvas.getContext('2d');

    const fill = (colour, alpha) => {
      const grad = ctx.createLinearGradient(0, 0, 0, canvas.offsetHeight || 300);
      grad.addColorStop(0, colour + alpha);
      grad.addColorStop(1, colour + '00');
      return grad;
    };

    destroy(canvas.id);
    registry[canvas.id] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: series.labels,
        datasets: [
          {
            label: 'Income',
            data: series.income,
            borderColor: BRAND.pink,
            backgroundColor: fill(BRAND.pink, '38'),
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: series.labels.length > 20 ? 0 : 3,
            pointHoverRadius: 6,
            pointBackgroundColor: BRAND.pink,
            pointBorderColor: '#fff',
            pointBorderWidth: 2,
          },
          {
            label: 'Expenses',
            data: series.expenses,
            borderColor: BRAND.plum,
            backgroundColor: fill(BRAND.plum, '26'),
            fill: true,
            tension: 0.35,
            borderWidth: 2.5,
            pointRadius: series.labels.length > 20 ? 0 : 3,
            pointHoverRadius: 6,
            pointBackgroundColor: BRAND.plum,
            pointBorderColor: '#fff',
            pointBorderWidth: 2,
          },
        ],
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            align: 'end',
            labels: { usePointStyle: true, pointStyle: 'circle', padding: 18, boxWidth: 8 },
          },
          tooltip: {
            callbacks: {
              label: (item) => `${item.dataset.label}: ${ugx(item.parsed.y)}`,
              footer: (items) => {
                const income = items.find((i) => i.dataset.label === 'Income');
                const spend = items.find((i) => i.dataset.label === 'Expenses');
                if (!income || !spend) return '';
                return 'Net: ' + ugx(income.parsed.y - spend.parsed.y);
              },
            },
          },
        },
        scales: { y: moneyAxis, x: categoryAxis },
      },
    });
  }

  /* Doughnut for any category breakdown */
  function breakdownChart(canvas, rows, label) {
    if (!canvas) return;
    if (!rows || !rows.length) {
      showEmpty(canvas, 'Nothing recorded in this period.');
      return;
    }
    destroy(canvas.id);
    registry[canvas.id] = new Chart(canvas.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: rows.map((r) => r.label),
        datasets: [{
          data: rows.map((r) => r.amount),
          backgroundColor: rows.map((r, i) => r.colour || PALETTE[i % PALETTE.length]),
          borderColor: '#fff',
          borderWidth: 3,
          hoverOffset: 10,
        }],
      },
      options: {
        cutout: '62%',
        plugins: {
          tooltip: {
            callbacks: {
              label: (item) => {
                const total = item.dataset.data.reduce((a, b) => a + b, 0);
                const pct = total ? ((item.parsed / total) * 100).toFixed(1) : 0;
                return `${item.label}: ${ugx(item.parsed)} (${pct}%)`;
              },
            },
          },
        },
      },
    });
  }

  /* Horizontal bars — payment methods, programme revenue, ageing */
  function barChart(canvas, rows, opts = {}) {
    if (!canvas) return;
    if (!rows || !rows.length) {
      showEmpty(canvas, 'No data for this period.');
      return;
    }
    destroy(canvas.id);
    registry[canvas.id] = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: rows.map((r) => r.label),
        datasets: [{
          data: rows.map((r) => r.amount),
          backgroundColor: rows.map((r, i) => r.colour || PALETTE[i % PALETTE.length]),
          borderRadius: 6,
          borderSkipped: false,
          barThickness: opts.thickness || 22,
        }],
      },
      options: {
        indexAxis: opts.horizontal === false ? 'x' : 'y',
        plugins: {
          tooltip: { callbacks: { label: (item) => ugx(item.parsed[opts.horizontal === false ? 'y' : 'x']) } },
        },
        scales: opts.horizontal === false
          ? { y: moneyAxis, x: categoryAxis }
          : { x: moneyAxis, y: categoryAxis },
      },
    });
  }

  /* Progress rubric radar */
  function radarChart(canvas, rows) {
    if (!canvas) return;
    if (!rows || !rows.length) {
      showEmpty(canvas, 'No scored report yet.');
      return;
    }
    destroy(canvas.id);
    registry[canvas.id] = new Chart(canvas.getContext('2d'), {
      type: 'radar',
      data: {
        labels: rows.map((r) => r.category),
        datasets: [{
          label: 'Score',
          data: rows.map((r) => r.percent),
          backgroundColor: 'rgba(238, 42, 123, .18)',
          borderColor: BRAND.pink,
          borderWidth: 2.5,
          pointBackgroundColor: BRAND.pink,
          pointBorderColor: '#fff',
          pointBorderWidth: 2,
          pointRadius: 5,
        }],
      },
      options: {
        scales: {
          r: {
            beginAtZero: true,
            max: 100,
            angleLines: { color: BRAND.line },
            grid: { color: BRAND.line },
            pointLabels: { font: { size: 11, weight: '600' } },
            ticks: { stepSize: 25, backdropColor: 'transparent', color: '#9c8b94' },
          },
        },
        plugins: { tooltip: { callbacks: { label: (i) => `${i.parsed.r}%` } } },
      },
    });
  }

  /* Multi-line progress trend over assessment periods */
  function trendChart(canvas, trend) {
    if (!canvas) return;
    if (!trend || !trend.labels || trend.labels.length < 1) {
      showEmpty(canvas, 'Progress charts appear once reports are published.');
      return;
    }
    const datasets = [{
      label: 'Overall',
      data: trend.overall,
      borderColor: BRAND.pink,
      backgroundColor: 'rgba(238,42,123,.12)',
      borderWidth: 3,
      tension: 0.35,
      fill: true,
      pointRadius: 5,
      pointBackgroundColor: BRAND.pink,
      pointBorderColor: '#fff',
      pointBorderWidth: 2,
    }];

    (trend.categories || []).forEach((cat, i) => {
      datasets.push({
        label: cat.name,
        data: cat.values,
        borderColor: cat.colour || PALETTE[(i + 1) % PALETTE.length],
        borderWidth: 1.75,
        borderDash: [5, 4],
        tension: 0.35,
        fill: false,
        pointRadius: 3,
      });
    });

    destroy(canvas.id);
    registry[canvas.id] = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels: trend.labels, datasets },
      options: {
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: true, position: 'bottom',
            labels: { usePointStyle: true, pointStyle: 'circle', padding: 14, boxWidth: 8 },
          },
          tooltip: { callbacks: { label: (i) => `${i.dataset.label}: ${i.parsed.y ?? '—'}%` } },
        },
        scales: {
          y: { beginAtZero: true, max: 100, border: { display: false },
               grid: { color: BRAND.line }, ticks: { callback: (v) => v + '%' } },
          x: categoryAxis,
        },
      },
    });
  }

  /* Attendance percentage over time */
  function attendanceChart(canvas, data) {
    if (!canvas) return;
    if (!data || !data.labels || !data.labels.length) {
      showEmpty(canvas, 'Attendance appears once registers are taken.');
      return;
    }
    destroy(canvas.id);
    registry[canvas.id] = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: data.labels,
        datasets: [{
          data: data.rates,
          backgroundColor: data.rates.map((r) =>
            r === null ? BRAND.line : r >= 85 ? BRAND.success : r >= 70 ? BRAND.warning : BRAND.danger),
          borderRadius: 6,
          borderSkipped: false,
        }],
      },
      options: {
        plugins: { tooltip: { callbacks: { label: (i) => (i.parsed.y ?? '—') + '% attended' } } },
        scales: {
          y: { beginAtZero: true, max: 100, border: { display: false },
               grid: { color: BRAND.line }, ticks: { callback: (v) => v + '%' } },
          x: categoryAxis,
        },
      },
    });
  }

  function showEmpty(canvas, text) {
    if (!canvas) return;
    const box = canvas.closest('.chart-box') || canvas.parentElement;
    if (box) {
      box.innerHTML =
        `<div class="empty"><i class="fas fa-chart-simple"></i><p>${text}</p></div>`;
    }
  }

  /* --------------------------------------------------------- wire them up */
  function initCharts() {
    if (!chartDefaults()) {
      // Chart.js unreachable (offline, blocked CDN). Say so rather than
      // leaving the reader staring at empty white boxes.
      $$('.chart-box').forEach((box) => {
        box.innerHTML =
          '<div class="empty"><i class="fas fa-chart-simple"></i>' +
          '<p>Charts could not load. The figures beside them are still accurate.</p></div>';
      });
      return;
    }

    incomeExpenseChart($('#chart-income-expense'), readData('data-series'));
    breakdownChart($('#chart-expense-breakdown'), readData('data-expenses'));
    breakdownChart($('#chart-income-breakdown'), readData('data-income'));
    barChart($('#chart-methods'), readData('data-methods'));
    barChart($('#chart-programmes'), readData('data-programmes'));
    barChart($('#chart-ageing'), readData('data-ageing'), { horizontal: false });
    radarChart($('#chart-radar'), readData('data-radar'));
    trendChart($('#chart-trend'), readData('data-trend'));
    attendanceChart($('#chart-attendance'), readData('data-attendance'));
  }

  /* Live period switching on the reports page, without a full reload. */
  function initPeriodSwitch() {
    const bar = $('[data-period-switch]');
    if (!bar) return;
    const endpoint = bar.dataset.periodSwitch;

    bar.addEventListener('click', async (e) => {
      const button = e.target.closest('[data-period]');
      if (!button) return;
      e.preventDefault();

      $$('[data-period]', bar).forEach((b) => b.classList.remove('active'));
      button.classList.add('active');
      bar.setAttribute('aria-busy', 'true');

      try {
        const res = await fetch(`${endpoint}?period=${encodeURIComponent(button.dataset.period)}`, {
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (!res.ok) throw new Error(res.statusText);
        const data = await res.json();

        const label = $('[data-period-label]');
        if (label) label.textContent = data.period_label;

        Object.entries({
          total_income: 'income', total_expenses: 'expenses',
          net: 'net', outstanding: 'outstanding',
        }).forEach(([key, slot]) => {
          const node = $(`[data-kpi="${slot}"]`);
          if (node && data.summary[key] !== undefined) node.textContent = ugx(data.summary[key]);
        });

        incomeExpenseChart($('#chart-income-expense'), data.series);
        breakdownChart($('#chart-expense-breakdown'), data.expenses);
        breakdownChart($('#chart-income-breakdown'), data.income);
        barChart($('#chart-methods'), data.methods);
        barChart($('#chart-programmes'), data.programmes);
      } catch (err) {
        console.error('Could not refresh the report', err);
        window.location.search = '?period=' + button.dataset.period;
      } finally {
        bar.removeAttribute('aria-busy');
      }
    });
  }

  /* ---------------------------------------------------------- confirmations */
  function initConfirms() {
    document.addEventListener('submit', (e) => {
      const form = e.target;
      const message = form.dataset.confirm;
      if (message && !window.confirm(message)) e.preventDefault();
    });
  }

  /* ------------------------------------------------------------------ init */
  function init() {
    initShell();
    initDropdowns();
    initRegister();
    initPaymentForm();
    initCharts();
    initPeriodSwitch();
    initConfirms();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.BDSU = { incomeExpenseChart, breakdownChart, barChart, radarChart,
                  trendChart, attendanceChart, BRAND, PALETTE, ugx };
})();
