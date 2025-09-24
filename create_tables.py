from db_manager import DatabaseManager

def create_all_tables(db_manager: DatabaseManager):
    """
    Create all necessary tables (clients, media_types, decrypted_media).
    """

    # clients table
    db_manager.create_table(
        "clients",
        "("
        " client_id VARCHAR(255) PRIMARY KEY,"
        " client_ip VARCHAR(255),"
        " client_port INT,"
        " last_seen DATETIME,"
        " ddos_status BOOLEAN,"
        " total_sent_media INT,"
        " password_hash VARCHAR(255)"
        ")"
    )

    # media_types table (dictionary of IDs)
    db_manager.create_table(
        "media_types",
        "("
        " id INT PRIMARY KEY,"
        " name VARCHAR(64) NOT NULL,"
        " is_original BOOLEAN NOT NULL"
        ")"
    )

    # decrypted_media table (original + processed images per client)
    db_manager.create_table(
        "decrypted_media",
        "("
        " id INT AUTO_INCREMENT PRIMARY KEY,"
        " user_id VARCHAR(255) NOT NULL,"
        " media_type_id INT NOT NULL,"
        " path_to_decrypted_media TEXT NOT NULL,"
        " created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        " INDEX idx_user_id (user_id),"
        " INDEX idx_media_type (media_type_id)"
        ")"
    )

def populate_media_types(db_manager: DatabaseManager):
    """
    Populate the media_types dictionary so IDs are human-readable in GUI.
    """
    rows = db_manager.get_all_rows("media_types")
    if rows:
        return

    data = [
        (1,   "Face blur (processed)",          False),
        (2,   "Background blur (processed)",    False),
        (3,   "User-selected blur (processed)", False),
        (101, "Face blur (original)",           True),
        (102, "Background blur (original)",     True),
        (103, "User-selected blur (original)",  True),
    ]
    for row in data:
        db_manager.insert_row(
            "media_types",
            "(id, name, is_original)",
            "(%s, %s, %s)",
            row
        )
