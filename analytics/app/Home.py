"""KaaranguePay — Streamlit entry point.  Run:  streamlit run app/Home.py"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="KaaranguePay", page_icon=":material/shield:", layout="wide")

pages = st.navigation([
    st.Page("views/business.py", title="Vue métier", icon=":material/monitoring:", default=True),
    st.Page("views/fraud.py", title="Console fraude", icon=":material/gpp_maybe:"),
])
with st.sidebar:
    st.markdown("### KaaranguePay\nPlateforme data mobile money")
    st.caption("PostgreSQL → Debezium → Kafka → Delta Lake → Spark → dbt → cette appli. "
               "Données simulées, aucune donnée réelle.")
pages.run()
