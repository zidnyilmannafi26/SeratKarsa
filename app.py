"""
app.py - Tampilan utama Serat Karsa (Streamlit)
===============================================
Jalankan dengan:  streamlit run app.py

Isi halaman:
  - Sidebar : status sistem, tombol One-Click ETL Pipeline, upload PDF SOP
  - Tab 1   : Live Chatbot (Hybrid RAG) + expander "Lihat Proses Data"
  - Tab 2   : Inventory & Chat Analytics Dashboard

Tema "batik sogan" punya versi gelap dan terang (lihat .streamlit/config.toml).
Warna untuk CSS custom dan grafik diambil dari PALET sesuai tema yang aktif.
"""

import html
import os
import sqlite3
import time
from string import Template

import pandas as pd
import plotly.express as px
import streamlit as st

from etl_pipeline import CHROMA_DIR, DB_PATH, NAMA_KOLEKSI, SOP_DIR, run_pipeline
from rag_sql_engine import MODEL_UTAMA, jawab_pertanyaan

# ---------------------------------------------------------------------------
# KONFIGURASI HALAMAN & WARNA
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Serat Karsa", page_icon="🪷", layout="wide")

# Nilai harus sama dengan [theme.dark] / [theme.light] di config.toml
PALET = {
    "dark": dict(ground="#1E140D", surface="#3A2515", deep="#2A1B10", line="#6B4A2E",
                 ink="#F3E6D3", muted="#BFA88A", accent="#D98E32", hot="#F28C1B", on="#1E140D"),
    "light": dict(ground="#FBF5EA", surface="#F3E6D3", deep="#EADAC2", line="#D4BC98",
                  ink="#2C1E12", muted="#7A5E42", accent="#A85F16", hot="#D86A08", on="#FFF8EE"),
}
mode = getattr(getattr(st.context, "theme", None), "type", None) or "dark"
W = PALET.get(mode, PALET["dark"])

WARNA_KATEGORI = {"Pria": W["muted"], "Wanita": W["accent"]}
BATAS_STOK_MENIPIS = 5


def svg_url(svg):
    """SVG kecil sebagai background-image CSS (tanpa base64)."""
    return 'url("data:image/svg+xml,' + svg.replace("#", "%23").replace('"', "'").replace("<", "%3C").replace(">", "%3E") + '")'


# Motif kawung (sidebar) dan parang (header), opasitas rendah agar teks tetap terbaca
KAWUNG = svg_url(
    f"<svg xmlns='http://www.w3.org/2000/svg' width='56' height='56' viewBox='0 0 56 56'>"
    f"<g fill='none' stroke='{W['accent']}' stroke-opacity='0.10' stroke-width='1.2'>"
    "<ellipse cx='28' cy='14' rx='7' ry='13'/><ellipse cx='28' cy='42' rx='7' ry='13'/>"
    "<ellipse cx='14' cy='28' rx='13' ry='7'/><ellipse cx='42' cy='28' rx='13' ry='7'/></g>"
    f"<g fill='{W['accent']}' fill-opacity='0.13'><circle cx='28' cy='28' r='2'/><circle cx='0' cy='0' r='2'/>"
    "<circle cx='56' cy='0' r='2'/><circle cx='0' cy='56' r='2'/><circle cx='56' cy='56' r='2'/></g></svg>"
)
PARANG = svg_url(
    f"<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'>"
    f"<g fill='none' stroke='{W['accent']}' stroke-opacity='0.11' stroke-width='1.4'>"
    "<path d='M-10 30 C0 30 0 20 10 20 S20 10 30 10 S40 0 50 0'/>"
    "<path d='M-10 50 C0 50 0 40 10 40 S20 30 30 30 S40 20 50 20'/></g>"
    f"<g fill='{W['accent']}' fill-opacity='0.11'><circle cx='6' cy='6' r='1.6'/><circle cx='26' cy='26' r='1.6'/></g></svg>"
)

CSS = Template("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Pinyon+Script&display=swap');

/* ---- kerangka ---- */
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.5rem; }
[data-testid="stSidebar"] { background-image: $kawung; }

/* ---- header: logo + pita parang ---- */
.sk-header { background-image: $parang; border: 1px solid $line; border-radius: 14px;
             padding: 30px 36px 26px; display: flex; justify-content: space-between;
             align-items: flex-end; gap: 24px; margin-bottom: .5rem; }
.sk-title { font-family: 'Outfit', sans-serif; font-weight: 800; font-size: 44px;
            letter-spacing: -.02em; line-height: 1; color: $ink; margin: 0; }
.sk-title em, .sk-logo em { font-family: 'Pinyon Script', cursive; font-style: normal;
                            font-weight: 400; color: $accent; }
.sk-title em { font-size: 64px; margin-left: 4px; }
.sk-sub { margin: 10px 0 0; color: $muted; font-size: 15px; }
.sk-head-r { display: flex; flex-direction: column; align-items: flex-end; gap: 16px; }
.sk-mode { display: inline-flex; padding: 3px; border: 1px solid $line; border-radius: 999px; background: $deep; }
.sk-mode button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent;
                  color: $muted; font: 600 13px 'Plus Jakarta Sans', sans-serif; padding: 6px 14px;
                  border-radius: 999px; cursor: pointer; }
.sk-mode button:hover { color: $accent; }
.sk-mode button[aria-pressed="true"] { background: $accent; color: $on; cursor: default; }
.sk-mode button:focus-visible { outline: 2px solid $accent; outline-offset: 2px; }
.sk-meta { text-align: right; font-size: 12px; color: $muted; white-space: nowrap; }
.sk-meta b { display: block; color: $ink; font-size: 14px; font-weight: 600; }

/* ---- tabs ---- */
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 32px; border-bottom: 1px solid $line; }
[data-testid="stTab"] p { font-weight: 600; font-size: 14px; }
[data-testid="stTab"][aria-selected="false"] p { color: $muted; }

/* ---- sidebar ---- */
.sk-logo { font-family: 'Outfit', sans-serif; font-weight: 800; font-size: 26px; line-height: 1; color: $ink; }
.sk-logo em { font-size: 38px; margin-left: 2px; }
.sk-cap { font-size: 12px; color: $muted; letter-spacing: .06em; text-transform: uppercase; margin: 6px 0 18px; }
.sk-side-h { font-family: 'Outfit', sans-serif; font-size: 14px; font-weight: 700; letter-spacing: .12em;
             text-transform: uppercase; color: $accent; display: flex; justify-content: space-between;
             padding-bottom: 8px; border-bottom: 1px solid $line; margin: 18px 0 12px; }
.sk-side-h span { color: $muted; font-weight: 500; letter-spacing: 0; text-transform: none; }
.sk-stat { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; font-size: 14px; }
.sk-stat li { display: flex; align-items: center; gap: 10px; margin: 0; font-size: 14px; line-height: 1.5; }
.sk-stat i { width: 8px; height: 8px; border-radius: 50%; flex: none; background: $accent; }
.sk-stat i.off { background: $hot; box-shadow: 0 0 0 3px $deep; }
.sk-stat code { font-size: 12px; color: $accent; background: transparent; padding: 0; }
.sk-note { font-size: 12px; color: $muted; padding-left: 10px; border-left: 2px solid $accent; line-height: 1.6; }
[data-testid="stFileUploaderDropzone"] { border: 1px dashed $line; background: $deep; }
.sk-doc { font-size: 14px; line-height: 1.4; padding: 8px 0; overflow-wrap: anywhere; }
.sk-doc-tag { font-size: 12px; color: $muted; border: 1px solid $line; border-radius: 999px;
              padding: 1px 8px; margin-left: 6px; display: inline-block; white-space: nowrap; }

/* ---- tombol sekunder (ghost) ---- */
[data-testid="stBaseButton-secondary"] { background: transparent; border-color: $line; }
[data-testid="stBaseButton-secondary"]:hover { border-color: $accent; color: $accent; }
[data-testid="stBaseButton-secondary"] p { white-space: normal; overflow: visible; text-overflow: clip;
                                           font-weight: 600; font-size: 14px; line-height: 1.3; }

/* ---- chat ---- */
[data-testid="stChatMessage"] { background: transparent; gap: 12px; padding: 0; margin-bottom: 18px; }
[data-testid="stChatMessageContent"] { background: $surface; border: 1px solid $line; color: $ink;
        border-radius: 4px 16px 16px 16px; padding: 14px 18px; max-width: 82%; flex: 0 1 auto; margin: 0; }
[data-testid="stChatMessageContent"]::before { content: "Karsa"; display: block; font-size: 12px; font-weight: 700;
        letter-spacing: .08em; text-transform: uppercase; color: $accent; margin-bottom: 4px; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { flex-direction: row-reverse; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
        background: transparent; border-color: $accent; border-radius: 16px 4px 16px 16px; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"]::before {
        content: "Anda"; color: $muted; text-align: right; }
[data-testid="stChatMessageContent"] strong { color: $accent; }
[data-testid="stChatMessageAvatarAssistant"] { background: $accent; color: $on; border-radius: 50%;
        width: 36px; height: 36px; display: grid; place-items: center; }
[data-testid="stChatMessageAvatarAssistant"] > * { display: none; }
[data-testid="stChatMessageAvatarAssistant"]::after { content: "K"; font-family: 'Pinyon Script', cursive;
        font-size: 24px; line-height: 1; margin-top: 4px; }
[data-testid="stChatMessageAvatarUser"] { background: $deep; border: 1px solid $line; color: $muted;
        border-radius: 50%; width: 36px; height: 36px; }
[data-testid="stChatInput"] { background: $surface; border-color: $line; }
[data-testid="stChatInputSubmitButton"] { background: $accent; color: $on; border-radius: 6px; }

/* ---- expander "Lihat Proses Data" ---- */
[data-testid="stExpander"] details { background: $deep; border-color: $line; }
[data-testid="stExpander"] summary p { font-weight: 600; font-size: 14px; }
[data-testid="stExpander"] summary svg { color: $accent; }
[data-testid="stCode"] pre { border: 1px solid $line; border-left: 3px solid $accent; }

/* ---- komponen kecil ---- */
.sk-label { font-size: 12px; text-transform: uppercase; letter-spacing: .1em; color: $muted;
            font-weight: 600; margin: 4px 0 8px; }
.sk-badge { display: inline-flex; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 700;
            letter-spacing: .04em; border: 1px solid $line; color: $muted; margin-right: 6px; white-space: nowrap; }
.sk-badge.sql { background: $accent; border-color: $accent; color: $on; }
.sk-badge.pdf { border-color: $accent; color: $accent; }
.sk-badge.hybrid { background: $hot; border-color: $hot; color: $on; }
.sk-quote { display: flex; gap: 14px; margin-bottom: 10px; }
.sk-quote-t { flex: 1; padding: 12px 16px; border-left: 3px solid $accent; background: $ground;
              border-radius: 0 6px 6px 0; font-size: 14px; line-height: 1.6; }
.sk-quote-t small { display: block; margin-top: 6px; font-size: 12px; color: $muted; }
.sk-sim { flex: none; width: 112px; display: flex; flex-direction: column; justify-content: center;
          align-items: center; gap: 6px; border: 1px solid $line; border-radius: 6px; }
.sk-sim span { font-size: 10px; text-transform: uppercase; letter-spacing: .1em; color: $muted; font-weight: 600; }
.sk-sim b { font-family: 'Outfit', sans-serif; font-size: 24px; color: $accent; }
.sk-sim u { width: 72px; height: 4px; border-radius: 2px; background: $surface; overflow: hidden; display: block; }
.sk-sim u i { display: block; height: 100%; background: $accent; }

/* ---- dashboard ---- */
[data-testid="stMetric"] { background: $surface; border: 1px solid $line; border-top: 3px solid $accent;
                           border-radius: 10px; padding: 18px 20px; }
[data-testid="stMetricLabel"] p { font-size: 12px; text-transform: uppercase; letter-spacing: .1em;
                                  color: $muted; font-weight: 600; }
[data-testid="stMetricValue"] { font-family: 'Outfit', sans-serif; }
.st-key-kpi_alert [data-testid="stMetric"] { border-top-color: $hot; }
.st-key-kpi_alert [data-testid="stMetricValue"] { color: $hot; }
.sk-sec { font-family: 'Outfit', sans-serif; font-size: 24px; font-weight: 700; letter-spacing: -.01em;
          margin: 28px 0 12px; display: flex; align-items: baseline; gap: 14px; }
.sk-sec small { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 14px; font-weight: 400; color: $muted; }
[class*="st-key-panel"] { background: $surface; }
.sk-pt { font-family: 'Outfit', sans-serif; font-size: 18px; font-weight: 600; display: flex;
         justify-content: space-between; align-items: baseline; gap: 12px; }
.sk-pt span { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 12px; font-weight: 400; color: $muted; }
.sk-share { display: flex; height: 14px; border-radius: 4px; overflow: hidden; gap: 2px; margin-top: 18px; }
.sk-share-l { display: flex; justify-content: space-between; font-size: 12px; color: $muted; margin: 6px 0 4px; }
.sk-split { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid $line; margin-top: 8px; }
.sk-split > div { padding: 16px 0 0 16px; display: flex; flex-direction: column; gap: 14px; }
.sk-split > div:first-child { padding-left: 0; padding-right: 16px; border-right: 1px solid $line; }
.sk-split .k { font-size: 12px; text-transform: uppercase; letter-spacing: .1em; font-weight: 600;
               display: flex; align-items: center; gap: 8px; color: $muted; }
.sk-split .k b { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.sk-split .n { font-family: 'Outfit', sans-serif; font-size: 32px; font-weight: 700; line-height: 1; }
.sk-split .r { font-family: 'Outfit', sans-serif; font-size: 18px; font-weight: 600; }
.sk-split small { display: block; font-size: 12px; color: $muted; margin-top: 4px; }
.sk-hint { font-size: 14px; color: $muted; line-height: 1.55; padding: 12px 14px; background: $deep;
           border-radius: 6px; margin-top: 18px; }
.sk-src { display: flex; align-items: center; gap: 40px; flex-wrap: wrap; padding: 16px 22px;
          border: 1px solid $line; border-radius: 10px; margin-top: 8px; }
.sk-src > span { font-size: 12px; text-transform: uppercase; letter-spacing: .1em; color: $muted; font-weight: 600; }
.sk-src div { display: flex; align-items: center; gap: 10px; }
.sk-src b { font-family: 'Outfit', sans-serif; font-size: 24px; }
.sk-src small { font-size: 12px; color: $muted; }
[data-baseweb="tag"] { background: $deep; border: 1px solid $line; color: $ink; }
</style>
""")
st.markdown(CSS.substitute(W, kawung=KAWUNG, parang=PARANG), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# FUNGSI BANTUAN
# ---------------------------------------------------------------------------
def baca_tabel(sql):
    """Menjalankan SELECT dan mengembalikan DataFrame pandas."""
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


def status_sistem():
    """Mengumpulkan angka kesehatan sistem untuk sidebar."""
    status = {"api_key": bool(os.getenv("GEMINI_API_KEY")), "db": DB_PATH.exists(),
              "products": 0, "orders": 0, "chat_logs": 0, "chunk": 0, "pdf": 0}
    if status["db"]:
        try:
            for tabel in ("products", "orders", "chat_logs"):
                status[tabel] = int(baca_tabel(f"SELECT COUNT(*) AS n FROM {tabel}")["n"][0])
        except Exception:
            status["db"] = False
    try:
        import chromadb
        status["chunk"] = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(NAMA_KOLEKSI).count()
    except Exception:
        pass
    if SOP_DIR.exists():
        status["pdf"] = len(list(SOP_DIR.glob("*.pdf")))
    return status


def rupiah(angka):
    return "Rp" + f"{int(angka):,}".replace(",", ".")


def rapikan_grafik(fig, tinggi=420):
    """Menyamakan gaya semua grafik Plotly dengan tema batik yang aktif."""
    fig.update_layout(
        height=tinggi, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=W["ink"]), legend_title_text="",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(gridcolor=W["line"], zerolinecolor=W["line"], color=W["muted"])
    fig.update_yaxes(gridcolor=W["line"], zerolinecolor=W["line"], color=W["muted"])
    return fig


def judul_seksi(teks, keterangan=""):
    st.markdown(f'<div class="sk-sec">{teks} <small>{keterangan}</small></div>', unsafe_allow_html=True)


def judul_panel(teks, keterangan=""):
    st.markdown(f'<div class="sk-pt">{teks}<span>{keterangan}</span></div>', unsafe_allow_html=True)


def titik(ok):
    return '<i></i>' if ok else '<i class="off"></i>'


# ---------------------------------------------------------------------------
# SIDEBAR - status sistem, ETL, upload PDF
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sk-logo">Serat <em>Karsa</em></div>'
                '<div class="sk-cap">Panel Admin &amp; Tim Data</div>', unsafe_allow_html=True)

    info = status_sistem()
    baris_status = [
        (info["api_key"], "Gemini API key terpasang" if info["api_key"] else "GEMINI_API_KEY belum diisi di .env"),
        (True, f"Model <code>{MODEL_UTAMA}</code>"),
        (info["db"], f"SQL: {info['products']} produk, {info['orders']} pesanan, {info['chat_logs']} log chat"
                     if info["db"] else "Database belum ada, jalankan ETL"),
        (info["chunk"] > 0, f"Vector DB: {info['chunk']} potongan dari {info['pdf']} PDF"),
    ]
    st.markdown('<div class="sk-side-h">Status Sistem</div><ul class="sk-stat">'
                + "".join(f"<li>{titik(ok)}{teks}</li>" for ok, teks in baris_status)
                + "</ul>", unsafe_allow_html=True)

    st.markdown('<div class="sk-side-h">One-Click ETL Pipeline</div>', unsafe_allow_html=True)
    st.caption("Memperbarui tabel SQL dan memproses ulang semua PDF SOP.")

    pdf_baru = st.file_uploader(
        "Unggah PDF SOP tambahan (opsional)", type="pdf", accept_multiple_files=True,
        help="Isi PDF akan menjadi bahan jawaban chatbot. Unggah hanya dokumen kebijakan toko.",
    )

    if st.button("Jalankan ETL Pipeline", type="primary", width="stretch", icon=":material/rocket_launch:"):
        # simpan PDF yang diunggah ke data/sop agar ikut diproses
        SOP_DIR.mkdir(parents=True, exist_ok=True)
        for berkas in pdf_baru or []:
            (SOP_DIR / berkas.name).write_bytes(berkas.getbuffer())

        mulai = time.time()
        with st.status("Menjalankan ETL...", expanded=True) as kotak_status:
            batang = st.progress(0)

            def lapor(pesan, persen):
                batang.progress(min(int(persen), 100), text=pesan)
                if not pesan.startswith("Embedding"):   # jangan tulis satu baris per potongan
                    st.write(pesan)

            try:
                hasil = run_pipeline(lapor)
                kotak_status.update(label="ETL selesai", state="complete", expanded=False)
                hasil["durasi"] = round(time.time() - mulai, 1)
                hasil["waktu"] = time.strftime("%H:%M:%S")
                st.session_state["hasil_etl"] = hasil
                st.session_state.pop("perlu_etl", None)
            except Exception as e:
                kotak_status.update(label="ETL gagal", state="error")
                st.error(f"Terjadi error: {e}")
                st.stop()
        st.rerun()   # muat ulang halaman agar angka status & dashboard ikut berubah

    # Laporan ETL tetap tampil setelah halaman dimuat ulang
    if "hasil_etl" in st.session_state:
        h = st.session_state["hasil_etl"]
        st.markdown(
            f'<div class="sk-note">ETL selesai pukul {h["waktu"]} ({h["durasi"]} detik)<br>'
            f'products {h["baris_sql"]["products"]} · orders {h["baris_sql"]["orders"]} · '
            f'chat_logs {h["baris_sql"]["chat_logs"]} baris<br>'
            f'Vector DB: {h["jumlah_chunk"]} potongan dari {h["jumlah_pdf"]} PDF</div>',
            unsafe_allow_html=True,
        )

    # --- Kelola dokumen SOP: lihat & hapus PDF yang pernah diunggah ---
    st.markdown(f'<div class="sk-side-h">Kelola Dokumen SOP <span>{info["pdf"]} PDF</span></div>',
                unsafe_allow_html=True)
    for pdf in sorted(SOP_DIR.glob("*.pdf")) if SOP_DIR.exists() else []:
        # <wbr> setelah garis bawah: nama panjang turun baris di batas kata, tidak terpotong
        nama = html.escape(pdf.name).replace("_", "_<wbr>")
        if pdf.name == "sop_serat_karsa.pdf":
            # dibuat ulang otomatis oleh ETL, jadi tidak bisa dihapus
            st.markdown(f'<div class="sk-doc">{nama}<span class="sk-doc-tag">utama</span></div>',
                        unsafe_allow_html=True)
            continue
        kiri, kanan = st.columns([6, 1], vertical_alignment="center", gap="small")
        kiri.markdown(f'<div class="sk-doc">{nama}</div>', unsafe_allow_html=True)
        if kanan.button("", key=f"hapus-{pdf.name}", help=f"Hapus {pdf.name}",
                        icon=":material/delete:", type="tertiary"):
            pdf.unlink()
            st.session_state["perlu_etl"] = True
            st.rerun()

    if st.session_state.get("perlu_etl"):
        st.warning("Dokumen sudah dihapus, tetapi isinya masih ada di Vector DB. "
                   "Klik **Jalankan ETL Pipeline** agar chatbot berhenti memakainya.")


# ---------------------------------------------------------------------------
# JUDUL
# ---------------------------------------------------------------------------
diperbarui = (time.strftime("%d %b %Y, %H:%M", time.localtime(DB_PATH.stat().st_mtime))
              if DB_PATH.exists() else "belum ada data")
# Tombol terang/gelap: Streamlit belum punya API untuk mengganti tema, jadi pilihan
# disimpan ke localStorage (kunci yang sama dengan menu Settings > Theme) lalu halaman dimuat ulang.
IKON_TERANG = ('<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
               'stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
               'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>')
IKON_GELAP = ('<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
              'stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>')
st.html(
    '<div class="sk-header"><div><h1 class="sk-title">Serat <em>Karsa</em></h1>'
    '<p class="sk-sub">Smart Customer Service, ETL Pipeline, dan Inventory Analytics untuk bisnis batik modern</p>'
    '</div><div class="sk-head-r">'
    '<div class="sk-mode" role="group" aria-label="Pilih tema">'
    f'<button type="button" data-tema="Light" aria-pressed="{str(mode == "light").lower()}">{IKON_TERANG}Terang</button>'
    f'<button type="button" data-tema="Dark" aria-pressed="{str(mode == "dark").lower()}">{IKON_GELAP}Gelap</button>'
    f'</div><div class="sk-meta">Data diperbarui<b>{diperbarui}</b></div></div></div>'
    """<script>
    document.querySelectorAll('.sk-mode button').forEach(function (b) {
      b.addEventListener('click', function () {
        if (b.getAttribute('aria-pressed') === 'true') return;
        var kunci = 'stActiveTheme-' + window.location.pathname + '-v2';
        window.localStorage.setItem(kunci, JSON.stringify(b.dataset.tema));
        window.location.reload();
      });
    });
    </script>""",
    unsafe_allow_javascript=True,
)

if not info["db"]:
    st.warning("Database belum tersedia. Klik **Jalankan ETL Pipeline** di sidebar terlebih dahulu.")
    st.stop()

tab_chat, tab_dashboard = st.tabs(["Live Chatbot", "Inventory & Chat Analytics"])


# ---------------------------------------------------------------------------
# TAB 1 - LIVE CHATBOT
# ---------------------------------------------------------------------------
def tampilkan_detail(detail):
    """Expander transparansi: memperlihatkan cara sistem menemukan jawabannya."""
    with st.expander("Lihat Proses Data (SQL & PDF)"):
        rute = str(detail.get("rute") or "UMUM")
        st.markdown(
            f'<span class="sk-badge {html.escape(rute.lower())}">Rute: {html.escape(rute)}</span>'
            f'<span class="sk-badge">Kategori: {html.escape(str(detail.get("kategori")))}</span>',
            unsafe_allow_html=True,
        )
        if detail.get("sql"):
            st.markdown('<div class="sk-label">Kueri SQL yang dijalankan</div>', unsafe_allow_html=True)
            st.code(detail["sql"], language="sql")
            if detail.get("hasil_sql"):
                st.dataframe(pd.DataFrame(detail["hasil_sql"]), width="stretch", hide_index=True)
            else:
                st.caption("Kueri tidak mengembalikan baris.")
        if detail.get("kutipan_pdf"):
            st.markdown('<div class="sk-label">Kutipan dokumen SOP yang diambil</div>', unsafe_allow_html=True)
            for k in detail["kutipan_pdf"]:
                try:
                    skor = float(k["kemiripan"])
                except (TypeError, ValueError):
                    skor = 0.0
                lebar = max(0, min(100, round(skor * 100)))
                st.markdown(
                    f'<div class="sk-quote"><div class="sk-quote-t">"{html.escape(str(k["teks"]))}"'
                    f'<small>{html.escape(str(k["sumber"]))}, potongan {html.escape(str(k["chunk"]))}</small></div>'
                    f'<div class="sk-sim"><span>Kemiripan</span><b>{html.escape(str(k["kemiripan"]))}</b>'
                    f'<u><i style="width:{lebar}%"></i></u></div></div>',
                    unsafe_allow_html=True,
                )
        if detail.get("catatan"):
            st.caption("Catatan sistem: " + " | ".join(detail["catatan"]))
        if not detail.get("sql") and not detail.get("kutipan_pdf"):
            st.caption("Pertanyaan ini dijawab tanpa mengambil data.")


with tab_chat:
    if "pesan" not in st.session_state:
        st.session_state["pesan"] = [{
            "peran": "assistant",
            "isi": "Halo, saya Karsa. Silakan tanya stok, harga, status pesanan, aturan retur, "
                   "atau rekomendasi batik untuk acara Anda.",
        }]

    if not info["api_key"]:
        st.warning("Chatbot belum bisa menjawab karena **GEMINI_API_KEY** belum diisi. "
                   "Salin `.env.example` menjadi `.env`, isi API key, lalu jalankan ulang aplikasi.",
                   icon=":material/key_off:")

    st.markdown('<div class="sk-label">Contoh pertanyaan</div>', unsafe_allow_html=True)
    contoh = [
        "Tunik batik ukuran M masih ada?",
        "Pesanan #SK-105 sudah sampai mana?",
        "Bagaimana cara mencuci batik tulis?",
        "Batik pria untuk wisuda yang ready ukuran L",
    ]
    pertanyaan_baru = None
    for kolom, teks in zip(st.columns(len(contoh)), contoh):
        if kolom.button(teks, width="stretch"):
            pertanyaan_baru = teks

    kotak_chat = st.container(height=560)
    with kotak_chat:
        for pesan in st.session_state["pesan"]:
            with st.chat_message(pesan["peran"]):
                st.markdown(pesan["isi"])
                if pesan.get("detail"):
                    tampilkan_detail(pesan["detail"])

    kolom_input, kolom_hapus = st.columns([5, 1], vertical_alignment="center")
    with kolom_input:
        ketikan = st.chat_input("Tulis pertanyaan Anda di sini...")
    pertanyaan_baru = ketikan or pertanyaan_baru

    if pertanyaan_baru:
        # riwayat singkat agar pertanyaan lanjutan ("yang ukuran L?") tetap nyambung
        riwayat = [("Pelanggan" if p["peran"] == "user" else "Karsa", p["isi"])
                   for p in st.session_state["pesan"][1:]]
        st.session_state["pesan"].append({"peran": "user", "isi": pertanyaan_baru})
        with kotak_chat:
            with st.chat_message("user"):
                st.markdown(pertanyaan_baru)
            with st.chat_message("assistant"):
                with st.spinner("Karsa sedang mencari data..."):
                    hasil = jawab_pertanyaan(pertanyaan_baru, riwayat)
        st.session_state["pesan"].append({"peran": "assistant", "isi": hasil["jawaban"], "detail": hasil})
        st.rerun()

    if len(st.session_state["pesan"]) > 1 and kolom_hapus.button("Hapus percakapan", width="stretch"):
        del st.session_state["pesan"]
        st.rerun()


# ---------------------------------------------------------------------------
# TAB 2 - DASHBOARD ANALITIK
# ---------------------------------------------------------------------------
with tab_dashboard:
    produk = baca_tabel("SELECT * FROM products")
    logs = baca_tabel("SELECT * FROM chat_logs")

    menipis = produk[produk["stok"] < BATAS_STOK_MENIPIS]

    # --- angka ringkas ---
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total SKU", len(produk),
              help=f"{produk['nama_model'].nunique()} model batik")
    k2.metric("Total stok", f"{int(produk['stok'].sum()):,} pcs".replace(",", "."))
    with k3.container(key="kpi_alert"):
        st.metric("SKU stok menipis", len(menipis), help=f"Stok di bawah {BATAS_STOK_MENIPIS} pcs")
    k4.metric("Pertanyaan pelanggan", len(logs))

    # --- A. Inventori: Pria vs Wanita ---
    judul_seksi("Inventori: Batik Pria vs Wanita",
                f"{len(produk)} SKU dari {produk['nama_model'].nunique()} model")
    per_kategori = produk.groupby("kategori").agg(stok=("stok", "sum"), harga=("harga", "mean"),
                                                 model=("nama_model", "nunique"))
    per_model = (produk.groupby(["nama_model", "kategori"], as_index=False)
                 .agg(total_stok=("stok", "sum"), rata_harga=("harga", "mean")))

    kiri, kanan = st.columns([1.65, 1])
    with kiri.container(border=True, key="panel_stok"):
        judul_panel("Total stok per model", "pcs, semua motif dan ukuran")
        fig = px.bar(per_model.sort_values("total_stok"), x="total_stok", y="nama_model", color="kategori",
                     orientation="h", color_discrete_map=WARNA_KATEGORI, text="total_stok",
                     labels={"total_stok": "Stok (pcs)", "nama_model": ""})
        fig.update_traces(textfont_color=W["muted"], textposition="outside", cliponaxis=False)
        fig.update_yaxes(categoryorder="total ascending")
        fig.update_xaxes(range=[0, per_model["total_stok"].max() * 1.12])
        st.plotly_chart(rapikan_grafik(fig, 440), width="stretch")
    with kanan.container(border=True, key="panel_kategori"):
        judul_panel("Pria vs Wanita", "porsi stok")
        total = max(int(per_kategori["stok"].sum()), 1)
        kotak, persen = [], {}
        for kategori in ("Pria", "Wanita"):
            if kategori not in per_kategori.index:
                continue
            baris = per_kategori.loc[kategori]
            persen[kategori] = baris["stok"] / total * 100
            warna = WARNA_KATEGORI[kategori]
            kotak.append(
                f'<div><div class="k"><b style="background:{warna}"></b>{kategori}</div>'
                f'<div><div class="n">{int(baris["stok"]):,}</div><small>pcs dari {int(baris["model"])} model</small></div>'
                f'<div><div class="r">{rupiah(baris["harga"])}</div><small>rata-rata harga</small></div></div>'
                .replace(",", ".")
            )
        tipis = per_model.sort_values("total_stok").iloc[0]
        jumlah_sku = int((produk["nama_model"] == tipis["nama_model"]).sum())
        st.markdown(
            '<div class="sk-share">'
            + "".join(f'<i style="width:{p:.1f}%;background:{WARNA_KATEGORI[k]}"></i>' for k, p in persen.items())
            + '</div><div class="sk-share-l">'
            + "".join(f"<span>{k} {p:.1f}%</span>".replace(".", ",") for k, p in persen.items())
            + f'</div><div class="sk-split">{"".join(kotak)}</div>'
            f'<div class="sk-hint">Stok {html.escape(tipis["nama_model"])} paling tipis: '
            f'{int(tipis["total_stok"])} pcs untuk {jumlah_sku} SKU.</div>',
            unsafe_allow_html=True,
        )

    # --- B. Low-Stock Alert ---
    judul_seksi("Low-Stock Alert", f"stok di bawah {BATAS_STOK_MENIPIS} pcs")
    if menipis.empty:
        st.success("Semua produk stoknya aman.")
    else:
        pilihan = st.multiselect("Saring kategori", ["Pria", "Wanita"], default=["Pria", "Wanita"])
        tabel = (menipis[menipis["kategori"].isin(pilihan)]
                 .sort_values(["stok", "nama_model"])
                 [["sku", "nama_model", "kategori", "motif", "ukuran", "harga", "stok"]]
                 .assign(status=lambda d: d["stok"].map(lambda s: "Habis" if s == 0 else "Menipis")))
        st.dataframe(
            tabel, width="stretch", hide_index=True, height=320,
            column_config={
                "sku": "SKU", "nama_model": "Model", "kategori": "Kategori", "motif": "Motif",
                "ukuran": "Ukuran", "status": "Status",
                "harga": st.column_config.NumberColumn("Harga (Rp)", format="%d"),
                "stok": st.column_config.ProgressColumn("Stok", min_value=0, max_value=BATAS_STOK_MENIPIS, format="%d"),
            },
        )
        st.caption(f"{int((tabel['stok'] == 0).sum())} SKU habis dan "
                   f"{int((tabel['stok'] > 0).sum())} SKU menipis pada saringan ini.")

    # --- C. Analitik chat ---
    judul_seksi("Analitik Pertanyaan Pelanggan", f"{len(logs)} pertanyaan")
    if logs.empty:
        st.info("Belum ada riwayat pertanyaan.")
    else:
        kiri, kanan = st.columns(2)
        with kiri.container(border=True, key="panel_sebaran"):
            judul_panel("Distribusi kategori pertanyaan", "% dari total")
            sebaran = logs["kategori"].value_counts().rename_axis("kategori").reset_index(name="jumlah")
            sebaran["label"] = (sebaran["jumlah"] / sebaran["jumlah"].sum() * 100).round(1).astype(str) + "%"
            fig = px.bar(sebaran.sort_values("jumlah"), x="jumlah", y="kategori", orientation="h", text="label",
                         color_discrete_sequence=[W["accent"]], labels={"jumlah": "Jumlah pertanyaan", "kategori": ""})
            fig.update_traces(textfont_color=W["muted"], textposition="outside", cliponaxis=False)
            fig.update_xaxes(range=[0, sebaran["jumlah"].max() * 1.2])   # ruang untuk label persen
            st.plotly_chart(rapikan_grafik(fig, 340), width="stretch")
        with kanan.container(border=True, key="panel_tren"):
            judul_panel("Tren pertanyaan per hari", "jumlah pertanyaan")
            harian = (logs.assign(tanggal=pd.to_datetime(logs["waktu"]).dt.date)
                      .groupby("tanggal", as_index=False).size().rename(columns={"size": "jumlah"}))
            fig = px.area(harian, x="tanggal", y="jumlah", markers=True, color_discrete_sequence=[W["accent"]],
                          labels={"tanggal": "", "jumlah": "Jumlah pertanyaan"})
            merah, hijau, biru = (int(W["accent"][i:i + 2], 16) for i in (1, 3, 5))
            fig.update_traces(line_width=2.5, fillcolor=f"rgba({merah},{hijau},{biru},0.14)",
                              marker=dict(size=7, color=W["ground"], line=dict(color=W["accent"], width=2)))
            st.plotly_chart(rapikan_grafik(fig, 340), width="stretch")

        sumber = logs["sumber_data"].value_counts()
        st.markdown(
            '<div class="sk-src"><span>Sumber data chatbot</span>'
            + "".join(f'<div><span class="sk-badge {html.escape(str(s).lower())}">{html.escape(str(s))}</span>'
                      f"<b>{n}</b><small>pertanyaan</small></div>" for s, n in sumber.items())
            + "</div>",
            unsafe_allow_html=True,
        )

        with st.expander("Lihat 10 pertanyaan terbaru"):
            st.dataframe(logs.sort_values("waktu", ascending=False).head(10)[["waktu", "pertanyaan", "kategori", "sumber_data"]],
                         width="stretch", hide_index=True)
