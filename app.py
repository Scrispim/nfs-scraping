from datetime import datetime, timedelta

import streamlit as st

from scraper import NFSeScraper, ScraperError
from report import generate_report, generate_report_completo


st.set_page_config(
    page_title="NFS-e — Extrator de Relatórios",
    page_icon="📄",
    layout="centered",
)

st.markdown(
    """
    <style>
    .block-container { max-width: 760px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("## 📄 NFS-e — Extrator de Relatórios")
st.markdown("Portal Contribuinte · Notas Fiscais de Serviço Eletrônica")
st.divider()

# ------------------------------------------------------------------
# Período
# ------------------------------------------------------------------

st.markdown("### 📅 Período")

hoje = datetime.today().date()
default_inicio = hoje - timedelta(days=30)

col_di, col_df = st.columns(2)
with col_di:
    data_inicial = st.date_input("Data Inicial", value=default_inicio, format="DD/MM/YYYY")
with col_df:
    data_final = st.date_input("Data Final", value=hoje, format="DD/MM/YYYY")

if (data_final - data_inicial).days > 30:
    st.warning("O portal limita a consulta a no máximo 30 dias por vez.")

# ------------------------------------------------------------------
# Botão principal
# ------------------------------------------------------------------

st.divider()

modo_teste      = st.checkbox("Modo teste (somente 10 primeiras páginas)")
relatorio_tipo  = st.radio(
    "Tipo de relatório",
    options=["Simples", "Completo (com dados da nota)"],
    horizontal=True,
    help="Simples: 6 colunas básicas. Completo: inclui todos os campos do XML de cada nota (mais lento).",
)

if st.button("🔍  Buscar e Gerar Relatório", type="primary", use_container_width=True):
    progress_bar = st.progress(0, text="Iniciando…")
    log_area = st.empty()
    log_lines: list[str] = []

    def on_progress(msg: str, pct: int):
        progress_bar.progress(min(pct, 100), text=msg)

    def on_log(msg: str):
        log_lines.append(msg)
        log_area.code("\n".join(log_lines), language=None)

    relatorio_completo = relatorio_tipo.startswith("Completo")

    scraper = NFSeScraper(
        data_inicial=data_inicial.strftime("%d/%m/%Y"),
        data_final=data_final.strftime("%d/%m/%Y"),
        progress_callback=on_progress,
        log_callback=on_log,
        max_pages=10 if modo_teste else 0,
        fetch_xml=relatorio_completo,
    )

    records = None
    error = None

    try:
        records = scraper.run()
    except ScraperError as e:
        error = str(e)
    except Exception as e:
        import traceback
        error = f"Erro inesperado: {e}\n\n```\n{traceback.format_exc()}\n```"

    progress_bar.empty()

    if error:
        st.error(error)

    elif records is not None:
        if not records:
            st.warning("Nenhuma nota encontrada no período informado.")
        else:
            st.success(f"✅  {len(records)} nota(s) encontrada(s).")

            gen_fn   = generate_report_completo if relatorio_completo else generate_report
            suffix   = "_completo" if relatorio_completo else ""
            xlsx_bytes = gen_fn(
                records,
                data_inicial.strftime("%d/%m/%Y"),
                data_final.strftime("%d/%m/%Y"),
            )

            filename = f"NFSe_{data_inicial.strftime('%d-%m-%Y')}_a_{data_final.strftime('%d-%m-%Y')}{suffix}.xlsx"

            st.download_button(
                label="⬇️  Baixar Relatório Excel",
                data=xlsx_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                type="primary",
            )

            st.divider()
            st.markdown("#### Prévia dos dados")
            import pandas as pd
            df_preview = pd.DataFrame(records)
            st.dataframe(df_preview, use_container_width=True, hide_index=True)
