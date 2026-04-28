import threading
import time
import os
import random
from cyber_client import Client

TOTAL_CLIENTS = 20 

def create_mock_creds():
    if not os.path.exists("test_creds"): os.makedirs("test_creds")
    
    # 6 הצלחות (וודא שהם רשומים ב-DB או שהרצת אותם פעם אחת כ-signup)
    for i in range(1, 7):
        with open(f"test_creds/success_{i}.txt", "w") as f:
            f.write(f"user{i}\npass{i}")
            
    # 2 כשלונות (סיסמה לא נכונה)
    for i in range(1, 3):
        with open(f"test_creds/fail_{i}.txt", "w") as f:
            f.write(f"user{i}\nWRONG_PASS")
            
    # 2 הרשמות חדשות (שמות משתמש רנדומליים כדי שלא יהיה קיים)
    for i in range(1, 3):
        rand_id = random.randint(1000, 9999)
        with open(f"test_creds/signup_{i}.txt", "w") as f:
            f.write(f"newuser_{rand_id}\nnewpass123")

def run_single_client(client_id, cred_file):
    client = Client()
    client.connect_to_server()
    if not client.client_socket: return

    success = client.send_credentials(None, auto_file=cred_file)
    
    if success:
        print(f"[Thread {client_id}] SUCCESS! Holding connection to trigger DDoS...")
        # השורה הכי חשובה: נשארים מחוברים 15 שניות בלי לעשות כלום
        # זה יגרום ל-active_connections בשרת לגדול
        time.sleep(15) 
        try:
            client.client_socket.close()
        except: pass
    else:
        print(f"[Thread {client_id}] FAILED/REJECTED")
    
    client.client_socket.close()

if __name__ == "__main__":
    TOTAL_CLIENTS = 20 # עכשיו זה באמת יריץ 20
    create_mock_creds()
    
    files = ([f"test_creds/success_{i}.txt" for i in range(1, 7)] + 
             [f"test_creds/fail_{i}.txt" for i in range(1, 3)] + 
             [f"test_creds/signup_{i}.txt" for i in range(1, 3)])
    
    threads = []
    print(f"--- Launching {TOTAL_CLIENTS} clients ---")
    for i in range(TOTAL_CLIENTS):
        # שימוש ב-Modulo כדי למחזר קבצים אם NUM_THREADS > כמות הקבצים
        target_file = files[i % len(files)]
        
        t = threading.Thread(target=run_single_client, args=(i, target_file))
        threads.append(t)
        t.start()
        # חשוב: השהייה קצרה מאוד כדי שהשרת יספיק לרשום את כולם ב-active_connections
        time.sleep(0.05) 

    for t in threads: t.join()
    print("--- Stress Test Finished ---")