"""Dashboard of the banking lakehouse: what the pipeline cleaned, which fraud rules work, and
why window functions matter. Reads the small extracts in dashboard/data (written by
`python -m banking_lakehouse.pipeline`), so it needs no Spark and opens instantly.

Run with:  streamlit run dashboard/app.py
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from theme import CHART, page_css

DATA = Path(__file__).parent / "data"
REPO = "https://github.com/mmartinezvaras/banking-lakehouse-pyspark"
THEMES = {"auto": ("brightness_auto", "Auto"), "light": ("light_mode", "Claro"), "dark": ("dark_mode", "Noche")}
REASONS = {
    "duplicate_delivery": "Fila repetida (enviada dos veces)",
    "missing_or_unparseable_amount": "Importe vacío o ilegible",
    "non_positive_amount": "Importe negativo o cero",
    "unknown_customer": "Cliente que no existe",
    "unparseable_timestamp": "Fecha ilegible",
    "invalid_tx_type": "Tipo de operación desconocido",
    "invalid_channel": "Canal desconocido",
    "invalid_country": "País no válido",
    "invalid_tx_id": "Identificador no válido",
}
RULE_SHORT = {"naive": "Regla simple", "window": "Ventanas", "window_review": "Ventanas + revisión"}

st.set_page_config(page_title="Fraude bancario · Lakehouse", page_icon=":material/account_balance:", layout="wide")
mode_choice = st.session_state.get("theme") or "auto"
st.html(page_css(mode_choice))


def chart_mode() -> str:
    if mode_choice != "auto":
        return mode_choice
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:
        return "light"


C = CHART[chart_mode()]


def esc(value) -> str:
    return html.escape(str(value))


def pct(x: float) -> str:
    """Whole percent, but never round 99.9 % up to a misleading 100 %."""
    v = x * 100
    text = f"{v:.0f}" if round(v) < 100 or v >= 100 else f"{v:.1f}"
    return text.replace(".", ",") + " %"


def eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def num(x: int) -> str:
    return f"{x:,}".replace(",", ".")


def icon(name: str) -> str:
    return f'<span class="ms" aria-hidden="true">{name}</span>'


def style(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure(background="transparent", font="Inter")
        .configure_view(stroke=None)
        .configure_axis(
            labelColor=C["label"], titleColor=C["label"], gridColor=C["grid"], domainColor=C["grid"],
            tickColor=C["grid"], labelFontSize=12, titleFontSize=12, titleFontWeight=500,
        )
        .configure_legend(labelColor=C["label"], titleColor=C["label"], orient="top", labelFontSize=12, titleFontSize=12)
        .configure_header(labelColor=C["label"], titleColor=C["label"], labelFontSize=13, labelFontWeight=600)
    )


# ---------- Header ----------
st.segmented_control(
    "Tema", options=list(THEMES), format_func=lambda k: f":material/{THEMES[k][0]}: {THEMES[k][1]}",
    default="auto", key="theme", label_visibility="collapsed",
)

if not (DATA / "summary.json").exists():
    st.html(
        '<div class="lx-hero"><h1>Fraude bancario en un lakehouse</h1>'
        "<p>Aún no hay datos. Ejecuta <code>python -m banking_lakehouse.generate_data</code> y "
        "<code>python -m banking_lakehouse.pipeline</code>, y recarga.</p></div>"
    )
    st.stop()

S = json.loads((DATA / "summary.json").read_text())
L = S["layers"]
M = {m["rule"]: m for m in S["rule_metrics"]}
naive, window, review = M["naive"], M["window"], M["window_review"]

st.html(
    f"""<header class="lx-hero">
<h1>Detectar fraude con tarjeta entre {num(L['silver_rows'])} movimientos bancarios</h1>
<p>Un lakehouse construido con <b>PySpark</b> y <b>Delta Lake</b>: los ficheros sucios del banco entran en
<b>Bronze</b>, se limpian en <b>Silver</b> y en <b>Gold</b> se calculan señales de fraude con
<b>window functions</b>. Los datos son sintéticos, con el fraude escondido como en la vida real:
uno de cada {round(L['silver_rows'] / max(L['fraud_transactions'], 1)):,} movimientos.</p>
</header>"""
)

kpis = [
    (num(L["silver_rows"]), "movimientos limpios en Silver", f"{num(L['quarantined_rows'])} filas sucias apartadas"),
    (pct(window["share_stopped"]), "del dinero robado se habría frenado", f"con la regla simple: {pct(naive['share_stopped'])}"),
    (f"{window['bursts_detected']} de {window['bursts']}", "ataques detectados", f"regla simple: {naive['bursts_detected']} de {naive['bursts']}"),
    (f"{window['false_alerts_per_day']:.1f}".replace(".", ","), "falsas alarmas al día", f"regla simple: {str(naive['false_alerts_per_day']).replace('.', ',')}"),
]
st.html(
    '<div class="lx-kpis">'
    + "".join(
        f'<div class="lx-kpi" style="--i:{i}"><div class="v">{esc(v)}</div><div class="l">{esc(label)}</div><div class="c">{esc(c)}</div></div>'
        for i, (v, label, c) in enumerate(kpis)
    )
    + "</div>"
)

# ---------- 1. Layers ----------
b1, *rest = S["batches"] or [{}]
inc = rest[0] if rest else {}
st.html(
    f"""<section class="lx-sec"><h2>Del CSV sucio a tablas fiables</h2>
<p>El banco envía ficheros con problemas reales: filas repetidas, importes como «1.234,56» o «€ 42,10», fechas en dos
formatos, clientes que no existen. Nada se pierde: lo que se puede arreglar se arregla y lo imposible se aparta en
cuarentena con su motivo.</p></section>
<div class="lx-flow">
  <div class="lx-step"><div class="n">{icon('description')}Origen</div><div class="t">CSV del banco</div>
    <div class="v">{num(L['bronze_rows'])}</div><div class="d">filas recibidas en {len(S['batches'])} entregas</div></div>
  <div class="lx-step"><div class="n">{icon('inventory_2')}Bronze</div><div class="t">Copia fiel + auditoría</div>
    <div class="v">{num(L['bronze_rows'])}</div><div class="d">todo como texto, con fichero de origen y hora de carga</div></div>
  <div class="lx-step"><div class="n">{icon('cleaning_services')}Silver</div><div class="t">Limpio y tipado</div>
    <div class="v">{num(L['silver_rows'])}</div><div class="d">{L['silver_partitions']} particiones por mes · {num(L['quarantined_rows'])} en cuarentena</div></div>
  <div class="lx-step"><div class="n">{icon('insights')}Gold</div><div class="t">Señales de fraude</div>
    <div class="v">{len(S['rules'])} reglas</div><div class="d">features por cliente con ventanas de tiempo</div></div>
</div>"""
)

reasons = pd.DataFrame(
    [{"Motivo": REASONS.get(k, k), "Filas": v} for k, v in L["quarantine_reasons"].items()]
)
if not reasons.empty:
    bars = alt.Chart(reasons).encode(
        y=alt.Y("Motivo:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        x=alt.X("Filas:Q", title="Filas en cuarentena"),
    )
    chart = bars.mark_bar(color=C["ink"], cornerRadiusEnd=4, height=16) + bars.mark_text(
        align="left", dx=6, color=C["label"], fontSize=12
    ).encode(text="Filas:Q")
    st.altair_chart(style(chart.properties(height=34 * len(reasons) + 20)), use_container_width=True)

# ---------- 2. Rules ----------
st.html(
    """<section class="lx-sec"><h2>¿Qué regla funciona mejor?</h2>
<p>La regla que se le ocurre a cualquiera, «pago grande en el extranjero», marca los hoteles de quien está de viaje y
no ve los ataques que se quedan por debajo de 900 €. Las reglas con <b>window functions</b> miran cada pago en el
contexto de los anteriores del mismo cliente: cuántos lleva en 10 minutos, si justo antes hubo un cobro diminuto de
prueba, si ha saltado de país.</p></section>"""
)
rows = [
    ("Fraude detectado (recall)", "recall", pct),
    ("Alertas que eran fraude (precisión)", "precision", pct),
    ("Ataques detectados", None, lambda m: f"{m['bursts_detected']} de {m['bursts']}"),
    ("Dinero robado que se habría frenado", "share_stopped", pct),
    ("Falsas alarmas al día", "false_alerts_per_day", lambda v: f"{v:.2f}".replace(".", ",")),
    ("Pago del ataque en que salta la alarma (mediana)", "median_payment_of_first_alert", lambda v: "—" if v is None else f"{v}.º"),
]
order = ["naive", "window", "window_review"]
head = "".join(f'<th class="num">{esc(RULE_SHORT[k])}</th>' for k in order)
body = ""
for label, key, fmt in rows:
    cells = "".join(f'<td class="num">{esc(fmt(M[k] if key is None else M[k][key]))}</td>' for k in order)
    body += f"<tr><td>{esc(label)}</td>{cells}</tr>"
st.html(
    f'<div class="lx-card lx-scroll"><table class="lx-table"><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>'
    '<p class="lx-note"><b>Regla simple</b>: pago con tarjeta en el extranjero de más de 900 €. '
    "<b>Ventanas</b>: velocidad (3+ pagos online en el extranjero en 10 min), prueba de tarjeta (pago de 100 €+ "
    "en los 10 min siguientes a un cobro diminuto) y salto de país con importe 5× el habitual; solo usan datos "
    "pasados, así que valdrían en tiempo real. <b>+ revisión</b>: añade una regla con <code>lead()</code> que, al "
    "día siguiente, marca también los cobros de prueba.</p></div>"
)

metric_rows = []
for k in order:
    for label, key in [("Dinero frenado", "share_stopped"), ("Fraude detectado", "recall"), ("Precisión", "precision")]:
        metric_rows.append({"Regla": RULE_SHORT[k], "Métrica": label, "Valor": M[k][key]})
mdf = pd.DataFrame(metric_rows)
tones = alt.Scale(domain=[RULE_SHORT[k] for k in order], range=[C["soft"], C["ink"], C["mid"]])
base = alt.Chart(mdf).encode(
    y=alt.Y("Regla:N", sort=[RULE_SHORT[k] for k in order], title=None),
    x=alt.X("Valor:Q", axis=alt.Axis(format="%", tickCount=5), scale=alt.Scale(domain=[0, 1]), title=None),
)
rules_chart = (
    (base.mark_bar(cornerRadiusEnd=4, height=18).encode(color=alt.Color("Regla:N", scale=tones, legend=None))
     + base.mark_text(align="left", dx=6, color=C["label"], fontSize=12).encode(text=alt.Text("Valor:Q", format=".0%")))
    .properties(height=96)
    .facet(row=alt.Row("Métrica:N", sort=["Dinero frenado", "Fraude detectado", "Precisión"], title=None,
                       header=alt.Header(labelAngle=0, labelAlign="left", labelAnchor="start", labelPadding=4)))
    .resolve_scale(y="independent")
)
st.altair_chart(style(rules_chart), use_container_width=True)

# ---------- 3. Anatomy of an attack ----------
burst = pd.read_csv(DATA / "burst_example.csv", parse_dates=["ts"])
st.html(
    """<section class="lx-sec"><h2>Anatomía de un ataque</h2>
<p>Un cliente real del conjunto de datos: horas de actividad normal y, de repente, una tarjeta comprometida. Primero
un cobro de prueba de pocos euros; minutos después, pagos online en el extranjero. Las ventanas lo ven al segundo
pago; la regla simple, solo si algún importe supera 900 €.</p></section>"""
)
if not burst.empty:
    burst["Tipo"] = burst["fraud_label"].map({1: "Fraude", 0: "Legítimo"})
    burst["Alerta"] = burst["rule_window"].map({1: "Alerta de las ventanas", 0: "Sin alerta"})
    burst["Hora"] = burst["ts"]
    burst["Importe"] = burst["amount_d"]
    base = alt.Chart(burst).encode(
        x=alt.X("Hora:T", title=None, axis=alt.Axis(format="%H:%M")),
        y=alt.Y("Importe:Q", scale=alt.Scale(type="log"), title="Importe (€, escala log)"),
        tooltip=[
            alt.Tooltip("Hora:T", format="%d/%m %H:%M:%S"), alt.Tooltip("Importe:Q", format=",.2f"), "country:N",
            "channel:N", alt.Tooltip("tx_count_10m:Q", title="Pagos en 10 min"), "Tipo:N", "Alerta:N",
        ],
    )
    points = base.mark_point(size=110, filled=True, opacity=1).encode(
        shape=alt.Shape("Tipo:N", scale=alt.Scale(domain=["Legítimo", "Fraude"], range=["circle", "cross"]), title=None),
        color=alt.Color("Tipo:N", scale=alt.Scale(domain=["Legítimo", "Fraude"], range=[C["soft"], C["ink"]]), legend=None),
    )
    rings = base.transform_filter(alt.datum.rule_window == 1).mark_point(size=420, filled=False, strokeWidth=1.6).encode(
        stroke=alt.Stroke("Alerta:N", scale=alt.Scale(range=[C["mid"]]), title=None)
    )
    st.altair_chart(style((points + rings).properties(height=320)), use_container_width=True)

    def tick(v) -> str:
        return '<span class="lx-tag solid">Sí</span>' if v == 1 else '<span class="lx-tag ghost">No</span>'

    rows_html = ""
    for _, r in burst[burst["ts"] >= burst.loc[burst["fraud_label"] == 1, "ts"].min() - pd.Timedelta(minutes=30)].iterrows():
        signals = [name for col, name in [("probe_before_10m", "prueba previa"), ("rule_velocity", "velocidad"),
                                          ("rule_country_hop", "salto de país"), ("rule_probe_attack", "cobro de prueba")] if r[col] == 1]
        rows_html += (
            f'<tr class="{"is-fraud" if r["fraud_label"] == 1 else ""}"><td>{r["ts"]:%H:%M:%S}</td>'
            f'<td class="num">{r["amount_d"]:,.2f} €</td><td>{esc(r["country"])}</td><td>{esc(r["channel"])}</td>'
            f'<td class="num">{int(r["tx_count_10m"])}</td><td>{esc(", ".join(signals) or "—")}</td>'
            f'<td>{tick(r["rule_naive"])}</td><td>{tick(r["rule_window"])}</td><td>{"Fraude" if r["fraud_label"] == 1 else "Legítimo"}</td></tr>'
        )
    st.html(
        '<div class="lx-card lx-scroll"><table class="lx-table"><thead><tr><th>Hora</th><th class="num">Importe</th><th>País</th>'
        '<th>Canal</th><th class="num">Pagos en 10 min</th><th>Señales</th><th>Regla simple</th><th>Ventanas</th><th>Realidad</th>'
        f"</tr></thead><tbody>{rows_html}</tbody></table>"
        '<p class="lx-note">Filas resaltadas: el fraude real (la etiqueta que el banco conocería días después por las '
        "reclamaciones). Las reglas no la usan; sirve para medirlas.</p></div>"
    )

# ---------- 4. A traveller ----------
trip = pd.read_csv(DATA / "trip_example.csv", parse_dates=["ts"])
if not trip.empty:
    fp = int(trip["rule_naive"].sum())
    st.html(
        f"""<section class="lx-sec"><h2>Un viajero no es un fraude</h2>
<p>El cliente al que más falsas alarmas daría la regla simple: un viaje a {esc(trip['country'].mode()[0])} con
{len(trip)} pagos. La regla simple marca {fp} (el hotel, el coche de alquiler); las ventanas, {int(trip['rule_window'].sum())}:
son pagos en tienda, espaciados en días y en un único país.</p></section>"""
    )
    tbase = alt.Chart(trip.assign(Importe=trip["amount_d"], Hora=trip["ts"],
                                  Regla=trip["rule_naive"].map({1: "Marcado por la regla simple", 0: "Sin alerta"}))).encode(
        x=alt.X("Hora:T", title=None, axis=alt.Axis(format="%d/%m")),
        y=alt.Y("Importe:Q", title="Importe (€)"),
        tooltip=[alt.Tooltip("Hora:T", format="%d/%m %H:%M"), alt.Tooltip("Importe:Q", format=",.2f"), "country:N", "Regla:N"],
    )
    trip_chart = tbase.mark_bar(width=4, color=C["soft"]) + tbase.transform_filter(alt.datum.rule_naive == 1).mark_point(
        shape="triangle-down", size=140, filled=True, yOffset=-10
    ).encode(color=alt.Color("Regla:N", scale=alt.Scale(range=[C["ink"]]), title=None))
    st.altair_chart(style(trip_chart.properties(height=260)), use_container_width=True)

# ---------- 5. Delta Lake ----------
D = S["delta"]
tt = D["time_travel"]
labels = {"WRITE": "Primera carga", "MERGE": "Carga incremental", "OPTIMIZE": "Compactación"}
items = ""
for h in D["silver_history"]:
    m = h["metrics"]
    if h["operation"] == "MERGE":
        detail = f"{num(m.get('numTargetRowsInserted', 0))} filas nuevas · {num(m.get('numTargetRowsUpdated', 0))} corregidas"
    elif h["operation"] == "OPTIMIZE":
        detail = f"{num(m.get('numFilesRemoved', 0))} ficheros pequeños → {num(m.get('numFilesAdded', 0))}"
    else:
        detail = f"{num(m.get('numOutputRows', 0))} filas"
    items += (f'<li><span class="ver">v{h["version"]}</span><span class="op">{esc(labels.get(h["operation"], h["operation"]))}</span>'
              f'<span class="m">{esc(detail)}</span></li>')
ex = tt.get("example")
travel = ""
if ex:
    travel = (
        f'<div class="lx-card"><div class="lx-note" style="margin:0 0 .5rem">{icon("history")}Viaje en el tiempo: el movimiento '
        f'{ex["tx_id"]} del {ex["ts"][:10]}, leído en la versión 0 y hoy</div><div class="lx-travel">'
        f'<span class="amt old">{ex["amount_before"]:,.2f} €</span><span class="ms" aria-hidden="true">arrow_forward</span>'
        f'<span class="amt">{ex["amount_after"]:,.2f} €</span></div><p class="lx-note">El banco reenvió '
        f'{tt["corrected_rows"]} movimientos con el importe corregido. <code>MERGE</code> los actualiza en lugar de '
        "duplicarlos, y la versión anterior sigue consultable.</p></div>"
    )
st.html(
    f"""<section class="lx-sec"><h2>Delta Lake: historial, correcciones y viaje en el tiempo</h2>
<p>Cada escritura en la tabla Silver es una versión. La segunda entrega del banco trae un día nuevo y correcciones
de días anteriores: se aplican con <code>MERGE</code> por identificador, sin duplicar nada, y se puede volver a
consultar la tabla tal como estaba.</p></section>
<div class="lx-card"><ul class="lx-versions">{items}</ul></div>{travel}"""
)

# ---------- 6. Alerts over time ----------
daily = pd.read_csv(DATA / "daily.csv", parse_dates=["tx_date"])
if not daily.empty:
    weekly = daily.set_index("tx_date").resample("W-MON").sum(numeric_only=True).reset_index()
    long = weekly.melt(id_vars="tx_date", value_vars=["alerts_naive", "alerts_window", "fraud"], var_name="Serie", value_name="Movimientos")
    names = {"alerts_naive": "Alertas de la regla simple", "alerts_window": "Alertas de las ventanas", "fraud": "Fraude real"}
    long["Serie"] = long["Serie"].map(names)
    st.html(
        """<section class="lx-sec"><h2>Alertas por semana</h2>
<p>Cuántas alertas tendría que revisar el equipo de fraude cada semana con cada regla, frente al fraude que hubo
de verdad.</p></section>"""
    )
    line = alt.Chart(long).mark_line(point=True, strokeWidth=2).encode(
        x=alt.X("tx_date:T", title=None, axis=alt.Axis(format="%d %b")),
        y=alt.Y("Movimientos:Q", title="Movimientos por semana"),
        color=alt.Color("Serie:N", scale=alt.Scale(domain=list(names.values()), range=[C["soft"], C["ink"], C["mid"]]), title=None),
        strokeDash=alt.StrokeDash("Serie:N", scale=alt.Scale(domain=list(names.values()), range=[[6, 4], [1, 0], [2, 3]]), title=None),
        tooltip=[alt.Tooltip("tx_date:T", title="Semana del", format="%d/%m"), "Serie:N", "Movimientos:Q"],
    )
    st.altair_chart(style(line.properties(height=280)), use_container_width=True)

st.html(
    f'<p class="lx-note" style="margin:3rem 0 1rem">{icon("code")}<a href="{REPO}">Código en GitHub</a> · '
    "PySpark 4 · Delta Lake 4 · datos sintéticos, ningún cliente real.</p>"
)
