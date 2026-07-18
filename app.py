"""
app.py
Aplikasi Flask utama untuk "Majalaya Crypto" - SESI 3
"FULL MECHANICS UPDATE & INTEGRASI PROGRESIF"

Perubahan dari Sesi 2/3-awal -> Sesi 3 (update ini), bersifat AKUMULATIF
(tidak menghapus fitur lama, hanya menambah & memperbaiki):

- [FIX] Dropdown profil navbar (nama user, badge role, Logout, Switch to
  Admin Login, Switch to User/Guest Login) sekarang dijamin selalu terkirim
  lengkap ke template untuk SEMUA role (admin maupun user biasa), dengan
  variabel session yang konsisten. Tidak ada lagi cabang render_template()
  yang lupa mengirim data profil.
- [OVERHAUL] Logika trading dirombak total agar mendukung pecahan desimal:
    * BELI  -> user input NOMINAL RUPIAH (bukan jumlah koin). Minimal
      pembelian Rp10.000. Jumlah koin baru dihitung otomatis:
          jumlah_koin_baru = nominal_beli_idr / harga_koin_live
      lalu disimpan sebagai pecahan desimal (dibulatkan 8 digit di belakang
      koma) di tabel portfolio. Ini menghilangkan bug lama di mana input
      "jumlah koin" ditafsirkan sebagai nilai besar/eksponensial
      (mis. '2e+06 BTC') yang membuat validasi saldo selalu gagal.
    * JUAL  -> user tetap input JUMLAH KOIN (pecahan desimal) yang mereka
      mau jual dari kepemilikan mereka saat ini, dikonversi ke saldo Rupiah
      berdasarkan harga live saat transaksi.
- [FITUR BARU] Route POST /reset-akun untuk tab "Pengaturan": me-reset saldo
  user (ulangi gacha saldo awal) dan mengosongkan seluruh portofolio koin
  milik user tersebut ke 0, tanpa menyentuh akun user lain.
- [FITUR BARU] Route GET /api/admin/ringkasan (khusus admin, JSON) untuk
  tombol "Refresh Ringkasan" interaktif di tab Master Control, agar total
  user & total koin bisa diperbarui live tanpa reload halaman.
- [FITUR BARU] Query daftar seluruh user (tanpa password) dikirim ke
  dashboard admin untuk mengisi tab "Kelola User".
- Semua fitur SESI 3 sebelumnya (loading screen, session.clear() sebelum
  login, refresh harga AJAX, fluktuasi harga multi-kondisi, USDT flat)
  tetap dipertahankan seutuhnya di bawah ini.

Cara menjalankan:
    1. python app.py          -> otomatis membuat skema DB jika belum ada
    2. Buka http://127.0.0.1:5000/ di browser
"""

import csv
import io
import json
import os
import random
import sqlite3
from datetime import datetime, timedelta
from flask import (
    Flask, request, redirect, url_for, session,
    render_template, flash, jsonify, Response
)
from werkzeug.utils import secure_filename

# ============================================================
# KONFIGURASI DASAR APLIKASI
# ============================================================
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = "ganti-dengan-kunci-rahasia-anda-sendiri"  # wajib diganti sebelum deploy

# Umur session dibuat eksplisit & session di-set permanent saat login, supaya
# cookie session konsisten selama masa aktif.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=6)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

DB_NAME = "majalaya_crypto.db"

ADMIN_USERNAME = "superadmin_majalaya"
ADMIN_PASSWORD = "Wytta07_Secret2026"

GACHA_SALDO_MIN = 50_000_000
GACHA_SALDO_MAX = 500_000_000

# [SESI 3 UPDATE] Minimal nominal pembelian dalam Rupiah.
MIN_BELI_IDR = 10_000

# Jumlah digit desimal maksimum yang disimpan untuk pecahan koin, supaya
# angka fraksi (mis. 0.00012345 BTC) tetap presisi tapi tidak "kotor" oleh
# sisa pembagian floating point yang tidak berguna.
PRESISI_FRAKSI_KOIN = 8

# [SESI 3 - MEGA MECHANICS UPDATE] Multiplier intensitas fluktuasi berdasarkan
# "Mode Volatilitas Pasar" yang dipilih user di tab Pengaturan (disimpan di
# session). Normal = intensitas asli, Konservatif = diredam, Agresif = dilipatgandakan.
KONFIG_VOLATILITAS = {
    "konservatif": 0.4,
    "normal": 1.0,
    "agresif": 2.2,
}
VOLATILITAS_DEFAULT = "normal"

# [SESI 3] Nominal tombol admin "Suntik Saldo Massal" di panel Developer Options.
NOMINAL_SUNTIK_SALDO = 50_000_000

# [SESI 3] Maksimum jumlah titik data yang disimpan untuk Line Chart tren BTC
# (in-memory, direset ulang setiap kali server Flask di-restart).
MAX_RIWAYAT_HARGA_BTC = 20

# [SESI 4 - EDIT PROFIL] Direktori penyimpanan foto profil yang diupload user,
# beserta ekstensi file yang diizinkan untuk mencegah upload berkas berbahaya.
FOLDER_FOTO_PROFIL = os.path.join("static", "img")
EKSTENSI_FOTO_DIIZINKAN = {"png", "jpg", "jpeg", "gif", "webp"}

KONFIG_FLUKTUASI = {
    "BTC":  (1, 3),
    "ETH":  (1, 3),
    "SOL":  (4, 8),
    "DOGE": (10, 25),
    # [SESI 2 - FINAL UPGRADE] Intensitas fluktuasi 5 koin baru, diselaraskan
    # dengan karakter koin aslinya: BNB relatif stabil seperti BTC/ETH, XRP
    # & ADA menengah, NEAR agak agresif seperti SOL, dan SHIB paling liar
    # (meme coin) mengikuti karakter DOGE.
    "BNB":  (1, 3),
    "XRP":  (2, 5),
    "ADA":  (2, 5),
    "NEAR": (4, 8),
    "SHIB": (10, 25),
}

HARGA_USDT_FLAT = 15_000

# [SESI 2 - FINAL UPGRADE] Batas bawah harga fiktif secara umum supaya tidak
# pernah menyentuh 0/negatif akibat fluktuasi acak. Sebelumnya hardcode ke
# "1" (asumsi semua koin bernilai minimal Rp1), tapi itu jadi bug untuk koin
# berharga pecahan sangat kecil seperti SHIB (Rp0.4) -- setiap kali harga
# turun, harga akan langsung "terjepit" naik paksa ke Rp1 dan macet di
# sana. Dengan epsilon sekecil ini, koin bernilai sub-Rupiah tetap bisa
# berfluktuasi naik-turun secara wajar tanpa pernah benar-benar 0.
HARGA_MINIMUM_FIKTIF = 0.00000001

HARGA_DASAR_KOIN = [
    ("BTC", 1_000_000_000),
    ("ETH", 50_000_000),
    ("SOL", 2_500_000),
    ("DOGE", 6_000),
    ("USDT", HARGA_USDT_FLAT),
    # [SESI 2 - FINAL UPGRADE] 5 koin baru, total aset di platform menjadi 10.
    ("BNB", 9_000_000),
    ("XRP", 10_000),
    ("ADA", 7_000),
    ("NEAR", 75_000),
    # SHIB sengaja bernilai desimal kecil (< Rp1) -- kolom harga_fiktif
    # bertipe REAL (float) sehingga aman menyimpan pecahan sekecil ini
    # tanpa kehilangan presisi berarti, dan seluruh logika trading (yang
    # sudah berbasis pembagian float) tetap berfungsi normal untuknya.
    ("SHIB", 0.4),
]


# ============================================================
# KONEKSI DATABASE
# ============================================================
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# PASTIKAN SKEMA DATABASE SELALU ADA SAAT APP START
# ============================================================
def ensure_database():
    """
    Membuat tabel users, crypto_market, portfolio jika belum ada,
    dan mengisi harga dasar koin jika crypto_market masih kosong.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            saldo_idr INTEGER NOT NULL
        )
    """)

    # [SESI 4 - MIGRASI SKEMA AMAN] Tambahkan kolom baru ke tabel users tanpa
    # merusak data lama: `modal_awal_idr` menyimpan nominal gacha saldo awal
    # (dipakai untuk menghitung persentase P&L global), dan `foto_profil`
    # menyimpan nama file foto profil yang diupload user lewat tab
    # Pengaturan. Dicek dulu lewat PRAGMA supaya ALTER TABLE tidak pernah
    # dijalankan dua kali (yang akan menyebabkan error kolom duplikat).
    kolom_users_sekarang = [row["name"] for row in cur.execute("PRAGMA table_info(users)").fetchall()]

    if "modal_awal_idr" not in kolom_users_sekarang:
        cur.execute("ALTER TABLE users ADD COLUMN modal_awal_idr INTEGER")
        # Backfill akun lama yang sudah terlanjur ada sebelum kolom ini
        # dibuat -- modal awal diasumsikan sama dengan saldo_idr saat ini
        # (asumsi paling adil karena riwayat gacha asli mereka tidak
        # tercatat), supaya P&L mereka mulai terhitung dari 0% alih-alih
        # error karena modal_awal_idr kosong (NULL).
        cur.execute("UPDATE users SET modal_awal_idr = saldo_idr WHERE modal_awal_idr IS NULL")

    if "foto_profil" not in kolom_users_sekarang:
        cur.execute("ALTER TABLE users ADD COLUMN foto_profil TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS crypto_market (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_koin TEXT UNIQUE NOT NULL,
            harga_fiktif REAL NOT NULL
        )
    """)

    # jumlah_koin bertipe REAL supaya SQLite bisa menyimpan pecahan desimal
    # panjang (mis. 0.00012345) tanpa kehilangan presisi berarti.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            nama_koin TEXT NOT NULL,
            jumlah_koin REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (nama_koin) REFERENCES crypto_market (nama_koin)
        )
    """)

    # [SESI 2 - FINAL UPGRADE] Sebelumnya seeding hanya jalan kalau tabel
    # crypto_market BENAR-BENAR kosong (total_koin == 0), sehingga di
    # database lama yang sudah berisi 5 koin awal, 5 koin baru (BNB, XRP,
    # ADA, NEAR, SHIB) tidak akan pernah masuk. Sekarang dicek PER KOIN:
    # koin yang sudah ada di database (beserta harga live-nya saat ini)
    # dibiarkan utuh, dan hanya koin yang benar-benar belum terdaftar yang
    # disisipkan dengan harga awalnya -- aman dijalankan berkali-kali tanpa
    # pernah menimpa/mendobel data yang sudah ada.
    koin_sudah_ada = {
        row["nama_koin"]
        for row in cur.execute("SELECT nama_koin FROM crypto_market").fetchall()
    }
    koin_baru_perlu_seed = [
        (kode, harga) for kode, harga in HARGA_DASAR_KOIN if kode not in koin_sudah_ada
    ]
    if koin_baru_perlu_seed:
        cur.executemany(
            "INSERT INTO crypto_market (nama_koin, harga_fiktif) VALUES (?, ?)",
            koin_baru_perlu_seed
        )

        # Koin yang baru disisipkan ke database lama harus langsung punya
        # baris portfolio (jumlah_koin = 0) untuk SEMUA user yang sudah ada,
        # sama seperti perlakuan saat user baru mendaftar -- supaya donut
        # chart alokasi aset & form trading tidak error karena baris
        # portfolio-nya belum pernah dibuat sama sekali.
        semua_user_id = [row["id"] for row in cur.execute("SELECT id FROM users").fetchall()]
        for user_id in semua_user_id:
            for kode, _harga in koin_baru_perlu_seed:
                sudah_punya_baris = cur.execute(
                    "SELECT id FROM portfolio WHERE user_id = ? AND nama_koin = ?",
                    (user_id, kode)
                ).fetchone()
                if sudah_punya_baris is None:
                    cur.execute(
                        "INSERT INTO portfolio (user_id, nama_koin, jumlah_koin) VALUES (?, ?, 0)",
                        (user_id, kode)
                    )

    # [SESI 3 - INTEGRASI BUKU BESAR RIWAYAT TRANSAKSI]
    # nama_koin ditambahkan sebagai kolom pelengkap (di luar kolom wajib) agar
    # tabel "Recent Activities" di dashboard bisa menampilkan kolom Koin.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transaction_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            tipe_transaksi TEXT NOT NULL,
            nama_koin TEXT,
            nominal_idr REAL NOT NULL,
            jumlah_koin REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    # [SESI 4 - SOCIAL TRADING FEED] Kolom `feed_hidden` menandai post yang
    # sudah "dihapus" pemiliknya dari Social Trading Feed. Sengaja berupa
    # SOFT DELETE (bukan menghapus baris asli) supaya riwayat transaksi resmi
    # di tab "Recent Activities" & buku besar tetap utuh -- yang hilang hanya
    # tampilannya di feed sosial.
    kolom_riwayat_sekarang = [row["name"] for row in cur.execute("PRAGMA table_info(transaction_history)").fetchall()]
    if "feed_hidden" not in kolom_riwayat_sekarang:
        cur.execute("ALTER TABLE transaction_history ADD COLUMN feed_hidden INTEGER NOT NULL DEFAULT 0")

    # [SESI 3 - DEVELOPER OPTIONS] Tabel key-value kecil untuk menyimpan status
    # global sistem (mis. status "Global Market Suspend") yang harus tetap
    # konsisten untuk SEMUA user, sehingga tidak bisa hanya disimpan di session.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    ada_setting_suspend = cur.execute(
        "SELECT 1 FROM system_settings WHERE key = 'market_suspended'"
    ).fetchone()
    if ada_setting_suspend is None:
        cur.execute(
            "INSERT INTO system_settings (key, value) VALUES ('market_suspended', '0')"
        )

    # [SESI 4 - SOCIAL TRADING FEED: LIKE] Satu baris per (post_id, username)
    # -- UNIQUE constraint mencegah user like berkali-kali di post yang sama;
    # toggle like/unlike cukup INSERT lalu DELETE baris yang sama.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feed_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            UNIQUE(post_id, username)
        )
    """)

    # [SESI 5 - TAB CONTACT] Tabel untuk menampung pesan dari form "Hubungi
    # Kami" (tab Contact) di dashboard. Kolom `username_pengirim` diisi kalau
    # yang mengirim sedang login (boleh NULL untuk Guest yang belum login),
    # sedangkan `nama_pengirim` & `email_pengirim` selalu diisi dari input
    # form itu sendiri. `dibaca` dipakai kalau nanti admin butuh menandai
    # pesan yang sudah ditindaklanjuti (default belum dibaca = 0).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username_pengirim TEXT,
            nama_pengirim TEXT NOT NULL,
            email_pengirim TEXT NOT NULL,
            isi_pesan TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            dibaca INTEGER NOT NULL DEFAULT 0
        )
    """)

    # [SESI 4 - SOCIAL TRADING FEED: KOMENTAR & BALAS CHAT] `parent_id`
    # menunjuk ke `id` komentar lain di tabel yang sama untuk membentuk
    # thread balasan bertingkat ala YouTube (NULL = komentar tingkat atas).
    # `comment_hidden` dipakai untuk SOFT DELETE komentar milik sendiri,
    # konsisten dengan pola feed_hidden di transaction_history.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feed_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            parent_id INTEGER,
            username TEXT NOT NULL,
            isi_komentar TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            comment_hidden INTEGER NOT NULL DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


# Jalankan sekali saat modul di-import / app start
ensure_database()


# ============================================================
# [SESI 3] RIWAYAT HARGA BTC (untuk Line Chart Tren Pasar)
# ============================================================
# Disimpan in-memory (bukan tabel DB) karena sifatnya cuma "titik data
# sementara" untuk grafik live -- akan direset ulang tiap server restart,
# dan itu tidak masalah karena hanya dipakai untuk visualisasi tren.
#
# [REFACTOR - DISTRIBUSI KODE] Diperluas dari yang tadinya hanya menyimpan
# riwayat BTC saja, menjadi riwayat 4 koin (BTC, ETH, SOL, DOGE) sekaligus,
# supaya endpoint /api/market-history bisa menyuplai data historis yang lebih
# lengkap ke static/js/dashboard.js. USDT sengaja tidak dilacak karena
# harganya selalu flat (stablecoin simulasi).
#
# [SESI 2 - FINAL UPGRADE] Ditambah 5 koin baru (BNB, XRP, ADA, NEAR, SHIB)
# supaya mini sparkline di ticker strip DAN Line Chart "Tren Pasar" utama
# ikut menyala dengan riwayat harga historis sejak server pertama kali
# dijalankan, sama persis seperti 4 koin lama. USDT tetap satu-satunya
# koin yang tidak dilacak karena flat.
KOIN_TERLACAK_HISTORI = ["BTC", "ETH", "SOL", "DOGE", "BNB", "XRP", "ADA", "NEAR", "SHIB"]
RIWAYAT_HARGA = {kode: [] for kode in KOIN_TERLACAK_HISTORI}

# Alias lama dipertahankan (masih menunjuk ke list objek yang SAMA dengan
# RIWAYAT_HARGA["BTC"]) supaya kode lain yang masih memanggil nama variabel
# ini (mis. /api/chart/btc) tetap jalan tanpa perlu diubah.
RIWAYAT_HARGA_BTC = RIWAYAT_HARGA["BTC"]


def catat_titik_harga():
    """Menambahkan satu titik data harga terbaru untuk seluruh koin di
    KOIN_TERLACAK_HISTORI ke riwayat in-memory, dipanggil setiap kali
    perbarui_harga_crypto() selesai jalan."""
    conn = get_db_connection()
    placeholder = ",".join("?" for _ in KOIN_TERLACAK_HISTORI)
    rows = conn.execute(
        f"SELECT nama_koin, harga_fiktif FROM crypto_market WHERE nama_koin IN ({placeholder})",
        tuple(KOIN_TERLACAK_HISTORI)
    ).fetchall()
    conn.close()

    waktu_sekarang = datetime.now().strftime("%H:%M:%S")
    for row in rows:
        kode_koin = row["nama_koin"]
        if kode_koin not in RIWAYAT_HARGA:
            continue
        RIWAYAT_HARGA[kode_koin].append({
            "waktu": waktu_sekarang,
            "harga": row["harga_fiktif"]
        })
        while len(RIWAYAT_HARGA[kode_koin]) > MAX_RIWAYAT_HARGA_BTC:
            RIWAYAT_HARGA[kode_koin].pop(0)


# Nama fungsi lama dipertahankan sebagai alias supaya tidak ada pemanggil
# lama yang pecah, sekalipun sekarang mencatat lebih dari sekadar BTC.
catat_titik_harga_btc = catat_titik_harga


# ============================================================
# [SESI 4 - OPTIMALISASI UX GRAFIK] PRE-POPULATE RIWAYAT HARGA HISTORIS
# ============================================================
def seed_riwayat_harga_historis(jumlah_titik=MAX_RIWAYAT_HARGA_BTC):
    """
    Mem-pre-populate RIWAYAT_HARGA (in-memory) dengan `jumlah_titik` titik
    data historis SIMULASI untuk BTC/ETH/SOL/DOGE, dibangun mundur dari
    harga live saat ini lewat random walk memakai intensitas fluktuasi yang
    sama dengan KONFIG_FLUKTUASI, lalu dibalik urutannya supaya kronologis
    (titik tertua -> titik terbaru == harga live sekarang).

    Tujuannya supaya Line Chart Tren Pasar & sparkline Total Saldo langsung
    berisi jejak tren naik-turun yang realistis SEJAK dashboard pertama kali
    dibuka user, tanpa harus menekan tombol "Refresh Harga" berkali-kali
    dahulu. Dipanggil sekali saat modul di-import (server start).

    List di RIWAYAT_HARGA dimutasi IN-PLACE (clear + extend, bukan
    reassignment) supaya alias lama RIWAYAT_HARGA_BTC tetap menunjuk ke
    objek list yang sama persis.
    """
    conn = get_db_connection()
    placeholder = ",".join("?" for _ in KOIN_TERLACAK_HISTORI)
    rows = conn.execute(
        f"SELECT nama_koin, harga_fiktif FROM crypto_market WHERE nama_koin IN ({placeholder})",
        tuple(KOIN_TERLACAK_HISTORI)
    ).fetchall()
    conn.close()

    waktu_sekarang = datetime.now()

    for row in rows:
        kode_koin = row["nama_koin"]
        if kode_koin not in RIWAYAT_HARGA:
            continue

        harga_live = row["harga_fiktif"]
        persen_min, persen_max = KONFIG_FLUKTUASI.get(kode_koin, (1, 3))

        # Bangun mundur (dari sekarang ke masa lalu) supaya titik TERAKHIR
        # tetap presisi sama dengan harga_fiktif live saat ini.
        titik_mundur = [harga_live]
        harga_berjalan = harga_live
        for _ in range(jumlah_titik - 1):
            persentase_acak = random.uniform(persen_min, persen_max)
            arah = random.choice([1, -1])
            # Membalik rumus fluktuasi maju (harga_baru = lama * (1 + persen*arah))
            # supaya konsisten dengan intensitas naik-turun yang sama.
            harga_sebelumnya = harga_berjalan / (1 + (persentase_acak / 100) * arah)
            harga_sebelumnya = max(harga_sebelumnya, HARGA_MINIMUM_FIKTIF)
            titik_mundur.append(harga_sebelumnya)
            harga_berjalan = harga_sebelumnya

        titik_mundur.reverse()  # urut kronologis: tertua -> terbaru (live)

        # [SESI 2 - FINAL UPGRADE] Koin bernilai sub-Rupiah (mis. SHIB, harga
        # < Rp1) dibulatkan ke 8 digit desimal (bukan 2) supaya titik-titik
        # historisnya tidak semua terpangkas jadi 0.0 di chart/sparkline.
        digit_presisi = 8 if harga_live < 1 else 2

        RIWAYAT_HARGA[kode_koin].clear()
        RIWAYAT_HARGA[kode_koin].extend([
            {
                "waktu": (waktu_sekarang - timedelta(minutes=(jumlah_titik - 1 - idx))).strftime("%H:%M:%S"),
                "harga": round(harga, digit_presisi)
            }
            for idx, harga in enumerate(titik_mundur)
        ])


# Pre-populate riwayat harga historis untuk KEEMPAT koin (bukan cuma 1
# titik) supaya chart & sparkline langsung penuh sejak dashboard pertama
# kali dibuka, sebelum tombol "Refresh Harga" pernah ditekan sama sekali.
seed_riwayat_harga_historis()


# ============================================================
# [SESI 3] STATUS "GLOBAL MARKET SUSPEND" (Developer Options Admin)
# ============================================================
def get_market_suspended():
    """True jika admin sudah menyalakan Global Market Suspend -- refresh
    harga di sisi user biasa akan terkunci selama status ini aktif."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT value FROM system_settings WHERE key = 'market_suspended'"
    ).fetchone()
    conn.close()
    return bool(row) and row["value"] == "1"


def set_market_suspended(status_aktif):
    conn = get_db_connection()
    conn.execute(
        "UPDATE system_settings SET value = ? WHERE key = 'market_suspended'",
        ("1" if status_aktif else "0",)
    )
    conn.commit()
    conn.close()


# ============================================================
# ALGORITMA GACHA SALDO AWAL
# ============================================================
def gacha_saldo_awal():
    kelipatan = 1_000_000
    minimum_step = GACHA_SALDO_MIN // kelipatan
    maksimum_step = GACHA_SALDO_MAX // kelipatan
    return random.randint(minimum_step, maksimum_step) * kelipatan


# ============================================================
# FLUKTUASI HARGA CRYPTO (MULTI-KONDISI)
# ============================================================
def perbarui_harga_crypto(multiplier=1.0):
    """
    Menjalankan simulasi fluktuasi pasar untuk semua koin di KONFIG_FLUKTUASI
    (BTC/ETH stabil 1-3%, SOL agresif 4-8%, DOGE liar 10-25%, arah naik/turun
    acak), lalu memaksa USDT tetap flat di HARGA_USDT_FLAT karena berperan
    sebagai stablecoin simulasi.

    [SESI 3] Parameter `multiplier` datang dari "Mode Volatilitas Pasar" yang
    dipilih user di tab Pengaturan (Konservatif=0.4x, Normal=1x, Agresif=2.2x)
    -- dipakai untuk memperbesar/memperkecil intensitas persentase acak di
    atas tanpa mengubah konfigurasi dasar tiap koin.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    for nama_koin, (persen_min, persen_max) in KONFIG_FLUKTUASI.items():
        row = cursor.execute(
            "SELECT harga_fiktif FROM crypto_market WHERE nama_koin = ?",
            (nama_koin,)
        ).fetchone()
        if row is None:
            continue

        harga_lama = row["harga_fiktif"]
        persentase_acak = random.uniform(persen_min, persen_max) * multiplier
        arah = random.choice([1, -1])
        perubahan = harga_lama * (persentase_acak / 100) * arah
        harga_baru = max(harga_lama + perubahan, HARGA_MINIMUM_FIKTIF)

        cursor.execute(
            "UPDATE crypto_market SET harga_fiktif = ? WHERE nama_koin = ?",
            (harga_baru, nama_koin)
        )

    # USDT = stablecoin simulasi, selalu flat, tidak pernah ikut fluktuasi.
    cursor.execute(
        "UPDATE crypto_market SET harga_fiktif = ? WHERE nama_koin = 'USDT'",
        (HARGA_USDT_FLAT,)
    )

    conn.commit()
    conn.close()

    # [SESI 3] Catat titik data terbaru untuk Line Chart tren BTC.
    catat_titik_harga_btc()


def ambil_portofolio_user(user_id):
    """
    Mengambil seluruh baris portofolio milik user, digabung (JOIN) dengan
    harga_fiktif terbaru dari crypto_market, sekaligus menghitung nilai
    rupiah tiap koin (jumlah_koin * harga_fiktif). Dipakai untuk menampilkan
    tab "Portofolio" beserta form Beli/Jual di dashboard user.
    """
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT p.nama_koin, p.jumlah_koin, c.harga_fiktif,
               (p.jumlah_koin * c.harga_fiktif) AS nilai_rupiah
        FROM portfolio p
        JOIN crypto_market c ON c.nama_koin = p.nama_koin
        WHERE p.user_id = ?
        ORDER BY c.id
    """, (user_id,)).fetchall()
    conn.close()
    return rows


def hitung_asset_allocation(user_id):
    """
    Menghitung persentase alokasi aset user (cash IDR vs tiap koin yang
    dimiliki) berdasarkan nilai saat ini, untuk ditampilkan di donut chart.
    """
    conn = get_db_connection()
    user = conn.execute("SELECT saldo_idr FROM users WHERE id = ?", (user_id,)).fetchone()
    portofolio = conn.execute("""
        SELECT p.nama_koin, p.jumlah_koin, c.harga_fiktif
        FROM portfolio p
        JOIN crypto_market c ON c.nama_koin = p.nama_koin
        WHERE p.user_id = ?
    """, (user_id,)).fetchall()
    conn.close()

    saldo_idr = user["saldo_idr"] if user else 0
    nilai_koin = {row["nama_koin"]: row["jumlah_koin"] * row["harga_fiktif"] for row in portofolio}
    total = saldo_idr + sum(nilai_koin.values())

    if total <= 0:
        return [{"label": "Cash IDR", "persen": 100}]

    alokasi = [{"label": "Cash IDR", "persen": round(saldo_idr / total * 100, 1)}]
    for nama_koin, nilai in nilai_koin.items():
        if nilai > 0:
            alokasi.append({"label": nama_koin, "persen": round(nilai / total * 100, 1)})
    return alokasi


def hitung_pnl_user(user_id):
    """
    [SESI 4 - WIDGET P&L GLOBAL] Menghitung persentase Profit/Loss (P&L)
    global seorang user, dengan membandingkan NILAI TOTAL ASET saat ini
    (saldo_idr + nilai seluruh koin di portofolio berdasarkan harga live)
    terhadap MODAL AWAL gacha mereka (modal_awal_idr, diisi sekali saat
    registrasi & tidak pernah berubah).

    Rumus: persen = ((nilai_total_sekarang - modal_awal) / modal_awal) * 100

    Mengembalikan dict berisi nilai_total, modal_awal, persen (2 desimal),
    dan nominal (selisih Rupiah). Kalau user_id tidak ditemukan atau modal
    awal 0 (mis. akun rusak), persen dikembalikan 0.0 supaya template tidak
    pernah error karena pembagian oleh nol.
    """
    conn = get_db_connection()
    user = conn.execute(
        "SELECT saldo_idr, modal_awal_idr FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    portofolio = conn.execute("""
        SELECT p.jumlah_koin, c.harga_fiktif
        FROM portfolio p
        JOIN crypto_market c ON c.nama_koin = p.nama_koin
        WHERE p.user_id = ?
    """, (user_id,)).fetchall()
    conn.close()

    if user is None:
        return {"nilai_total": 0, "modal_awal": 0, "persen": 0.0, "nominal": 0}

    nilai_koin = sum(row["jumlah_koin"] * row["harga_fiktif"] for row in portofolio)
    saldo_idr = user["saldo_idr"] or 0
    modal_awal = user["modal_awal_idr"] or 0
    nilai_total_sekarang = saldo_idr + nilai_koin

    if modal_awal <= 0:
        persen = 0.0
    else:
        persen = ((nilai_total_sekarang - modal_awal) / modal_awal) * 100

    return {
        "nilai_total": nilai_total_sekarang,
        "modal_awal": modal_awal,
        "persen": round(persen, 2),
        "nominal": round(nilai_total_sekarang - modal_awal, 0)
    }


def hitung_riwayat_nilai_portofolio(user_id):
    """
    [SESI 4 - SPARKLINE WIDGET TOTAL SALDO] Merekonstruksi jejak nilai TOTAL
    kekayaan user (saldo_idr + nilai seluruh koin yang dimiliki) pada setiap
    titik waktu yang sudah tercatat di RIWAYAT_HARGA (BTC/ETH/SOL/DOGE),
    memakai jumlah koin yang dimiliki user SAAT INI sebagai basis (saldo
    cash diasumsikan konstan sepanjang jejak singkat ini karena tidak
    dilacak historisnya). Hasilnya dipakai untuk mini canvas Chart.js
    'Sparkline' di widget Total Saldo, supaya langsung terisi jejak tren
    naik-turun sejak dashboard pertama kali dibuka (RIWAYAT_HARGA sudah
    di-pre-populate lewat seed_riwayat_harga_historis()).
    """
    conn = get_db_connection()
    user = conn.execute("SELECT saldo_idr FROM users WHERE id = ?", (user_id,)).fetchone()
    portofolio = conn.execute(
        "SELECT nama_koin, jumlah_koin FROM portfolio WHERE user_id = ? AND jumlah_koin > 0",
        (user_id,)
    ).fetchall()
    conn.close()

    saldo_idr = user["saldo_idr"] if user else 0
    kepemilikan = {row["nama_koin"]: row["jumlah_koin"] for row in portofolio}

    jumlah_titik = max((len(v) for v in RIWAYAT_HARGA.values()), default=0)
    hasil = []
    for i in range(jumlah_titik):
        nilai = saldo_idr
        for kode_koin, jumlah_dimiliki in kepemilikan.items():
            if kode_koin == "USDT":
                nilai += jumlah_dimiliki * HARGA_USDT_FLAT
                continue
            riwayat_koin = RIWAYAT_HARGA.get(kode_koin)
            if riwayat_koin and i < len(riwayat_koin):
                nilai += jumlah_dimiliki * riwayat_koin[i]["harga"]
        hasil.append(round(nilai, 0))
    return hasil


def ambil_like_info(post_id, username_aktif):
    """[SESI 4 - LIKE] Mengembalikan total like sebuah post & apakah user
    yang sedang login sudah nge-like post tersebut."""
    conn = get_db_connection()
    total = conn.execute(
        "SELECT COUNT(*) AS total FROM feed_likes WHERE post_id = ?", (post_id,)
    ).fetchone()["total"]
    sudah_like = False
    if username_aktif:
        row = conn.execute(
            "SELECT 1 FROM feed_likes WHERE post_id = ? AND username = ?",
            (post_id, username_aktif)
        ).fetchone()
        sudah_like = row is not None
    conn.close()
    return {"total_like": total, "sudah_like": sudah_like}


def ambil_komentar_tree(post_id):
    """[SESI 4 - REPLY THREAD] Mengambil seluruh komentar (yang belum
    di-soft-delete) milik satu post, lalu menyusunnya menjadi struktur
    pohon bertingkat berdasarkan `parent_id`, ala sistem balas komentar
    YouTube (komentar bisa saling membalas berlapis)."""
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT * FROM feed_comments
           WHERE post_id = ? AND comment_hidden = 0
           ORDER BY id ASC""",
        (post_id,)
    ).fetchall()
    conn.close()

    simpul = {}
    akar = []
    for row in rows:
        simpul[row["id"]] = {
            "id": row["id"],
            "username": row["username"],
            "isi_komentar": row["isi_komentar"],
            "timestamp": row["timestamp"],
            "parent_id": row["parent_id"],
            "balasan": []
        }
    for row in rows:
        node = simpul[row["id"]]
        if row["parent_id"] and row["parent_id"] in simpul:
            simpul[row["parent_id"]]["balasan"].append(node)
        else:
            akar.append(node)
    return akar


def ambil_social_feed(limit=15, username_aktif=None):
    """
    [SESI 4 - SOCIAL TRADING FEED] Mengambil N transaksi terbaru dari SELURUH
    user (bukan cuma user yang sedang login) untuk ditampilkan sebagai
    "shoutout" performa komunitas di card Social Trading Feed. Post yang
    sudah di-soft-delete oleh pemiliknya (feed_hidden = 1) otomatis
    disembunyikan. Setiap post juga dilampiri persentase P&L global terkini
    milik si pengirim (lewat hitung_pnl_user), supaya shoutout terasa hidup
    -- mis. "User gacor baru saja menukar BTC ke ETH dengan profit +5%".
    """
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT th.id, th.username, th.tipe_transaksi, th.nama_koin,
               th.nominal_idr, th.jumlah_koin, th.timestamp, u.id AS user_id
        FROM transaction_history th
        LEFT JOIN users u ON u.username = th.username
        WHERE th.feed_hidden = 0
        ORDER BY th.id DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    feed = []
    for row in rows:
        pnl_persen = None
        if row["user_id"] is not None:
            pnl_persen = hitung_pnl_user(row["user_id"])["persen"]

        like_info = ambil_like_info(row["id"], username_aktif)

        feed.append({
            "id": row["id"],
            "username": row["username"],
            "tipe_transaksi": row["tipe_transaksi"],
            "nama_koin": row["nama_koin"],
            "nominal_idr": row["nominal_idr"],
            "jumlah_koin": row["jumlah_koin"],
            "timestamp": row["timestamp"],
            "pnl_persen": pnl_persen,
            "total_like": like_info["total_like"],
            "sudah_like": like_info["sudah_like"],
            "komentar": ambil_komentar_tree(row["id"])
        })
    return feed


def catat_riwayat_transaksi(conn, username, tipe_transaksi, nama_koin, nominal_idr, jumlah_koin):
    """
    [SESI 3 - BUKU BESAR RIWAYAT TRANSAKSI]
    Menyisipkan satu baris baru ke tabel transaction_history menggunakan
    koneksi (conn) yang SAMA dengan transaksi trading/tukar yang sedang
    berjalan, supaya insert riwayat ini ikut ter-commit / ter-rollback
    sebagai satu kesatuan dengan update saldo & portofolio.
    Timestamp diambil presisi jam:menit:detik & tanggal via modul datetime.
    """
    waktu_sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """INSERT INTO transaction_history
           (username, tipe_transaksi, nama_koin, nominal_idr, jumlah_koin, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (username, tipe_transaksi, nama_koin, nominal_idr, jumlah_koin, waktu_sekarang)
    )


def ambil_riwayat_transaksi(username, limit=10):
    """Mengambil N riwayat transaksi terbaru milik seorang user (terbaru
    dahulu) untuk ditampilkan di seksi "Recent Activities" dashboard."""
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT * FROM transaction_history
           WHERE username = ?
           ORDER BY id DESC
           LIMIT ?""",
        (username, limit)
    ).fetchall()
    conn.close()
    return rows


def ambil_semua_user():
    """
    [SESI 3 - TAB "Kelola User"] Mengambil daftar seluruh user terdaftar
    (tanpa password) beserta saldo & jumlah baris portofolio yang mereka
    punya, untuk ditampilkan di tab Kelola User pada dashboard admin.
    """
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT u.id, u.username, u.role, u.saldo_idr,
               COALESCE(SUM(p.jumlah_koin), 0) AS total_koin_dimiliki
        FROM users u
        LEFT JOIN portfolio p ON p.user_id = u.id AND p.jumlah_koin > 0
        GROUP BY u.id
        ORDER BY u.id
    """).fetchall()
    conn.close()
    return rows


# ============================================================
# ROUTE: LOGIN ( '/' )
# ============================================================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username dan password wajib diisi.", "danger")
            return redirect(url_for("login"))

        # Bersihkan session lama SEBELUM mengisi yang baru, supaya kunci
        # session dari akun/role sebelumnya tidak pernah tercampur dengan
        # session akun baru saat user berpindah akun (switch login).
        session.clear()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.permanent = True
            session["user_id"] = 0
            session["username"] = ADMIN_USERNAME
            session["role"] = "admin"
            flash("Login admin berhasil. Selamat datang, Master!", "success")
            return redirect(url_for("dashboard"))

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND password = ?",
            (username, password)
        ).fetchone()
        conn.close()

        if user:
            session.permanent = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash(f"Selamat datang kembali, {user['username']}!", "success")
            return redirect(url_for("dashboard"))

        flash("Username atau password salah. Silakan coba lagi.", "danger")
        return redirect(url_for("login"))

    # mode dipakai dropdown "Switch to Admin/User Login" untuk mengubah
    # judul & placeholder form saja (form & proses login tetap satu, terpadu)
    mode = request.args.get("mode", "user")
    return render_template("login.html", mode=mode)


# ============================================================
# ROUTE: REGISTER ( '/register' )
# ============================================================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username dan password wajib diisi.", "danger")
            return redirect(url_for("register"))

        if len(username) < 3:
            flash("Username minimal 3 karakter.", "danger")
            return redirect(url_for("register"))

        if len(password) < 4:
            flash("Password minimal 4 karakter.", "danger")
            return redirect(url_for("register"))

        conn = get_db_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()

            if existing:
                flash("Username sudah terdaftar, silakan gunakan username lain.", "danger")
                return redirect(url_for("register"))

            saldo_gacha = gacha_saldo_awal()

            cur = conn.cursor()
            cur.execute(
                """INSERT INTO users (username, password, role, saldo_idr, modal_awal_idr)
                   VALUES (?, ?, 'user', ?, ?)""",
                (username, password, saldo_gacha, saldo_gacha)
            )
            new_user_id = cur.lastrowid

            # Insert baris awal portfolio (0 koin) untuk tiap koin yang ada
            # di crypto_market, supaya donut chart & fitur trading tidak
            # error karena data portfolio kosong.
            semua_koin = conn.execute("SELECT nama_koin FROM crypto_market").fetchall()
            for koin in semua_koin:
                cur.execute(
                    "INSERT INTO portfolio (user_id, nama_koin, jumlah_koin) VALUES (?, ?, 0)",
                    (new_user_id, koin["nama_koin"])
                )

            conn.commit()

            saldo_gacha_format = f"{saldo_gacha:,.0f}".replace(",", ".")
            flash(
                f"Registrasi berhasil! Selamat, kamu mendapat gacha saldo awal "
                f"sebesar Rp{saldo_gacha_format}. Silakan login.",
                "success"
            )
            return redirect(url_for("login"))

        except sqlite3.Error as e:
            conn.rollback()
            flash(f"Gagal mendaftar karena masalah database: {e}", "danger")
            return redirect(url_for("register"))

        finally:
            conn.close()

    mode = request.args.get("mode", "user")
    return render_template("register.html", mode=mode)


# ============================================================
# ROUTE: DASHBOARD ( '/dashboard' )
# ============================================================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "danger")
        return redirect(url_for("login"))

    # [FIX KONSISTENSI DROPDOWN PROFIL] username diambil satu kali di sini
    # dari session, lalu SELALU dikirim ke render_template() di kedua cabang
    # (admin & user) dengan nama variabel yang sama, supaya navbar & dropdown
    # profil tidak pernah "hilang" atau tidak lengkap untuk role apapun.
    username_aktif = session["username"]
    role_aktif = session.get("role", "user")
    is_admin = role_aktif == "admin"

    conn = get_db_connection()

    if is_admin:
        total_user = conn.execute("SELECT COUNT(*) as total FROM users").fetchone()["total"]
        total_koin_terdaftar = conn.execute("SELECT COUNT(*) as total FROM crypto_market").fetchone()["total"]
        semua_koin = conn.execute("SELECT * FROM crypto_market").fetchall()

        # [FITUR BARU] Widget "Kotak Masuk Pesan (Admin Only)" di tab Contact:
        # ambil seluruh pesan dari tabel contact_messages, terbaru di atas,
        # supaya admin bisa melihat & mengelola pesan yang masuk dari form
        # "Kirim Pesan" (baik dari Guest maupun User yang sudah login).
        pesan_kontak = conn.execute(
            "SELECT * FROM contact_messages ORDER BY id DESC"
        ).fetchall()

        conn.close()

        semua_user = ambil_semua_user()

        return render_template(
            "dashboard.html",
            is_admin=True,
            username=username_aktif,
            role=role_aktif,
            total_user=total_user,
            total_koin_terdaftar=total_koin_terdaftar,
            semua_koin=semua_koin,
            semua_user=semua_user,
            messages=pesan_kontak,
            saldo_idr=None,
            alokasi_aset=[],
            portofolio_user=[],
            min_beli_idr=MIN_BELI_IDR,
            riwayat_transaksi=[],
            riwayat_harga_btc_json=json.dumps(RIWAYAT_HARGA_BTC),
            market_suspended=get_market_suspended(),
            volatilitas_aktif=session.get("volatilitas", VOLATILITAS_DEFAULT),
            konfig_volatilitas=list(KONFIG_VOLATILITAS.keys()),
            nominal_suntik_saldo=NOMINAL_SUNTIK_SALDO,
            # [SESI 4] Akun admin (superadmin) tidak punya baris di tabel
            # users, jadi tidak ada foto profil ataupun P&L pribadi -- tapi
            # tetap bisa MELIHAT Social Trading Feed seluruh user (read-only,
            # tanpa tombol hapus, demi transparansi rekam jejak performa).
            foto_profil=None,
            pnl_data=None,
            social_feed=ambil_social_feed(username_aktif=username_aktif),
            sparkline_json=json.dumps([]),
            koin_tren_list=KOIN_TERLACAK_HISTORI
        )
    else:
        # Kalau user_id yang tersimpan di session ternyata sudah tidak ada
        # lagi di database (mis. dihapus admin), jangan biarkan halaman
        # error 500 -- paksa logout bersih & kembali ke halaman login.
        user_data = conn.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()

        if user_data is None:
            conn.close()
            session.clear()
            flash("Sesi kamu tidak valid lagi, silakan login ulang.", "danger")
            return redirect(url_for("login"))

        semua_koin = conn.execute("SELECT * FROM crypto_market").fetchall()
        conn.close()

        alokasi_aset = hitung_asset_allocation(session["user_id"])
        portofolio_user = ambil_portofolio_user(session["user_id"])
        riwayat_transaksi = ambil_riwayat_transaksi(username_aktif, limit=10)

        # [SESI 4] Widget Total Saldo & indikator P&L global, dihitung dari
        # nilai total aset (saldo + portofolio) saat ini vs modal awal gacha.
        pnl_data = hitung_pnl_user(session["user_id"])

        # [SESI 4] Jejak nilai total kekayaan untuk sparkline mini di widget
        # Total Saldo, dibangun dari RIWAYAT_HARGA yang sudah dipre-populate.
        sparkline_json = json.dumps(hitung_riwayat_nilai_portofolio(session["user_id"]))

        return render_template(
            "dashboard.html",
            is_admin=False,
            username=username_aktif,
            role=role_aktif,
            saldo_idr=user_data["saldo_idr"],
            semua_koin=semua_koin,
            semua_user=[],
            total_user=None,
            total_koin_terdaftar=None,
            messages=[],
            alokasi_aset=alokasi_aset,
            portofolio_user=portofolio_user,
            min_beli_idr=MIN_BELI_IDR,
            riwayat_transaksi=riwayat_transaksi,
            riwayat_harga_btc_json=json.dumps(RIWAYAT_HARGA_BTC),
            market_suspended=get_market_suspended(),
            volatilitas_aktif=session.get("volatilitas", VOLATILITAS_DEFAULT),
            konfig_volatilitas=list(KONFIG_VOLATILITAS.keys()),
            nominal_suntik_saldo=NOMINAL_SUNTIK_SALDO,
            # [SESI 4] Foto profil (dropdown navbar), P&L widget, & Social
            # Trading Feed (termasuk hak hapus post milik sendiri).
            foto_profil=user_data["foto_profil"],
            pnl_data=pnl_data,
            social_feed=ambil_social_feed(username_aktif=username_aktif),
            sparkline_json=sparkline_json,
            koin_tren_list=KOIN_TERLACAK_HISTORI
        )


# ============================================================
# ROUTE: REFRESH HARGA CRYPTO (fallback non-JS, full reload)
# ============================================================
@app.route("/market/refresh")
def market_refresh():
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "danger")
        return redirect(url_for("login"))

    # [SESI 3 - DEVELOPER OPTIONS] Jika admin sudah menyalakan Global Market
    # Suspend, tombol refresh harga di sisi user biasa terkunci otomatis.
    # Admin sendiri tetap bisa refresh (mis. untuk mengecek sebelum membuka
    # suspend lagi).
    if get_market_suspended() and session.get("role") != "admin":
        flash("Pasar sedang DISUSPEND oleh admin. Refresh harga sementara dikunci.", "danger")
        return redirect(url_for("dashboard"))

    multiplier = KONFIG_VOLATILITAS.get(
        session.get("volatilitas", VOLATILITAS_DEFAULT), 1.0
    )
    perbarui_harga_crypto(multiplier=multiplier)
    flash("Harga crypto berhasil diperbarui (simulasi fluktuasi acak).", "success")
    return redirect(url_for("dashboard"))


# ============================================================
# ROUTE: REFRESH HARGA CRYPTO -- VERSI JSON (dipakai tombol AJAX)
# ============================================================
@app.route("/api/refresh-harga", methods=["POST"])
def api_refresh_harga():
    """
    Dipanggil lewat fetch() oleh tombol "Refresh Harga" di dashboard supaya
    harga bisa ter-update secara live tanpa reload halaman penuh, dibarengi
    animasi loading screen di sisi frontend. Mengembalikan JSON berisi harga
    terbaru seluruh koin, sekaligus data terbaru Line Chart tren BTC.

    [SESI 3] Jika Global Market Suspend sedang aktif dan yang menekan tombol
    bukan admin, permintaan ditolak (dikunci) dengan status 423.
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "message": "Sesi login habis, silakan login ulang."}), 401

    if get_market_suspended() and session.get("role") != "admin":
        return jsonify({
            "ok": False,
            "message": "Pasar sedang DISUSPEND oleh admin. Refresh harga terkunci sementara."
        }), 423

    multiplier = KONFIG_VOLATILITAS.get(
        session.get("volatilitas", VOLATILITAS_DEFAULT), 1.0
    )
    perbarui_harga_crypto(multiplier=multiplier)

    conn = get_db_connection()
    semua_koin = conn.execute("SELECT nama_koin, harga_fiktif FROM crypto_market").fetchall()
    conn.close()

    data = [{"nama_koin": r["nama_koin"], "harga_fiktif": r["harga_fiktif"]} for r in semua_koin]
    return jsonify({
        "ok": True,
        "message": "Harga crypto berhasil diperbarui.",
        "data": data,
        "chart_btc": RIWAYAT_HARGA_BTC,        # dipertahankan untuk kompatibilitas lama
        "chart_history": RIWAYAT_HARGA          # [BARU] riwayat lengkap BTC/ETH/SOL/DOGE
    })


# ============================================================
# ROUTE: RINGKASAN ADMIN -- VERSI JSON (tab Master Control interaktif)
# ============================================================
@app.route("/api/admin/ringkasan")
def api_admin_ringkasan():
    """
    [SESI 3 - Master Control interaktif] Dipanggil lewat fetch() oleh tombol
    "Refresh Ringkasan" di tab Master Control supaya total user & total koin
    ter-update live tanpa reload halaman penuh.
    """
    if "user_id" not in session or session.get("role") != "admin":
        return jsonify({"ok": False, "message": "Akses ditolak. Hanya untuk admin."}), 403

    conn = get_db_connection()
    total_user = conn.execute("SELECT COUNT(*) as total FROM users").fetchone()["total"]
    total_koin = conn.execute("SELECT COUNT(*) as total FROM crypto_market").fetchone()["total"]
    conn.close()

    return jsonify({
        "ok": True,
        "message": "Ringkasan Master Control berhasil diperbarui.",
        "total_user": total_user,
        "total_koin": total_koin
    })


# ============================================================
# ROUTE: [SESI 3] DATA LINE CHART TREN HARGA BTC -- VERSI JSON
# ============================================================
@app.route("/api/chart/btc")
def api_chart_btc():
    """
    Dipakai Chart.js di dashboard untuk memuat ulang seluruh titik data tren
    harga BTC (waktu & harga) kapan pun dibutuhkan, terpisah dari endpoint
    refresh harga utama.
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "message": "Sesi login habis, silakan login ulang."}), 401

    return jsonify({"ok": True, "chart_btc": RIWAYAT_HARGA_BTC})


# ============================================================
# ROUTE: [SESI 3 - REFACTOR] RIWAYAT HARGA MULTI-KOIN -- VERSI JSON
# ============================================================
@app.route("/api/market-history")
def api_market_history():
    """
    [DISTRIBUSI KODE] Dipakai static/js/dashboard.js saat dashboard pertama
    kali dimuat, untuk mengisi Line Chart tren pasar dengan jejak harga
    historis (BTC, ETH, SOL, DOGE) supaya grafik tidak kosong sebelum tombol
    "Refresh Harga" pernah ditekan. Dipisah dari /api/chart/btc supaya masih
    kompatibel dengan pemanggil lama yang hanya butuh data BTC saja.

    [SESI 4] Mendukung query parameter opsional `?coin=KODE_KOIN` (dipakai
    oleh button group multi-coin di dashboard.js) supaya hanya riwayat harga
    koin yang diminta yang dikirim balik. Kalau parameter tidak disertakan
    (pemanggil lama) atau kodenya tidak dikenali, endpoint tetap
    mengembalikan seluruh riwayat seperti sebelumnya supaya tidak ada
    pemanggil lama yang pecah.
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "message": "Sesi login habis, silakan login ulang."}), 401

    kode_koin_diminta = request.args.get("coin", "").strip().upper()

    if kode_koin_diminta:
        if kode_koin_diminta not in RIWAYAT_HARGA:
            return jsonify({
                "ok": False,
                "message": f"Riwayat harga untuk koin '{kode_koin_diminta}' tidak tersedia."
            }), 404
        return jsonify({
            "ok": True,
            "data": {kode_koin_diminta: RIWAYAT_HARGA[kode_koin_diminta]}
        })

    return jsonify({"ok": True, "data": RIWAYAT_HARGA})


# ============================================================
# ROUTE: TRADING (BELI / JUAL) CRYPTO FIKTIF -- FRAKSI DESIMAL
# ============================================================
@app.route("/trade", methods=["POST"])
def trade():
    """
    [SESI 3 - OVERHAUL LOGIKA TRADING]
    - aksi='beli' -> input yang dipakai adalah NOMINAL RUPIAH (nominal_beli),
      minimal Rp10.000. Jumlah koin baru = nominal_beli_idr / harga_koin_live,
      dibulatkan ke 8 digit desimal, lalu ditambahkan ke portfolio.
    - aksi='jual' -> input yang dipakai adalah JUMLAH KOIN (jumlah_koin,
      pecahan desimal) yang mau dijual dari kepemilikan user saat ini.
      Hasil konversi ke Rupiah ditambahkan ke saldo_idr user.
    """
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "danger")
        return redirect(url_for("login"))

    if session.get("role") == "admin":
        flash("Akun admin tidak memiliki portofolio untuk trading.", "danger")
        return redirect(url_for("dashboard"))

    nama_koin = request.form.get("nama_koin", "").strip().upper()
    aksi = request.form.get("aksi", "").strip().lower()

    if aksi not in ("beli", "jual"):
        flash("Aksi transaksi tidak dikenali.", "danger")
        return redirect(url_for("dashboard"))

    conn = get_db_connection()
    try:
        koin = conn.execute(
            "SELECT * FROM crypto_market WHERE nama_koin = ?", (nama_koin,)
        ).fetchone()
        if koin is None:
            flash("Koin yang dipilih tidak ditemukan di pasar.", "danger")
            return redirect(url_for("dashboard"))

        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if user is None:
            conn.close()
            session.clear()
            flash("Sesi kamu tidak valid lagi, silakan login ulang.", "danger")
            return redirect(url_for("login"))

        harga_saat_ini = koin["harga_fiktif"]

        # -------------------- ALUR BELI (nominal Rupiah) --------------------
        if aksi == "beli":
            nominal_raw = (
                request.form.get("nominal_beli", "")
                .strip()
                .replace("Rp", "")
                .replace(".", "")
                .replace(",", "")
            )
            try:
                nominal_beli_idr = float(nominal_raw)
            except ValueError:
                flash("Nominal pembelian harus berupa angka yang valid.", "danger")
                return redirect(url_for("dashboard"))

            if nominal_beli_idr < MIN_BELI_IDR:
                batas_format = f"{MIN_BELI_IDR:,.0f}".replace(",", ".")
                flash(f"Minimal pembelian adalah Rp{batas_format}.", "danger")
                return redirect(url_for("dashboard"))

            if user["saldo_idr"] < nominal_beli_idr:
                saldo_format = f"{user['saldo_idr']:,.0f}".replace(",", ".")
                flash(
                    f"Saldo tidak cukup. Saldo kamu saat ini Rp{saldo_format}.",
                    "danger"
                )
                return redirect(url_for("dashboard"))

            # Rumus inti: konversi nominal Rupiah menjadi pecahan koin
            # berdasarkan harga live saat ini.
            jumlah_koin_baru = round(nominal_beli_idr / harga_saat_ini, PRESISI_FRAKSI_KOIN)

            if jumlah_koin_baru <= 0:
                flash("Nominal terlalu kecil untuk menghasilkan pecahan koin yang valid.", "danger")
                return redirect(url_for("dashboard"))

            conn.execute(
                "UPDATE users SET saldo_idr = saldo_idr - ? WHERE id = ?",
                (nominal_beli_idr, user["id"])
            )
            baris_portofolio = conn.execute(
                "SELECT id FROM portfolio WHERE user_id = ? AND nama_koin = ?",
                (user["id"], nama_koin)
            ).fetchone()
            if baris_portofolio:
                conn.execute(
                    "UPDATE portfolio SET jumlah_koin = jumlah_koin + ? WHERE user_id = ? AND nama_koin = ?",
                    (jumlah_koin_baru, user["id"], nama_koin)
                )
            else:
                conn.execute(
                    "INSERT INTO portfolio (user_id, nama_koin, jumlah_koin) VALUES (?, ?, ?)",
                    (user["id"], nama_koin, jumlah_koin_baru)
                )

            catat_riwayat_transaksi(
                conn, user["username"], "Beli", nama_koin,
                nominal_beli_idr, jumlah_koin_baru
            )
            conn.commit()

            nominal_format = f"{nominal_beli_idr:,.0f}".replace(",", ".")
            flash(
                f"Berhasil membeli {jumlah_koin_baru:.8f} {nama_koin} "
                f"seharga Rp{nominal_format}.",
                "success"
            )

        # -------------------- ALUR JUAL (jumlah koin fraksi) --------------------
        else:
            jumlah_raw = request.form.get("jumlah_koin", "").strip().replace(",", ".")
            try:
                jumlah_koin_jual = float(jumlah_raw)
            except ValueError:
                flash("Jumlah koin yang dijual harus berupa angka yang valid.", "danger")
                return redirect(url_for("dashboard"))

            if jumlah_koin_jual <= 0:
                flash("Jumlah koin yang dijual harus lebih besar dari 0.", "danger")
                return redirect(url_for("dashboard"))

            baris_portofolio = conn.execute(
                "SELECT jumlah_koin FROM portfolio WHERE user_id = ? AND nama_koin = ?",
                (user["id"], nama_koin)
            ).fetchone()
            dimiliki = baris_portofolio["jumlah_koin"] if baris_portofolio else 0

            if dimiliki < jumlah_koin_jual:
                flash(
                    f"Koin {nama_koin} yang kamu miliki ({dimiliki:.8f}) tidak cukup "
                    f"untuk menjual {jumlah_koin_jual:.8f}.",
                    "danger"
                )
                return redirect(url_for("dashboard"))

            total_rupiah = round(harga_saat_ini * jumlah_koin_jual, 2)
            total_format = f"{total_rupiah:,.0f}".replace(",", ".")

            conn.execute(
                "UPDATE portfolio SET jumlah_koin = jumlah_koin - ? WHERE user_id = ? AND nama_koin = ?",
                (jumlah_koin_jual, user["id"], nama_koin)
            )
            conn.execute(
                "UPDATE users SET saldo_idr = saldo_idr + ? WHERE id = ?",
                (total_rupiah, user["id"])
            )
            catat_riwayat_transaksi(
                conn, user["username"], "Jual", nama_koin,
                total_rupiah, jumlah_koin_jual
            )
            conn.commit()
            flash(
                f"Berhasil menjual {jumlah_koin_jual:.8f} {nama_koin} seharga Rp{total_format}.",
                "success"
            )

    except sqlite3.Error as e:
        conn.rollback()
        flash(f"Transaksi gagal karena masalah database: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("dashboard"))


# ============================================================
# ROUTE: PENGATURAN -- RESET AKUN & ULANGI GACHA SALDO
# ============================================================
@app.route("/reset-akun", methods=["POST"])
def reset_akun():
    """
    [SESI 3 - Tab Pengaturan] Mereset akun user yang sedang login ke kondisi
    awal: saldo_idr diundi ulang lewat gacha_saldo_awal(), dan seluruh baris
    portfolio milik user tersebut dikembalikan ke 0 (tanpa menghapus baris,
    supaya relasi & riwayat koin tetap ada). Hanya berlaku untuk akun user
    biasa, bukan admin.
    """
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "danger")
        return redirect(url_for("login"))

    if session.get("role") == "admin":
        flash("Akun admin tidak memiliki data akun untuk direset.", "danger")
        return redirect(url_for("dashboard"))

    conn = get_db_connection()
    try:
        saldo_baru = gacha_saldo_awal()
        conn.execute(
            "UPDATE users SET saldo_idr = ? WHERE id = ?",
            (saldo_baru, session["user_id"])
        )
        conn.execute(
            "UPDATE portfolio SET jumlah_koin = 0 WHERE user_id = ?",
            (session["user_id"],)
        )
        conn.commit()

        saldo_format = f"{saldo_baru:,.0f}".replace(",", ".")
        flash(
            f"Akun berhasil direset! Gacha saldo baru: Rp{saldo_format}, "
            f"seluruh portofolio koin dikembalikan ke 0.",
            "success"
        )
    except sqlite3.Error as e:
        conn.rollback()
        flash(f"Reset akun gagal karena masalah database: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("dashboard"))


# ============================================================
# ROUTE: [SESI 4] SOCIAL TRADING FEED -- HAPUS POST (SPECIAL PERMISSION)
# ============================================================
@app.route("/social-feed/hapus/<int:post_id>", methods=["POST"])
def hapus_post_feed(post_id):
    """
    Aturan Penghapusan (Delete Permission):
    - USER/GUEST biasa BOLEH menghapus post di Social Trading Feed, TAPI
      hanya post milik mereka sendiri (dicocokkan lewat username di session).
    - ADMIN TIDAK BOLEH menghapus post SAMA SEKALI (baik miliknya sendiri
      atau siapapun), demi menjaga transparansi rekam jejak performa
      seluruh mahasiswa. Aturan ini ditegakkan di backend (bukan cuma
      menyembunyikan tombol di frontend) supaya tidak bisa dilewati lewat
      request manual.

    Penghapusan bersifat SOFT DELETE (kolom feed_hidden diset 1) supaya
    baris asli di transaction_history tetap utuh untuk "Recent Activities"
    & buku besar transaksi -- yang hilang murni tampilannya di feed sosial.
    """
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "danger")
        return redirect(url_for("login"))

    if session.get("role") == "admin":
        flash(
            "Admin tidak diizinkan menghapus post apapun di Social Trading "
            "Feed, demi menjaga transparansi rekam jejak performa mahasiswa.",
            "danger"
        )
        return redirect(url_for("dashboard"))

    conn = get_db_connection()
    try:
        post = conn.execute(
            "SELECT username FROM transaction_history WHERE id = ?", (post_id,)
        ).fetchone()

        if post is None:
            flash("Post tidak ditemukan (mungkin sudah dihapus sebelumnya).", "danger")
            return redirect(url_for("dashboard"))

        if post["username"] != session["username"]:
            flash("Kamu hanya bisa menghapus post milikmu sendiri di Social Trading Feed.", "danger")
            return redirect(url_for("dashboard"))

        conn.execute(
            "UPDATE transaction_history SET feed_hidden = 1 WHERE id = ?", (post_id,)
        )
        conn.commit()
        flash("Post berhasil dihapus dari Social Trading Feed.", "success")
    except sqlite3.Error as e:
        conn.rollback()
        flash(f"Gagal menghapus post karena masalah database: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("dashboard"))


# ============================================================
# ROUTE: [SESI 4] SOCIAL TRADING FEED -- TOGGLE LIKE (AJAX/JSON)
# ============================================================
@app.route("/api/social-feed/like/<int:post_id>", methods=["POST"])
def toggle_like_feed(post_id):
    """
    Dipanggil lewat fetch() oleh tombol Like (ikon hati) di setiap item
    Social Trading Feed. Satu user hanya bisa like sekali per post --
    ditegakkan lewat UNIQUE(post_id, username) di tabel feed_likes, jadi
    endpoint ini murni toggle: kalau baris like sudah ada -> hapus
    (unlike), kalau belum ada -> insert (like).
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "message": "Silakan login terlebih dahulu."}), 401

    conn = get_db_connection()
    try:
        post = conn.execute(
            "SELECT id FROM transaction_history WHERE id = ? AND feed_hidden = 0", (post_id,)
        ).fetchone()
        if post is None:
            return jsonify({"ok": False, "message": "Post tidak ditemukan di Social Trading Feed."}), 404

        existing = conn.execute(
            "SELECT id FROM feed_likes WHERE post_id = ? AND username = ?",
            (post_id, session["username"])
        ).fetchone()

        if existing:
            conn.execute("DELETE FROM feed_likes WHERE id = ?", (existing["id"],))
            sudah_like = False
        else:
            conn.execute(
                "INSERT INTO feed_likes (post_id, username) VALUES (?, ?)",
                (post_id, session["username"])
            )
            sudah_like = True

        conn.commit()
        total_like = conn.execute(
            "SELECT COUNT(*) AS total FROM feed_likes WHERE post_id = ?", (post_id,)
        ).fetchone()["total"]

        return jsonify({"ok": True, "liked": sudah_like, "total_like": total_like})
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"ok": False, "message": f"Gagal memproses like: {e}"}), 500
    finally:
        conn.close()


# ============================================================
# ROUTE: [SESI 4] SOCIAL TRADING FEED -- TAMBAH KOMENTAR / BALASAN (AJAX)
# ============================================================
@app.route("/api/social-feed/komentar", methods=["POST"])
def tambah_komentar_feed():
    """
    Menambahkan komentar baru ATAU balasan (kalau `parent_id` disertakan)
    ke sebuah post di Social Trading Feed, ala sistem komentar YouTube.
    Mengembalikan seluruh pohon komentar terbaru milik post tersebut supaya
    frontend bisa langsung render ulang tanpa reload halaman.
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "message": "Silakan login terlebih dahulu."}), 401

    post_id = request.form.get("post_id", type=int)
    parent_id = request.form.get("parent_id", type=int)
    isi_komentar = request.form.get("isi_komentar", "").strip()

    if not post_id:
        return jsonify({"ok": False, "message": "Post tujuan komentar tidak valid."}), 400
    if not isi_komentar:
        return jsonify({"ok": False, "message": "Komentar tidak boleh kosong."}), 400
    if len(isi_komentar) > 500:
        return jsonify({"ok": False, "message": "Komentar maksimal 500 karakter."}), 400

    conn = get_db_connection()
    try:
        post = conn.execute(
            "SELECT id FROM transaction_history WHERE id = ? AND feed_hidden = 0", (post_id,)
        ).fetchone()
        if post is None:
            return jsonify({"ok": False, "message": "Post tidak ditemukan di Social Trading Feed."}), 404

        if parent_id:
            induk = conn.execute(
                "SELECT id FROM feed_comments WHERE id = ? AND post_id = ? AND comment_hidden = 0",
                (parent_id, post_id)
            ).fetchone()
            if induk is None:
                return jsonify({"ok": False, "message": "Komentar yang mau dibalas tidak ditemukan."}), 404

        waktu_sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO feed_comments (post_id, parent_id, username, isi_komentar, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (post_id, parent_id if parent_id else None, session["username"], isi_komentar, waktu_sekarang)
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"ok": False, "message": f"Gagal mengirim komentar: {e}"}), 500
    finally:
        conn.close()

    return jsonify({"ok": True, "komentar": ambil_komentar_tree(post_id)})


# ============================================================
# ROUTE: [SESI 4] SOCIAL TRADING FEED -- HAPUS KOMENTAR (SPECIAL PERMISSION)
# ============================================================
@app.route("/api/social-feed/hapus-komentar/<int:comment_id>", methods=["POST"])
def hapus_komentar_feed(comment_id):
    """
    Aturan hak hapus KOMENTAR mengikuti aturan hak hapus POST demi
    konsistensi transparansi rekam jejak diskusi komunitas:
    - USER/GUEST boleh menghapus komentar (atau balasan) MILIK SENDIRI saja.
    - ADMIN TIDAK BOLEH menghapus komentar siapapun (termasuk miliknya
      sendiri kalau admin ikut berkomentar), sama seperti admin tidak boleh
      menghapus post apapun di Social Trading Feed.
    Bersifat SOFT DELETE (comment_hidden = 1) supaya thread balasan di
    bawahnya tetap utuh strukturnya.
    """
    if "user_id" not in session:
        return jsonify({"ok": False, "message": "Silakan login terlebih dahulu."}), 401

    conn = get_db_connection()
    try:
        komentar = conn.execute(
            "SELECT * FROM feed_comments WHERE id = ?", (comment_id,)
        ).fetchone()
        if komentar is None:
            return jsonify({"ok": False, "message": "Komentar tidak ditemukan (mungkin sudah dihapus)."}), 404

        if session.get("role") == "admin":
            return jsonify({
                "ok": False,
                "message": "Admin tidak diizinkan menghapus komentar apapun di Social Trading Feed, "
                           "demi menjaga transparansi rekam jejak diskusi komunitas."
            }), 403

        if komentar["username"] != session["username"]:
            return jsonify({"ok": False, "message": "Kamu hanya bisa menghapus komentar milikmu sendiri."}), 403

        conn.execute("UPDATE feed_comments SET comment_hidden = 1 WHERE id = ?", (comment_id,))
        conn.commit()
        post_id = komentar["post_id"]
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"ok": False, "message": f"Gagal menghapus komentar: {e}"}), 500
    finally:
        conn.close()

    return jsonify({"ok": True, "komentar": ambil_komentar_tree(post_id)})


# ============================================================
# ROUTE: [SESI 4] PENGATURAN -- EDIT PROFIL (USERNAME/PASSWORD/FOTO)
# ============================================================
def _ekstensi_foto_diizinkan(nama_file):
    return (
        "." in nama_file
        and nama_file.rsplit(".", 1)[1].lower() in EKSTENSI_FOTO_DIIZINKAN
    )


@app.route("/profil/edit", methods=["POST"])
def edit_profil():
    """
    Form "Edit Profil" di tab Pengaturan: mendukung ganti username, ganti
    password, dan/atau upload foto profil baru -- SEMUA kolom bersifat
    opsional, dikirim sekaligus lewat satu form (multipart/form-data),
    kolom yang dikosongkan tidak akan diubah.

    Foto profil asli yang diupload disimpan ke static/img/ dengan nama file
    baru yang aman (memakai id user + timestamp, bukan nama file asli dari
    user, untuk mencegah path traversal / nama file berbahaya), lalu nama
    file tersebut disimpan ke kolom foto_profil di tabel users supaya bisa
    ditampilkan dinamis di dropdown profil navbar.
    """
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "danger")
        return redirect(url_for("login"))

    if session.get("role") == "admin":
        flash("Akun admin (superadmin) tidak memiliki baris profil di database untuk diedit lewat form ini.", "danger")
        return redirect(url_for("dashboard"))

    username_baru = request.form.get("username_baru", "").strip()
    password_baru = request.form.get("password_baru", "").strip()
    file_foto = request.files.get("foto_profil")

    conn = get_db_connection()
    try:
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if user is None:
            conn.close()
            session.clear()
            flash("Sesi kamu tidak valid lagi, silakan login ulang.", "danger")
            return redirect(url_for("login"))

        perubahan = []

        # -------------------- GANTI USERNAME --------------------
        if username_baru and username_baru != user["username"]:
            if len(username_baru) < 3:
                flash("Username baru minimal 3 karakter.", "danger")
                return redirect(url_for("dashboard"))

            username_dipakai = conn.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?",
                (username_baru, user["id"])
            ).fetchone()
            if username_dipakai:
                flash("Username baru sudah dipakai user lain, silakan pilih username lain.", "danger")
                return redirect(url_for("dashboard"))

            conn.execute(
                "UPDATE users SET username = ? WHERE id = ?", (username_baru, user["id"])
            )
            # Jaga konsistensi riwayat transaksi & Social Trading Feed lama
            # supaya tetap tertaut ke akun yang sama setelah ganti nama.
            conn.execute(
                "UPDATE transaction_history SET username = ? WHERE username = ?",
                (username_baru, user["username"])
            )
            session["username"] = username_baru
            perubahan.append("username")

        # -------------------- GANTI PASSWORD --------------------
        if password_baru:
            if len(password_baru) < 4:
                flash("Password baru minimal 4 karakter.", "danger")
                return redirect(url_for("dashboard"))
            conn.execute(
                "UPDATE users SET password = ? WHERE id = ?", (password_baru, user["id"])
            )
            perubahan.append("password")

        # -------------------- UPLOAD FOTO PROFIL --------------------
        if file_foto and file_foto.filename:
            if not _ekstensi_foto_diizinkan(file_foto.filename):
                flash("Format foto tidak didukung. Gunakan PNG/JPG/JPEG/GIF/WEBP.", "danger")
                return redirect(url_for("dashboard"))

            ekstensi = file_foto.filename.rsplit(".", 1)[1].lower()
            nama_file_baru = secure_filename(
                f"profil_user{user['id']}_{int(datetime.now().timestamp())}.{ekstensi}"
            )
            os.makedirs(FOLDER_FOTO_PROFIL, exist_ok=True)
            file_foto.save(os.path.join(FOLDER_FOTO_PROFIL, nama_file_baru))

            conn.execute(
                "UPDATE users SET foto_profil = ? WHERE id = ?", (nama_file_baru, user["id"])
            )
            perubahan.append("foto profil")

        conn.commit()

        if perubahan:
            flash("Berhasil memperbarui: " + ", ".join(perubahan) + ".", "success")
        else:
            flash("Tidak ada perubahan yang dikirim (semua kolom dikosongkan).", "info")

    except sqlite3.Error as e:
        conn.rollback()
        flash(f"Gagal memperbarui profil karena masalah database: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("dashboard"))


# ============================================================
# ROUTE: [SESI 3] QUICK EXCHANGE -- TUKAR KILAT ANTAR KOIN
# ============================================================
@app.route("/quick-exchange", methods=["POST"])
def quick_exchange():
    """
    Panel "Quick Exchange" di dashboard: menukar sejumlah koin yang dimiliki
    user (dari_koin) langsung menjadi koin lain (ke_koin) berdasarkan nilai
    Rupiah live kedua koin tersebut saat ini, tanpa melalui saldo_idr sama
    sekali (murni tukar-menukar portofolio).
    """
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "danger")
        return redirect(url_for("login"))

    if session.get("role") == "admin":
        flash("Akun admin tidak memiliki portofolio untuk ditukar.", "danger")
        return redirect(url_for("dashboard"))

    dari_koin = request.form.get("dari_koin", "").strip().upper()
    ke_koin = request.form.get("ke_koin", "").strip().upper()
    jumlah_raw = request.form.get("jumlah_dari", "").strip().replace(",", ".")

    if not dari_koin or not ke_koin or dari_koin == ke_koin:
        flash("Pilih dua koin yang berbeda untuk ditukar.", "danger")
        return redirect(url_for("dashboard"))

    try:
        jumlah_dari = float(jumlah_raw)
    except ValueError:
        flash("Jumlah koin yang ditukar harus berupa angka yang valid.", "danger")
        return redirect(url_for("dashboard"))

    if jumlah_dari <= 0:
        flash("Jumlah koin yang ditukar harus lebih besar dari 0.", "danger")
        return redirect(url_for("dashboard"))

    conn = get_db_connection()
    try:
        harga_dari = conn.execute(
            "SELECT harga_fiktif FROM crypto_market WHERE nama_koin = ?", (dari_koin,)
        ).fetchone()
        harga_ke = conn.execute(
            "SELECT harga_fiktif FROM crypto_market WHERE nama_koin = ?", (ke_koin,)
        ).fetchone()
        if harga_dari is None or harga_ke is None:
            flash("Salah satu koin yang dipilih tidak ditemukan di pasar.", "danger")
            return redirect(url_for("dashboard"))

        baris_dimiliki = conn.execute(
            "SELECT jumlah_koin FROM portfolio WHERE user_id = ? AND nama_koin = ?",
            (session["user_id"], dari_koin)
        ).fetchone()
        dimiliki = baris_dimiliki["jumlah_koin"] if baris_dimiliki else 0

        if dimiliki < jumlah_dari:
            flash(
                f"Koin {dari_koin} yang kamu miliki ({dimiliki:.8f}) tidak cukup "
                f"untuk ditukar sejumlah {jumlah_dari:.8f}.",
                "danger"
            )
            return redirect(url_for("dashboard"))

        nilai_rupiah = jumlah_dari * harga_dari["harga_fiktif"]
        jumlah_ke = round(nilai_rupiah / harga_ke["harga_fiktif"], PRESISI_FRAKSI_KOIN)

        if jumlah_ke <= 0:
            flash("Jumlah tukar terlalu kecil untuk menghasilkan pecahan koin yang valid.", "danger")
            return redirect(url_for("dashboard"))

        conn.execute(
            "UPDATE portfolio SET jumlah_koin = jumlah_koin - ? WHERE user_id = ? AND nama_koin = ?",
            (jumlah_dari, session["user_id"], dari_koin)
        )
        baris_ke = conn.execute(
            "SELECT id FROM portfolio WHERE user_id = ? AND nama_koin = ?",
            (session["user_id"], ke_koin)
        ).fetchone()
        if baris_ke:
            conn.execute(
                "UPDATE portfolio SET jumlah_koin = jumlah_koin + ? WHERE user_id = ? AND nama_koin = ?",
                (jumlah_ke, session["user_id"], ke_koin)
            )
        else:
            conn.execute(
                "INSERT INTO portfolio (user_id, nama_koin, jumlah_koin) VALUES (?, ?, ?)",
                (session["user_id"], ke_koin, jumlah_ke)
            )

        catat_riwayat_transaksi(
            conn, session["username"], "Tukar", f"{dari_koin}→{ke_koin}",
            nilai_rupiah, jumlah_ke
        )
        conn.commit()

        flash(
            f"Berhasil menukar {jumlah_dari:.8f} {dari_koin} menjadi "
            f"{jumlah_ke:.8f} {ke_koin}.",
            "success"
        )
    except sqlite3.Error as e:
        conn.rollback()
        flash(f"Tukar kilat gagal karena masalah database: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("dashboard"))


# ============================================================
# ROUTE: [SESI 3] PENGATURAN -- MODE VOLATILITAS PASAR (USER)
# ============================================================
@app.route("/pengaturan/volatilitas", methods=["POST"])
def set_volatilitas():
    """
    Menyimpan pilihan "Mode Volatilitas Pasar" (Normal/Konservatif/Agresif)
    ke session user, dipakai sebagai multiplier intensitas fluktuasi setiap
    kali tombol Refresh Harga ditekan oleh user tersebut.
    """
    if "user_id" not in session:
        flash("Silakan login terlebih dahulu.", "danger")
        return redirect(url_for("login"))

    mode = request.form.get("mode_volatilitas", "").strip().lower()
    if mode not in KONFIG_VOLATILITAS:
        flash("Mode volatilitas tidak dikenali.", "danger")
        return redirect(url_for("dashboard"))

    session["volatilitas"] = mode
    flash(f"Mode Volatilitas Pasar diubah ke: {mode.upper()}.", "success")
    return redirect(url_for("dashboard"))


# ============================================================
# ROUTE: [SESI 3] DEVELOPER OPTIONS -- GLOBAL MARKET SUSPEND (ADMIN)
# ============================================================
@app.route("/admin/toggle-suspend", methods=["POST"])
def admin_toggle_suspend():
    if "user_id" not in session or session.get("role") != "admin":
        flash("Akses ditolak. Hanya untuk admin.", "danger")
        return redirect(url_for("dashboard"))

    status_baru = not get_market_suspended()
    set_market_suspended(status_baru)

    if status_baru:
        flash("Global Market Suspend DIAKTIFKAN. Refresh harga user biasa terkunci.", "danger")
    else:
        flash("Global Market Suspend DINONAKTIFKAN. Pasar berjalan normal kembali.", "success")

    return redirect(url_for("dashboard"))


# ============================================================
# ROUTE: [SESI 3] DEVELOPER OPTIONS -- SUNTIK SALDO MASSAL (ADMIN)
# ============================================================
@app.route("/admin/suntik-saldo", methods=["POST"])
def admin_suntik_saldo():
    if "user_id" not in session or session.get("role") != "admin":
        flash("Akses ditolak. Hanya untuk admin.", "danger")
        return redirect(url_for("dashboard"))

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET saldo_idr = saldo_idr + ?", (NOMINAL_SUNTIK_SALDO,)
        )
        conn.commit()
        nominal_format = f"{NOMINAL_SUNTIK_SALDO:,.0f}".replace(",", ".")
        flash(
            f"Berhasil menyuntikkan Rp{nominal_format} ke seluruh user terdaftar.",
            "success"
        )
    except sqlite3.Error as e:
        conn.rollback()
        flash(f"Suntik saldo massal gagal karena masalah database: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("dashboard"))
@app.route("/switch/<mode>")
def switch_login(mode):
    """
    Dipanggil dari dropdown foto profil:
    - /switch/admin -> logout paksa, arahkan ke form login (mode admin)
    - /switch/user  -> logout paksa, arahkan ke form login (mode user/guest)
    session.clear() memastikan tidak ada sisa data akun sebelumnya yang
    "nyangkut" saat berganti akun.
    """
    session.clear()
    if mode == "admin":
        flash("Silakan login sebagai Admin.", "info")
        return redirect(url_for("login", mode="admin"))

    flash("Silakan login sebagai User/Guest.", "info")
    return redirect(url_for("login", mode="user"))


# ============================================================
# ROUTE: [SESI 5] TAB CONTACT -- SIMPAN PESAN "HUBUNGI KAMI" (AJAX/JSON)
# ============================================================
@app.route("/api/contact/kirim", methods=["POST"])
def kirim_pesan_kontak():
    """
    Menangani submit form "Kirim Pesan" di tab Contact (dashboard.js,
    fungsi pasangMenuContactDanForm()). Dibuat sebagai endpoint JSON
    (dipanggil lewat fetch(), bukan submit form biasa) supaya frontend bisa
    tetap menampilkan toast sukses/gagal tanpa reload halaman penuh, persis
    seperti UX yang sudah ada di tombol "Refresh Harga".

    Tersedia untuk GUEST (belum login) MAUPUN user yang sudah login --
    kalau session berisi user_id, username_pengirim ikut dicatat supaya
    pesan bisa ditautkan ke akun aslinya; kalau tidak ada session, pesan
    tetap tersimpan dengan username_pengirim = NULL (murni dari nama & email
    yang diisi manual di form).
    """
    nama_pengirim = request.form.get("nama_pengirim", "").strip()
    email_pengirim = request.form.get("email_pengirim", "").strip()
    isi_pesan = request.form.get("isi_pesan", "").strip()

    if not nama_pengirim or not email_pengirim or not isi_pesan:
        return jsonify({
            "ok": False,
            "message": "Nama, email, dan isi pesan wajib diisi."
        }), 400

    if len(isi_pesan) > 1000:
        return jsonify({
            "ok": False,
            "message": "Isi pesan maksimal 1000 karakter."
        }), 400

    username_pengirim = session.get("username") if "user_id" in session else None
    waktu_sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO contact_messages
               (username_pengirim, nama_pengirim, email_pengirim, isi_pesan, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (username_pengirim, nama_pengirim, email_pengirim, isi_pesan, waktu_sekarang)
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({
            "ok": False,
            "message": f"Gagal menyimpan pesan karena masalah database: {e}"
        }), 500
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "message": f"Terima kasih {nama_pengirim}, pesanmu sudah tercatat untuk developer!"
    })


# ============================================================
# ROUTE: [FITUR BARU] TAB CONTACT -- HAPUS PESAN KOTAK MASUK (AJAX/JSON,
#        KHUSUS ADMIN)
# ============================================================
@app.route("/api/contact/hapus/<int:id>", methods=["POST"])
def hapus_pesan_kontak(id):
    """
    Dipanggil dari tombol "Hapus" di widget "📬 Kotak Masuk Pesan (Admin
    Only)" pada tab Contact (dashboard.js). Endpoint JSON murni (fetch),
    jadi baris tabel yang dihapus bisa langsung hilang dari UI tanpa reload
    halaman penuh. Khusus ADMIN -- ditegakkan di backend, bukan cuma
    menyembunyikan tombolnya di frontend.
    """
    if "user_id" not in session or session.get("role") != "admin":
        return jsonify({
            "ok": False,
            "message": "Hanya admin yang boleh menghapus pesan kotak masuk."
        }), 403

    conn = get_db_connection()
    try:
        pesan = conn.execute(
            "SELECT id FROM contact_messages WHERE id = ?", (id,)
        ).fetchone()

        if pesan is None:
            return jsonify({
                "ok": False,
                "message": "Pesan tidak ditemukan (mungkin sudah dihapus sebelumnya)."
            }), 404

        conn.execute("DELETE FROM contact_messages WHERE id = ?", (id,))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({
            "ok": False,
            "message": f"Gagal menghapus pesan karena masalah database: {e}"
        }), 500
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "message": "Pesan berhasil dihapus dari kotak masuk."
    })


# ============================================================
# ROUTE: [FITUR BARU] TAB CONTACT -- EKSPOR DATA PESAN KE CSV
#        (ON-THE-FLY, KHUSUS ADMIN)
# ============================================================
@app.route("/api/contact/ekspor-csv")
def ekspor_pesan_kontak_csv():
    """
    Dipanggil dari tombol "📥 Ekspor Data Pesan (CSV)" di atas widget
    "Kotak Masuk Pesan (Admin Only)". Seluruh baris di contact_messages
    diracik jadi string CSV langsung di memori (io.StringIO), tanpa pernah
    menulis file fisik apapun ke folder proyek, lalu dikembalikan sebagai
    response dengan header Content-Disposition supaya browser otomatis
    mengunduhnya sebagai file .csv.
    """
    if "user_id" not in session or session.get("role") != "admin":
        # [HOTFIX] Tombol "Ekspor Data Pesan (CSV)" sekarang dipicu lewat
        # fetch() di dashboard.js (bukan navigasi <a href> biasa lagi),
        # supaya spinner tombolnya bisa dijamin berhenti lewat blok
        # try/finally di sisi JS. Kalau sesi admin ternyata sudah habis,
        # request AJAX ini HARUS dibalas JSON -- bukan redirect ke HTML
        # halaman login/dashboard -- karena kalau tetap redirect, isi HTML
        # itu akan "berhasil" diunduh browser sebagai file bernama
        # laporan_pesan_majalaya.csv yang isinya kacau (bukan CSV asli).
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "ok": False,
                "message": "Sesi admin sudah berakhir. Silakan login ulang."
            }), 403
        flash("Hanya admin yang boleh mengekspor data pesan kotak masuk.", "danger")
        return redirect(url_for("dashboard"))

    conn = get_db_connection()
    semua_pesan = conn.execute(
        "SELECT * FROM contact_messages ORDER BY id DESC"
    ).fetchall()
    conn.close()

    buffer_csv = io.StringIO()
    penulis_csv = csv.writer(buffer_csv)
    penulis_csv.writerow([
        "ID", "Username Pengirim", "Nama Pengirim", "Email Pengirim",
        "Isi Pesan", "Waktu Kirim", "Dibaca"
    ])
    for pesan in semua_pesan:
        penulis_csv.writerow([
            pesan["id"],
            pesan["username_pengirim"] or "-",
            pesan["nama_pengirim"],
            pesan["email_pengirim"],
            pesan["isi_pesan"],
            pesan["timestamp"],
            "Ya" if pesan["dibaca"] else "Tidak"
        ])

    return Response(
        buffer_csv.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Type": "text/csv",
            "Content-Disposition": "attachment; filename=laporan_pesan_majalaya.csv"
        }
    )


# ============================================================
# ROUTE: LOGOUT
# ============================================================
@app.route("/logout")
def logout():
    session.clear()
    flash("Kamu berhasil logout.", "success")
    return redirect(url_for("login"))


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    app.run(debug=True)

# ============================================================
# [DEPLOYMENT] HANDLER WSGI UNTUK VERCEL
# ============================================================
# Vercel (lewat runtime @vercel/python, lihat vercel.json) tidak memanggil
# app.run() -- ia mencari objek WSGI bernama "app" langsung dari modul ini
# dan menjalankannya sebagai handler serverless. Objek "app" sudah dibuat
# di baris "app = Flask(__name__, static_folder='static',
# static_url_path='/static')" di bagian atas file, dengan folder statis
# didefinisikan secara eksplisit agar konsisten dengan rute "/static/(.*)"
# pada vercel.json. Baris "handler = app" di bawah ini hanya alias, bukan
# instance Flask baru, agar terlihat eksplisit bagi siapa pun yang membaca
# konfigurasi deployment.
#
# Aset statis (CSS/JS/gambar) di folder static/ dideploy Vercel lewat build
# terpisah "@vercel/static" (lihat vercel.json), sehingga permintaan ke
# "/static/..." dilayani langsung sebagai file statis, bukan diteruskan ke
# fungsi serverless Python ini.
#
# ensure_database() juga sudah dipanggil secara otomatis di level modul
# (lihat baris pemanggilan "ensure_database()" tepat setelah definisinya di
# atas), yaitu saat file ini pertama kali di-import. Karena Vercel meng-
# import modul ini untuk mendapatkan objek "app", inisialisasi skema
# database akan otomatis berjalan juga saat cold start di Vercel, persis
# seperti saat dijalankan lokal lewat "python app.py".
handler = app
