import requests

# Ganti dengan token & chat_id kamu
BOT_TOKEN = "8309387013:"
CHAT_ID = ""

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(url, data=payload, timeout=10)
        print("Response status:", r.status_code)
        print("Response body:", r.text)
        return r.json()
    except Exception as e:
        print("Error kirim:", e)
        return None

if __name__ == "__main__":
    result = send_message("🚀 Hello World! Bot kamu sudah jalan.")
    print("Result:", result)
