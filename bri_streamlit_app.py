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

# General functions

# Genetal Functions

def read_pdf_to_text(pdf_path):
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {e}")
    return text

def extract_filename_id(filename: str) -> str:
    if '/' in filename or '\\' in filename:
        filename = Path(filename).name
    filename_without_ext = os.path.splitext(filename)[0]

    return filename_without_ext

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

# BRI 2024 Format

def extract_cms_account_info(text):
    lines = clean_statement_lines(text)
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

    if not account_info:
        lines = text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()

            if 'Account No' in line and ':' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    account_info['Account Number'] = parts[1].strip()

            elif 'Account Name' in line and ':' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    account_info['Account Name'] = parts[1].strip()
                elif 'Account Name' in line and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not any(keyword in next_line for keyword in ['Account', 'Today', 'Period']):
                        account_info['Account Name'] = next_line

            elif 'Period' in line and ':' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    period_text = parts[1].strip()
                    period_match = re.search(r'(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})', period_text)
                    if period_match:
                        account_info['Start Period'] = period_match.group(1)
                        account_info['End Period'] = period_match.group(2)

    return account_info

def extract_cms_transactions(text):
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

                            # Parse amounts
                            debet = clean_amount(debet_str) if debet_str != '0.00' else 0.0
                            credit = clean_amount(credit_str) if credit_str != '0.00' else 0.0
                            ledger = clean_amount(ledger_str)

                            # Extract remark (description)
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

                        except (ValueError, IndexError) as e:
                            continue

            except Exception as e:
                continue

    return transactions

def extract_cms_summary(text):
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

# BRI 2025 Format
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

    # Ekstrak nama - dengan multiple patterns yang lebih fleksibel
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

    # Jika nama masih kosong, coba pattern yang lebih sederhana
    if 'Account Name' not in personal_info:
        simple_nama_pattern = r'Kepada\s+Yth\.\s*/\s*To\s*:\s*\n\s*([A-Z][A-Z\s]+)'
        simple_match = re.search(simple_nama_pattern, text, re.IGNORECASE)
        if simple_match:
            personal_info['nama'] = simple_match.group(1).strip()

    # Ekstrak tanggal laporan dengan error handling
    tanggal_patterns = [
        r'Tanggal\s+Laporan\s*[:\s]*(\d{2}/\d{2}/\d{2,4})',
        r'Statement\s+Date\s*[:\s]*(\d{2}/\d{2}/\d{2,4})',
    ]
    for pattern in tanggal_patterns:
        tanggal_match = re.search(pattern, text, re.IGNORECASE)
        if tanggal_match:
            personal_info['Report Date'] = tanggal_match.group(1)
            break

    # Ekstrak periode transaksi dengan error handling
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

    # Ekstrak nomor rekening dengan error handling
    rekening_patterns = [
        r'No\.\s*Rekening\s*\n*Account\s*No\s*[,:]*\s*(\d+)',
        r'No\.\s*Rekening\s*[:\s]*(\d+)',
        r'Account\s*No\s*[:\s]*(\d+)',
    ]
    for pattern in rekening_patterns:
        rekening_match = re.search(pattern, text, re.IGNORECASE)
        if rekening_match:
            personal_info['Account Number'] = rekening_match.group(1)
            break

    # Ekstrak nama produk dengan error handling
    produk_patterns = [
        r'(?:Nama\s+Produk|Product\s+Name)\s*[,:]*\s*(.*?)(?=\s*(?:Unit\s*Kerja|Business\s*Unit|Valuta|Currency|Alamat\s*Unit\s*Kerja|\n|$))',
    ]
    for pattern in produk_patterns:
        produk_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if produk_match:
            personal_info['Product Name'] = produk_match.group(1).strip()
            break

    # Ekstrak valuta dengan error handling
    valuta_patterns = [
        r'Valuta\s*\n*Currency\s*[,:]*\s*([A-Z]+)',
        r'Valuta\s*[:\s]*([A-Z]+)',
        r'Currency\s*[:\s]*([A-Z]+)',
    ]
    for pattern in valuta_patterns:
        valuta_match = re.search(pattern, text, re.IGNORECASE)
        if valuta_match:
            personal_info['Currency'] = valuta_match.group(1).strip()
            break

    # Ekstrak unit kerja dengan error handling
    unit_patterns = [
        r'Unit\s+Kerja\s*\n*Business\s+Unit\s*[,:]*\s*([A-Z][A-Z\s]*?)(?=\s*(?:Alamat\s+Unit|Business\s+Unit\s+Address|\n|$))',
        r'Unit\s+Kerja\s*[:\s]*([A-Z][A-Z\s]*?)(?=\s*(?:Alamat\s+Unit|Business\s+Unit\s+Address|\n|$))',
        r'Business\s+Unit\s*[:\s]*([A-Z][A-Z\s]*?)(?=\s*(?:Alamat\s+Unit|Business\s+Unit\s+Address|\n|$))',
    ]
    for pattern in unit_patterns:
        unit_match = re.search(pattern, text, re.IGNORECASE)
        if unit_match:
            personal_info['Branch'] = unit_match.group(1).strip()
            break

    # Ekstrak alamat unit kerja dengan error handling
    alamat_unit_kerja_patterns = [
        r'(?:Alamat\s+Unit\s+Kerja|Business\s+Unit\s+Address)\s*[,:]*\s*\n\s*([A-Z][A-Z\s]*?)\n\s*([A-Z][A-Z\s]*?)(?=\n|$)',
        r'(?:Alamat\s+Unit\s+Kerja|Business\s+Unit\s+Address)\s*[,:]*\s*([A-Z][A-Z\s]*?)\n\s*([A-Z][A-Z\s]*?)(?=\n|$)',
        r'(?:Alamat\s+Unit\s+Kerja|Business\s+Unit\s+Address)\s*[,:]*\s*([A-Z][A-Z\s]*?)(?=\n|$)',
    ]

    for pattern in alamat_unit_kerja_patterns:
        alamat_unit_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if alamat_unit_match:
            if len(alamat_unit_match.groups()) >= 2:
                alamat_temp = f"{alamat_unit_match.group(1).strip()} {alamat_unit_match.group(2).strip()}"
            else:
                alamat_temp = alamat_unit_match.group(1).strip()

            alamat_temp = re.sub(r'Product\s+Name\s*Business\s+Unit\s*Address ', '', alamat_temp, flags=re.IGNORECASE).strip()
            personal_info['Business Unit Address'] = alamat_temp
            break

    # --- Ekstraksi Informasi Finansial (Saldo) dengan error handling ---
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
                financial_summary['opening_balance'] = parse_amount(amounts[0])
                financial_summary['total_debit_transaction'] = parse_amount(amounts[1])
                financial_summary['total_credit_transaction'] = parse_amount(amounts[2])
                financial_summary['closing_balance'] = parse_amount(amounts[3])

    except Exception as e:
        print(f"Error extracting financial summary: {e}")

    # Gabungkan informasi finansial ke dalam dictionary utama
    # personal_info.update(financial_summary)

    return personal_info, financial_summary

def extract_transactions(text: str) -> List[Dict]:
    """Extract semua transaksi dari bank statement"""
    transactions = []

    # Pattern untuk menangkap transaksi
    # Format: DD/MM/YY HH:MM:SS Description TellerID Debit Credit Balance
    transaction_pattern = r'(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)\s+(\d{7})\s+([\d,\.]+)\s+([\d,\.]+)\s+([\d,\.]+)'

    lines = text.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Cek apakah baris dimulai dengan tanggal
        if re.match(r'^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}', line):
            # Split berdasarkan spasi, tapi hati-hati dengan deskripsi yang panjang
            parts = line.split()
            if len(parts) >= 7:
                try:
                    date = parts[0]
                    time = parts[1]
                    teller_id = None
                    debit = None
                    credit = None
                    balance = None

                    # Cari teller ID (7 digit number), debit, credit, balance dari akhir
                    # Ambil 4 elemen terakhir
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

                        # Description adalah sisa parts setelah date, time dan sebelum 4 numeric parts terakhir
                        desc_start = 2  # setelah date dan time
                        desc_end = len(parts) - 4  # sebelum 4 numeric parts
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

                except (ValueError, IndexError) as e:
                    # Skip baris yang tidak bisa diparse
                    continue

    return transactions

def extract_partner_name_bri(description: str):

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

    # Clean and prepare text
    cleaned = description.strip()

    # Pattern for BM5/BM6 transactions (most common in BRI CMS)
    if re.search(r'BM\d+', cleaned):
        lines = [line.strip() for line in cleaned.split('\n') if line.strip()]

        company_words = []
        esb_found = False

        for line in lines:
            # Skip ESB technical line
            if line.startswith('ESB:'):
                esb_found = True
                continue

            # Process BM line and subsequent company name lines
            if re.match(r'^BM\d+\s+\d+\s+\d+', line):
                # Extract company name part from BM line if any
                bm_match = re.search(r'BM\d+\s+\d+\s+\d+\s+(.+)', line)
                if bm_match:
                    company_part = bm_match.group(1).strip()
                    # Extract alphabetic words only
                    words = [word for word in company_part.split() if word.isalpha() and len(word) >= 2]
                    company_words.extend(words)
            else:
                # This is a company name continuation line
                if not esb_found:  # Only process if we haven't hit ESB line yet
                    words = [word for word in line.split() if word.isalpha() and len(word) >= 2]
                    company_words.extend(words)

        if company_words:
            return ' '.join(company_words)

    # NBMB pattern
    if "NBMB" in cleaned.upper():
        nbmb_pattern = r'NBMB\s+(.*?)\s+TO\s+(.*?)(?:\n|ESB:|$)'
        nbmb_match = re.search(nbmb_pattern, cleaned, re.IGNORECASE | re.DOTALL)
        if nbmb_match:
            receiver = nbmb_match.group(2).strip()
            sender = nbmb_match.group(1).strip()
            return receiver if receiver else sender

    # WBNKTRF pattern
    elif "WBNKTRF" in cleaned.upper():
        # Extract everything after the WBNKTRF code pattern
        after_wbnk = re.sub(r'WBNKTRF\w+', '', cleaned, flags=re.IGNORECASE)
        after_wbnk = re.sub(r'ESB:.*', '', after_wbnk, flags=re.DOTALL)
        words = [word for word in after_wbnk.split() if word.isalpha() and len(word) >= 2]
        if words:
            return ' '.join(words)

    # BFST pattern
    elif "BFST" in cleaned.upper():
        bfst_content = re.sub(r'BFST\d+', '', cleaned, flags=re.IGNORECASE)
        bfst_content = re.sub(r'ESB:.*', '', bfst_content, flags=re.DOTALL)
        bfst_content = re.sub(r'\d{8,}', '', bfst_content)  # Remove long numbers

        if ':' in bfst_content:
            names = bfst_content.split(':')
            for name in names:
                clean_name = ''.join(c for c in name if c.isalpha() or c.isspace()).strip()
                if clean_name and len(clean_name) >= 3:
                    return clean_name
        else:
            words = [word for word in bfst_content.split() if word.isalpha() and len(word) >= 2]
            if words:
                return ' '.join(words)

    # Bank transfer patterns
    elif any(bank in cleaned.upper() for bank in ['BCA', 'BNI', 'MANDIRI', 'DANAMON']):
        # Extract company name before bank reference
        bank_pattern = r'(.*?)(?:-BANK|-BCA|-BNI|-MANDIRI|-DANAMON)'
        bank_match = re.search(bank_pattern, cleaned, re.IGNORECASE | re.DOTALL)
        if bank_match:
            company_part = bank_match.group(1).strip()
            # Remove PT prefix and extract words
            company_part = re.sub(r'^(PT\s+)?', '', company_part, flags=re.IGNORECASE)
            words = [word for word in company_part.split() if word.isalpha() and len(word) >= 2]
            if words:
                return ' '.join(words)

    # IBIZ pattern
    elif "IBIZ" in cleaned.upper():
        if " TO " in cleaned.upper():
            parts = cleaned.split(" TO ")
            if len(parts) > 1:
                # Usually we want the receiver (after TO)
                receiver_part = parts[1].split("ESB:")[0].strip()  # Remove ESB part
                words = [word for word in receiver_part.split() if word.isalpha() and len(word) >= 2]
                if words:
                    return ' '.join(words[:4])  # Limit to 4 words

    # Payroll
    elif "PAYROLL" in cleaned.upper():
        return "PAYROLL"

    # Sales deposits
    elif "SETOR" in cleaned.upper() and "PENJUALAN" in cleaned.upper():
        return "PENJUALAN INTERNAL"

    # General fallback - extract any meaningful company-like words
    else:
        # Remove technical parts
        general_clean = re.sub(r'ESB:.*', '', cleaned, flags=re.DOTALL)
        general_clean = re.sub(r'\b\d{7,}\b', '', general_clean)  # Remove long numbers
        general_clean = re.sub(r'\b[A-Z]{2,}\d+[A-Z]*\b', '', general_clean)  # Remove codes

        # Extract alphabetic words
        words = [word for word in general_clean.split() if word.isalpha() and len(word) >= 2]

        # Filter out very common words
        filtered_words = [w for w in words if w.upper() not in ['THE', 'AND', 'OR', 'TO', 'FROM', 'FOR', 'WITH']]

        if len(filtered_words) >= 2:
            return ' '.join(filtered_words[:4])  # Max 4 words

    return None

def detect_bri_format(transactions_df):
    if 'Remark' in transactions_df.columns:
        return 'CMS'
    elif 'deskripsi' in transactions_df.columns:
        return 'E_STATEMENT'
    else:
        return 'UNKNOWN'

def analyze_bri_partners_unified(transactions_df):
    if transactions_df.empty:
        return transactions_df, pd.DataFrame()

    # Detect format
    format_type = detect_bri_format(transactions_df)
    df = transactions_df.copy()

    # Standardize column names based on format
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

    print(f"📝 Using columns: {desc_col}, {debit_col}, {credit_col}")

    # Extract partner names
    df['partner_name'] = df[desc_col].apply(extract_partner_name_bri)

    # Add transaction type
    df['transaction_type'] = df.apply(
        lambda row: 'DEBIT' if row[debit_col] > 0 else 'CREDIT' if row[credit_col] > 0 else 'UNKNOWN',
        axis=1
    )

    # Add total amount
    df['amount'] = df[debit_col] + df[credit_col]

    # Filter transactions with identified partners
    partner_transactions = df[df['partner_name'].notna()].copy()

    if partner_transactions.empty:
        return df, pd.DataFrame()

    # Aggregate by partner
    partner_summary = partner_transactions.groupby(['partner_name', 'transaction_type']).agg({
        debit_col: 'sum',
        credit_col: 'sum',
        'amount': 'sum',
        desc_col: 'count'
    }).rename(columns={desc_col: 'transaction_count'}).reset_index()

    # Sort by amount
    partner_summary = partner_summary.sort_values('amount', ascending=False)
    partner_summary_table = create_partner_summary_table(df)

    return partner_summary, partner_summary_table
    # df, partner_summary, partner_summary_table

def create_partner_summary_table(partner_df):
    """Create partner summary table in the requested format"""
    if partner_df.empty or 'partner_name' not in partner_df.columns:
        return pd.DataFrame()

    partner_transactions = partner_df[partner_df['partner_name'].notna()].copy()

    if partner_transactions.empty:
        return pd.DataFrame()

    # Detect format (sesuaikan dengan function Anda)
    if 'Debit' in partner_transactions.columns and 'Credit' in partner_transactions.columns:
        debit_col = 'Debit'
        credit_col = 'Credit'
    elif 'debit' in partner_transactions.columns and 'kredit' in partner_transactions.columns:
        debit_col = 'debit'
        credit_col = 'kredit'
    else:
        return pd.DataFrame()

    # Create summary
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
    if partner_df.empty or 'partner_name' not in partner_df.columns:
        return pd.DataFrame()

    # Filter only transactions with identified partners
    partner_transactions = partner_df[partner_df['partner_name'].notna()].copy()

    if partner_transactions.empty:
        return pd.DataFrame()

    # Detect column format
    if 'Debit' in partner_transactions.columns and 'Credit' in partner_transactions.columns:
        debit_col = 'Debit'
        credit_col = 'Credit'
    elif 'debit' in partner_transactions.columns and 'kredit' in partner_transactions.columns:
        debit_col = 'debit'
        credit_col = 'kredit'
    else:
        return pd.DataFrame()

    # Calculate overall statistics
    total_credit_transactions = len(partner_transactions[partner_transactions[credit_col] > 0])
    total_debit_transactions = len(partner_transactions[partner_transactions[debit_col] > 0])

    total_credit_amount = partner_transactions[credit_col].sum()
    total_debit_amount = partner_transactions[debit_col].sum()

    total_unique_partners = partner_transactions['partner_name'].nunique()

    # Find top partner by total volume
    partner_volumes = partner_transactions.groupby('partner_name').agg({
        debit_col: 'sum',
        credit_col: 'sum'
    }).reset_index()

    partner_volumes['total_volume'] = partner_volumes[debit_col] + partner_volumes[credit_col]
    top_partner_row = partner_volumes.loc[partner_volumes['total_volume'].idxmax()]

    top_partner_name = top_partner_row['partner_name']
    top_partner_amount = top_partner_row['total_volume']

    # Create summary dictionary
    summary_data = {
        'No_of_Credit': total_credit_transactions,
        'No_of_Debit': total_debit_transactions,
        'Total_Credit_Amount': total_credit_amount,
        'Total_Debit_Amount': total_debit_amount,
        'Total_Partners': total_unique_partners,
        'Top_Partner': top_partner_name,
        'Top_Partner_Amount': top_partner_amount
    }

    # Convert to DataFrame
    summary_df = pd.DataFrame([summary_data])

    return summary_df

def parse_bri_statement(pdf_path, folder_path, filename):
    full_path = os.path.join(folder_path, filename)
    pdf_text = read_pdf_to_text(full_path)
    file_id = extract_filename_id(filename)

    # Initialize variables to empty DataFrames or dicts
    personal_info = {}
    summary_info = {}
    transactions = []
    trx_df = pd.DataFrame()
    partner_df = pd.DataFrame()
    partner_trx_df = pd.DataFrame()
    analytics_df = pd.DataFrame()


    # If block: Handles files *not* containing "2025" (CMS format assumed)
    if "2025" not in file_id:
        personal_info = extract_cms_account_info(pdf_text)
        summary_info = extract_cms_summary(pdf_text)
        transactions = extract_cms_transactions(pdf_text)

    # Else block: Handles files containing "2025" (E-STATEMENT format assumed)
    else:
        personal_info, summary_info = extract_personal_info(pdf_text)
        transactions = extract_transactions(pdf_text)


    # Create transaction DataFrame after transactions list is populated
    trx_df = pd.DataFrame(transactions)

    # Perform partner analysis and summary creation using trx_df
    if not trx_df.empty:
        partner_df, partner_trx_df = analyze_bri_partners_unified(trx_df)
        analytics_df = create_partner_statistics_summary(partner_df)


    # Create personal and summary DataFrames
    personal_df = pd.DataFrame([personal_info])
    summary_df = pd.DataFrame([summary_info])


    # Return all relevant DataFrames
    return personal_df, summary_df, trx_df, partner_trx_df, analytics_df

# ---------------------- Streamlit App UI ---------------------- #
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
        file_name=f"BCA_Statement_Analysis_{personal_df.iloc[0]['Period'] if not personal_df.empty else 'Unknown'}.xlsx",
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
