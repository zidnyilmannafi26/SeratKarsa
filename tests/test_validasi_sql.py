"""Tes pagar pengaman Text-to-SQL. Tidak butuh API key maupun database.

Jalankan:  python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag_sql_engine import validasi_sql  # noqa: E402

DIIZINKAN = [
    "SELECT nama_model, motif, ukuran, harga, stok FROM products WHERE ukuran = 'L' LIMIT 20",
    "select * from products;",
    "WITH s AS (SELECT * FROM products) SELECT * FROM s",
    "SELECT o.status, p.nama_model FROM orders o JOIN products p ON o.product_id = p.product_id "
    "WHERE o.order_id = '#SK-103'",
]

DITOLAK = [
    "DROP TABLE products",
    "SELECT * FROM products; DELETE FROM products",
    "UPDATE products SET stok = 0",
    "SELECT name FROM sqlite_master",
    "SELECT * FROM products UNION SELECT sql, 1, 1, 1, 1 FROM sqlite_schema",
    "SELECT * FROM chat_logs",
    "ATTACH DATABASE 'x.db' AS x",
    "PRAGMA table_info(products)",
    # privasi pesanan
    "SELECT * FROM orders",
    "SELECT * FROM orders WHERE order_id LIKE '#SK-%'",
    "SELECT * FROM orders WHERE order_id = '#SK-101' OR 1=1",
    "SELECT * FROM orders WHERE nama_pelanggan = 'Budi'",
]


class TesValidasiSQL(unittest.TestCase):
    def test_kueri_aman_lolos(self):
        for sql in DIIZINKAN:
            with self.subTest(sql=sql):
                self.assertNotIn(";", validasi_sql(sql))

    def test_kueri_berbahaya_ditolak(self):
        for sql in DITOLAK:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                validasi_sql(sql)


if __name__ == "__main__":
    unittest.main()
