from db_manager import DatabaseManager

# Initialize the manager
db = DatabaseManager("localhost", "root", "davids74", "veilguard_db")

print("Resetting database tables...")

# Use the manager's built-in execute method 
# (assuming your DatabaseManager has a method that executes SQL)
# If it doesn't, this will likely work if you check the file 
# or use this common pattern:
try:
    # We bypass the specific table name and run raw SQL if your manager supports it
    # or just create a quick raw connection
    import mysql.connector
    conn = mysql.connector.connect(host="localhost", user="root", password="davids74", database="veilguard_db")
    cursor = conn.cursor()
    
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    cursor.execute("DROP TABLE IF EXISTS decrypted_media")
    cursor.execute("DROP TABLE IF EXISTS clients")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()
    
    print("Database reset successfully!")
    cursor.close()
    conn.close()
except Exception as e:
    print(f"Error: {e}")