import os
import sqlite3

def run_migration(db_path, migration_path):
    print(f"Applying migration {migration_path} to database {db_path}...")
    if not os.path.exists(migration_path):
        print(f"Error: Migration file not found: {migration_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        with open(migration_path, "r", encoding="utf-8") as f:
            sql = f.read()
        conn.executescript(sql)
        conn.commit()
        conn.close()
        print("Success!")
        return True
    except Exception as e:
        print(f"Error running migration: {e}")
        return False

def main():
    # Paths
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    local_ref_db = os.path.join(base_dir, "local_data", "justo_pricing_local_reference.db")
    dev_db = os.path.join(base_dir, "db", "justo_pricing.db")
    
    schema_v1 = os.path.join(base_dir, "database", "migrations", "001_local_sqlite_schema.sql")
    schema_v2 = os.path.join(base_dir, "database", "migrations", "002_justo_new_tables_sqlite.sql")
    
    # 1. Apply schema to local reference database if it exists
    if os.path.exists(local_ref_db):
        run_migration(local_ref_db, schema_v2)
    else:
        print(f"Reference database not found at {local_ref_db}, skipping.")
        
    # 2. Initialize and apply schemas to development database
    os.makedirs(os.path.dirname(dev_db), exist_ok=True)
    
    # If dev_db is brand new, apply schema_v1 first
    is_new = not os.path.exists(dev_db)
    if is_new:
        print("Creating new development database...")
        run_migration(dev_db, schema_v1)
        
    run_migration(dev_db, schema_v2)
    
    print("\nInitialization finished!")

if __name__ == "__main__":
    main()
