"""
rag_sql_engine.py - Otak Hybrid RAG Serat Karsa
===============================================
Alur satu pertanyaan pelanggan:

  1. ROUTER   : Gemini memutuskan sumber data -> SQL, PDF, HYBRID, atau UMUM,
                sekaligus menulis kueri SQL dan kata kunci pencarian PDF.
  2. RETRIEVE : menjalankan kueri SQL (hanya-baca) dan/atau mencari potongan
                SOP yang paling mirip di ChromaDB.
  3. GENERATE : Gemini menyusun jawaban HANYA dari data yang ditemukan.
  4. LOG      : pertanyaan + kategori disimpan ke tabel chat_logs.

Cara tes dari terminal :  python rag_sql_engine.py
Cara pakai dari app.py :  from rag_sql_engine import jawab_pertanyaan
"""

import json
import os
import re
import sqlite3
import time
from datetime import datetime

from dotenv import load_dotenv

from etl_pipeline import CHROMA_DIR, DB_PATH, NAMA_KOLEKSI, buat_client_gemini, buat_embedding

load_dotenv()

MODEL_UTAMA = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
MODEL_CADANGAN = os.getenv("GEMINI_MODEL_CADANGAN", "")
JUMLAH_KUTIPAN_PDF = 5    # berapa potongan SOP yang diambil per pertanyaan
MAKS_BARIS_SQL = 30        # batas baris hasil SQL yang dikirim ke Gemini

KATEGORI_VALID = ["Stok & Harga", "Retur & SOP", "Lacak Pesanan", "Rekomendasi", "Lainnya"]
RUTE_VALID = ["SQL", "PDF", "HYBRID", "UMUM"]

_client = None  # client Gemini dibuat sekali lalu dipakai ulang


def _gemini():
    global _client
    if _client is None:
        _client = buat_client_gemini()
    return _client


# ===========================================================================
# 1. MEMANGGIL GEMINI (dengan model cadangan bila server sibuk)
# ===========================================================================

def panggil_llm(prompt, format_json=False):
    """Mengirim prompt ke Gemini. Jika model utama gagal, pindah ke model cadangan."""
    from google.genai import types

    config = types.GenerateContentConfig(response_mime_type="application/json") if format_json else None
    daftar_model = [m for m in (MODEL_UTAMA, MODEL_CADANGAN) if m]
    error_terakhir = None
    for putaran in range(2):                 # dua putaran: utama -> cadangan -> utama -> cadangan
        for model in daftar_model:
            try:
                respons = _gemini().models.generate_content(model=model, contents=prompt, config=config)
                if respons.text:
                    return respons.text.strip()
                error_terakhir = RuntimeError("Gemini mengembalikan jawaban kosong")
            except Exception as e:           # 503 server sibuk, 429 kuota habis, dll.
                error_terakhir = e
        time.sleep(4 * (putaran + 1))
    raise RuntimeError(f"Gemini tidak bisa dihubungi: {error_terakhir}")


def _baca_json(teks):
    """Mengubah teks jawaban Gemini menjadi dict Python, walau dibungkus ```json ... ```."""
    teks = re.sub(r"^```(?:json)?|```$", "", teks.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(teks)
    except json.JSONDecodeError:
        cocok = re.search(r"\{.*\}", teks, flags=re.DOTALL)
        if cocok:
            return json.loads(cocok.group(0))
        raise


# ===========================================================================
# 2. ROUTER - menentukan sumber data + menulis SQL
# ===========================================================================

SKEMA_DB = """
Tabel products (katalog, satu baris = satu kombinasi model + motif + ukuran):
  product_id INTEGER, sku TEXT,
  nama_model TEXT  -- salah satu dari: 'Kemeja Batik Lengan Panjang', 'Kemeja Batik Lengan Pendek',
                   -- 'Batik Kombinasi Polos', 'Jas / Outer Batik Pria', 'Tunik Batik', 'Gamis & Dress Batik',
                   -- 'Outer / Cardigan / Blazer Batik', 'Kaftan Batik', 'Blus Batik (Blouse)',
                   -- 'Model Kutubaru', 'Rok Batik & One Set'
  kategori TEXT    -- 'Pria' atau 'Wanita'
  motif TEXT       -- 'Parang', 'Kawung', 'Mega Mendung', 'Truntum', 'Sekar Jagad'
  jenis_kain TEXT  -- 'Katun Primisima', 'Dobby', 'Viscose', 'Sutra Baron'
  teknik TEXT      -- 'Tulis' atau 'Cap'
  ukuran TEXT      -- 'S', 'M', 'L', 'XL', 'XXL'
  harga INTEGER    -- Rupiah
  stok INTEGER     -- pcs; 0 berarti habis
  deskripsi TEXT

Tabel orders (pesanan pelanggan):
  order_id TEXT    -- format '#SK-101'
  nama_pelanggan TEXT, product_id INTEGER (-> products.product_id), jumlah INTEGER,
  total_harga INTEGER, tanggal_pesan TEXT (YYYY-MM-DD),
  status TEXT      -- 'Diproses', 'Dikemas', 'Dikirim', 'Selesai', 'Dibatalkan'
  kurir TEXT, no_resi TEXT   -- NULL jika belum dikirim
"""

PROMPT_ROUTER = """Kamu adalah router untuk chatbot layanan pelanggan toko batik "Serat Karsa".
Tugasmu menentukan sumber data untuk menjawab pertanyaan pelanggan, BUKAN menjawabnya.

SUMBER DATA:
- SQL    : database katalog & pesanan (harga, stok, ukuran, motif, kain, status/resi pesanan).
- PDF    : dokumen SOP (aturan retur & tukar ukuran, cara merawat/mencuci batik, makna motif,
           rekomendasi motif & model untuk acara, panduan ukuran, jadwal & estimasi pengiriman),
           ditambah dokumen kebijakan lain yang diunggah admin (misalnya promo atau jam operasional).
           Jika ragu antara PDF dan UMUM untuk pertanyaan seputar toko, pilih PDF.
- HYBRID : butuh keduanya (contoh: "batik untuk kondangan yang stok M-nya ada").
- UMUM   : sapaan, ucapan terima kasih, atau pertanyaan di luar topik toko.

SKEMA DATABASE (SQLite):
{skema}

ATURAN MENULIS SQL:
- Hanya satu pernyataan SELECT. Jangan pernah mengubah data.
- Cocokkan teks dengan LIKE dan % (contoh: nama_model LIKE '%Kemeja%Panjang%').
- "Tersedia / ready / masih ada" berarti stok > 0.
- Untuk tabel orders WAJIB memfilter order_id = '#SK-xxx' sesuai nomor yang disebut pelanggan.
  Jika pelanggan tidak menyebut nomor order, isi "sql" dengan null.
- Saat mengambil pesanan, JOIN ke products agar nama_model, motif, dan ukuran ikut tampil.
- Setiap kueri ke tabel products WAJIB menyertakan kolom nama_model, motif, ukuran, harga, stok
  (boleh ditambah jenis_kain atau teknik bila relevan), lalu tambahkan LIMIT 20.
- Untuk rute HYBRID, kamu boleh memakai pengetahuan dari daftar motif/model di skema
  untuk membuat filter SQL yang masuk akal.

RIWAYAT PERCAKAPAN TERAKHIR (untuk memahami pertanyaan lanjutan):
{riwayat}

PERTANYAAN PELANGGAN:
{pertanyaan}

Balas HANYA dengan JSON berbentuk:
{{
  "rute": "SQL" | "PDF" | "HYBRID" | "UMUM",
  "kategori": "Stok & Harga" | "Retur & SOP" | "Lacak Pesanan" | "Rekomendasi" | "Lainnya",
  "sql": "SELECT ..." atau null,
  "kueri_pdf": "kalimat pencarian untuk dokumen SOP" atau null
}}"""


def tentukan_rute(pertanyaan, riwayat=None):
    """Meminta Gemini memilih rute. Mengembalikan dict: rute, kategori, sql, kueri_pdf."""
    teks_riwayat = "\n".join(f"{peran}: {isi}" for peran, isi in (riwayat or [])[-4:]) or "(belum ada)"
    prompt = PROMPT_ROUTER.format(skema=SKEMA_DB, riwayat=teks_riwayat, pertanyaan=pertanyaan)
    hasil = _baca_json(panggil_llm(prompt, format_json=True))

    rute = str(hasil.get("rute", "")).upper()
    if rute not in RUTE_VALID:
        rute = "PDF"  # pilihan aman: cari di SOP daripada mengarang
    kategori = hasil.get("kategori")
    if kategori not in KATEGORI_VALID:
        kategori = "Lainnya"
    return {
        "rute": rute,
        "kategori": kategori,
        "sql": hasil.get("sql") or None,
        "kueri_pdf": hasil.get("kueri_pdf") or pertanyaan,
    }


PROMPT_SQL_HYBRID = """Kamu menulis kueri SQLite untuk chatbot toko batik "Serat Karsa".
Pelanggan meminta rekomendasi. Kutipan dokumen SOP di bawah menjelaskan model dan motif
yang disarankan (atau kurang dianjurkan) untuk berbagai acara.

SKEMA DATABASE:
{skema}

KUTIPAN DOKUMEN SOP:
{kutipan}

PERTANYAAN PELANGGAN:
{pertanyaan}

KUERI AWAL (belum memperhitungkan SOP):
{sql_awal}

TUGAS: tulis ulang kueri agar hanya mengambil produk yang sesuai SOP untuk acara yang ditanyakan.
- Tambahkan filter nama_model IN (...) berisi model yang disarankan SOP untuk acara itu
  (sesuaikan dengan kategori Pria/Wanita yang diminta pelanggan).
- Tambahkan filter motif IN (...) berisi HANYA motif yang disarankan SOP untuk acara itu.
  Jangan sertakan motif yang menurut SOP kurang dianjurkan.
- Tulis nama model dan motif PERSIS seperti di skema.
- Pertahankan filter lain dari pelanggan (ukuran, harga, stok > 0, dan seterusnya).
- SELECT wajib memuat nama_model, motif, ukuran, harga, stok. Urutkan dengan ORDER BY nama_model, harga
  dan akhiri dengan LIMIT 20. Hanya satu pernyataan SELECT.
- Jika kutipan SOP tidak membahas acara yang ditanyakan, kembalikan kueri awal apa adanya.

Balas HANYA dengan JSON: {{"sql": "SELECT ..."}}"""


def tulis_sql_hybrid(pertanyaan, kutipan, sql_awal):
    """Rute HYBRID: menulis SQL yang filternya mengikuti anjuran SOP (model & motif per acara)."""
    teks_kutipan = "\n\n".join(k["teks"] for k in kutipan)
    prompt = PROMPT_SQL_HYBRID.format(skema=SKEMA_DB, kutipan=teks_kutipan,
                                      pertanyaan=pertanyaan, sql_awal=sql_awal or "(tidak ada)")
    return _baca_json(panggil_llm(prompt, format_json=True)).get("sql") or sql_awal


# ===========================================================================
# 3. RETRIEVE - SQL (hanya-baca) dan Vector Search
# ===========================================================================

def validasi_sql(sql):
    """Pagar pengaman: memastikan SQL buatan AI aman dijalankan. Error jika tidak aman."""
    bersih = sql.strip().rstrip(";").strip()
    if ";" in bersih:
        raise ValueError("Hanya boleh satu pernyataan SQL.")
    if not re.match(r"(?is)^(select|with)\b", bersih):
        raise ValueError("Hanya kueri SELECT yang diizinkan.")
    if re.search(r"(?i)\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum)\b", bersih):
        raise ValueError("Kueri mengandung perintah yang dilarang.")
    if re.search(r"(?i)\b(chat_logs|sqlite_master|sqlite_schema)\b", bersih):
        raise ValueError("Tabel tersebut tidak boleh diakses chatbot.")
    # privasi: data pesanan hanya boleh dibuka dengan nomor order yang spesifik
    if re.search(r"(?i)\borders\b", bersih):
        if not re.search(r"(?i)order_id\s*=\s*'#SK-\d+'", bersih) or re.search(r"(?i)\bor\b", bersih):
            raise ValueError("Data pesanan hanya bisa dicek dengan satu nomor order, contoh #SK-101.")
    return bersih


def jalankan_sql(sql):
    """Menjalankan SELECT pada koneksi hanya-baca. Mengembalikan list of dict."""
    sql = validasi_sql(sql)
    # mode=ro = read only; walau validasi terlewat, database tetap tidak bisa diubah
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        baris = conn.execute(sql).fetchmany(MAKS_BARIS_SQL)
        return [dict(b) for b in baris]
    finally:
        conn.close()


def ambil_data_sql(sql, pertanyaan):
    """Menjalankan SQL; jika error sintaks, minta Gemini memperbaikinya satu kali."""
    try:
        return sql, jalankan_sql(sql), None
    except ValueError as e:          # ditolak pagar pengaman -> jangan dicoba ulang
        return sql, [], str(e)
    except sqlite3.Error as e:
        prompt = (
            f"Kueri SQLite berikut error.\n\nSKEMA:\n{SKEMA_DB}\n\nPERTANYAAN: {pertanyaan}\n"
            f"KUERI: {sql}\nERROR: {e}\n\n"
            'Perbaiki kuerinya. Balas HANYA dengan JSON: {"sql": "SELECT ..."}'
        )
        try:
            sql_baru = _baca_json(panggil_llm(prompt, format_json=True))["sql"]
            return sql_baru, jalankan_sql(sql_baru), None
        except Exception as e2:
            return sql, [], f"Kueri gagal dijalankan: {e2}"


def cari_di_pdf(kueri, jumlah=JUMLAH_KUTIPAN_PDF):
    """Mencari potongan SOP yang maknanya paling mirip dengan kueri."""
    import chromadb

    db = chromadb.PersistentClient(path=str(CHROMA_DIR))
    koleksi = db.get_collection(NAMA_KOLEKSI)
    # WAJIB memakai model embedding yang sama dengan saat ETL
    model = (koleksi.metadata or {}).get("model_embedding") or os.getenv("GEMINI_EMBED_MODEL")
    vektor = buat_embedding(_gemini(), model, kueri)
    hasil = koleksi.query(query_embeddings=[vektor], n_results=jumlah)
    kutipan = []
    for teks, meta, jarak in zip(hasil["documents"][0], hasil["metadatas"][0], hasil["distances"][0]):
        kutipan.append({
            "teks": teks,
            "sumber": meta.get("sumber", "?"),
            "chunk": meta.get("chunk", "?"),
            "kemiripan": round(1 - jarak, 3),   # jarak cosine -> makin dekat 1 makin mirip
        })
    return kutipan


# ===========================================================================
# 4. GENERATE - menyusun jawaban dari data yang ditemukan
# ===========================================================================

PROMPT_JAWABAN = """Kamu adalah "Karsa", asisten layanan pelanggan toko batik modern "Serat Karsa".
Jawab pertanyaan pelanggan dalam Bahasa Indonesia yang ramah, sopan, dan ringkas.

ATURAN PENTING:
- Jawab HANYA berdasarkan DATA di bawah. Jangan mengarang harga, stok, resi, atau aturan.
- Jika data tidak cukup untuk menjawab, katakan terus terang dan sarankan langkah berikutnya
  (misalnya meminta nomor order berformat #SK-101, atau menghubungi admin).
- Tulis harga dalam format Rupiah, contoh: Rp285.000.
- Jika hasilnya lebih dari tiga produk, tampilkan sebagai daftar singkat.
- Jangan menyebut istilah teknis seperti SQL, database, chunk, atau PDF kepada pelanggan.
- Langsung jawab intinya. Jangan memperkenalkan diri atau mengucapkan salam pembuka,
  kecuali pelanggan sendiri yang menyapa lebih dulu.
- Untuk permintaan rekomendasi: tampilkan HANYA produk yang model DAN motifnya disarankan
  dokumen SOP untuk acara tersebut. Jangan pernah menawarkan motif yang menurut SOP kurang
  dianjurkan untuk acara itu, walaupun stoknya ada. Jika tidak ada produk yang cocok, katakan terus terang.
- Stok dicatat per ukuran. Setiap baris data katalog adalah satu kombinasi model + motif + ukuran,
  dan semua baris di bawah SUDAH memenuhi filter pada kueri penyaring.

RIWAYAT PERCAKAPAN TERAKHIR:
{riwayat}

KUERI PENYARING YANG DIPAKAI (hanya untuk kamu pahami, jangan ditampilkan):
{sql}

DATA DARI KATALOG / PESANAN:
{data_sql}

DATA DARI DOKUMEN SOP:
{data_pdf}

PERTANYAAN PELANGGAN:
{pertanyaan}

JAWABAN:"""


def _format_baris(baris):
    if not baris:
        return "(tidak ada data)"
    return "\n".join(json.dumps(b, ensure_ascii=False) for b in baris)


def simpan_log(pertanyaan, kategori, sumber):
    """Mencatat pertanyaan ke chat_logs untuk dianalisis di dashboard."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO chat_logs (waktu, pertanyaan, kategori, sumber_data) VALUES (?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pertanyaan, kategori, sumber),
    )
    conn.commit()
    conn.close()


def jawab_pertanyaan(pertanyaan, riwayat=None, catat_log=True):
    """Fungsi utama yang dipanggil app.py.

    riwayat: list berisi (peran, isi), contoh [("Pelanggan", "..."), ("Karsa", "...")]
    Mengembalikan dict: jawaban, rute, kategori, sql, hasil_sql, kutipan_pdf, catatan
    """
    hasil = {"jawaban": "", "rute": None, "kategori": "Lainnya", "sql": None,
             "hasil_sql": [], "kutipan_pdf": [], "catatan": []}
    try:
        keputusan = tentukan_rute(pertanyaan, riwayat)
        hasil.update(rute=keputusan["rute"], kategori=keputusan["kategori"])
        rute = keputusan["rute"]

        # SOP dicari LEBIH DULU, supaya pada rute HYBRID isinya bisa dipakai untuk menulis SQL
        if rute in ("PDF", "HYBRID"):
            try:
                hasil["kutipan_pdf"] = cari_di_pdf(keputusan["kueri_pdf"])
            except Exception as e:
                hasil["catatan"].append(f"Pencarian SOP gagal: {e}")

        if rute == "HYBRID" and hasil["kutipan_pdf"]:
            try:
                keputusan["sql"] = tulis_sql_hybrid(pertanyaan, hasil["kutipan_pdf"], keputusan["sql"])
            except Exception as e:   # kalau gagal, pakai SQL dari router apa adanya
                hasil["catatan"].append(f"SQL hybrid gagal dibuat, memakai SQL router: {e}")

        if rute in ("SQL", "HYBRID"):
            if keputusan["sql"]:
                sql, baris, galat = ambil_data_sql(keputusan["sql"], pertanyaan)
                hasil.update(sql=sql, hasil_sql=baris)
                if galat:
                    hasil["catatan"].append(galat)
            else:
                hasil["catatan"].append("Router tidak membuat SQL (informasi dari pelanggan belum lengkap).")

        teks_riwayat = "\n".join(f"{p}: {i}" for p, i in (riwayat or [])[-4:]) or "(belum ada)"
        data_sql = _format_baris(hasil["hasil_sql"]) if rute in ("SQL", "HYBRID") else "(tidak dipakai)"
        if hasil["catatan"] and rute in ("SQL", "HYBRID"):
            data_sql += "\nCatatan sistem: " + " ".join(hasil["catatan"])
        data_pdf = "\n\n".join(f"[{k['sumber']}] {k['teks']}" for k in hasil["kutipan_pdf"]) or "(tidak dipakai)"

        hasil["jawaban"] = panggil_llm(PROMPT_JAWABAN.format(
            riwayat=teks_riwayat, sql=hasil["sql"] or "(tidak ada)", data_sql=data_sql, data_pdf=data_pdf, pertanyaan=pertanyaan))

    except Exception as e:
        hasil["jawaban"] = ("Maaf, sistem kami sedang sibuk sehingga saya belum bisa menjawab. "
                            "Silakan coba lagi sebentar lagi ya.")
        hasil["catatan"].append(f"Error: {e}")

    if catat_log:
        try:
            simpan_log(pertanyaan, hasil["kategori"], hasil["rute"] or "ERROR")
        except Exception as e:
            hasil["catatan"].append(f"Gagal menyimpan log: {e}")
    return hasil


# ===========================================================================
# TES CEPAT DARI TERMINAL
# ===========================================================================

if __name__ == "__main__":
    contoh_pertanyaan = [
        "Kemeja batik lengan panjang ukuran L masih ada? Harganya berapa?",   # harapan: SQL
        "Kalau ukurannya kekecilan, syarat tukar ukurannya apa saja?",        # harapan: PDF
        "Pesanan #SK-103 sudah sampai mana ya?",                              # harapan: SQL
        "Rekomendasi batik wanita untuk kondangan yang ready ukuran M dong",  # harapan: HYBRID
    ]
    print("Versi engine: 3 (HYBRID mencari SOP dulu, lalu menulis SQL)")
    for tanya in contoh_pertanyaan:
        print("=" * 70)
        print("TANYA   :", tanya)
        h = jawab_pertanyaan(tanya, catat_log=False)   # tes tidak ikut tercatat di chat_logs
        print("RUTE    :", h["rute"], "|", h["kategori"])
        if h["sql"]:
            print("SQL     :", h["sql"])
            print("BARIS   :", len(h["hasil_sql"]))
        for k in h["kutipan_pdf"]:
            print(f"KUTIPAN : ({k['kemiripan']}) {k['teks'][:80]}...")
        if h["catatan"]:
            print("CATATAN :", h["catatan"])
        print("JAWABAN :", h["jawaban"])
        time.sleep(5)   # jeda agar tidak melewati batas kuota gratis per menit