from pathlib import Path

app_code = r'''
import io
import re
import pandas as pd
import pdfplumber
import streamlit as st

# =============================
# Core utilities & parsers (reused from previous version)
# =============================

@st.cache_data(show_spinner=False)
def read_pdf_to_text(file_bytes: bytes) -> str:
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        st.warning(f"Error reading PDF: {e}")
    return text

def clean_amount(amount_str: str) -> float:
    if not amount_str or str(amount_str).strip() == "":
        return 0.0
    try:
        cleaned = re.sub(r"[,\s]", "", str(amount_str))
        if "." in cleaned:
            parts = cleaned.split(".")
            if len(parts) == 2 and len(parts[1]) == 2:
                return float(cleaned)
            else:
                cleaned = cleaned.replace(".", "")
        return float(cleaned)
    except Exception:
        return 0.0

# ---- CMS (older) format ----
def extract_cms_account_info(text):
    account_info = {
        "Bank": "BCA",
        "Account Name": None,
        "Account Number": None,
        "Start Period": None,
        "End Period": None,
        "Period": None,
    }
    account_patterns = [
        r"Account\s+No\s*:?\s*(\d{4}-\d{2}-\d{6}-\d{2}-\d)",
        r"Account\s+No\s*:?\s*(\d+)",
        r"Account\s+No\s*\n*\s*:?\s*(\d{4}-\d{2}-\d{6}-\d{2}-\d)",
        r"Account\s+No\s*\n*\s*(\d+)",
    ]
    for pattern in account_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            account_info["Account Number"] = m.group(1).strip()
            break

    name_patterns = [
        r"Account\s+Name\s*:?\s*([A-Z][A-Z\s&\.]+?)(?=\s*Today\s*Hold|\s*Period|\s*Account\s*Status)",
        r"Account\s+Name\s*\n*\s*:?\s*([A-Z][A-Z\s&\.]+?)(?=\s*Today|\s*Period|\s*Account\s*Status)",
        r"Account\s+Name\s+([A-Z][A-Z\s&\.]+?)(?=\s*Today|\s*Period|\s*Account\s*Status)",
        r"Account\s+Name\s*:?\s*(PT\s+[A-Z\s]+)",
        r"Account\s+Name\s*:?\s*([A-Z][A-Z\s&\.PT]+)",
        r"Account\s+Name\s*:?\s*([A-Z\s&\.PT]+?)(?=\s*\n|\s*Today|\s*Period|\s*Account)",
    ]
    for pattern in name_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            account_info["Account Name"] = m.group(1).strip()
            break

    period_patterns = [
        r"Period\s*:?\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})",
        r"Period\s*\n*\s*:?\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})",
    ]
    for pattern in period_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            account_info["Start Period"] = m.group(1)
            account_info["End Period"] = m.group(2)
            account_info["Period"] = f"{m.group(1)} - {m.group(2)}"
            break
    return account_info

def extract_cms_transactions(text):
    transactions = []
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}", line):
            try:
                parts = line.split()
                if len(parts) >= 6:
                    numeric_parts = []
                    for i in range(len(parts) - 1, -1, -1):
                        part = parts[i]
                        if re.match(r"^[\d,\.]+$", part) or re.match(r"^\d{7}$", part) or part in ["CMSPYRL", "BRI0372", "BRIMDBT"]:
                            numeric_parts.insert(0, part)
                            if len(numeric_parts) == 4:
                                break
                    if len(numeric_parts) >= 4:
                        debet_str = numeric_parts[0]
                        credit_str = numeric_parts[1]
                        ledger_str = numeric_parts[2]
                        debet = clean_amount(debet_str) if debet_str != "0.00" else 0.0
                        credit = clean_amount(credit_str) if credit_str != "0.00" else 0.0
                        ledger = clean_amount(ledger_str)
                        remark = " ".join(parts[2: len(parts) - 4]).strip() if len(parts) - 4 > 2 else ""
                        transactions.append({
                            "Date": parts[0],
                            "Remark": remark,
                            "Debit": debet,
                            "Credit": credit,
                            "Saldo": ledger
                        })
            except Exception:
                continue
    return transactions

def extract_cms_summary(text):
    summary = {}
    summary_pattern = re.compile(
        r"OPENING\s+BALANCE\s+TOTAL\s+DEBET\s+TOTAL\s+CREDIT\s+CLOSING\s+BALANCE\s*\n\s*([\d,\.]+)\s+([\d,\.]+)\s+([\d,\.]+)\s+([\d,\.]+)",
        re.IGNORECASE | re.MULTILINE,
    )
    m = summary_pattern.search(text)
    if m:
        try:
            summary["Saldo Awal"] = clean_amount(m.group(1))
            summary["Saldo Akhir"] = clean_amount(m.group(4))
            summary["Mutasi Debit"] = clean_amount(m.group(2))
            summary["Mutasi Credit"] = clean_amount(m.group(3))
        except Exception:
            pass
    return summary

# ---- 2025-like e-statement ----
def extract_personal_info(text):
    personal_info = {
        "Bank": "BCA",
        "Account Name": None,
        "Account Number": None,
        "Address": None,
        "Report Date": None,
        "Branch": None,
        "Business Unit Address": None,
        "Product Name": None,
        "Currency": None,
        "Period": None,
        "Start Period": None,
        "End Period": None,
    }
    nama_patterns = [
        r"(?:Kepada\s+Yth\.\s*/\s*To\s*:\s*\n\s*[A-Z][A-Z\s]*?\n)\s*(.*?)(?=\n\n|\nNo\.\s*Rekening|\nTanggal\s+Laporan|\nPeriode\s+Transaksi|\nNo\s+Rekening)",
        r"Kepada\s+Yth\.\s*/\s*To\s*:\s*\n\s*([^\n]+)(?:\n([^\n]*?))*?(?=\n\s*No\.\s*Rekening|\n\s*Tanggal\s+Laporan|\n\s*Account\s+No)",
        r"Kepada\s+Yth\.\s*/\s*To\s*:\s*\n\s*(.+?)(?=\n\s*No\.\s*Rekening)",
    ]
    for pattern in nama_patterns:
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            extracted_text = m.group(1).strip()
            lines = [ln.strip() for ln in extracted_text.split("\n") if ln.strip()]
            if lines:
                personal_info["Account Name"] = lines[0]
                if len(lines) > 1:
                    alamat_lines = lines[1:]
                    alamat_filtered = []
                    for ln in alamat_lines:
                        if not re.match(r"\d{2}/\d{2}/\d{2,4}", ln) and "Periode" not in ln:
                            alamat_filtered.append(ln)
                    if alamat_filtered:
                        alamat_cleaned = " ".join(alamat_filtered)
                        personal_info["Address"] = re.sub(r"\s+", " ", alamat_cleaned)
            break

    tanggal_patterns = [
        r"Tanggal\s+Laporan\s*[:\s]*(\d{2}/\d{2}/\d{2,4})",
        r"Statement\s+Date\s*[:\s]*(\d{2}/\d{2}/\d{2,4})",
    ]
    for pattern in tanggal_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            personal_info["Report Date"] = m.group(1)
            break

    periode_patterns = [
        r"Periode\s+Transaksi\s*[:\s]*(\d{2}/\d{2}/\d{2,4})\s*-\s*(\d{2}/\d{2}/\d{2,4})",
        r"Transaction\s+Period\s*[:\s]*(\d{2}/\d{2}/\d{2,4})\s*-\s*(\d{2}/\d{2}/\d{2,4})",
    ]
    for pattern in periode_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            personal_info["Start Period"] = m.group(1)
            personal_info["End Period"] = m.group(2)
            personal_info["Period"] = f"{m.group(1)} - {m.group(2)}"
            break

    rekening_patterns = [
        r"No\.\s*Rekening\s*\n*Account\s*No\s*[,:]*\s*(\d+)",
        r"No\.\s*Rekening\s*[:\s]*(\d+)",
        r"Account\s*No\s*[:\s]*(\d+)",
    ]
    for pattern in rekening_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            personal_info["Account Number"] = m.group(1)
            break

    produk_patterns = [r"(?:Nama\s+Produk|Product\s+Name)\s*[,:]*\s*(.*?)(?=\s*(?:Unit\s*Kerja|Business\s*Unit|Valuta|Currency|Alamat\s*Unit\s*Kerja|\n|$))"]
    for pattern in produk_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            personal_info["Product Name"] = m.group(1).strip()
            break

    valuta_patterns = [
        r"Valuta\s*\n*Currency\s*[,:]*\s*([A-Z]+)",
        r"Valuta\s*[:\s]*([A-Z]+)",
        r"Currency\s*[:\s]*([A-Z]+)",
    ]
    for pattern in valuta_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            personal_info["Currency"] = m.group(1).strip()
            break

    return personal_info

def extract_transactions(text: str):
    transactions = []
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}", line):
            parts = line.split()
            if len(parts) >= 7:
                try:
                    numeric_parts = []
                    for i in range(len(parts) - 1, -1, -1):
                        if re.match(r"^[\d,\.]+$", parts[i]) or re.match(r"^\d{7}$", parts[i]):
                            numeric_parts.insert(0, parts[i])
                            if len(numeric_parts) == 4:
                                break
                    if len(numeric_parts) == 4:
                        teller_id = numeric_parts[0]
                        debit = clean_amount(numeric_parts[1])
                        credit = clean_amount(numeric_parts[2])
                        balance = clean_amount(numeric_parts[3])
                        desc_start = 2
                        desc_end = len(parts) - 4
                        description = " ".join(parts[desc_start:desc_end])
                        transactions.append({
                            "tanggal": parts[0],
                            "waktu": parts[1],
                            "deskripsi": description.strip(),
                            "teller_id": teller_id,
                            "debit": debit,
                            "kredit": credit,
                            "saldo": balance,
                        })
                except Exception:
                    continue
    return transactions

# ---- Partner & analytics (generic) ----
def extract_partner_name_bri(description: str):
    if description is None or (isinstance(description, float) and pd.isna(description)):
        return None
    skip_keywords = ["BIAYA", "ADM", "BUNGA", "PAJAK", "KLIRING", "TARIK TUNAI",
                     "SETORAN", "BI-FAST", "BPJS", "TAX", "INTEREST",
                     "FEE", "SINGLE CN", "POLLING", "REWARD", "CLAIM", "BPJS TK", "BPJS KESEHATAN"]
    if any(k in str(description).upper() for k in skip_keywords):
        return None
    cleaned = str(description).strip()
    # For generic BCA, keep a simple fallback extraction
    words = [w for w in re.sub(r"\b\d{7,}\b", "", cleaned).split() if w.isalpha() and len(w) >= 2]
    if len(words) >= 2:
        return " ".join(words[:4])
    return None

def detect_format(df: pd.DataFrame) -> str:
    if "Remark" in df.columns:
        return "CMS"
    elif "deskripsi" in df.columns:
        return "E_STATEMENT"
    else:
        return "UNKNOWN"

def analyze_partners(transactions_df: pd.DataFrame):
    if transactions_df.empty:
        return transactions_df, pd.DataFrame()
    fmt = detect_format(transactions_df)
    df = transactions_df.copy()
    if fmt == "CMS":
        desc_col, debit_col, credit_col = "Remark", "Debit", "Credit"
    elif fmt == "E_STATEMENT":
        desc_col, debit_col, credit_col = "deskripsi", "debit", "kredit"
    else:
        return df, pd.DataFrame()
    df["partner_name"] = df[desc_col].apply(extract_partner_name_bri)
    df["transaction_type"] = df.apply(lambda r: "DEBIT" if r[debit_col] > 0 else ("CREDIT" if r[credit_col] > 0 else "UNKNOWN"), axis=1)
    df["amount"] = df[debit_col] + df[credit_col]
    partner_transactions = df[df["partner_name"].notna()].copy()
    if partner_transactions.empty:
        return df, pd.DataFrame()
    partner_summary = (
        partner_transactions
        .groupby(["partner_name", "transaction_type"])
        .agg({debit_col: "sum", credit_col: "sum", "amount": "sum", desc_col: "count"})
        .rename(columns={desc_col: "transaction_count"})
        .reset_index()
        .sort_values("amount", ascending=False)
    )
    partner_summary_table = create_partner_summary_table(df)
    return partner_summary, partner_summary_table

def create_partner_summary_table(partner_df: pd.DataFrame) -> pd.DataFrame:
    if partner_df.empty or "partner_name" not in partner_df.columns:
        return pd.DataFrame()
    partner_transactions = partner_df[partner_df["partner_name"].notna()].copy()
    if partner_transactions.empty:
        return pd.DataFrame()
    if "Debit" in partner_transactions.columns and "Credit" in partner_transactions.columns:
        debit_col, credit_col = "Debit", "Credit"
    elif "debit" in partner_transactions.columns and "kredit" in partner_transactions.columns:
        debit_col, credit_col = "debit", "kredit"
    else:
        return pd.DataFrame()

    summary_rows = []
    for partner in partner_transactions["partner_name"].unique():
        p = partner_transactions[partner_transactions["partner_name"] == partner]
        total_credit = p[credit_col].sum()
        total_debit = p[debit_col].sum()
        credit_count = (p[credit_col] > 0).sum()
        debit_count = (p[debit_col] > 0).sum()
        total_transactions = len(p)
        summary_rows.append({
            "Partner": partner,
            "Total_Credit": total_credit,
            "Total_Debit": total_debit,
            "Credit_Count": int(credit_count),
            "Debit_Count": int(debit_count),
            "Total_Transactions": total_transactions,
        })
    df = pd.DataFrame(summary_rows)
    df["Total_Volume"] = df["Total_Credit"] + df["Total_Debit"]
    df = df.sort_values("Total_Volume", ascending=False).drop(columns=["Total_Volume"]).reset_index(drop=True)
    return df

def create_partner_statistics_summary(partner_df: pd.DataFrame) -> pd.DataFrame:
    if partner_df.empty or "partner_name" not in partner_df.columns:
        return pd.DataFrame()
    partner_transactions = partner_df[partner_df["partner_name"].notna()].copy()
    if partner_transactions.empty:
        return pd.DataFrame()
    if "Debit" in partner_transactions.columns and "Credit" in partner_transactions.columns:
        debit_col, credit_col = "Debit", "Credit"
    elif "debit" in partner_transactions.columns and "kredit" in partner_transactions.columns:
        debit_col, credit_col = "debit", "kredit"
    else:
        return pd.DataFrame()

    total_credit_transactions = (partner_transactions[credit_col] > 0).sum()
    total_debit_transactions = (partner_transactions[debit_col] > 0).sum()
    total_credit_amount = partner_transactions[credit_col].sum()
    total_debit_amount = partner_transactions[debit_col].sum()
    total_unique_partners = partner_transactions["partner_name"].nunique()

    partner_volumes = partner_transactions.groupby("partner_name").agg({debit_col: "sum", credit_col: "sum"}).reset_index()
    partner_volumes["total_volume"] = partner_volumes[debit_col] + partner_volumes[credit_col]
    top_row = partner_volumes.loc[partner_volumes["total_volume"].idxmax()] if not partner_volumes.empty else None

    summary_data = {
        "No_of_Credit": int(total_credit_transactions),
        "No_of_Debit": int(total_debit_transactions),
        "Total_Credit_Amount": float(total_credit_amount),
        "Total_Debit_Amount": float(total_debit_amount),
        "Total_Partners": int(total_unique_partners),
        "Top_Partner": (top_row["partner_name"] if top_row is not None else None),
        "Top_Partner_Amount": (float(top_row["total_volume"]) if top_row is not None else 0.0),
    }
    return pd.DataFrame([summary_data])

# ---- Orchestrators ----
def parse_bca_statement(file_like) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Accepts io.BytesIO or file-like obj; returns
    personal_df, summary_df, trx_df, partner_trx_df, analytics_df
    """
    # read bytes
    file_like.seek(0)
    file_bytes = file_like.read()
    text = read_pdf_to_text(file_bytes)

    # Try 2025-like parsing first; if no transactions, fallback to CMS
    personal_info = extract_personal_info(text)
    trx_2025 = extract_transactions(text)
    if trx_2025:
        trx_df = pd.DataFrame(trx_2025)
        summary_df = pd.DataFrame()  # BCA variant may not have the same block; keep empty if not found
    else:
        personal_info = extract_cms_account_info(text)
        summary_df = pd.DataFrame([extract_cms_summary(text)])
        trx_df = pd.DataFrame(extract_cms_transactions(text))

    personal_df = pd.DataFrame([personal_info]) if personal_info else pd.DataFrame()

    # Partner analysis
    partner_df, partner_trx_df = (pd.DataFrame(), pd.DataFrame())
    analytics_df = pd.DataFrame()
    if not trx_df.empty:
        partner_df, partner_trx_df = analyze_partners(trx_df)
        analytics_df = create_partner_statistics_summary(partner_df)

    return personal_df, summary_df, trx_df, partner_trx_df, analytics_df

# =============================
# ---------------------- Streamlit App UI ----------------------
# =============================

st.set_page_config(page_title="BCA E-Statement Reader", layout="wide")
st.title("📄 BCA E-Statement Reader")

uploaded_pdf = st.file_uploader("Upload a BCA PDF e-statement", type="pdf")

if uploaded_pdf:
    st.success("✅ PDF uploaded. Processing...")

    # Read bytes once and reuse
    pdf_bytes = uploaded_pdf.read()

    personal_df, summary_df, trx_df, partner_trx_df, analytics_df = parse_bca_statement(io.BytesIO(pdf_bytes))

    # ✅ ADD DOWNLOAD SECTION
    st.markdown("---")
    st.subheader("📥 Download Complete Analysis")

    @st.cache_data
    def create_excel_download(personal_df, summary_df, trx_df, partner_trx_df, analytics_df):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            (personal_df if not personal_df.empty else pd.DataFrame()).to_excel(writer, sheet_name='Account Info', index=False)
            (summary_df if not summary_df.empty else pd.DataFrame()).to_excel(writer, sheet_name='Monthly Summary', index=False)
            (analytics_df if not analytics_df.empty else pd.DataFrame()).to_excel(writer, sheet_name='Analytics', index=False)
            (trx_df if not trx_df.empty else pd.DataFrame()).to_excel(writer, sheet_name='Transactions', index=False)
            (partner_trx_df if not partner_trx_df.empty else pd.DataFrame()).to_excel(writer, sheet_name='Partner Summary', index=False)
        output.seek(0)
        return output.getvalue()

    # Generate Excel file
    excel_data = create_excel_download(personal_df, summary_df, trx_df, partner_trx_df, analytics_df)

    # Compose filename period
    period_str = "Unknown"
    try:
        if not personal_df.empty and "Period" in personal_df.columns and pd.notna(personal_df.iloc[0]["Period"]):
            period_str = personal_df.iloc[0]["Period"]
        elif not personal_df.empty and "Start Period" in personal_df.columns and "End Period" in personal_df.columns:
            sp = personal_df.iloc[0].get("Start Period", None)
            ep = personal_df.iloc[0].get("End Period", None)
            if pd.notna(sp) and pd.notna(ep):
                period_str = f"{sp}-{ep}"
    except Exception:
        pass

    st.download_button(
        label="📊 Download Complete Analysis (Excel)",
        data=excel_data,
        file_name=f"BCA_Statement_Analysis_{period_str}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.markdown("---")

    # Tabs section
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📌 Account Info", "📊 Monthly Summary", "📈 Analytics", "💸 Transactions", "💳 Partner Transactions"])

    with tab1:
        st.dataframe(personal_df if not personal_df.empty else pd.DataFrame(), use_container_width=True)
    with tab2:
        st.dataframe(summary_df if not summary_df.empty else pd.DataFrame(), use_container_width=True)
    with tab3:
        st.dataframe(analytics_df if not analytics_df.empty else pd.DataFrame(), use_container_width=True)
    with tab4:
        st.dataframe(trx_df if not trx_df.empty else pd.DataFrame(), use_container_width=True)
    with tab5:
        st.dataframe(partner_trx_df if not partner_trx_df.empty else pd.DataFrame(), use_container_width=True)

else:
    st.info("Silakan upload satu file PDF e-statement BCA untuk diproses.")
'''

requirements = """streamlit==1.37.1
pandas>=2.0.0
pdfplumber>=0.11.0
XlsxWriter>=3.2.0
"""

Path("/mnt/data/app.py").write_text(app_code, encoding="utf-8")
Path("/mnt/data/requirements.txt").write_text(requirements, encoding="utf-8")

print("Updated files: /mnt/data/app.py and /mnt/data/requirements.txt")
