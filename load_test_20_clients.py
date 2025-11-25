import threading
import socket
import time
import random

from constants import IP, PORT
from encrypt import Encryption

# -----------------------------
# שלב 1: הגדרת משתמשים לבדיקה
# -----------------------------

# סיסמה "נכונה" שנשתמש בה לכל המשתמשים הטובים
CORRECT_PASSWORD = "1234"
WRONG_PASSWORD = "wrongpass"

# נגדיר 7 משתמשים "קיימים" שנרצה שיהיו במערכת
EXISTING_USERS = [f"load_user_{i}" for i in range(7)]

# -----------------------------
# פונקציית עזר: התחברות חד-פעמית כדי ליצור משתמש חדש (אם לא קיים)
# השרת שלך: אם user לא קיים -> יוצר רשומה ב-clients
# -----------------------------
def register_user_once(username: str, password: str):
    try:
        s = socket.socket()
        s.connect((IP, PORT))
        enc = Encryption()

        # שליחת credentials
        enc.send_encrypted_message(s, username)
        enc.send_encrypted_message(s, password)

        resp = enc.receive_encrypted_message(s)
        print(f"[REGISTER] {username}: {resp}")

        # אם ההתחברות הצליחה או יצרה משתמש חדש - נסגור יפה
        # השרת שלך אחרי login שולח תפריט, נקרא אותו ואז נשלח Logout
        menu = enc.receive_encrypted_message(s)
        # שולחים 4 = Logout
        enc.send_encrypted_message(s, "4")
        goodbye = enc.receive_encrypted_message(s)
        print(f"[REGISTER] {username}: logout -> {goodbye}")

    except Exception as e:
        print(f"[REGISTER] Error for {username}: {e}")
    finally:
        try:
            s.close()
        except Exception:
            pass


# -----------------------------
# שלב 2: הכנת משתמשים קיימים
# -----------------------------
def prepare_existing_users():
    print("=== Preparing existing users in DB ===")
    for u in EXISTING_USERS:
        register_user_once(u, CORRECT_PASSWORD)
    print("=== Done preparing existing users ===\n")


# -----------------------------
# פונקציית חוט (thread) לקוח
# scenario_type:
#   "existing_ok"  -> משתמש קיים, סיסמה נכונה
#   "new_ok"       -> משתמש חדש, סיסמה נכונה
#   "wrong_pwd"    -> משתמש קיים אבל סיסמה שגויה
# -----------------------------
def client_thread(idx: int, scenario_type: str):
    try:
        s = socket.socket()
        s.connect((IP, PORT))
        enc = Encryption()

        # בוחרים שם וסיסמה בהתאם לתסריט
        if scenario_type == "existing_ok":
            username = random.choice(EXISTING_USERS)
            password = CORRECT_PASSWORD

        elif scenario_type == "new_ok":
            # כל לקוח חדש יקבל שם ייחודי
            username = f"new_user_{idx}"
            password = CORRECT_PASSWORD

        elif scenario_type == "wrong_pwd":
            # נשתמש באחד המשתמשים הקיימים אבל נספק סיסמה לא נכונה
            username = random.choice(EXISTING_USERS)
            password = WRONG_PASSWORD

        else:
            print(f"[CLIENT {idx}] Unknown scenario type: {scenario_type}")
            s.close()
            return

        # שליחת credentials
        enc.send_encrypted_message(s, username)
        enc.send_encrypted_message(s, password)

        resp = enc.receive_encrypted_message(s)
        print(f"[CLIENT {idx}] login response: {resp}")

        # אם השרת החזיר "PASSWORD INCORRECT" -> מסיימים
        if "PASSWORD INCORRECT" in resp:
            print(f"[CLIENT {idx}] Expected failure (wrong password) - closing.")
            s.close()
            return

        # אם הגענו לכאן - ההתחברות הצליחה
        # השרת שלך שולח עכשיו menu, נקרא אותו:
        menu = enc.receive_encrypted_message(s)
        print(f"[CLIENT {idx}] got menu:\n{menu}")

        # לצורך הבדיקה נשלח אופציה 4 = Logout
        enc.send_encrypted_message(s, "4")
        goodbye = enc.receive_encrypted_message(s)
        print(f"[CLIENT {idx}] logout response: {goodbye}")

    except Exception as e:
        print(f"[CLIENT {idx}] Error: {e}")
    finally:
        try:
            s.close()
        except Exception:
            pass


# -----------------------------
# שלב 3: בניית תרחיש של 20 לקוחות
# בכל 10:
#   7 existing_ok
#   2 new_ok
#   1 wrong_pwd
# -----------------------------
def build_20_clients_scenarios():
    scenarios_for_10 = (
        ["existing_ok"] * 7 +
        ["new_ok"] * 2 +
        ["wrong_pwd"] * 1
    )
    # ל-20 לקוחות -> פעמיים אותו דפוס
    scenarios_20 = scenarios_for_10 * 2
    return scenarios_20


def main():
    # לפני הכל: להכין את המשתמשים הקיימים ב-DB
    prepare_existing_users()

    scenarios = build_20_clients_scenarios()
    threads = []

    print("=== Starting 20 parallel clients ===")

    for i, scenario_type in enumerate(scenarios):
        t = threading.Thread(target=client_thread, args=(i, scenario_type))
        t.start()
        threads.append(t)

    # נחכה שכל ה-threads יסתיימו
    for t in threads:
        t.join()

    print("=== All clients finished ===")


if __name__ == "__main__":
    main()
