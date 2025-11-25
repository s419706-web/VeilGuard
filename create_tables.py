from db_manager import DatabaseManager

def create_all_tables(db_manager: DatabaseManager):
    """
    Create all necessary tables (clients, media_types, decrypted_media).
    Fully aligned with the final SQL schema for VeilGuard.
    """

    # ============================
    # clients table
    # ============================
    db_manager.create_table(
        "clients",
        "("
        " client_id VARCHAR(255) NOT NULL PRIMARY KEY,"
        " client_ip VARCHAR(255) NOT NULL,"
        " client_port INT NOT NULL,"
        " last_seen DATETIME NOT NULL,"
        " ddos_status TINYINT(1) NOT NULL DEFAULT 0,"
        " total_sent_media INT NOT NULL DEFAULT 0,"
        " password_hash VARCHAR(255) NOT NULL"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"
    )

    # ============================
    # media_types table
    # ============================
    db_manager.create_table(
        "media_types",
        "("
        " id INT NOT NULL PRIMARY KEY,"
        " name VARCHAR(64) NOT NULL,"
        " is_original TINYINT(1) NOT NULL"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"
    )

    # ============================
    # decrypted_media table
    # ============================
    db_manager.create_table(
        "decrypted_media",
        "("
        " id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,"
        " user_id VARCHAR(255) NOT NULL,"
        " media_type_id INT NOT NULL,"
        " path_to_decrypted_media TEXT NOT NULL,"
        " created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"

        " INDEX idx_user_id (user_id),"
        " INDEX idx_media_type (media_type_id),"

        " CONSTRAINT fk_decrypted_media_user FOREIGN KEY (user_id)"
        "     REFERENCES clients(client_id)"
        "     ON DELETE CASCADE ON UPDATE CASCADE,"

        " CONSTRAINT fk_decrypted_media_type FOREIGN KEY (media_type_id)"
        "     REFERENCES media_types(id)"
        "     ON DELETE RESTRICT ON UPDATE CASCADE"

        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"
    )


def populate_media_types(db_manager: DatabaseManager):
    """
    Populate the media_types dictionary so IDs are human-readable in GUI.
    Only inserts if table is empty.
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
