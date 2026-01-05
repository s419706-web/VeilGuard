import threading
import time
import random
import os
import shutil
from cyber_client import Client  

file_lock = threading.Lock()

def setup_files_if_missing():
    if not os.path.exists("test_creds"):
        os.makedirs("test_creds")
        for i in range(1, 11):
            with open(f"test_creds/creds_{i}.txt", "w") as f:
                f.write(f"user_{i}\npass_{i}")

def run_single_automated_client(thread_id):
    setup_files_if_missing()
    
    try:
        # בחירת זהות וסנכרון קבצים
        with file_lock:
            random_idx = random.randint(1, 10)
            source = f"test_creds/creds_{random_idx}.txt"
            shutil.copy(source, "creds.txt")
            time.sleep(0.1) 

        # יצירת אובייקט הלקוח
        c = Client()

        # --- נטרול ממשק גרפי (התיקון לשגיאת ה-NoneType) ---
        # אנחנו מחליפים את הפונקציות של ה-UI בפונקציות ריקות שלא עושות כלום
        c.ui_set_status = lambda msg: print(f"[Thread {thread_id}] Status: {msg}")
        c.ui_show_preview = lambda img, is_processed: None
        c.ui_enable_controls = lambda enable: None
        c.ui_root = "Headless" # מסמנים שזה לא באמת אובייקט TK אבל הוא לא None
        # --------------------------------------------------

        c.connect_to_server()
        
        if c.client_socket:
            print(f"[Thread {thread_id}] Logging in and performing Face Blur...")
            c.send_credentials()
            c.receive_menu()
            
            # הרצת הפעולה (זה ישלח "1" לשרת ויקבל תמונות)
            c.ui_do_face()
            
            time.sleep(1) 
            c.ui_do_logout()
            print(f"[Thread {thread_id}] Finished Successfully.")
            
    except Exception as e:
        print(f"[Thread {thread_id}] Error: {e}")

def load_test_main():
    threads = []
    print("--- Starting 20 Clients Load Test (Headless) ---")
    
    for i in range(20):
        t = threading.Thread(target=run_single_automated_client, args=(i,))
        threads.append(t)
        t.start()
        time.sleep(0.2) 

    for t in threads:
        t.join()
    print("--- Load Test Finished Successfully ---")

if __name__ == "__main__":
    load_test_main()