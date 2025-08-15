# bri_estatement_app.py
import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime
from pathlib import Path

def clean_amount(amount_str: str) -> float:
    if not amount_str or amount_str.strip() == '':
        return 0.0
    try:
        cleaned = re.sub(r'[,\s]', '', str(amount_str))
        if '.' in cleaned:
            parts = cleaned.split('.')
            if len(parts) == 2 and len(parts[1]) == 2:
                return float(cleaned)
            else:
                cleaned = cleaned.replace('.', '')
        return float(cleaned)
    except:
        return 0.0

def extract_personal_info(text):
    # contoh sederhana, regex bisa disesuaikan
    return pd.DataFrame([{
        "Account Name": re.search(r'Nama\s*:\s*(.+)', text).group(1) if re.search(r'Nama\s*:\s*(.+)', text) else "",
        "Account Number": re.search(r'No\. Rekening\s*:\s*(\d+)', text).group(1) if re.search(r'No\. Rekening\s*:\s*(\d+)', text) else "",
        "Period": re.search(r'Periode\s*:\s*(.+)', text).group(1) if re.search(r'Periode\s*:\s*(.+)', text) else ""
    }])

def extract_summary(text):
    # summary saldo awal, akhir, total debit/kredit
    return pd.DataFrame([{
        "Opening Balance": 1000000,
        "Closing Balance": 1500000,
        "Total Debit": 500000,
        "Total Credit": 1000000
    }])

def extract_transactions(text):
    # regex parsing transaksi (dummy contoh)
    trx = []
    lines = text.split("\n")
    for line in lines:
        if re.match(r'\d{2}/\d{2}/\d{4}', line):
            parts = line.split()
            trx.append({
                "Date": parts[0],
                "Description": " ".join(parts[1:-2]),
                "Debit": clean_amount(parts[-2]),
                "Credit": clean_amount(parts[-1])
            })
    return pd.DataFrame(trx)

def extract_partner_summary(trx_df):
    # contoh grouping by description
    if trx_df.empty:
        return pd.DataFrame()
    partner_summary = trx_df.groupby("Description").agg({
        "Debit": "sum",
        "Credit": "sum"
    }).reset_index()
    return partner_summary

def extract_analytics(trx_df):
    if trx_df.empty:
        return pd.DataFrame()
    return pd.DataFrame([{
        "Total Transactions": len(trx_df),
        "Total Debit": trx_df["Debit"].sum(),
        "Total Credit": trx_df["Credit"].sum(),
        "Average Debit": trx_df["Debit"].mean(),
        "Average Credit": trx_df["Credit"].mean()
    }])

def parse_bri_statement(file_obj):
    text = ""
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

    personal_df = extract_personal_info(text)
    summary_df = extract_summary(text)
    trx_df = extract_transactions(text)
    partner_trx_df = extract_partner_summary(trx_df)
    analytics_df = extract_analytics(trx_df)

    return personal_df, summary_df, trx_df, partner_trx_df, analytics_df

# ---------------------- Streamlit App UI ---------------------- #
st.set_page_config(page_title="BRI E-Statement Reader", layout="wide")
st.title("📄 BRI E-Statement Reader")

uploaded_pdf = st.file_uploader("Upload a BRI PDF e-statement", type="pdf")

if uploaded_pdf:
    st.success("✅ PDF uploaded. Processing...")

    # Read bytes once and reuse
    pdf_bytes = uploaded_pdf.read()
    personal_df, summary_df, trx_df, partner_trx_df, analytics_df = parse_bri_statement(io.BytesIO(pdf_bytes))

    # ✅ ADD DOWNLOAD SECTION
    st.markdown("---")
    st.subheader("📥 Download Complete Analysis")
    
    @st.cache_data
    def create_excel_download(personal_df, summary_df, trx_df, partner_trx_df, analytics_df):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            personal_df.to_excel(writer, sheet_name='Account Info', index=False)
            summary_df.to_excel(writer, sheet_name='Monthly Summary', index=False)
            analytics_df.to_excel(writer, sheet_name='Analytics', index=False)
            trx_df.to_excel(writer, sheet_name='Transactions', index=False)
            partner_trx_df.to_excel(writer, sheet_name='Partner Summary', index=False)
        
        output.seek(0)
        return output.getvalue()

    excel_data = create_excel_download(personal_df, summary_df, trx_df, partner_trx_df, analytics_df)
    
    st.download_button(
        label="📊 Download Complete Analysis (Excel)",
        data=excel_data,
        file_name=f"BRI_Statement_Analysis_{personal_df.iloc[0]['Period'] if not personal_df.empty else 'Unknown'}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.markdown("---")
    
    # Tabs section
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📌 Account Info", "📊 Monthly Summary", "📈 Analytics", "💸 Transactions", "💳 Partner Transactions"])

    with tab1:
        st.dataframe(personal_df)

    with tab2:
        st.dataframe(summary_df)

    with tab3:
        st.dataframe(analytics_df)

    with tab4:
        st.dataframe(trx_df)

    with tab5:
        st.dataframe(partner_trx_df)
