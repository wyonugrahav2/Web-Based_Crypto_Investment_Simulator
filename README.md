# 🪙 Majalaya Crypto

**Sistem Informasi Simulasi Investasi Cryptocurrency untuk Mahasiswa**

Majalaya Crypto adalah aplikasi web edukasi berbasis Flask yang mensimulasikan
pengalaman trading aset kripto secara **fiktif dan bebas risiko**. Aplikasi
ini dirancang sebagai media pembelajaran bagi mahasiswa untuk memahami
konsep dasar investasi, fluktuasi harga, manajemen portofolio, dan interaksi
sosial seputar dunia crypto — tanpa melibatkan uang sungguhan.

---

## ✨ Fitur Utama

- **💰 10 Aset Kripto Simulasi**
  Tersedia 10 koin dengan karakter fluktuasi berbeda-beda: `BTC`, `ETH`,
  `SOL`, `DOGE`, `BNB`, `XRP`, `ADA`, `NEAR`, `SHIB`, dan `USDT` (stablecoin
  dengan harga flat). Setiap koin memiliki tingkat volatilitas sendiri, dari
  yang relatif stabil (BTC, ETH, BNB) hingga yang sangat liar layaknya
  meme coin (DOGE, SHIB).

- **📊 Dashboard Multi-Role**
  Tiga peran pengguna dengan tampilan dan kewenangan berbeda:
  - **Admin** — Master Control, kelola user, suntik saldo massal, suspend
    akun, ringkasan statistik live.
  - **User terdaftar** — Trading (beli/jual), portofolio pribadi, riwayat
    transaksi, edit profil, pengaturan volatilitas & reset akun.
  - **Guest/mode tamu** — Eksplorasi dashboard dengan akses terbatas.

- **📈 Simulasi Harga Real-Time**
  Harga tiap koin berfluktuasi otomatis dengan logika acak yang disesuaikan
  per koin, dilengkapi grafik tren pasar (Chart.js) dan histori harga BTC.

- **🔁 Mekanisme Trading Presisi**
  - **Beli**: input nominal Rupiah (minimal Rp10.000), jumlah koin dihitung
    otomatis dengan presisi hingga 8 digit desimal.
  - **Jual**: input jumlah koin (pecahan desimal) yang dikonversi ke Rupiah
    berdasarkan harga live saat transaksi.
  - Perbaikan khusus untuk koin bernilai sangat kecil seperti **SHIB**, agar
    harga tidak pernah "macet" di angka minimum akibat pembulatan.

- **📥 Export CSV**
  Admin dapat mengekspor data pesan/kontak masuk ke dalam format `.csv`
  untuk kebutuhan pelaporan atau arsip.

- **💬 Social Feed Interaktif**
  Fitur mirip media sosial di dalam dashboard: like, komentar (dengan
  balasan/reply), dan hapus komentar/postingan — semuanya berjalan secara
  **AJAX** tanpa perlu reload halaman.

- **🔍 Pencarian & Filter**
  Filter/search bar untuk mempermudah pencarian koin maupun data user.

- **🖼️ Edit Profil & Upload Foto**
  Pengguna dapat mengunggah foto profil dengan validasi ekstensi file yang
  aman (`png`, `jpg`, `jpeg`, `gif`, `webp`).

---

## 🗂️ Struktur Proyek

```
sistem informasi simulasi investasi crypto untuk mahasiswa/
├── static/
│   ├── css/
│   │   └── style.css          # Styling tampilan aplikasi (Dark Mode)
│   ├── img/                   # Penyimpanan aset gambar & foto profil unggahan
│   └── js/
│       └── dashboard.js       # Logika interaktif frontend (AJAX, Chart.js, Search, dsb.)
├── templates/
│   ├── base.html              # Layout utama (Navbar, Sidebar, notifikasi flash)
│   ├── dashboard.html         # Halaman dashboard dinamis (User & Admin Master Control)
│   ├── login.html             # Halaman autentikasi masuk sistem
│   └── register.html          # Halaman pendaftaran akun baru & gacha saldo
├── app.py                     # Backend Flask utama (Routing, proteksi role, logika SQLite)
├── README.md                  # Dokumentasi lengkap panduan aplikasi UAS
├── requirements.txt           # Daftar dependensi modul Python (Flask, dll.)
├── vercel.json                # Konfigurasi deployment serverless ke Vercel Cloud
└── majalaya_crypto.db         # Database SQLite lokal (dibuat otomatis saat app berjalan)
```

---

## ⚙️ Instalasi Lokal

### 1. Prasyarat
- Python **3.9** atau lebih baru
- `pip` (sudah termasuk dalam instalasi Python standar)

### 2. Clone / Ekstrak Proyek
```bash
cd "sistem informasi simulasi investasi crypto untuk mahasiswa"
```

### 3. (Opsional tapi disarankan) Buat Virtual Environment
```bash
python -m venv venv

# Aktifkan di Linux/Mac
source venv/bin/activate

# Aktifkan di Windows
venv\Scripts\activate
```

### 4. Instal Dependensi
```bash
pip install -r requirements.txt
```

---

## ▶️ Menjalankan Aplikasi

### Mode Pengembangan (lokal)
```bash
python app.py
```
Aplikasi akan otomatis membuat skema database (`majalaya_crypto.db`) jika
belum tersedia, lalu berjalan di:

```
http://127.0.0.1:5000/
```

### Mode Production (gunicorn)
```bash
gunicorn app:app --bind 0.0.0.0:8000
```

### Deploy ke Vercel
Proyek ini sudah menyertakan `vercel.json` yang mengarahkan seluruh request
ke instance WSGI `app` di `app.py`. Cukup hubungkan repositori ini ke akun
Vercel Anda (via CLI `vercel` atau dashboard Vercel), dan deployment akan
berjalan otomatis mengikuti konfigurasi tersebut.

> ⚠️ **Catatan penting**: Vercel menjalankan fungsi secara *serverless* dan
> *stateless*. Karena aplikasi ini memakai SQLite (file `.db` di filesystem
> lokal), perubahan data pada deployment Vercel bersifat sementara/tidak
> persisten antar-invocation. Untuk kebutuhan produksi jangka panjang,
> disarankan memakai database eksternal (mis. PostgreSQL/MySQL terkelola).

---

## 👤 Akun Default

| Role  | Username              | Password              |
|-------|-----------------------|------------------------|
| Admin | `superadmin_majalaya` | `Wytta07_Secret2026`  |
| User  | Daftar mandiri lewat halaman **Register** |

Setiap user baru akan mendapatkan saldo awal acak (antara Rp50.000.000 s.d.
Rp500.000.000) sebagai modal simulasi.

---

## 🛠️ Teknologi yang Digunakan

- **Backend**: Flask (Python)
- **Database**: SQLite3
- **Frontend**: HTML, CSS, JavaScript (vanilla + AJAX)
- **Visualisasi Data**: Chart.js
- **Deployment**: Gunicorn (VPS) / Vercel (serverless)

---

## 📄 Lisensi & Disclaimer

Proyek ini dibuat untuk **tujuan edukasi/tugas kuliah** semata. Seluruh data
harga koin bersifat **fiktif** dan disimulasikan secara acak — **bukan**
data pasar crypto yang sesungguhnya, dan tidak boleh dijadikan acuan
keputusan investasi nyata.
