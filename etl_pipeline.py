"""
etl_pipeline.py - Pipeline ETL Serat Karsa
==========================================
Extract   : membuat data katalog/pesanan dan membaca teks dari PDF SOP
Transform : membersihkan teks dan memotongnya menjadi potongan kecil (chunk)
Load      : menyimpan tabel ke SQLite dan potongan teks ke ChromaDB

Cara pakai dari terminal :  python etl_pipeline.py
Cara pakai dari app.py   :  from etl_pipeline import run_pipeline
"""

import os
import random
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# KONFIGURASI LOKASI FILE
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SOP_DIR = DATA_DIR / "sop"                 # semua PDF SOP disimpan di sini
DB_PATH = DATA_DIR / "serat_karsa.db"      # database SQLite
CHROMA_DIR = DATA_DIR / "chroma_db"        # folder Vector DB
SOP_UTAMA = SOP_DIR / "sop_serat_karsa.pdf"
NAMA_KOLEKSI = "sop_serat_karsa"

UKURAN_CHUNK = 700    # panjang maksimal satu potongan teks (karakter)
OVERLAP_CHUNK = 150   # bagian yang diulang antar potongan agar konteks tidak putus


# ===========================================================================
# BAGIAN 1 - DATA TERSTRUKTUR (SQL)
# ===========================================================================

# (nama_model, kategori, harga_dasar, deskripsi)
MODEL_BATIK = [
    ("Kemeja Batik Lengan Panjang", "Pria", 285000, "Klasik dan paling formal untuk bekerja, rapat, atau acara resmi."),
    ("Kemeja Batik Lengan Pendek", "Pria", 235000, "Santai namun rapi untuk business casual atau kegiatan harian."),
    ("Batik Kombinasi Polos", "Pria", 265000, "Memadukan kain batik dengan kain polos di kerah, saku, atau sisi badan."),
    ("Jas / Outer Batik Pria", "Pria", 495000, "Bahan tebal dan kokoh yang dijahit menjadi blazer atau jas kontemporer."),
    ("Tunik Batik", "Wanita", 275000, "Atasan panjang sampai paha/lutut untuk kerja maupun acara semi-formal."),
    ("Gamis & Dress Batik", "Wanita", 385000, "Terusan panjang atau midi dress yang feminin untuk pesta dan kondangan."),
    ("Outer / Cardigan / Blazer Batik", "Wanita", 325000, "Luaran praktis yang cocok dipadukan dengan kaos atau kemeja polos."),
    ("Kaftan Batik", "Wanita", 345000, "Model longgar dan lebar yang nyaman namun tetap anggun."),
    ("Blus Batik (Blouse)", "Wanita", 245000, "Atasan dengan variasi lengan 7/8 atau lengan balon untuk kerja harian."),
    ("Model Kutubaru", "Wanita", 295000, "Atasan tradisional dengan kain pelengkap di dada yang dimodernisasi."),
    ("Rok Batik & One Set", "Wanita", 365000, "Rok lilit atau setelan atasan dan bawahan dengan motif senada."),
]

MOTIF = ["Parang", "Kawung", "Mega Mendung", "Truntum", "Sekar Jagad"]

# jenis kain -> pengali harga
KAIN = {"Katun Primisima": 1.0, "Dobby": 1.1, "Viscose": 1.15, "Sutra Baron": 1.6}

# teknik pembuatan -> pengali harga (batik tulis jauh lebih mahal)
TEKNIK = {"Cap": 1.0, "Tulis": 2.2}

UKURAN = ["S", "M", "L", "XL", "XXL"]


def buat_data_produk():
    """Membuat daftar produk: 11 model x 3 varian motif x 5 ukuran = 165 baris."""
    rng = random.Random(42)  # angka 42 = "seed", supaya data acaknya selalu sama
    produk = []
    for nomor_model, (nama, kategori, harga_dasar, deskripsi) in enumerate(MODEL_BATIK, start=1):
        for nomor_varian, motif in enumerate(rng.sample(MOTIF, 3), start=1):
            kain = rng.choice(list(KAIN))
            teknik = rng.choices(list(TEKNIK), weights=[75, 25])[0]
            harga = harga_dasar * KAIN[kain] * TEKNIK[teknik]
            harga = int(round(harga / 5000) * 5000)  # bulatkan ke kelipatan 5.000
            for ukuran in UKURAN:
                # stok sengaja dibuat beragam: ada yang habis, menipis, dan aman
                stok = rng.choices(
                    [0, rng.randint(1, 4), rng.randint(5, 30)], weights=[6, 14, 80]
                )[0]
                sku = f"SK-{nomor_model:02d}{nomor_varian}-{ukuran}"
                produk.append((sku, nama, kategori, motif, kain, teknik, ukuran, harga, stok, deskripsi))
    return produk


def buat_data_pesanan(conn, jumlah=25):
    """Membuat pesanan dummy yang merujuk ke produk yang benar-benar ada."""
    rng = random.Random(7)
    nama_pelanggan = [
        "Andi Pratama", "Siti Rahma", "Budi Santoso", "Dewi Lestari", "Rizky Maulana",
        "Putri Ayu", "Agus Wijaya", "Maya Sari", "Fajar Nugroho", "Nadia Kusuma",
    ]
    daftar_produk = conn.execute("SELECT product_id, harga FROM products").fetchall()
    sekarang = datetime.now()
    pesanan = []
    for i in range(jumlah):
        order_id = f"#SK-{101 + i}"
        product_id, harga = rng.choice(daftar_produk)
        qty = rng.randint(1, 3)
        tanggal = sekarang - timedelta(days=rng.randint(0, 20))
        status = rng.choices(
            ["Diproses", "Dikemas", "Dikirim", "Selesai", "Dibatalkan"],
            weights=[15, 15, 30, 32, 8],
        )[0]
        # resi baru ada kalau paket sudah diserahkan ke kurir
        if status in ("Dikirim", "Selesai"):
            kurir = rng.choice(["JNE", "J&T", "SiCepat", "AnterAja"])
            resi = f"{kurir[:3].upper().replace('&', 'N')}{rng.randint(10**9, 10**10 - 1)}"
        else:
            kurir, resi = None, None
        pesanan.append((
            order_id, rng.choice(nama_pelanggan), product_id, qty, harga * qty,
            tanggal.strftime("%Y-%m-%d"), status, kurir, resi,
        ))
    return pesanan


def buat_data_chat_logs(jumlah=60):
    """Riwayat chat dummy agar dashboard analitik tidak kosong saat pertama dibuka."""
    rng = random.Random(11)
    contoh = {
        "Stok & Harga": (45, "SQL", [
            "Kemeja lengan panjang motif Parang ukuran L masih ada?",
            "Berapa harga tunik batik?",
            "Kaftan ukuran XL ready stok tidak?",
            "Ada batik pria di bawah 300 ribu?",
            "Gamis motif Mega Mendung tersedia ukuran apa saja?",
        ]),
        "Retur & SOP": (25, "PDF", [
            "Kalau kekecilan bisa tukar ukuran?",
            "Syarat retur apa saja?",
            "Cara mencuci batik tulis bagaimana?",
            "Boleh disetrika langsung tidak?",
        ]),
        "Lacak Pesanan": (20, "SQL", [
            "Pesanan #SK-105 sudah sampai mana?",
            "Minta nomor resi order #SK-112",
            "Status pesanan saya #SK-120 apa ya?",
        ]),
        "Rekomendasi": (10, "HYBRID", [
            "Batik apa yang cocok untuk wisuda dan stoknya ada?",
            "Rekomendasi batik untuk kondangan yang ready ukuran M",
        ]),
    }
    kategori = list(contoh)
    bobot = [contoh[k][0] for k in kategori]
    sekarang = datetime.now()
    logs = []
    for _ in range(jumlah):
        k = rng.choices(kategori, weights=bobot)[0]
        _, sumber, daftar_pertanyaan = contoh[k]
        waktu = sekarang - timedelta(days=rng.randint(0, 13), minutes=rng.randint(0, 1439))
        logs.append((waktu.strftime("%Y-%m-%d %H:%M:%S"), rng.choice(daftar_pertanyaan), k, sumber))
    return sorted(logs)


def load_sql():
    """LOAD data terstruktur ke SQLite. Mengembalikan jumlah baris tiap tabel."""
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # products & orders dibuat ulang setiap ETL (data master selalu segar)
    cur.executescript("""
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS products;

        CREATE TABLE products (
            product_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            sku         TEXT UNIQUE NOT NULL,
            nama_model  TEXT NOT NULL,   -- salah satu dari 11 model batik
            kategori    TEXT NOT NULL,   -- 'Pria' atau 'Wanita'
            motif       TEXT NOT NULL,   -- Parang, Kawung, Mega Mendung, Truntum, Sekar Jagad
            jenis_kain  TEXT NOT NULL,   -- Katun Primisima, Dobby, Viscose, Sutra Baron
            teknik      TEXT NOT NULL,   -- 'Tulis' atau 'Cap'
            ukuran      TEXT NOT NULL,   -- S, M, L, XL, XXL
            harga       INTEGER NOT NULL, -- dalam Rupiah
            stok        INTEGER NOT NULL, -- jumlah pcs tersedia
            deskripsi   TEXT
        );

        CREATE TABLE orders (
            order_id        TEXT PRIMARY KEY,  -- contoh: '#SK-101'
            nama_pelanggan  TEXT NOT NULL,
            product_id      INTEGER NOT NULL REFERENCES products(product_id),
            jumlah          INTEGER NOT NULL,
            total_harga     INTEGER NOT NULL,
            tanggal_pesan   TEXT NOT NULL,     -- format YYYY-MM-DD
            status          TEXT NOT NULL,     -- Diproses, Dikemas, Dikirim, Selesai, Dibatalkan
            kurir           TEXT,
            no_resi         TEXT
        );

        -- chat_logs TIDAK dihapus, supaya riwayat chat asli tetap tersimpan
        CREATE TABLE IF NOT EXISTS chat_logs (
            log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            waktu        TEXT NOT NULL,
            pertanyaan   TEXT NOT NULL,
            kategori     TEXT NOT NULL,  -- Stok & Harga, Retur & SOP, Lacak Pesanan, Rekomendasi, Lainnya
            sumber_data  TEXT NOT NULL   -- SQL, PDF, atau HYBRID
        );
    """)

    cur.executemany(
        """INSERT INTO products
           (sku, nama_model, kategori, motif, jenis_kain, teknik, ukuran, harga, stok, deskripsi)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        buat_data_produk(),
    )
    cur.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", buat_data_pesanan(conn))

    # isi chat_logs dengan data contoh hanya jika tabelnya masih kosong
    if cur.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO chat_logs (waktu, pertanyaan, kategori, sumber_data) VALUES (?, ?, ?, ?)",
            buat_data_chat_logs(),
        )

    conn.commit()
    jumlah = {
        tabel: cur.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]
        for tabel in ("products", "orders", "chat_logs")
    }
    conn.close()
    return jumlah


# ===========================================================================
# BAGIAN 2 - DATA TIDAK TERSTRUKTUR (PDF SOP)
# ===========================================================================

# Catatan: font bawaan PDF hanya mendukung huruf Latin biasa, jadi teks di bawah
# sengaja tidak memakai emoji atau simbol khusus.
ISI_SOP = [
    ("SOP 1 - KEBIJAKAN RETUR DAN TUKAR UKURAN", [
        "Serat Karsa menerima pengajuan retur atau tukar ukuran maksimal 3 (tiga) hari kalender sejak paket diterima pelanggan, dihitung dari tanggal status terkirim pada sistem kurir. Pengajuan setelah 3 hari tidak dapat diproses.",
        "Pelanggan WAJIB menyertakan video unboxing tanpa jeda dan tanpa potongan, dimulai dari paket masih tersegel sampai produk dikeluarkan dan diperiksa. Tanpa video unboxing, klaim retur maupun tukar ukuran tidak dapat diterima.",
        "Syarat produk yang ditukar: belum dicuci, belum dipakai selain untuk mencoba, tidak berbau parfum atau rokok, label dan hangtag masih terpasang, serta dikembalikan dengan kemasan aslinya.",
        "Tukar ukuran hanya berlaku untuk model dan motif yang sama, selama stok ukuran pengganti masih tersedia. Jika stok habis, pelanggan dapat memilih model lain dengan harga setara atau menerima pengembalian dana.",
        "Ongkos kirim tukar ukuran ditanggung pelanggan. Jika kesalahan berasal dari Serat Karsa, misalnya salah kirim produk atau produk cacat, seluruh ongkos kirim ditanggung Serat Karsa.",
        "Produk yang tidak dapat diretur: produk diskon di atas 50 persen, produk pesanan khusus (custom), dan batik tulis yang sudah dipotong atau dipermak.",
        "Pengembalian dana diproses 3 sampai 5 hari kerja setelah produk diterima dan lolos pemeriksaan tim gudang, ke rekening atau metode pembayaran asal.",
        "Cara mengajukan: hubungi layanan pelanggan dengan menyebutkan nomor order (contoh: #SK-101), alasan retur, dan lampirkan video unboxing.",
    ]),
    ("SOP 2 - PANDUAN PERAWATAN BATIK TULIS DAN BATIK CAP", [
        "Batik tulis dibuat sepenuhnya dengan tangan menggunakan canting dan malam, sehingga warnanya lebih peka dan memerlukan perawatan lebih hati-hati dibanding batik cap.",
        "Perawatan batik tulis: cuci dengan tangan menggunakan lerak atau sabun khusus batik. Jangan gunakan deterjen biasa, pemutih, atau mesin cuci. Rendam maksimal 15 menit, kucek perlahan, dan jangan diperas atau dipelintir.",
        "Perawatan batik cap: tetap dianjurkan dicuci dengan tangan menggunakan lerak atau sampo. Jika terpaksa memakai mesin cuci, gunakan mode lembut (gentle), air dingin, dan masukkan batik ke dalam kantong cuci (laundry bag).",
        "Penjemuran: jangan dijemur langsung di bawah sinar matahari karena warna batik akan cepat pudar. Angin-anginkan di tempat teduh dengan posisi kain bagian dalam menghadap keluar.",
        "Penyetrikaan: gunakan suhu rendah sampai sedang. Setrika dari bagian dalam kain atau lapisi dengan kain tipis. Jangan semprotkan pewangi atau pelicin langsung ke permukaan batik.",
        "Penyimpanan: gantung atau lipat rapi di lemari yang kering. Hindari kapur barus yang bersentuhan langsung dengan kain; gunakan merica atau akar wangi yang dibungkus tisu sebagai pengusir ngengat.",
        "Kain Sutra Baron sebaiknya dibawa ke dry clean. Kain Katun Primisima, Dobby, dan Viscose aman dicuci tangan sesuai panduan di atas.",
        "Cucian pertama: sedikit luntur pada cucian pertama adalah hal yang wajar, terutama untuk batik tulis berwarna gelap. Cuci terpisah dari pakaian lain pada 2 sampai 3 cucian pertama.",
    ]),
    ("SOP 3 - PANDUAN MOTIF DAN MODEL BATIK UNTUK BERBAGAI ACARA", [
        "Motif Parang melambangkan semangat yang tidak pernah padam dan kesinambungan perjuangan. Cocok untuk acara resmi, rapat penting, dan wisuda. Menurut tradisi keraton, motif Parang kurang dianjurkan dipakai tamu di acara pernikahan.",
        "Motif Kawung melambangkan kesucian hati, pengendalian diri, dan keadilan. Tampilannya rapi dan geometris sehingga cocok untuk kerja kantoran, rapat, dan wawancara kerja.",
        "Motif Mega Mendung khas Cirebon melambangkan kesabaran dan hati yang sejuk. Warnanya cerah sehingga cocok untuk acara santai, semi-formal, jalan-jalan, dan Jumat batik.",
        "Motif Truntum melambangkan cinta yang tumbuh kembali dan kasih sayang yang tulus. Sangat cocok untuk kondangan, acara pernikahan, lamaran, dan biasa dipakai orang tua pengantin.",
        "Motif Sekar Jagad melambangkan keindahan dan keberagaman dunia. Coraknya ramai dan berwarna sehingga cocok untuk pesta, kondangan, dan acara keluarga.",
        "Rekomendasi untuk rapat dan kerja formal: pria memakai Kemeja Batik Lengan Panjang atau Jas / Outer Batik Pria; wanita memakai Tunik Batik, Blus Batik, atau Outer / Blazer Batik. Motif yang disarankan Kawung atau Parang.",
        "Rekomendasi untuk wisuda: pria memakai Kemeja Batik Lengan Panjang; wanita memakai Model Kutubaru atau Rok Batik & One Set. Motif yang disarankan Parang atau Sekar Jagad.",
        "Rekomendasi untuk kondangan dan pesta: pria memakai Kemeja Batik Lengan Panjang atau Batik Kombinasi Polos; wanita memakai Gamis & Dress Batik, Kaftan Batik, atau Model Kutubaru. Motif yang disarankan Truntum atau Sekar Jagad.",
        "Rekomendasi untuk harian dan business casual: pria memakai Kemeja Batik Lengan Pendek atau Batik Kombinasi Polos; wanita memakai Blus Batik atau Outer / Cardigan Batik. Motif yang disarankan Mega Mendung atau Kawung.",
    ]),
    ("SOP 4 - PANDUAN UKURAN DAN PENGIRIMAN", [
        "Panduan lebar dada kemeja pria: S 50 cm, M 53 cm, L 56 cm, XL 59 cm, XXL 62 cm. Panduan lebar dada atasan wanita: S 46 cm, M 49 cm, L 52 cm, XL 55 cm, XXL 58 cm. Toleransi ukuran 1 sampai 2 cm karena proses jahit.",
        "Jika ukuran badan berada di antara dua ukuran, disarankan memilih ukuran yang lebih besar, terutama untuk bahan Katun Primisima yang tidak melar.",
        "Pesanan yang dibayar sebelum pukul 15.00 WIB dikirim pada hari yang sama. Pesanan setelah pukul 15.00 WIB dikirim pada hari kerja berikutnya. Tidak ada pengiriman pada hari Minggu dan libur nasional.",
        "Arti status pesanan: Diproses berarti pembayaran sudah diterima; Dikemas berarti produk sedang disiapkan gudang; Dikirim berarti paket sudah diserahkan ke kurir dan nomor resi sudah tersedia; Selesai berarti paket sudah diterima pelanggan.",
        "Estimasi pengiriman: Pulau Jawa 1 sampai 3 hari kerja, luar Pulau Jawa 3 sampai 7 hari kerja. Kurir yang tersedia: JNE, J&T, SiCepat, dan AnterAja.",
    ]),
]


def buat_pdf_sop():
    """Membuat file PDF SOP utama (hanya jika belum ada)."""
    from fpdf import FPDF

    SOP_DIR.mkdir(parents=True, exist_ok=True)
    if SOP_UTAMA.exists():
        return False  # sudah ada, tidak perlu dibuat ulang

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 10, "SERAT KARSA - Standar Operasional Prosedur Layanan Pelanggan",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for judul, daftar_paragraf in ISI_SOP:
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(0, 8, judul, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.set_font("Helvetica", "", 11)
        for paragraf in daftar_paragraf:
            pdf.multi_cell(0, 6, paragraf, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        pdf.ln(4)
    pdf.output(str(SOP_UTAMA))
    return True


def extract_pdf(path_pdf):
    """EXTRACT: membaca seluruh teks dari satu file PDF."""
    from pypdf import PdfReader

    reader = PdfReader(str(path_pdf))
    return "\n".join((halaman.extract_text() or "") for halaman in reader.pages)


def potong_teks(teks, ukuran=UKURAN_CHUNK, overlap=OVERLAP_CHUNK):
    """TRANSFORM: merapikan spasi lalu memotong teks menjadi chunk yang saling tumpang tindih."""
    teks = " ".join(teks.split())  # buang enter dan spasi berlebih
    potongan = []
    awal = 0
    while awal < len(teks):
        akhir = min(awal + ukuran, len(teks))
        if akhir < len(teks):
            # usahakan memotong di akhir kalimat, kalau tidak ada baru di spasi
            titik = teks.rfind(". ", awal, akhir)
            spasi = teks.rfind(" ", awal, akhir)
            if titik > awal + ukuran // 2:
                akhir = titik + 1
            elif spasi > awal:
                akhir = spasi
        potongan.append(teks[awal:akhir].strip())
        if akhir >= len(teks):
            break
        awal = max(akhir - overlap, awal + 1)
        # geser sedikit agar potongan berikutnya tidak dimulai di tengah kata
        spasi_berikut = teks.find(" ", awal, akhir)
        if spasi_berikut != -1:
            awal = spasi_berikut + 1
    return [p for p in potongan if p]


# ===========================================================================
# BAGIAN 3 - EMBEDDING & VECTOR DATABASE
# ===========================================================================

def buat_client_gemini():
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY belum diisi di file .env")
    return genai.Client(api_key=api_key)


def pilih_model_embedding(client):
    """Memilih model embedding: dari .env jika ada, kalau tidak tanya ke Google."""
    dari_env = os.getenv("GEMINI_EMBED_MODEL")
    if dari_env:
        return dari_env
    kandidat = []
    for m in client.models.list():
        aksi = getattr(m, "supported_actions", None) or []
        if "embedContent" in aksi:
            kandidat.append(m.name.replace("models/", ""))
    if not kandidat:
        raise RuntimeError("Tidak ada model embedding yang tersedia untuk API key ini.")
    # utamakan keluarga 'gemini-embedding' bila ada
    utama = [k for k in kandidat if "gemini-embedding" in k]
    return (utama or kandidat)[0]


def buat_embedding(client, model, teks, percobaan=4):
    """Mengubah satu teks menjadi vektor angka. Otomatis mencoba ulang jika server sibuk."""
    for ke in range(percobaan):
        try:
            hasil = client.models.embed_content(model=model, contents=teks)
            return list(hasil.embeddings[0].values)
        except Exception:
            if ke == percobaan - 1:
                raise
            time.sleep(3 * (ke + 1))  # tunggu 3, 6, 9 detik lalu coba lagi


def load_vector(daftar_chunk, lapor=None):
    """LOAD potongan teks + embedding-nya ke ChromaDB.

    daftar_chunk: list berisi (nama_file, nomor_chunk, teks)
    """
    import chromadb

    client = buat_client_gemini()
    model = pilih_model_embedding(client)

    vektor = []
    for i, (_, _, teks) in enumerate(daftar_chunk, start=1):
        vektor.append(buat_embedding(client, model, teks))
        if lapor:
            lapor(f"Embedding potongan {i}/{len(daftar_chunk)}", 50 + int(40 * i / len(daftar_chunk)))
        time.sleep(0.3)  # jeda kecil agar tidak melewati batas kuota gratis

    db = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # koleksi lama dihapus agar tidak ada potongan ganda setiap ETL dijalankan
    try:
        db.delete_collection(NAMA_KOLEKSI)
    except Exception:
        pass
    koleksi = db.create_collection(
        NAMA_KOLEKSI,
        # nama model disimpan agar Tahap 3 memakai model embedding yang SAMA
        metadata={"hnsw:space": "cosine", "model_embedding": model},
    )
    koleksi.add(
        ids=[f"{nama}-{nomor}" for nama, nomor, _ in daftar_chunk],
        documents=[teks for _, _, teks in daftar_chunk],
        embeddings=vektor,
        metadatas=[{"sumber": nama, "chunk": nomor} for nama, nomor, _ in daftar_chunk],
    )
    return koleksi.count(), model


# ===========================================================================
# BAGIAN 4 - MENJALANKAN SELURUH PIPELINE
# ===========================================================================

def run_pipeline(lapor=None):
    """Menjalankan ETL dari awal sampai akhir.

    lapor: fungsi opsional lapor(pesan, persen) untuk progress bar di Streamlit.
    Mengembalikan dict ringkasan hasil.
    """
    def info(pesan, persen):
        if lapor:
            lapor(pesan, persen)
        else:
            print(f"[{persen:3d}%] {pesan}")

    info("Memuat katalog, pesanan, dan riwayat chat ke SQLite...", 5)
    jumlah_baris = load_sql()

    info("Menyiapkan dokumen PDF SOP...", 25)
    buat_pdf_sop()

    info("Extract: membaca teks dari semua PDF di data/sop ...", 35)
    daftar_chunk = []
    daftar_pdf = sorted(SOP_DIR.glob("*.pdf"))
    for pdf in daftar_pdf:
        teks = extract_pdf(pdf)
        for nomor, potongan in enumerate(potong_teks(teks), start=1):
            daftar_chunk.append((pdf.name, nomor, potongan))

    info(f"Transform: {len(daftar_chunk)} potongan teks dari {len(daftar_pdf)} PDF", 45)

    info("Load: membuat embedding dan menyimpan ke ChromaDB...", 50)
    jumlah_vektor, model = load_vector(daftar_chunk, lapor)

    info("Selesai.", 100)
    return {
        "baris_sql": jumlah_baris,
        "jumlah_pdf": len(daftar_pdf),
        "jumlah_chunk": jumlah_vektor,
        "model_embedding": model,
    }


if __name__ == "__main__":
    hasil = run_pipeline()
    print("\n=== RINGKASAN ETL ===")
    for tabel, n in hasil["baris_sql"].items():
        print(f"Tabel {tabel:<10}: {n} baris")
    print(f"PDF diproses    : {hasil['jumlah_pdf']} file")
    print(f"Potongan teks   : {hasil['jumlah_chunk']} chunk di ChromaDB")
    print(f"Model embedding : {hasil['model_embedding']}")