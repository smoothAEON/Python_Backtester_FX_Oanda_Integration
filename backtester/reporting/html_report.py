"""HTML reporting for completed backtest runs."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape

from backtester.core.result import BacktestResult

from .json_report import build_backtest_json_payload

_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ metadata.strategy_name }} Report</title>
  <style>
    :root {
      --bg: #f4f1e8;
      --paper: #fffaf2;
      --ink: #1f2933;
      --muted: #52606d;
      --line: #d9d3c5;
      --accent: #8c3d2e;
      --accent-soft: #e9d5c3;
      --good: #2d6a4f;
      --bad: #b00020;
      --shadow: 0 18px 40px rgba(31, 41, 51, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(140, 61, 46, 0.12), transparent 30%),
        linear-gradient(180deg, #efe7d8 0%, var(--bg) 38%, #f8f5ef 100%);
    }
    .page {
      max-width: 1200px;
      margin: 0 auto;
      padding: 28px 18px 40px;
    }
    .hero, section {
      background: rgba(255, 250, 242, 0.92);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }
    .hero {
      padding: 28px;
      margin-bottom: 20px;
    }
    .hero h1 {
      margin: 0 0 8px;
      font-size: 2rem;
      line-height: 1.1;
    }
    .hero p {
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
    }
    .pill-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }
    .pill {
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid rgba(140, 61, 46, 0.18);
      font-size: 0.9rem;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }
    section {
      padding: 22px;
      margin-bottom: 20px;
    }
    h2 {
      margin: 0 0 14px;
      font-size: 1.2rem;
      color: var(--accent);
    }
    .kv {
      width: 100%;
      border-collapse: collapse;
    }
    .kv td {
      padding: 8px 0;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }
    .kv td:first-child {
      width: 42%;
      color: var(--muted);
      padding-right: 12px;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
    }
    .metric-card {
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fffdf9;
    }
    .metric-card .name {
      display: block;
      color: var(--muted);
      font-size: 0.88rem;
      margin-bottom: 6px;
    }
    .metric-card .value {
      font-size: 1.15rem;
      font-weight: 600;
    }
    ul {
      margin: 0;
      padding-left: 18px;
    }
    li { margin-bottom: 8px; }
    .warning { color: var(--bad); }
    .good { color: var(--good); }
    .chart-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }
    .chart-card {
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      background: #fffdf9;
    }
    .chart-card img {
      display: block;
      width: 100%;
      height: auto;
      background: white;
    }
    .chart-card h3 {
      margin: 0;
      padding: 12px 14px;
      font-size: 1rem;
      border-top: 1px solid var(--line);
      color: var(--ink);
    }
    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fffdf9;
    }
    table.data {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }
    table.data th,
    table.data td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
    }
    table.data th {
      position: sticky;
      top: 0;
      background: #f7efe4;
      color: var(--accent);
    }
    .empty {
      color: var(--muted);
      font-style: italic;
    }
    @media (max-width: 720px) {
      .page { padding: 14px; }
      .hero, section { padding: 18px; }
      .hero h1 { font-size: 1.6rem; }
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <h1>{{ metadata.strategy_name }} Backtest Report</h1>
      <p>{{ metadata.instrument }} on {{ metadata.timeframe }} from {{ metadata.start_time|display }} to {{ metadata.end_time|display }}</p>
      <div class="pill-row">
        <span class="pill">End Value: {{ metadata.end_value|display }}</span>
        <span class="pill">Start Cash: {{ metadata.start_cash|display }}</span>
        {% if metadata.timeframes|length > 1 %}
        <span class="pill">Timeframes: {{ metadata.timeframes|join(", ") }}</span>
        {% endif %}
        <span class="pill">Warnings: {{ warnings|length }}</span>
        <span class="pill">Generated: {{ generated_at|display }}</span>
      </div>
    </div>

    <div class="grid">
      <section>
        <h2>Parameters</h2>
        {% if parameter_rows %}
        <table class="kv">
          {% for row in parameter_rows %}
          <tr><td>{{ row.name }}</td><td>{{ row.value|display }}</td></tr>
          {% endfor %}
        </table>
        {% else %}
        <p class="empty">No strategy parameters were supplied.</p>
        {% endif %}
      </section>
      <section>
        <h2>Execution Assumptions</h2>
        <table class="kv">
          {% for row in execution_rows %}
          <tr><td>{{ row.name }}</td><td>{{ row.value|display }}</td></tr>
          {% endfor %}
        </table>
      </section>
    </div>

    <section>
      <h2>Key Metrics</h2>
      <div class="metric-grid">
        {% for metric in metrics %}
        <div class="metric-card">
          <span class="name">{{ metric.name }}</span>
          <span class="value">{{ metric.value|display }}</span>
        </div>
        {% endfor %}
      </div>
    </section>

    <div class="grid">
      <section>
        <h2>Caveats</h2>
        <ul>
          {% for caveat in caveats %}
          <li>{{ caveat.message }}</li>
          {% endfor %}
        </ul>
      </section>
      <section>
        <h2>Warnings</h2>
        {% if warnings %}
        <ul>
          {% for warning in warnings %}
          <li class="warning">{{ warning.message }}</li>
          {% endfor %}
        </ul>
        {% else %}
        <p class="good">No analyzer warnings were raised for this run.</p>
        {% endif %}
      </section>
    </div>

    <section>
      <h2>Trade Breakdown</h2>
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>Segment</th>
              <th>Closed Trades</th>
              <th>Wins</th>
              <th>Losses</th>
              <th>Gross PnL</th>
              <th>Net PnL</th>
              <th>Average Net PnL</th>
            </tr>
          </thead>
          <tbody>
            {% for row in trade_breakdown %}
            <tr>
              <td>{{ row.segment }}</td>
              <td>{{ row.closed_trades|display }}</td>
              <td>{{ row.wins|display }}</td>
              <td>{{ row.losses|display }}</td>
              <td>{{ row.gross_pnl|display }}</td>
              <td>{{ row.net_pnl|display }}</td>
              <td>{{ row.average_net_pnl|display }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>

    {% if charts %}
    <section>
      <h2>Charts</h2>
      <div class="chart-grid">
        {% for chart in charts %}
        <div class="chart-card">
          <img src="{{ chart.data_uri }}" alt="{{ chart.title }}">
          <h3>{{ chart.title }}</h3>
        </div>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    <section>
      <h2>Open Trades Snapshot</h2>
      {% if open_trade_rows %}
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              {% for column in open_trade_columns %}
              <th>{{ column|labelize }}</th>
              {% endfor %}
            </tr>
          </thead>
          <tbody>
            {% for row in open_trade_rows %}
            <tr>
              {% for column in open_trade_columns %}
              <td>{{ row[column]|display }}</td>
              {% endfor %}
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% else %}
      <p class="empty">No open trades remained at the end of the run.</p>
      {% endif %}
    </section>

    <section>
      <h2>Closed Trades</h2>
      {% if closed_trade_rows %}
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              {% for column in closed_trade_columns %}
              <th>{{ column|labelize }}</th>
              {% endfor %}
            </tr>
          </thead>
          <tbody>
            {% for row in closed_trade_rows %}
            <tr>
              {% for column in closed_trade_columns %}
              <td>{{ row[column]|display }}</td>
              {% endfor %}
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      {% else %}
      <p class="empty">No closed trades were recorded for this run.</p>
      {% endif %}
    </section>
  </div>
</body>
</html>
"""


def write_backtest_html_report(
    result: BacktestResult,
    output_path: str | Path,
    *,
    risk_free_rate: float = 0.0,
    chart_paths: dict[str, Path] | None = None,
    payload: dict[str, Any] | None = None,
) -> Path:
    """Write a portable HTML report for one backtest result."""

    if payload is None:
        payload = build_backtest_json_payload(result, risk_free_rate=risk_free_rate)
    metadata = payload["metadata"]
    execution_assumptions = payload["execution_assumptions"]
    metrics = payload["metrics"]
    trade_breakdown = payload["trade_breakdown"]
    warnings = payload["warnings"]
    caveats = payload["caveats"]
    ledgers = payload["ledgers"]

    context = {
        "generated_at": payload["generated_at"],
        "metadata": metadata,
        "execution_rows": [
            {"name": key, "value": value} for key, value in execution_assumptions.items()
        ],
        "parameter_rows": [
            {"name": key, "value": value} for key, value in metadata["parameters"].items()
        ],
        "metrics": [{"name": _labelize(key), "value": value} for key, value in metrics.items()],
        "trade_breakdown": _trade_breakdown_rows(trade_breakdown),
        "warnings": warnings,
        "caveats": caveats,
        "charts": _inline_chart_images(chart_paths or {}),
        "open_trade_rows": ledgers["open_trades"],
        "open_trade_columns": list(ledgers["open_trades"][0].keys()) if ledgers["open_trades"] else [],
        "closed_trade_rows": ledgers["closed_trades"],
        "closed_trade_columns": (
            list(ledgers["closed_trades"][0].keys()) if ledgers["closed_trades"] else []
        ),
    }

    env = Environment(autoescape=select_autoescape(default_for_string=True))
    env.filters["display"] = _display_value
    env.filters["labelize"] = _labelize
    template = env.from_string(_TEMPLATE)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.render(**context), encoding="utf-8")
    return path


def _inline_chart_images(chart_paths: dict[str, Path]) -> list[dict[str, str]]:
    ordered = [
        ("equity_curve", "Equity Curve"),
        ("drawdown", "Drawdown"),
        ("trade_distribution", "Trade PnL Distribution"),
        ("monthly_returns", "Monthly Returns"),
    ]
    charts: list[dict[str, str]] = []
    for key, title in ordered:
        path = chart_paths.get(key)
        if path is None or not path.exists():
            continue
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        charts.append(
            {
                "key": key,
                "title": title,
                "data_uri": f"data:image/png;base64,{encoded}",
            }
        )
    return charts


def _display_value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _labelize(value: str) -> str:
    return value.replace("_", " ").title()


def _trade_breakdown_rows(trade_breakdown: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment, values in trade_breakdown.items():
        row = dict(values)
        row["segment"] = segment
        rows.append(row)
    return rows
