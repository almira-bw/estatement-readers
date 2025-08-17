import io
import pandas as pd
import streamlit as st

# If your parsing logic lives in the uploaded file (/mnt/data/app.py),
# we import and wrap it so the signature matches the UI expectation.
# The uploaded module exposes: parse_bri_statement(file_bytes: bytes, filename: str)
try:
    from app import parse_bri_statement  # make sure your deployment includes app.py alongside this file
except Exception as e:  # Fallback if module name differs in your env
    # Try relative import when file named 'app.py' is in same folder
    import importlib.util, sys, pathlib
    _p = pathlib.Path(__file__).with_name("app.py")
    if _p.exists():
        spec = importlib.util.spec_from_file_location("app", str(_p))
        app_mod = importlib.util.module_from_spec(spec)
        sys.modules["app"] = app_mod
        spec.loader.exec_module(app_mod)  # type: ignore
        parse_bri_statement = app_mod.parse_bri_statement  # type: ignore
    else:
        raise


def parse_bca_statement(file_like_io: io.BytesIO):
    """Thin wrapper to reuse existing parser but match requested signature.

    Parameters
    ----------
    file_like_io : io.BytesIO
        BytesIO containing the uploaded PDF bytes.

    Returns
    -------
    Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]
        personal_df, summary_df, trx_df, partner_trx_df, analytics_df
    """
    if hasattr(file_like_io, "getvalue"):
        data = file_like_io.getvalue()
    else:
        # final fallback (read() may advance pointer)
        data = file_like_io.read()
    return parse_bri_statement(data, "uploaded.pdf")


# ---------------------- Streamlit App UI ---------------------- #
st.set_page_config(page_title="BCA E-Statement Reader", layout="wide")
st.title("📄 BCA E-Statement Reader")

uploaded_pdf = st.file_uploader("Upload a BCA PDF e-statement", type="pdf")

if uploaded_pdf:
    st.success("✅ PDF uploaded. Processing...")

    # Read bytes once and reuse
    pdf_bytes = uploaded_pdf.read()

    # Parse into dataframes (wrapper keeps compatibility with your existing code)
    personal_df, summary_df, trx_df, partner_trx_df, analytics_df = parse_bca_statement(io.BytesIO(pdf_bytes))

    # ✅ ADD DOWNLOAD SECTION
    st.markdown("---")
    st.subheader("📥 Download Complete Analysis")

    @st.cache_data(show_spinner=False)
    def create_excel_download(_personal_df, _summary_df, _trx_df, _partner_trx_df, _analytics_df) -> bytes:
        """Build an in‑memory Excel file containing all sheets."""
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            # Keep sheet order consistent & user-friendly
            (_personal_df or pd.DataFrame()).to_excel(writer, sheet_name="Account Info", index=False)
            (_summary_df or pd.DataFrame()).to_excel(writer, sheet_name="Monthly Summary", index=False)
            (_analytics_df or pd.DataFrame()).to_excel(writer, sheet_name="Analytics", index=False)
            (_trx_df or pd.DataFrame()).to_excel(writer, sheet_name="Transactions", index=False)
            (_partner_trx_df or pd.DataFrame()).to_excel(writer, sheet_name="Partner Summary", index=False)
        output.seek(0)
        return output.getvalue()

    # Generate Excel file
    excel_data = create_excel_download(personal_df, summary_df, trx_df, partner_trx_df, analytics_df)

    # Derive a friendly filename suffix if available
    try:
        period = personal_df.iloc[0]["Period"] if (isinstance(personal_df, pd.DataFrame) and not personal_df.empty and "Period" in personal_df.columns) else "Unknown"
    except Exception:
        period = "Unknown"

    # Download button
    st.download_button(
        label="📊 Download Complete Analysis (Excel)",
        data=excel_data,
        file_name=f"BCA_Statement_Analysis_{period}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("---")

    # Tabs section
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📌 Account Info",
        "📊 Monthly Summary",
        "📈 Analytics",
        "💸 Transactions",
        "💳 Partner Transactions",
    ])

    with tab1:
        st.dataframe(personal_df, use_container_width=True)

    with tab2:
        st.dataframe(summary_df, use_container_width=True)

    with tab3:
        st.dataframe(analytics_df, use_container_width=True)

    with tab4:
        st.dataframe(trx_df, use_container_width=True)

    with tab5:
        st.dataframe(partner_trx_df, use_container_width=True)
else:
    st.info("Silakan unggah file PDF untuk mulai memproses.")
