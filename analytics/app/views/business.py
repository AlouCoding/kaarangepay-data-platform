"""Vue métier: what management reads every morning (source: dbt marts in DuckDB)."""

from __future__ import annotations

import altair as alt
import streamlit as st

from kaarangepay_analytics import data
from kaarangepay_analytics.config import Settings

settings = Settings()
st.title("Vue métier")

if not data.warehouse_ready(settings):
    st.info("L'entrepôt n'est pas encore construit. Lance `docker compose run --rm analytics pipeline`.")
    st.stop()

h = data.headline(settings)
st.caption(f"Période simulée : du {h.first_day:%d/%m/%Y} au {h.last_day:%d/%m/%Y} · "
           "modèle dbt reconstruit à chaque `analytics pipeline`")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Transactions", data.thousands(h.transactions))
c2.metric("Volume (XOF)", data.xof_short(h.volume_xof), help=data.xof(h.volume_xof))
c3.metric("Frais (XOF)", data.xof_short(h.fees_xof), help=data.xof(h.fees_xof))
c4.metric("Taux d'échec", f"{h.failure_rate:.1%}")
c5.metric("Alertes fraude", int(h.fraud_alerts))

daily = data.daily(settings)
daily["période"] = daily["is_payday_period"].map({True: "Période de paie (25 → 3)", False: "Jours ordinaires"})

st.subheader("Volume encaissé par jour")
st.altair_chart(
    alt.Chart(daily).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("yearmonthdate(day):O", title=None, axis=alt.Axis(format="%d/%m", labelAngle=0)),
        y=alt.Y("volume_xof:Q", title="XOF"),
        color=alt.Color("période:N", legend=alt.Legend(orient="top", title=None),
                        scale=alt.Scale(domain=["Période de paie (25 → 3)", "Jours ordinaires"],
                                        range=["#0F6E56", "#B4B2A9"])),   # the payday peak is the story
        tooltip=[alt.Tooltip("day:T", title="Jour"), "day_name_fr:N", alt.Tooltip("volume_xof:Q", format=",.0f"),
                 "transactions:Q", alt.Tooltip("failure_rate:Q", format=".1%")],
    ).properties(height=280),
    width="stretch",
)

left, right = st.columns(2)
with left:
    st.subheader("Mix par type d'opération")
    types = data.by_type(settings)
    st.altair_chart(
        alt.Chart(types).mark_bar(color="#0F6E56").encode(
            y=alt.Y("transaction_type:N", sort="-x", title=None),
            x=alt.X("volume_xof:Q", title="Volume encaissé (XOF)"),
            tooltip=["transaction_type", "transactions", alt.Tooltip("volume_xof:Q", format=",.0f"),
                     alt.Tooltip("fees_xof:Q", format=",.0f"), alt.Tooltip("failure_rate:Q", format=".1%")],
        ).properties(height=260),
        width="stretch",
    )
with right:
    st.subheader("Quand les gens paient-ils ?")
    hours = data.by_hour(settings)
    st.altair_chart(
        alt.Chart(hours).mark_rect().encode(
            x=alt.X("hour_of_day:O", title="Heure", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("day_name_fr:N", title=None, sort=["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi",
                                                        "Samedi", "Dimanche"]),
            color=alt.Color("transactions:Q", scale=alt.Scale(scheme="greens"), legend=None),
            tooltip=["day_name_fr", "hour_of_day", "transactions"],
        ).properties(height=260),
        width="stretch",
    )

st.subheader("Taux d'échec quotidien")
st.altair_chart(
    alt.Chart(daily).mark_line(point=True, color="#993C1D").encode(
        x=alt.X("yearmonthdate(day):O", title=None, axis=alt.Axis(format="%d/%m", labelAngle=0)),
        y=alt.Y("failure_rate:Q", title=None, axis=alt.Axis(format="%")),
        tooltip=[alt.Tooltip("day:T"), alt.Tooltip("failure_rate:Q", format=".2%")],
    ).properties(height=200),
    width="stretch",
)
with st.expander("Comment ces chiffres sont calculés"):
    st.markdown(
        "- **Volume encaissé** et **frais** : transactions `COMPLETED` uniquement (`fct_transactions`).\n"
        "- **Taux d'échec** : refus (solde insuffisant…) / tentatives.\n"
        "- Chaque publication passe d'abord les **tests dbt** : clés uniques, valeurs autorisées, relations, "
        "et les invariants du ledger (débits = crédits, somme des soldes = 0). "
        "Si un test échoue, l'ancien entrepôt reste en ligne."
    )
