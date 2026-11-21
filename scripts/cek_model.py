import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 1. Minta daftar semua model yang bisa dipakai API key ini
kandidat = []
for m in client.models.list():
    nama = m.name.replace("models/", "")
    aksi = getattr(m, "supported_actions", None) or []
    if "generateContent" in aksi and "flash" in nama:
        kandidat.append(nama)

print("Model Flash yang tersedia:")
for nama in kandidat:
    print("  -", nama)

# 2. Coba satu per satu sampai ada yang berhasil menjawab
print("\nMencoba satu per satu...")
for nama in kandidat:
    try:
        r = client.models.generate_content(
            model=nama,
            contents="Sebutkan satu motif batik dalam satu kalimat.",
        )
        print(f"\nBERHASIL dengan model: {nama}")
        print("Jawaban:", r.text)
        break
    except Exception as e:
        print(f"  x {nama} gagal: {str(e)[:80]}")
else:
    print("\nSemua model gagal. Coba lagi beberapa menit lagi.")