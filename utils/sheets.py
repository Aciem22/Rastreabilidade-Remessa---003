# utils/sheets.py
import pandas as pd
import streamlit as st
from openpyxl import load_workbook

@st.cache_data
def carregar_lotes_validade():
    df = pd.read_excel("Controle_Lote_Validade.xlsx", sheet_name="Lotes")

    # 🔧 Forçando tipo string igual antes
    df["Código do Produto"] = df["Código do Produto"].astype(str)
    df["LOTE"] = df["LOTE"].astype(str).apply(lambda x: f"'{x}")
    df["VALIDADE"] = df["VALIDADE"].astype(str)

    return df