import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8647438259:AAEuCvrwGaThywz8TMP9UdUyiWcsJk96L9g")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1057725634"))

# Настройки Platega API
PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID", "ID_МАГАЗИНА")
PLATEGA_SECRET_KEY = os.getenv("PLATEGA_SECRET_KEY", "СЕКРЕТНЫЙ_КЛЮЧ")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://your-domain.com")  # Твой домен / ngrok
WEBHOOK_PORT = int(os.getenv("PORT", 8080))