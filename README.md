# WhatsApp AI Assistant (Khumaira)

Ini adalah asisten WhatsApp cerdas yang ditenagai oleh Google Gemini API. Asisten ini, bernama Khumaira, dirancang untuk berinteraksi dengan pengguna melalui WhatsApp, menjawab pertanyaan, melakukan query ke database sekolah, dan menjalankan tugas-tugas otomatis lainnya.

---

### Prasyarat

Sebelum memulai, pastikan sistem Anda telah terinstal:

1.  **Python 3.8+**
2.  **Git Bash**: Sangat direkomendasikan untuk menggunakan [Git Bash](https://git-scm.com/downloads/) di Windows agar semua perintah di bawah ini berjalan seragam seperti di Linux atau macOS.

### Panduan Instalasi

Ikuti langkah-langkah ini untuk menyiapkan dan menjalankan aplikasi.

**1. Clone atau Unduh Proyek**

Jika proyek ini berada di repositori Git, clone repositori tersebut. Jika tidak, pastikan Anda berada di direktori utama proyek (`d:\Python\computeruse`).

```bash
# Contoh jika menggunakan git
git clone <url-repositori-anda>
cd computeruse
```

**2. Buat dan Aktifkan Virtual Environment**

Sangat penting untuk menggunakan virtual environment agar dependensi proyek tidak tercampur dengan instalasi Python global Anda. Buka Git Bash di direktori proyek dan jalankan:

```bash
# Buat virtual environment bernama 'venv'
python -m venv venv

# Aktifkan virtual environment
source venv/Scripts/activate
```

Setelah aktif, Anda akan melihat `(venv)` di awal baris perintah Anda.

**3. Install Dependensi**

Install semua pustaka Python yang dibutuhkan yang tercantum dalam `requirements.txt`.

```bash
pip install -r requirements.txt
```

### Konfigurasi

Aplikasi ini memerlukan kredensial dan kunci API untuk berfungsi. Anda harus menyediakannya melalui file `.env`.

1.  Buat file baru bernama `.env` di direktori utama proyek.
2.  Salin konten di bawah ini ke dalam file `.env` Anda dan isi nilainya sesuai dengan kredensial Anda.

```env
# Kredensial WhatsApp Business API
WHATSAPP_PHONE_NUMBER_ID=NOMOR_ID_TELEPON_WHATSAPP_ANDA
WHATSAPP_BEARER_TOKEN=TOKEN_BEARER_WHATSAPP_ANDA
WHATSAPP_VERIFY_TOKEN=TOKEN_VERIFIKASI_WEBHOOK_ANDA

# Kunci API Google
GOOGLE_API_KEY=KUNCI_API_GEMINI_ANDA
GOOGLE_MODEL=model-gemini-yang-digunakan (misal: gemini-1.5-flash)

# Kredensial Database MySQL
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=password_database_anda
MYSQL_DATABASE=nama_database_anda
```

### Menjalankan Aplikasi

1.  Pastikan virtual environment Anda sudah aktif (`(venv)` terlihat di terminal).
2.  Jalankan skrip utama `wa.py`.

    ```bash
    python wa.py
    ```

3.  Jika berhasil, Anda akan melihat pesan di terminal yang menandakan server telah berjalan.

    ```
    INFO:root:Server started, listening on http://localhost:8123
    ```

4.  Aplikasi sekarang siap menerima permintaan webhook dari WhatsApp di alamat `http://localhost:8123/whatsapp/webhook`. Anda perlu menggunakan layanan seperti `ngrok` untuk mengekspos alamat lokal ini ke internet dan mengaturnya di dasbor Meta for Developers Anda.
