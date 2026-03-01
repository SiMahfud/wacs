import os
from dotenv import load_dotenv

load_dotenv()

# WhatsApp API Credentials
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_BEARER_TOKEN = os.getenv("WHATSAPP_BEARER_TOKEN")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v22.0")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

# Google API Credentials
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL")

# System Prompt
SYSTEM_PROMPT = """
    Kamu asisten whatsapp sman 1 campurdarat bernama Khumaira yang cerdas, lucu, sopan dan ramah. Bisa bicara bahasa apapun. 
    gunakan tool db_gukar_tool, atau db_siswa_tool untuk mencari data guru, karyawan, atau siswa. gunakan db_update_tool atau db_insert_tool untuk mengubah atau menambah data guru, karyawan, atau siswa.
    jawab pertanyaan user dengan pengetahuanmu meskipun pertanyaannya tidak ada hubungannya dengan sekolah.
    Jika user mengirim foto ijazah, langsung perbarui data nomor ijazah, tahun lulus dan sekolah asal siswa di database sesuai foto tersebut menggunakan tool yang disediakan. Jika foto lainnya, deskripsikan atau sesua permintaan user saja.
    jika mencari data siswa berdasarkan nisn tidak ada, coba cari berdasarkan nama depan, tengah, atau belakang nya.
    berikan output dengan format yang didukung whatsapp. tebal - diapit tanda satu *, dan sebagainya.
"""

# MySQL Credentials
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

# Admin Dashboard Auth
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SESSION_SECRET = os.getenv("SESSION_SECRET", "default_secret_change_me")

# Rate Limiting
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "20"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

# Constants
WHATSAPP_API_URL = "https://graph.facebook.com"

def get_whatsapp_config():
    """Returns only the WhatsApp-related config needed for API calls."""
    return {
        "WHATSAPP_BEARER_TOKEN": WHATSAPP_BEARER_TOKEN,
        "WHATSAPP_API_URL": WHATSAPP_API_URL,
        "WHATSAPP_API_VERSION": WHATSAPP_API_VERSION,
        "WHATSAPP_PHONE_NUMBER_ID": WHATSAPP_PHONE_NUMBER_ID,
    }
