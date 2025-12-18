# Python 3.11 asosida image
FROM python:3.11-slim

# Ishchi katalog
WORKDIR /app

# Dependencies copy va install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bot kodi
COPY . .

# Telegram API tokenini environment variable orqali uzatish
ENV BOT_TOKEN=8291345152:AAEeOP-2U9AfYvwCFnxrwDoFg7sjyWGwqGk
ENV API_ID=32460736
ENV API_HASH=285e2a8556652e6f4ffdb83658081031

# Botni ishga tushirish
CMD ["python", "bott.py"]
