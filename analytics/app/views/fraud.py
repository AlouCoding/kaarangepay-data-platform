"""Console fraude: alerts from the streaming job, read live, with the analyst's decision."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from kaarangepay_analytics import data, feedback
from kaarangepay_analytics.config import Settings

settings = Settings()
st.title("Console fraude")
st.caption("Règle « passage éclair » : un transfert reçu puis retiré en cash à 90-100 % en moins de 30 min. "
           "Source : table gold écrite par Spark Structured Streaming, relue toutes les 10 s.")

LABELS = {"pending": "À traiter", "fraud": "Fraude confirmée", "false_positive": "Faux positif"}


def short(account: str) -> str:
    return f"…{account[-6:]}"


def path_card(alert: pd.Series) -> None:
    """victim -> mule -> agent, with amounts and delay: what the analyst needs at a glance."""
    a, arrow1, b, arrow2, c = st.columns([3, 2, 3, 2, 3], vertical_alignment="center")
    a.markdown(f"**Victime**  \n`{short(alert.victim_account_id)}`")
    arrow1.markdown(f"→ **{data.xof(alert.transfer_amount_xof)}**  \n<small>transfert, {alert.transfer_at:%d/%m %H:%M}"
                    "</small>", unsafe_allow_html=True)
    b.markdown(f"**Mule**  \n`{short(alert.mule_account_id)}`")
    arrow2.markdown(f"→ **{data.xof(alert.cashout_amount_xof)}**  \n<small>retrait cash, "
                    f"{alert.minutes_between:.0f} min après</small>", unsafe_allow_html=True)
    c.markdown("**Agent**  \n<small>argent sorti du système</small>", unsafe_allow_html=True)


@st.fragment(run_every="10s")
def console() -> None:
    alerts = data.live_alerts(settings)
    pending = int((alerts["decision"] == "pending").sum())
    confirmed = int((alerts["decision"] == "fraud").sum())
    rejected = int((alerts["decision"] == "false_positive").sum())
    reviewed = confirmed + rejected

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Alertes", len(alerts))
    m2.metric("À traiter", pending)
    m3.metric("Fraudes confirmées", confirmed)
    m4.metric("Précision (analystes)", f"{confirmed / reviewed:.0%}" if reviewed else "—",
              help="Part des alertes revues que les analystes ont confirmées.")

    if alerts.empty:
        st.info("Aucune alerte pour l'instant. Lance `docker compose run --rm lake fraud`.")
        return

    only_pending = st.toggle("Afficher seulement les alertes à traiter", value=True)
    shown = alerts[alerts["decision"] == "pending"] if only_pending else alerts
    table = pd.DataFrame({
        "Retrait": shown["cashout_at"].dt.strftime("%d/%m %H:%M"),
        "Mule": shown["mule_account_id"].map(short),
        "Reçu (XOF)": shown["transfer_amount_xof"],
        "Retiré (XOF)": shown["cashout_amount_xof"],
        "Délai (min)": shown["minutes_between"].round(0),
        "Statut": shown["decision"].map(LABELS),
    })
    money = st.column_config.NumberColumn(format="localized")
    event = st.dataframe(table, hide_index=True, width="stretch",
                         height=min(36 * (len(table) + 1) + 3, 360),
                         column_config={"Reçu (XOF)": money, "Retiré (XOF)": money},
                         on_select="rerun", selection_mode="single-row")
    rows = event.selection.rows if event is not None else []
    if not rows:
        st.caption("Sélectionne une alerte pour voir le chemin de l'argent et décider.")
        return

    alert = shown.iloc[rows[0]]
    with st.container(border=True):
        st.markdown(f"#### Alerte `{alert.alert_id[:8]}` · {LABELS[alert.decision]}")
        path_card(alert)
        yes, no, _ = st.columns([2, 2, 5])
        if yes.button("Confirmer la fraude", type="primary", key=f"f-{alert.alert_id}"):
            feedback.record(settings.feedback_db, alert.alert_id, "fraud")
            st.rerun(scope="fragment")
        if no.button("Faux positif", key=f"n-{alert.alert_id}"):
            feedback.record(settings.feedback_db, alert.alert_id, "false_positive")
            st.rerun(scope="fragment")


console()
st.caption("Les décisions sont gardées à part (SQLite) : en phase 5, "
           "elles serviront d'étiquettes pour entraîner un modèle.")
