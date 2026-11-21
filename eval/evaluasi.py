"""Evaluasi chatbot dengan kumpulan pertanyaan uji berlabel.

Mengukur:
  - akurasi router  : rute pilihan Gemini sama dengan label
  - SQL berhasil    : rute SQL/HYBRID menghasilkan kueri yang lolos validasi dan berjalan
  - SOP ditemukan   : rute PDF/HYBRID mendapat minimal satu kutipan SOP

Prasyarat: .env berisi GEMINI_API_KEY dan ETL sudah dijalankan.
Jalankan  : python eval/evaluasi.py
Hasil per pertanyaan disimpan ke eval/hasil_evaluasi.csv.
"""

import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parent))

from rag_sql_engine import jawab_pertanyaan  # noqa: E402

JEDA_DETIK = 4  # menjaga kuota API gratis


def persen(a, b):
    return f"{a}/{b} ({a / b:.0%})" if b else "-"


def main():
    soal = json.loads((FOLDER / "pertanyaan_uji.json").read_text(encoding="utf-8"))
    baris, benar_per_rute, total_per_rute = [], Counter(), Counter()
    sql_ok = sql_total = pdf_ok = pdf_total = 0

    for i, s in enumerate(soal, start=1):
        h = jawab_pertanyaan(s["tanya"], catat_log=False)
        benar = h["rute"] == s["rute"]
        total_per_rute[s["rute"]] += 1
        benar_per_rute[s["rute"]] += benar

        if h["rute"] in ("SQL", "HYBRID"):
            sql_total += 1
            sql_ok += bool(h["sql"]) and not any("SQL" in c or "Error" in c for c in h["catatan"])
        if h["rute"] in ("PDF", "HYBRID"):
            pdf_total += 1
            pdf_ok += bool(h["kutipan_pdf"])

        print(f"[{i:2}/{len(soal)}] {'OK ' if benar else 'XX '} label={s['rute']:6} dapat={h['rute']}  {s['tanya']}")
        baris.append({"tanya": s["tanya"], "label": s["rute"], "rute": h["rute"], "benar": benar,
                      "sql": h["sql"] or "", "jumlah_baris": len(h["hasil_sql"]),
                      "jumlah_kutipan": len(h["kutipan_pdf"]), "catatan": " | ".join(h["catatan"]),
                      "jawaban": h["jawaban"]})
        time.sleep(JEDA_DETIK)

    with open(FOLDER / "hasil_evaluasi.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=baris[0].keys())
        w.writeheader()
        w.writerows(baris)

    print("\n=== RINGKASAN ===")
    print("Akurasi router :", persen(sum(benar_per_rute.values()), len(soal)))
    for rute in total_per_rute:
        print(f"  {rute:6}       :", persen(benar_per_rute[rute], total_per_rute[rute]))
    print("SQL berhasil   :", persen(sql_ok, sql_total))
    print("SOP ditemukan  :", persen(pdf_ok, pdf_total))


if __name__ == "__main__":
    main()
