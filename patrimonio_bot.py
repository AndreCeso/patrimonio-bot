import os
import sys

print("=== TEST AVVIO BOT ===")
print(f"SUPABASE_URL presente: {bool(os.environ.get('SUPABASE_URL'))}")
print(f"SUPABASE_KEY presente: {bool(os.environ.get('SUPABASE_KEY'))}")
print(f"SUPABASE_USER_ID presente: {bool(os.environ.get('SUPABASE_USER_ID'))}")
print(f"TELEGRAM_TOKEN presente: {bool(os.environ.get('TELEGRAM_TOKEN'))}")
print(f"TELEGRAM_CHAT_ID presente: {bool(os.environ.get('TELEGRAM_CHAT_ID'))}")
print("=== FINE TEST ===")
sys.exit(0)
