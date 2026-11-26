"""
Finds your Telegram chat ID.
1. Put your bot token in config.py
2. Send any message (e.g. "hi") to your bot in Telegram
3. Run:  python get_chat_id.py
"""
import requests

import config as C

r = requests.get(f"https://api.telegram.org/bot{C.TELEGRAM_TOKEN}/getUpdates", timeout=10).json()
if not r.get("ok"):
    print("Error - check the token in config.py:", r)
elif not r["result"]:
    print("No messages found. Send a message to your bot in Telegram first, then run this again.")
else:
    seen = set()
    for u in r["result"]:
        chat = (u.get("message") or u.get("channel_post") or {}).get("chat")
        if chat and chat["id"] not in seen:
            seen.add(chat["id"])
            print(f"Chat ID: {chat['id']}   ({chat.get('first_name') or chat.get('title')})")
    print("\nCopy the number into TELEGRAM_CHAT_ID in config.py")
