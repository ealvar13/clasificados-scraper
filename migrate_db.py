#!/usr/bin/env python3
"""
Database migration script to add missing columns to existing database.
Run this once to update your existing database schema.
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.environ.get("DB_URL", "sqlite:///mavericks.db")

def migrate_database():
    engine = create_engine(DB_URL)
    
    with engine.connect() as conn:
        # Check if still_available column exists
        try:
            conn.execute(text("SELECT still_available FROM cars LIMIT 1"))
            print("✅ 'still_available' column already exists")
        except Exception:
            print("Adding 'still_available' column...")
            conn.execute(text("ALTER TABLE cars ADD COLUMN still_available BOOLEAN DEFAULT 1"))
            conn.commit()
            print("✅ Added 'still_available' column")
            
            # Set all existing records to available (True)
            result = conn.execute(text("UPDATE cars SET still_available = 1 WHERE still_available IS NULL"))
            conn.commit()
            print(f"✅ Set {result.rowcount} existing records to still_available = True")
        
        # Check if manual_price column exists
        try:
            conn.execute(text("SELECT manual_price FROM cars LIMIT 1"))
            print("✅ 'manual_price' column already exists")
        except Exception:
            print("Adding 'manual_price' column...")
            conn.execute(text("ALTER TABLE cars ADD COLUMN manual_price BOOLEAN DEFAULT 0"))
            conn.commit()
            print("✅ Added 'manual_price' column")
        
        # Check if year column exists
        try:
            conn.execute(text("SELECT year FROM cars LIMIT 1"))
            print("✅ 'year' column already exists")
        except Exception:
            print("Adding 'year' column...")
            conn.execute(text("ALTER TABLE cars ADD COLUMN year TEXT DEFAULT 'Unknown'"))
            conn.commit()
            print("✅ Added 'year' column")
        
        # Update existing records with extracted years if needed
        print("Updating existing records with year information...")
        result = conn.execute(text("""
            UPDATE cars 
            SET year = CASE 
                WHEN listing LIKE '%2019%' THEN '2019'
                WHEN listing LIKE '%2020%' THEN '2020'
                WHEN listing LIKE '%2021%' THEN '2021'
                WHEN listing LIKE '%2022%' THEN '2022'
                WHEN listing LIKE '%2023%' THEN '2023'
                WHEN listing LIKE '%2024%' THEN '2024'
                WHEN listing LIKE '%2025%' THEN '2025'
                ELSE 'Unknown'
            END
            WHERE year IS NULL OR year = 'Unknown'
        """))
        conn.commit()
        print(f"✅ Updated {result.rowcount} records with year information")

if __name__ == "__main__":
    print("🔄 Starting database migration...")
    migrate_database()
    print("🎉 Database migration completed!")
