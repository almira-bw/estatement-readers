import io
import re
import pandas as pd
import pdfplumber
import streamlit as st

# =============================
# Utilities
# =============================

st.set_page_config(page_title="BRI E-Statement Reader", layout="wide")

@st.cache_data(show_spinner=False)
def read_pdf_to_text(file_bytes: bytes) -> str:
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\\n"
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

# =============================
# Parsers — CMS (older) format
# =============================

def extract_cms_account_info(text):
    account_info = {
        "Bank": "BRI",
        "Account Name": None,
        "Account Number": None,
        "Start Period": None,
        "End Period": None,
    }

    account_patterns = [
        r"Account\\s+No\\s*:?\\s*(\\d{4}-\\d{2}-\\d{6}-\\d{2}-\\d)",
        r"Account\\s+No\\s*:?\\s*(\\d+)",
        r"Account\\s+No\\s*\\n*\\s*:?\\s*(\\d{4}-\\d{2}-\\d{6}-\\d{2}-\\d)",
        r"Account\\s+No\\s*\\n*\\s*(\\d+)",
    ]
    for pattern in account_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            account_info["Account Number"] = m.group(1).strip()
            break

    name_patterns = [
        r"Account\\s+Name\\s*:?\\s*([A-Z][A-Z\\s&\\.]+?)(?=\\s*Today\\s*Hold|\\s*Period|\\s*Account\\s*Status)",
        r"Account\\s+Name\\s*\\n*\\s*:?\\s*([A-Z][A-Z\\s&\\.]+?)(?=\\s*Today|\\s*Period|\\s*Account\\s*Status)",
        r"Account\\s+Name\\s+([A-Z][A-Z\\s&\\.]+?)(?=\\s*Today|\\s*Period|\\s*Account\\s*Status)",
        r"Account\\s+Name\\s*:?\\s*(PT\\s+[A-Z\\s]+)",
        r"Account\\s+Name\\s*:?\\s*([A-Z][A-Z\\s&\\.PT]+)",
        r"Account\\s+Name\\s*:?\\s*([A-Z\\s&\\.PT]+?)(?=\\s*\\n|\\s*Today|\\s*Period|\\s*Account)",
    ]
    for pattern in name_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            account_info["Account Name"] = m.group(1).strip()
            break

    period_patterns = [
        r"Period\\s*:?\\s*(\\d{2}/\\d{2}/\\d{4})\\s*-\\s*(\\d{2}/\\d{2}/\\d{4})",
        r"Period\\s*\\n*\\s*:?\\s*(\\d{2}/\\d{2}/\\d{4})\\s*-\\s*(\\d{2}/\\d{2}/\\d{4})",
    ]
    for pattern in period_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            account_info["Start Period"] = m.group(1)
            account_info["End Period"] = m.group(2)
            break

    if not any(account_info.values()):
        lines = text.split("\\n")
        for i, line in enumerate(lines):
            line = line.strip()
            if "Account No" in line and ":" in line:
                parts = line.split(":")
                if len(parts) > 1:
                    account_info["Account Number"] = parts[1].strip()
            elif "Account Name" in line and ":" in line:
                parts = line.split(":")
                if len(parts) > 1:
                    account_info["Account Name"] = parts[1].strip()
                elif i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not any(k in next_line for k in ["Account", "Today", "Period"]):
                        account_info["Account Name"] = next_line
            elif "Period" in line and ":" in line:
                parts = line.split(":")
                if len(parts) > 1:
                    pm = re.search(r"(\\d{2}/\\d{2}/\\d{4})\\s*-\\s*(\\d{2}/\\d{2}/\\d{4})", parts[1])
                    if pm:
                        account_info["Start Period"] = pm.group(1)
                        account_info["End Period"] = pm.group(2)
    return account_info

def extract_cms_transactions(text):
    transactions = []
    lines = text.split("\\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\\d{2}/\\d{2}/\\d{2}\\s+\\d{2}:\\d{2}:\\d{2}", line):
            try:
                parts = line.split()
                if len(parts) >= 6:
                    numeric_parts = []
                    for i in range(len(parts) - 1, -1, -1):
                        part = parts[i]
                        if re.match(r"^[\\d,\\.]+$", part) or re.match(r"^\\d{7}$", part) or part in ["CMSPYRL", "BRI0372", "BRIMDBT"]:
                            numeric_parts.insert(0, part)
                            if len(numeric_parts) == 4:
                                break
                    if len(numeric_parts) >= 4:
                        debet_str = numeric_parts[0]
                        credit_str = numeric_parts[1]
                        ledger_str = numeric_parts[2]
                        # teller_id = numeric_parts[3]  # not used in output here
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
        r"OPENING\\s+BALANCE\\s+TOTAL\\s+DEBET\\s+TOTAL\\s+CREDIT\\s+CLOSING\\s+BALANCE\\s*\\n\\s*([\\d,\\.]+)\\s+([\\d,\\.]+)\\s+([\\d,\\.]+)\\s+([\\d,\\.]+)",
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

# =============================
# Parsers — 2025 e-statement
# =============================

def extract_personal_info(text):
    personal_info = {
        "Bank": "BRI",
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
        r"(?:Kepada\\s+Yth\\.\\s*/\\s*To\\s*:\\s*\\n\\s*[A-Z][A-Z\\s]*?\\n)\\s*(.*?)(?=\\n\\n|\\nNo\\.\\s*Rekening|\\nTanggal\\s+Laporan|\\nPeriode\\s+Transaksi|\\nNo\\s+Rekening)",
        r"Kepada\\s+Yth\\.\\s*/\\s*To\\s*:\\s*\\n\\s*([^\\n]+)(?:\\n([^\\n]*?))*?(?=\\n\\s*No\\.\\s*Rekening|\\n\\s*Tanggal\\s+Laporan|\\n\\s*Account\\s+No)",
        r"Kepada\\s+Yth\\.\\s*/\\s*To\\s*:\\s*\\n\\s*(.+?)(?=\\n\\s*No\\.\\s*Rekening)",
    ]
    for pattern in nama_patterns:
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            extracted_text = m.group(1).strip()
            lines = [ln.strip() for ln in extracted_text.split("\\n") if ln.strip()]
            if lines:
                personal_info["Account Name"] = lines[0]
                if len(lines) > 1:
                    alamat_lines = lines[1:]
                    alamat_filtered = []
                    for ln in alamat_lines:
                        if not re.match(r"\\d{2}/\\d{2}/\\d{2,4}", ln) and "Periode" not in ln:
                            alamat_filtered.append(ln)
                    if alamat_filtered:
                        alamat_cleaned = " ".join(alamat_filtered)
                        personal_info["Address"] = re.sub(r"\\s+", " ", alamat_cleaned)
            break

    if not personal_info.get("Account Name"):
        sm = re.search(r"Kepada\\s+Yth\\.\\s*/\\s*To\\s*:\\s*\\n\\s*([A-Z][A-Z\\s]+)", text, re.IGNORECASE)
        if sm:
            personal_info["Account Name"] = sm.group(1).strip()

    tanggal_patterns = [
        r"Tanggal\\s+Laporan\\s*[:\\s]*(\\d{2}/\\d{2}/\\d{2,4})",
        r"Statement\\s+Date\\s*[:\\s]*(\\d{2}/\\d{2}/\\d{2,4})",
    ]
    for pattern in tanggal_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            personal_info["Report Date"] = m.group(1)
            break

    periode_patterns = [
        r"Periode\\s+Transaksi\\s*[:\\s]*(\\d{2}/\\d{2}/\\d{2,4})\\s*-\\s*(\\d{2}/\\d{2}/\\d{2,4})",
        r"Transaction\\s+Period\\s*[:\\s]*(\\d{2}/\\d{2}/\\d{2,4})\\s*-\\s*(\\d{2}/\\d{2}/\\d{2,4})",
    ]
    for pattern in periode_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            personal_info["Start Period"] = m.group(1)
            personal_info["End Period"] = m.group(2)
            break

    rekening_patterns = [
        r"No\\.\\s*Rekening\\s*\\n*Account\\s*No\\s*[,:]*\\s*(\\d+)",
        r"No\\.\\s*Rekening\\s*[:\\s]*(\\d+)",
        r"Account\\s*No\\s*[:\\s]*(\\d+)",
    ]
    for pattern in rekening_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            personal_info["Account Number"] = m.group(1)
            break

    produk_patterns = [r"(?:Nama\\s+Produk|Product\\s+Name)\\s*[,:]*\\s*(.*?)(?=\\s*(?:Unit\\s*Kerja|Business\\s*Unit|Valuta|Currency|Alamat\\s*Unit\\s*Kerja|\\n|$))"]
    for pattern in produk_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            personal_info["Product Name"] = m.group(1).strip()
            break

    valuta_patterns = [
        r"Valuta\\s*\\n*Currency\\s*[,:]*\\s*([A-Z]+)",
        r"Valuta\\s*[:\\s]*([A-Z]+)",
        r"Currency\\s*[:\\s]*([A-Z]+)",
    ]
    for pattern in valuta_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            personal_info["Currency"] = m.group(1).strip()
            break

    unit_patterns = [
        r"Unit\\s+Kerja\\s*\\n*Business\\s+Unit\\s*[,:]*\\s*([A-Z][A-Z\\s]*?)(?=\\s*(?:Alamat\\s+Unit|Business\\s+Unit\\s+Address|\\n|$))",
        r"Unit\\s+Kerja\\s*[:\\s]*([A-Z][A-Z\\s]*?)(?=\\s*(?:Alamat\\s+Unit|Business\\s+Unit\\s+Address|\\n|$))",
        r"Business\\s+Unit\\s*[:\\s]*([A-Z][A-Z\\s]*?)(?=\\s*(?:Alamat\\s+Unit|Business\\s+Unit\\s+Address|\\n|$))",
    ]
    for pattern in unit_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            personal_info["Branch"] = m.group(1).strip()
            break

    alamat_unit_kerja_patterns = [
        r"(?:Alamat\\s+Unit\\s+Kerja|Business\\s+Unit\\s+Address)\\s*[,:]*\\s*\\n\\s*([A-Z][A-Z\\s]*?)\\n\\s*([A-Z][A-Z\\s]*?)(?=\\n|$)",
        r"(?:Alamat\\s+Unit\\s+Kerja|Business\\s+Unit\\s+Address)\\s*[,:]*\\s*([A-Z][A-Z\\s]*?)\\n\\s*([A-Z][A-Z\\s]*?)(?=\\n|$)",
        r"(?:Alamat\\s+Unit\\s+Kerja|Business\\s+Unit\\s+Address)\\s*[,:]*\\s*([A-Z][A-Z\\s]*?)(?=\\n|$)",
    ]
    for pattern in alamat_unit_kerja_patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            if len(m.groups()) >= 2:
                alamat_temp = f"{m.group(1).strip()} {m.group(2).strip()}"
            else:
                alamat_temp = m.group(1).strip()
            alamat_temp = re.sub(r"Product\\s+Name\\s*Business\\s*Unit\\s*Address ", "", alamat_temp, flags=re.IGNORECASE).strip()
            personal_info["Business Unit Address"] = alamat_temp
            break

    financial_summary = {}
    try:
        balance_summary_pattern = re.compile(
            r"(?:Saldo Awal|Opening Balance)\\s*\\n?"
            r"(?:Opening Balance)?\\s*\\n?"
            r"(?:Total Transaksi Debet|Total Debit Transaction)\\s*\\n?"
            r"(?:Total Debit Transaction)?\\s*\\n?"
            r"(?:Total Transaksi Kredit|Total Credit Transaction)\\s*\\n?"
            r"(?:Total Credit Transaction)?\\s*\\n?"
            r"(?:Saldo Akhir|Closing Balance)\\s*\\n?"
            r"(?:Closing Balance)?\\s*\\n?"
            r"([\\d,\\.]+\\s+[\\d,\\.]+\\s+[\\d,\\.]+\\s+[\\d,\\.]+)",
            re.IGNORECASE | re.DOTALL,
        )
        fm = balance_summary_pattern.search(text)
        if fm:
            amounts_line = fm.group(1).strip()
            amounts = amounts_line.split()

            def parse_amount(amount_str):
                try:
                    s = amount_str.strip()
                    if "," in s and s.rfind(",") > s.rfind("."):
                        s = s.replace(".", "").replace(",", ".")
                    elif "," in s:
                        s = s.replace(",", "")
                    elif s.count(".") > 1:
                        parts = s.rsplit(".", 1)
                        integer_part = parts[0].replace(".", "")
                        decimal_part = parts[1] if len(parts) > 1 else ""
                        s = f"{integer_part}.{decimal_part}" if decimal_part else integer_part
                    return float(s)
                except Exception:
                    return 0.0

            if len(amounts) >= 4:
                financial_summary["opening_balance"] = parse_amount(amounts[0])
                financial_summary["total_debit_transaction"] = parse_amount(amounts[1])
                financial_summary["total_credit_transaction"] = parse_amount(amounts[2])
                financial_summary["closing_balance"] = parse_amount(amounts[3])
    except Exception as e:
        st.warning(f"Error extracting financial summary: {e}")

    return personal_info, financial_summary

def extract_transactions(text: str):
    transactions = []
    lines = text.split("\\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if re.match(r"^\\d{2}/\\d{2}/\\d{2}\\s+\\d{2}:\\d{2}:\\d{2}", line):
            parts = line.split()
            if len(parts) >= 7:
                try:
                    numeric_parts = []
                    for i in range(len(parts) - 1, -1, -1):
                        if re.match(r"^[\\d,\\.]+$", parts[i]) or re.match(r"^\\d{7}$", parts[i]):
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

# =============================
# Partner detection & analytics
# =============================

def extract_partner_name_bri(description: str):
    if description is None or (isinstance(description, float) and pd.isna(description)):
        return None
    skip_keywords = [
        "BIAYA", "ADM", "BUNGA", "PAJAK", "KLIRING", "TARIK TUNAI",
        "SETORAN", "BI-FAST", "BPJS", "TAX", "INTEREST",
        "FEE", "SINGLE CN", "POLLING", "REWARD", "CLAIM", "BPJS TK", "BPJS KESEHATAN"
    ]
    if any(k in str(description).upper() for k in skip_keywords):
        return None
    cleaned = str(description).strip()
    if re.search(r"BM\\d+", cleaned):
        lines = [ln.strip() for ln in cleaned.split("\\n") if ln.strip()]
        company_words = []
        esb_found = False
        for ln in lines:
            if ln.startswith("ESB:"):
                esb_found = True
                continue
            if re.match(r"^BM\\d+\\s+\\d+\\s+\\d+", ln):
                bm_match = re.search(r"BM\\d+\\s+\\d+\\s+\\d+\\s+(.+)", ln)
                if bm_match:
                    company_part = bm_match.group(1).strip()
                    words = [w for w in company_part.split() if w.isalpha() and len(w) >= 2]
                    company_words.extend(words)
            else:
                if not esb_found:
                    words = [w for w in ln.split() if w.isalpha() and len(w) >= 2]
                    company_words.extend(words)
        if company_words:
            return " ".join(company_words)
    if "NBMB" in cleaned.upper():
        nbmb_pattern = r"NBMB\\s+(.*?)\\s+TO\\s+(.*?)(?:\\n|ESB:|$)"
        m = re.search(nbmb_pattern, cleaned, re.IGNORECASE | re.DOTALL)
        if m:
            receiver = m.group(2).strip()
            sender = m.group(1).strip()
            return receiver if receiver else sender
    elif "WBNKTRF" in cleaned.upper():
        after = re.sub(r"WBNKTRF\\w+", "", cleaned, flags=re.IGNORECASE)
        after = re.sub(r"ESB:.*", "", after, flags=re.DOTALL)
        words = [w for w in after.split() if w.isalpha() and len(w) >= 2]
        if words:
            return " ".join(words)
    elif "BFST" in cleaned.upper():
        content = re.sub(r"BFST\\d+", "", cleaned, flags=re.IGNORECASE)
        content = re.sub(r"ESB:.*", "", content, flags=re.DOTALL)
        content = re.sub(r"\\d{8,}", "", content)
        if ":" in content:
            names = content.split(":")
            for name in names:
                clean_name = "".join(c for c in name if c.isalpha() or c.isspace()).strip()
                if clean_name and len(clean_name) >= 3:
                    return clean_name
        else:
            words = [w for w in content.split() if w.isalpha() and len(w) >= 2]
            if words:
                return " ".join(words)
    elif any(bank in cleaned.upper() for bank in ["BCA", "BNI", "MANDIRI", "DANAMON"]):
        bank_pattern = r"(.*?)(?:-BANK|-BCA|-BNI|-MANDIRI|-DANAMON)"
        m = re.search(bank_pattern, cleaned, re.IGNORECASE | re.DOTALL)
        if m:
            company_part = re.sub(r"^(PT\\s+)?", "", m.group(1).strip(), flags=re.IGNORECASE)
            words = [w for w in company_part.split() if w.isalpha() and len(w) >= 2]
            if words:
                return " ".join(words)
    elif "IBIZ" in cleaned.upper():
        if " TO " in cleaned.upper():
            parts = cleaned.split(" TO ")
            if len(parts) > 1:
                receiver_part = parts[1].split("ESB:")[0].strip()
                words = [w for w in receiver_part.split() if w.isalpha() and len(w) >= 2]
                if words:
                    return " ".join(words[:4])
    elif "PAYROLL" in cleaned.upper():
        return "PAYROLL"
    elif "SETOR" in cleaned.upper() and "PENJUALAN" in cleaned.upper():
        return "PENJUALAN INTERNAL"
    else:
        general_clean = re.sub(r"ESB:.*", "", cleaned, flags=re.DOTALL)
        general_clean = re.sub(r"\\b\\d{7,}\\b", "", general_clean)
        general_clean = re.sub(r"\\b[A-Z]{2,}\\d+[A-Z]*\\b", "", general_clean)
        words = [w for w in general_clean.split() if w.isalpha() and len(w) >= 2]
        filtered = [w for w in words if w.upper() not in ["THE", "AND", "OR", "TO", "FROM", "FOR", "WITH"]]
        if len(filtered) >= 2:
            return " ".join(filtered[:4])
    return None

def detect_bri_format(df: pd.DataFrame) -> str:
    if "Remark" in df.columns:
        return "CMS"
    elif "deskripsi" in df.columns:
        return "E_STATEMENT"
    else:
        return "UNKNOWN"

def analyze_bri_partners_unified(transactions_df: pd.DataFrame):
    if transactions_df.empty:
        return transactions_df, pd.DataFrame()
    fmt = detect_bri_format(transactions_df)
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
            "Credit_Count": credit_count,
            "Debit_Count": debit_count,
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

# =============================
# Orchestrator
# =============================

def parse_bri_statement(file_bytes: bytes, filename: str):
    text = read_pdf_to_text(file_bytes)

    # Try 2025 e-statement first; if empty, fall back to CMS
    personal_info, summary_info = extract_personal_info(text)
    trx_2025 = extract_transactions(text)
    if not trx_2025:
        # fallback to CMS
        personal_info = extract_cms_account_info(text)
        summary_info = extract_cms_summary(text)
        trx_df = pd.DataFrame(extract_cms_transactions(text))
    else:
        trx_df = pd.DataFrame(trx_2025)

    partner_df, partner_trx_df = (pd.DataFrame(), pd.DataFrame())
    analytics_df = pd.DataFrame()
    if not trx_df.empty:
        partner_df, partner_trx_df = analyze_bri_partners_unified(trx_df)
        analytics_df = create_partner_statistics_summary(partner_df)
    personal_df = pd.DataFrame([personal_info])
    summary_df = pd.DataFrame([summary_info]) if summary_info else pd.DataFrame()
    return personal_df, summary_df, trx_df, partner_trx_df, analytics_df

def df_download_button(df: pd.DataFrame, label: str, filename: str):
    if df is not None and not df.empty:
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(label=label, data=csv, file_name=filename, mime="text/csv")
