"""
app.py - Tampilan utama Serat Karsa (Streamlit)
===============================================
Jalankan dengan:  streamlit run app.py

Isi halaman:
  - Sidebar : status sistem, tombol One-Click ETL Pipeline, upload PDF SOP
  - Tab 1   : Live Chatbot (Hybrid RAG) + expander "Lihat Proses Data"
  - Tab 2   : Inventory & Chat Analytics Dashboard
"""

import os
import sqlite3
import time

import pandas as pd
import plotly.express as px
import streamlit as st

from etl_pipeline import CHROMA_DIR, DB_PATH, NAMA_KOLEKSI, SOP_DIR, run_pipeline
from rag_sql_engine import MODEL_UTAMA, jawab_pertanyaan

# ---------------------------------------------------------------------------
# KONFIGURASI HALAMAN & WARNA
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Serat Karsa", page_icon="🪷", layout="wide")

TERAKOTA = "#C84B31"
EMAS = "#E6A100"
INDIGO = "#1F6E8C"
COKELAT = "#2C221E"
KREM = "#FFF3E0"
WARNA_KATEGORI = {"Pria": INDIGO, "Wanita": TERAKOTA}
BATAS_STOK_MENIPIS = 5

st.markdown(
    f"""
    <style>
      .judul-utama {{ font-size: 2.1rem; font-weight: 800; color: {TERAKOTA}; margin-bottom: 0; }}
      .sub-judul   {{ color: {COKELAT}; opacity: .75; margin-top: 0; }}
      .garis-batik {{ height: 6px; border-radius: 3px; margin: .4rem 0 1rem 0;
                      background: linear-gradient(90deg, {TERAKOTA} 0 40%, {EMAS} 40% 70%, {INDIGO} 70% 100%); }}
      [data-testid="stMetric"] {{ background: {KREM}; border-left: 5px solid {TERAKOTA};
                                  border-radius: 10px; padding: .8rem 1rem; }}
      .lencana {{ display: inline-block; padding: 2px 10px; border-radius: 12px; color: white;
                  font-size: .8rem; font-weight: 600; margin-right: 6px; }}
    </style>
    """,
    unsafe_allow_html=True,
)


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
    """Menyamakan gaya semua grafik Plotly dengan tema batik."""
    fig.update_layout(
        height=tinggi, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=COKELAT), legend_title_text="",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(gridcolor="#EADFCB")
    fig.update_yaxes(gridcolor="#EADFCB")
    return fig


# ---------------------------------------------------------------------------
# SIDEBAR - status sistem, ETL, upload PDF
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🪷 Serat Karsa")
    st.caption("Panel Admin & Tim Data")

    info = status_sistem()
    st.markdown("### Status Sistem")
    st.write("🟢 Gemini API key terpasang" if info["api_key"] else "🔴 GEMINI_API_KEY belum diisi di .env")
    st.write(f"🤖 Model: `{MODEL_UTAMA}`")
    if info["db"]:
        st.write(f"🗄️ SQL: {info['products']} produk, {info['orders']} pesanan, {info['chat_logs']} log chat")
    else:
        st.write("🔴 Database belum ada, jalankan ETL")
    st.write(f"📚 Vector DB: {info['chunk']} potongan dari {info['pdf']} PDF")

    st.divider()
    st.markdown("### One-Click ETL Pipeline")
    st.caption("Memperbarui tabel SQL dan memproses ulang semua PDF SOP.")

    pdf_baru = st.file_uploader(
        "Unggah PDF SOP tambahan (opsional)", type="pdf", accept_multiple_files=True,
        help="Isi PDF akan menjadi bahan jawaban chatbot. Unggah hanya dokumen kebijakan toko.",
    )

    if st.button("🚀 Jalankan ETL Pipeline", type="primary", width="stretch"):
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
        st.success(
            f"✅ ETL selesai pukul {h['waktu']} ({h['durasi']} detik)\n\n"
            f"- products: {h['baris_sql']['products']} baris\n"
            f"- orders: {h['baris_sql']['orders']} baris\n"
            f"- chat_logs: {h['baris_sql']['chat_logs']} baris\n"
            f"- Vector DB: {h['jumlah_chunk']} potongan dari {h['jumlah_pdf']} PDF"
        )

    # --- Kelola dokumen SOP: lihat & hapus PDF yang pernah diunggah ---
    with st.expander(f"📄 Kelola dokumen SOP ({info['pdf']} PDF)"):
        for pdf in sorted(SOP_DIR.glob("*.pdf")) if SOP_DIR.exists() else []:
            kiri, kanan = st.columns([4, 1])
            kiri.write(pdf.name)
            if pdf.name == "sop_serat_karsa.pdf":
                kanan.caption("utama")   # dibuat ulang otomatis oleh ETL, jadi tidak perlu dihapus
            elif kanan.button("🗑️", key=f"hapus-{pdf.name}", help=f"Hapus {pdf.name}"):
                pdf.unlink()
                st.session_state["perlu_etl"] = True
                st.rerun()

    if st.session_state.get("perlu_etl"):
        st.warning("Dokumen sudah dihapus, tetapi isinya masih ada di Vector DB. "
                   "Klik **Jalankan ETL Pipeline** agar chatbot berhenti memakainya.")


# ---------------------------------------------------------------------------
# JUDUL
# ---------------------------------------------------------------------------
st.markdown('<p class="judul-utama">🪷 Serat Karsa</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-judul">Smart Customer Service, ETL Pipeline, dan Inventory Analytics '
            'untuk bisnis batik modern</p>', unsafe_allow_html=True)
st.markdown('<div class="garis-batik"></div>', unsafe_allow_html=True)

if not info["db"]:
    st.warning("Database belum tersedia. Klik **Jalankan ETL Pipeline** di sidebar terlebih dahulu.")
    st.stop()

tab_chat, tab_dashboard = st.tabs(["💬 Live Chatbot", "📊 Inventory & Chat Analytics"])


# ---------------------------------------------------------------------------
# TAB 1 - LIVE CHATBOT
# ---------------------------------------------------------------------------
WARNA_RUTE = {"SQL": INDIGO, "PDF": EMAS, "HYBRID": TERAKOTA, "UMUM": "#7A6F68"}


def tampilkan_detail(detail):
    """Expander transparansi: memperlihatkan cara sistem menemukan jawabannya."""
    with st.expander("🔍 Lihat Proses Data (SQL & PDF)"):
        warna = WARNA_RUTE.get(detail.get("rute"), "#7A6F68")
        st.markdown(
            f'<span class="lencana" style="background:{warna}">Rute: {detail.get("rute")}</span>'
            f'<span class="lencana" style="background:#7A6F68">Kategori: {detail.get("kategori")}</span>',
            unsafe_allow_html=True,
        )
        if detail.get("sql"):
            st.markdown("**Kueri SQL yang dijalankan**")
            st.code(detail["sql"], language="sql")
            if detail.get("hasil_sql"):
                st.dataframe(pd.DataFrame(detail["hasil_sql"]), width="stretch", hide_index=True)
            else:
                st.caption("Kueri tidak mengembalikan baris.")
        if detail.get("kutipan_pdf"):
            st.markdown("**Kutipan dokumen SOP yang diambil**")
            for k in detail["kutipan_pdf"]:
                st.markdown(f"*{k['sumber']}, potongan {k['chunk']} (kemiripan {k['kemiripan']})*")
                st.info(k["teks"])
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

    st.caption("Contoh pertanyaan:")
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

    kotak_chat = st.container(height=480)
    with kotak_chat:
        for pesan in st.session_state["pesan"]:
            with st.chat_message(pesan["peran"], avatar="🪷" if pesan["peran"] == "assistant" else None):
                st.markdown(pesan["isi"])
                if pesan.get("detail"):
                    tampilkan_detail(pesan["detail"])

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
            with st.chat_message("assistant", avatar="🪷"):
                with st.spinner("Karsa sedang mencari data..."):
                    hasil = jawab_pertanyaan(pertanyaan_baru, riwayat)
        st.session_state["pesan"].append({"peran": "assistant", "isi": hasil["jawaban"], "detail": hasil})
        st.rerun()

    if len(st.session_state["pesan"]) > 1 and st.button("🧹 Hapus percakapan"):
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
    k1.metric("Model batik", produk["nama_model"].nunique())
    k2.metric("Total stok (pcs)", f"{int(produk['stok'].sum()):,}".replace(",", "."))
    k3.metric("SKU stok menipis", len(menipis), help=f"Stok di bawah {BATAS_STOK_MENIPIS} pcs")
    k4.metric("Pertanyaan pelanggan", len(logs))

    # --- A. Inventori: Pria vs Wanita ---
    st.subheader("Inventori: Batik Pria vs Wanita")
    per_kategori = produk.groupby("kategori").agg(stok=("stok", "sum"), harga=("harga", "mean"))
    kolom_kategori = st.columns(4)
    for i, kategori in enumerate(["Pria", "Wanita"]):
        if kategori in per_kategori.index:
            kolom_kategori[i * 2].metric(f"Stok {kategori}", f"{int(per_kategori.loc[kategori, 'stok'])} pcs")
            kolom_kategori[i * 2 + 1].metric(f"Rata-rata harga {kategori}", rupiah(per_kategori.loc[kategori, "harga"]))

    per_model = (produk.groupby(["nama_model", "kategori"], as_index=False)
                 .agg(total_stok=("stok", "sum"), rata_harga=("harga", "mean")))

    kiri, kanan = st.columns(2)
    with kiri:
        st.markdown("**Total stok per model**")
        fig = px.bar(per_model.sort_values("total_stok"), x="total_stok", y="nama_model", color="kategori",
                     orientation="h", color_discrete_map=WARNA_KATEGORI, text="total_stok",
                     labels={"total_stok": "Stok (pcs)", "nama_model": ""})
        st.plotly_chart(rapikan_grafik(fig), width="stretch")
    with kanan:
        st.markdown("**Rata-rata harga per model**")
        data_harga = per_model.sort_values("rata_harga").assign(label=lambda d: d["rata_harga"].map(rupiah))
        fig = px.bar(data_harga, x="rata_harga", y="nama_model", color="kategori", orientation="h",
                     color_discrete_map=WARNA_KATEGORI, text="label",
                     labels={"rata_harga": "Harga rata-rata (Rp)", "nama_model": ""})
        st.plotly_chart(rapikan_grafik(fig), width="stretch")

    # --- B. Low-Stock Alert ---
    st.subheader(f"Low-Stock Alert (stok di bawah {BATAS_STOK_MENIPIS} pcs)")
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
    st.subheader("Analitik Pertanyaan Pelanggan")
    if logs.empty:
        st.info("Belum ada riwayat pertanyaan.")
    else:
        kiri, kanan = st.columns(2)
        with kiri:
            st.markdown("**Distribusi kategori pertanyaan**")
            sebaran = logs["kategori"].value_counts().rename_axis("kategori").reset_index(name="jumlah")
            sebaran["label"] = (sebaran["jumlah"] / sebaran["jumlah"].sum() * 100).round(1).astype(str) + "%"
            fig = px.bar(sebaran.sort_values("jumlah"), x="jumlah", y="kategori", orientation="h", text="label",
                         color_discrete_sequence=[EMAS], labels={"jumlah": "Jumlah pertanyaan", "kategori": ""})
            st.plotly_chart(rapikan_grafik(fig, 340), width="stretch")
        with kanan:
            st.markdown("**Tren pertanyaan per hari**")
            harian = (logs.assign(tanggal=pd.to_datetime(logs["waktu"]).dt.date)
                      .groupby("tanggal", as_index=False).size().rename(columns={"size": "jumlah"}))
            fig = px.line(harian, x="tanggal", y="jumlah", markers=True, color_discrete_sequence=[INDIGO],
                          labels={"tanggal": "", "jumlah": "Jumlah pertanyaan"})
            st.plotly_chart(rapikan_grafik(fig, 340), width="stretch")

        st.markdown("**Sumber data yang dipakai chatbot**")
        sumber = logs["sumber_data"].value_counts().rename_axis("sumber").reset_index(name="jumlah")
        kolom_sumber = st.columns(len(sumber))
        for kolom, baris in zip(kolom_sumber, sumber.itertuples()):
            kolom.metric(baris.sumber, f"{baris.jumlah} pertanyaan")

        with st.expander("Lihat 10 pertanyaan terbaru"):
            st.dataframe(logs.sort_values("waktu", ascending=False).head(10)[["waktu", "pertanyaan", "kategori", "sumber_data"]],
                         width="stretch", hide_index=True)