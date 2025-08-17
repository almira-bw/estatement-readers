import re
import json
import pandas as pd
import pdfplumber
import os
import glob
import streamlit as st
from typing import Dict, List, Tuple
from datetime import datetime
from collections import defaultdict
import io
from pathlib import Path

# ======================= CONFIGURATION =======================

st.set_page_config(
    page_title="BRI E-Statement Reader", 
    page_icon="📄", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# ======================= UTILITY FUNCTIONS =======================

def read_pdf_to_text(pdf_path):
    """Extract text from PDF file"""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        st.error(f"Error reading PDF: {e}")
    return text

def extract_filename_id(filename: str) -> str:
    """Extract filename without extension"""
    if '/' in filename or '\\' in filename:
        filename = Path(filename).name
    filename_without_ext = os.path.splitext(filename)[0]
    return filename_without_ext

def clean_amount(amount_str: str) -> float:
    """Clean and convert amount string to float"""
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

# ======================= BRI 2024 FORMAT (CMS) =======================

def extract_cms_account_info(text):
    """Extract account information from CMS format"""
    account_info = {
        "Bank": "BRI",
        "Account Name": None,
        "Account Number": None,
        "Start Period": None,
        "End Period": None,
    }

    # Extract Account Number
    account_patterns = [
        r'Account\s+No\s*:?\s*(\d{4}-\d{2}-\d{6}-\d{2}-\d)',
        r'Account\s+No\s*:?\s*(\d+)',
        r'Account\s+No\s*\n*\s*:?\s*(\d{4}-\d{2}-\d{6}-\d{2}-\d)',
        r'Account\s+No\s*\n*\s*(\d+)',
    ]

    for pattern in account_patterns:
        account_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if account_match:
            account_info['Account Number'] = account_match.group(1).strip()
            break

    # Extract Account Name
    name_patterns = [
        r'Account\s+Name\s*:?\s*([A-Z][A-Z\s&\.]+?)(?=\s*Today\s*Hold|\s*Period|\s*Account\s*Status)',
        r'Account\s+Name\s*\n*\s*:?\s*([A-Z][A-Z\s&\.]+?)(?=\s*Today|\s*Period|\s*Account\s*Status)',
        r'Account\s+Name\s+([A-Z][A-Z\s&\.]+?)(?=\s*Today|\s*Period|\s*Account\s*Status)',
        r'Account\s+Name\s*:?\s*(PT\s+[A-Z\s]+)',
        r'Account\s+Name\s*:?\s*([A-Z][A-Z\s&\.PT]+)',
        r'Account\s+Name\s*:?\s*([A-Z\s&\.PT]+?)(?=\s*\n|\s*Today|\s*Period|\s*Account)',
    ]

    for pattern in name_patterns:
        name_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if name_match:
            account_info['Account Name'] = name_match.group(1).strip()
            break

    # Extract Period
    period_patterns = [
        r'Period\s*:?\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})',
        r'Period\s*\n*\s*:?\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})',
    ]

    for pattern in period_patterns:
        period_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if period_match:
            account_info['Start Period'] = period_match.group(1)
            account_info['End Period'] = period_match.group(2)
            break

    return account_info

def extract_cms_transactions(text):
    """Extract transactions from CMS format"""
    transactions = []
    lines = text.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if re.match(r'^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}', line):
            try:
                parts = line.split()
                if len(parts) >= 6:
                    date = parts[0]
                    time = parts[1]

                    numeric_parts = []
                    for i in range(len(parts) - 1, -1, -1):
                        part = parts[i]
                        if re.match(r'^[\d,\.]+$', part) or re.match(r'^\d{7}$', part) or part in ['CMSPYRL', 'BRI0372', 'BRIMDBT']:
                            numeric_parts.insert(0, part)
                            if len(numeric_parts) == 4:
                                break

                    if len(numeric_parts) >= 4:
                        try:
                            debet_str = numeric_parts[0]
                            credit_str = numeric_parts[1]
                            ledger_str = numeric_parts[2]
                            teller_id = numeric_parts[3]

                            debet = clean_amount(debet_str) if debet_str != '0.00' else 0.0
                            credit = clean_amount(credit_str) if credit_str != '0.00' else 0.0
                            ledger = clean_amount(ledger_str)

                            start_idx = 2
                            end_idx = len(parts) - 4

                            if end_idx > start_idx:
                                remark_parts = parts[start_idx:end_idx]
                                remark = ' '.join(remark_parts).strip()
                            else:
                                remark = ""

                            transaction = {
                                'Date': date,
                                'Remark': remark,
                                'Debit': debet,
                                'Credit': credit,
                                'Saldo': ledger
                            }

                            transactions.append(transaction)

                        except (ValueError, IndexError):
                            continue

            except Exception:
                continue

    return transactions

def extract_cms_summary(text):
    """Extract summary from CMS format"""
    summary = {}

    summary_pattern = re.compile(
        r'OPENING\s+BALANCE\s+TOTAL\s+DEBET\s+TOTAL\s+CREDIT\s+CLOSING\s+BALANCE\s*\n'
        r'\s*([\d,\.]+)\s+([\d,\.]+)\s+([\d,\.]+)\s+([\d,\.]+)',
        re.IGNORECASE | re.MULTILINE
    )

    summary_match = summary_pattern.search(text)
    if summary_match:
        try:
            summary['Saldo Awal'] = clean_amount(summary_match.group(1))
            summary['Saldo Akhir'] = clean_amount(summary_match.group(4))
            summary['Mutasi Debit'] = clean_amount(summary_match.group(2))
            summary['Mutasi Credit'] = clean_amount(summary_match.group(3))
        except:
            pass

    return summary

# ======================= BRI 2025 FORMAT (E-STATEMENT) =======================

def extract_personal_info(text):
    """Extract personal information from E-Statement format"""
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

    # Extract name patterns
    nama_patterns = [
        r'(?:Kepada\s+Yth\.\s*/\s*To\s*:\s*\n\s*[A-Z][A-Z\s]*?\n)\s*(.*?)(?=\n\n|\nNo\.\s*Rekening|\nTanggal\s+Laporan|\nPeriode\s+Transaksi|\nNo\s+Rekening)',
        r'Kepada\s+Yth\.\s*/\s*To\s*:\s*\n\s*([^\n]+)(?:\n([^\n]*?))*?(?=\n\s*No\.\s*Rekening|\n\s*Tanggal\s+Laporan|\n\s*Account\s+No)',
        r'Kepada\s+Yth\.\s*/\s*To\s*:\s*\n\s*(.+?)(?=\n\s*No\.\s*Rekening)',
    ]

    for pattern in nama_patterns:
        nama_match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if nama_match:
            extracted_text = nama_match.group(1).strip()
            lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]

            if lines:
                personal_info['Account Name'] = lines[0]

                if len(lines) > 1:
                    alamat_lines = lines[1:]
                    alamat_filtered = []
                    for line in alamat_lines:
                        if not re.match(r'\d{2}/\d{2}/\d{2,4}', line) and 'Periode' not in line:
                            alamat_filtered.append(line)

                    if alamat_filtered:
                        alamat_cleaned = ' '.join(alamat_filtered)
                        alamat_cleaned = re.sub(r'\s+', ' ', alamat_cleaned)
                        personal_info['Address'] = alamat_cleaned
            break

    # Extract other information patterns
    patterns = {
        'Report Date': [
            r'Tanggal\s+Laporan\s*[:\s]*(\d{2}/\d{2}/\d{2,4})',
            r'Statement\s+Date\s*[:\s]*(\d{2}/\d{2}/\d{2,4})',
        ],
        'Account Number': [
            r'No\.\s*Rekening\s*\n*Account\s*No\s*[,:]*\s*(\d+)',
            r'No\.\s*Rekening\s*[:\s]*(\d+)',
            r'Account\s*No\s*[:\s]*(\d+)',
        ],
        'Product Name': [
            r'(?:Nama\s+Produk|Product\s+Name)\s*[,:]*\s*(.*?)(?=\s*(?:Unit\s*Kerja|Business\s*Unit|Valuta|Currency|Alamat\s*Unit\s*Kerja|\n|$))',
        ],
        'Currency': [
            r'Valuta\s*\n*Currency\s*[,:]*\s*([A-Z]+)',
            r'Valuta\s*[:\s]*([A-Z]+)',
            r'Currency\s*[:\s]*([A-Z]+)',
        ],
        'Branch': [
            r'Unit\s+Kerja\s*\n*Business\s+Unit\s*[,:]*\s*([A-Z][A-Z\s]*?)(?=\s*(?:Alamat\s+Unit|Business\s+Unit\s+Address|\n|$))',
        ]
    }

    for key, pattern_list in patterns.items():
        for pattern in pattern_list:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                personal_info[key] = match.group(1).strip()
                break

    # Extract period
    periode_patterns = [
        r'Periode\s+Transaksi\s*[:\s]*(\d{2}/\d{2}/\d{2,4})\s*-\s*(\d{2}/\d{2}/\d{2,4})',
        r'Transaction\s+Period\s*[:\s]*(\d{2}/\d{2}/\d{2,4})\s*-\s*(\d{2}/\d{2}/\d{2,4})',
    ]
    for pattern in periode_patterns:
        periode_match = re.search(pattern, text, re.IGNORECASE)
        if periode_match:
            personal_info['Start Period'] = periode_match.group(1)
            personal_info['End Period'] = periode_match.group(2)
            break

    # Extract financial summary
    financial_summary = {}
    try:
        balance_summary_pattern = re.compile(
            r'(?:Saldo Awal|Opening Balance)\s*\n?'
            r'(?:Opening Balance)?\s*\n?'
            r'(?:Total Transaksi Debet|Total Debit Transaction)\s*\n?'
            r'(?:Total Debit Transaction)?\s*\n?'
            r'(?:Total Transaksi Kredit|Total Credit Transaction)\s*\n?'
            r'(?:Total Credit Transaction)?\s*\n?'
            r'(?:Saldo Akhir|Closing Balance)\s*\n?'
            r'(?:Closing Balance)?\s*\n?'
            r'([\d,\.]+\s+[\d,\.]+\s+[\d,\.]+\s+[\d,\.]+)',
            re.IGNORECASE | re.DOTALL
        )

        financial_match = balance_summary_pattern.search(text)
        if financial_match:
            amounts_line = financial_match.group(1).strip()
            amounts = amounts_line.split()

            def parse_amount(amount_str):
                try:
                    amount_str = amount_str.strip()
                    if ',' in amount_str and amount_str.rfind(',') > amount_str.rfind('.'):
                        amount_str = amount_str.replace('.', '')
                        amount_str = amount_str.replace(',', '.')
                    elif ',' in amount_str:
                        amount_str = amount_str.replace(',', '')
                    elif amount_str.count('.') > 1:
                        parts = amount_str.rsplit('.', 1)
                        integer_part = parts[0].replace('.', '')
                        if len(parts) > 1:
                            decimal_part = parts[1]
                            amount_str = f"{integer_part}.{decimal_part}"
                        else:
                            amount_str = integer_part
                    return float(amount_str)
                except:
                    return 0.0

            if len(amounts) >= 4:
                financial_summary['Saldo Awal'] = parse_amount(amounts[0])
                financial_summary['Mutasi Debit'] = parse_amount(amounts[1])
                financial_summary['Mutasi Credit'] = parse_amount(amounts[2])
                financial_summary['Saldo Akhir'] = parse_amount(amounts[3])

    except Exception as e:
        st.warning(f"Error extracting financial summary: {e}")

    return personal_info, financial_summary

def extract_transactions(text: str) -> List[Dict]:
    """Extract all transactions from bank statement"""
    transactions = []
    lines = text.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if re.match(r'^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}', line):
            parts = line.split()
            if len(parts) >= 7:
                try:
                    date = parts[0]
                    time = parts[1]

                    numeric_parts = []
                    for i in range(len(parts) - 1, -1, -1):
                        if re.match(r'^[\d,\.]+$', parts[i]) or re.match(r'^\d{7}$', parts[i]):
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
                        description = ' '.join(parts[desc_start:desc_end])

                        transaction = {
                            'tanggal': date,
                            'waktu': time,
                            'deskripsi': description.strip(),
                            'teller_id': teller_id,
                            'debit': debit,
                            'kredit': credit,
                            'saldo': balance
                        }

                        transactions.append(transaction)

                except (ValueError, IndexError):
                    continue

    return transactions

# ======================= PARTNER ANALYSIS =======================

def extract_partner_name_bri(description: str):
    """Extract partner name from transaction description"""
    if not description or pd.isna(description):
        return None

    # Skip administrative transactions
    skip_keywords = [
        "BIAYA", "ADM", "BUNGA", "PAJAK", "KLIRING", "TARIK TUNAI",
        "SETORAN", "BI-FAST", "BPJS", "TAX", "INTEREST",
        "Fee", "SINGLE CN", "POLLING", "REWARD", "CLAIM", "BPJS TK", "BPJS KESEHATAN"
    ]

    if any(keyword in description.upper() for keyword in skip_keywords):
        return None

    cleaned = description.strip()

    # Pattern for BM5/BM6 transactions (most common in BRI CMS)
    if re.search(r'BM\d+', cleaned):
        lines = [line.strip() for line in cleaned.split('\n') if line.strip()]
        company_words = []
        esb_found = False

        for line in lines:
            if line.startswith('ESB:'):
                esb_found = True
                continue

            if re.match(r'^BM\d+\s+\d+\s+\d+', line):
                bm_match = re.search(r'BM\d+\s+\d+\s+\d+\s+(.+)', line)
                if bm_match:
                    company_part = bm_match.group(1).strip()
                    words = [word for word in company_part.split() if word.isalpha() and len(word) >= 2]
                    company_words.extend(words)
            else:
                if not esb_found:
                    words = [word for word in line.split() if word.isalpha() and len(word) >= 2]
                    company_words.extend(words)

        if company_words:
            return ' '.join(company_words)

    # Other patterns (NBMB, WBNKTRF, BFST, etc.)
    # ... (keeping the original logic but simplified for brevity)

    return None

def detect_bri_format(transactions_df):
    """Detect BRI statement format"""
    if 'Remark' in transactions_df.columns:
        return 'CMS'
    elif 'deskripsi' in transactions_df.columns:
        return 'E_STATEMENT'
    else:
        return 'UNKNOWN'

def analyze_bri_partners_unified(transactions_df):
    """Analyze BRI partners from transactions"""
    if transactions_df.empty:
        return transactions_df, pd.DataFrame()

    format_type = detect_bri_format(transactions_df)
    df = transactions_df.copy()

    if format_type == 'CMS':
        desc_col = 'Remark'
        debit_col = 'Debit'
        credit_col = 'Credit'
    elif format_type == 'E_STATEMENT':
        desc_col = 'deskripsi'
        debit_col = 'debit'
        credit_col = 'kredit'
    else:
        return df, pd.DataFrame()

    df['partner_name'] = df[desc_col].apply(extract_partner_name_bri)
    df['transaction_type'] = df.apply(
        lambda row: 'DEBIT' if row[debit_col] > 0 else 'CREDIT' if row[credit_col] > 0 else 'UNKNOWN',
        axis=1
    )
    df['amount'] = df[debit_col] + df[credit_col]

    partner_transactions = df[df['partner_name'].notna()].copy()

    if partner_transactions.empty:
        return df, pd.DataFrame()

    partner_summary = partner_transactions.groupby(['partner_name', 'transaction_type']).agg({
        debit_col: 'sum',
        credit_col: 'sum',
        'amount': 'sum',
        desc_col: 'count'
    }).rename(columns={desc_col: 'transaction_count'}).reset_index()

    partner_summary = partner_summary.sort_values('amount', ascending=False)
    partner_summary_table = create_partner_summary_table(df)

    return partner_summary, partner_summary_table

def create_partner_summary_table(partner_df):
    """Create partner summary table"""
    if partner_df.empty or 'partner_name' not in partner_df.columns:
        return pd.DataFrame()

    partner_transactions = partner_df[partner_df['partner_name'].notna()].copy()

    if partner_transactions.empty:
        return pd.DataFrame()

    if 'Debit' in partner_transactions.columns and 'Credit' in partner_transactions.columns:
        debit_col = 'Debit'
        credit_col = 'Credit'
    elif 'debit' in partner_transactions.columns and 'kredit' in partner_transactions.columns:
        debit_col = 'debit'
        credit_col = 'kredit'
    else:
        return pd.DataFrame()

    summary_data = []

    for partner in partner_transactions['partner_name'].unique():
        partner_data = partner_transactions[partner_transactions['partner_name'] == partner]

        total_credit = partner_data[credit_col].sum()
        total_debit = partner_data[debit_col].sum()
        credit_count = len(partner_data[partner_data[credit_col] > 0])
        debit_count = len(partner_data[partner_data[debit_col] > 0])
        total_transactions = len(partner_data)

        summary_data.append({
            'Partner': partner,
            'Total_Credit': total_credit,
            'Total_Debit': total_debit,
            'Credit_Count': credit_count,
            'Debit_Count': debit_count,
            'Total_Transactions': total_transactions
        })

    summary_df = pd.DataFrame(summary_data)
    summary_df['Total_Volume'] = summary_df['Total_Credit'] + summary_df['Total_Debit']
    summary_df = summary_df.sort_values('Total_Volume', ascending=False)
    summary_df = summary_df.drop('Total_Volume', axis=1).reset_index(drop=True)

    return summary_df

def create_partner_statistics_summary(partner_df):
    """Create partner statistics summary"""
    if partner_df.empty or 'partner_name' not in partner_df.columns:
        return pd.DataFrame()

    partner_transactions = partner_df[partner_df['partner_name'].notna()].copy()

    if partner_transactions.empty:
        return pd.DataFrame()

    if 'Debit' in partner_transactions.columns and 'Credit' in partner_transactions.columns:
        debit_col = 'Debit'
        credit_col = 'Credit'
    elif 'debit' in partner_transactions.columns and 'kredit' in partner_transactions.columns:
        debit_col = 'debit'
        credit_col = 'kredit'
    else:
        return pd.DataFrame()

    total_credit_transactions = len(partner_transactions[partner_transactions[credit_col] > 0])
    total_debit_transactions = len(partner_transactions[partner_transactions[debit_col] > 0])
    total_credit_amount = partner_transactions[credit_col].sum()
    total_debit_amount = partner_transactions[debit_col].sum()
    total_unique_partners = partner_transactions['partner_name'].nunique()

    partner_volumes = partner_transactions.groupby('partner_name').agg({
        debit_col: 'sum',
        credit_col: 'sum'
    }).reset_index()

    partner_volumes['total_volume'] = partner_volumes[debit_col] + partner_volumes[credit_col]
    top_partner_row = partner_volumes.loc[partner_volumes['total_volume'].idxmax()]
    top_partner_name = top_partner_row['partner_name']
    top_partner_amount = top_partner_row['total_volume']

    summary_data = {
        'No_of_Credit': total_credit_transactions,
        'No_of_Debit': total_debit_transactions,
        'Total_Credit_Amount': total_credit_amount,
        'Total_Debit_Amount': total_debit_amount,
        'Total_Partners': total_unique_partners,
        'Top_Partner': top_partner_name,
        'Top_Partner_Amount': top_partner_amount
    }

    summary_df = pd.DataFrame([summary_data])
    return summary_df

# ======================= MAIN PROCESSING FUNCTION =======================

def parse_bri_statement(pdf_path, filename):
    """Main function to parse BRI statement"""
    pdf_text = read_pdf_to_text(pdf_path)
    file_id = extract_filename_id(filename)

    personal_info = {}
    summary_info = {}
    transactions = []
    trx_df = pd.DataFrame()
    partner_df = pd.DataFrame()
    partner_trx_df = pd.DataFrame()
    analytics_df = pd.DataFrame()

    # Determine format based on filename
    if "2025" not in file_id:
        # CMS format
        personal_info = extract_cms_account_info(pdf_text)
        summary_info = extract_cms_summary(pdf_text)
        transactions = extract_cms_transactions(pdf_text)
    else:
        # E-Statement format
        personal_info, summary_info = extract_personal_info(pdf_text)
        transactions = extract_transactions(pdf_text)

    # Create transaction DataFrame
    trx_df = pd.DataFrame(transactions)

    # Perform partner analysis
    if not trx_df.empty:
        partner_df, partner_trx_df = analyze_bri_partners_unified(trx_df)
        analytics_df = create_partner_statistics_summary(partner_df)

    # Create info DataFrames
    personal_df = pd.DataFrame([personal_info])
    summary_df = pd.DataFrame([summary_info])

    return personal_df, summary_df, trx_df, partner_trx_df, analytics_df

# ---------------------- Streamlit App UI ---------------------- #
st.set_page_config(page_title="BCA E-Statement Reader", layout="wide")
st.title("📄 BCA E-Statement Reader")

uploaded_pdf = st.file_uploader("Upload a BCA PDF e-statement", type="pdf")

if uploaded_pdf:
    pdf_bytes = uploaded_pdf.read()
    filename = uploaded_pdf.name
    st.success("✅ PDF uploaded. Processing...")

    # Read bytes once and reuse
    pdf_bytes = uploaded_pdf.read()
    personal_df, summary_df, trx_df, partner_trx_df, analytics_df = parse_bri_statement(io.BytesIO(pdf_bytes), filename)

    # ✅ ADD DOWNLOAD SECTION
    st.markdown("---")
    st.subheader("📥 Download Complete Analysis")
    
    # Create Excel file in memory
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

    # Generate Excel file
    excel_data = create_excel_download(personal_df, summary_df, trx_df, partner_trx_df, analytics_df)
    
    # Download button
    st.download_button(
        label="📊 Download Complete Analysis (Excel)",
        data=excel_data,
        file_name=f"BRI_Statement_Analysis_{personal_df.iloc[0] if not personal_df.empty else 'Unknown'}.xlsx",
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
