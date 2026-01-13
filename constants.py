# constants.py
# This file contains constants used across the application.

# constants.py
CHUNK_SIZE = 4096
IP = "127.0.0.1"
PORT = 9921

# מגבלות חיבורים חדשות
MAX_TOTAL_CONNECTIONS = 15
MAX_CONNECTIONS_PER_IP = 3

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "davids74",
    "database": "mysql"
}