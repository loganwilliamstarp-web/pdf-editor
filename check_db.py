#!/usr/bin/env python3

import os
import psycopg2
import json

# Database connection
DATABASE_URL = os.environ.get("DATABASE_URL")

def check_database():
    """Check database connection and content"""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        return

    try:
        print("Connecting to database...")
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()

        # Check if tables exist
        print("\nChecking tables...")
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)

        tables = cur.fetchall()
        print(f"Found tables: {[table[0] for table in tables]}")

        # Check master_templates content
        if any(table[0] == 'master_templates' for table in tables):
            print("\nChecking master_templates table...")
            cur.execute('SELECT COUNT(*) FROM master_templates')
            count = cur.fetchone()[0]
            print(f"Number of templates: {count}")

            if count > 0:
                cur.execute('SELECT id, template_name, template_type FROM master_templates LIMIT 5')
                templates = cur.fetchall()
                print("Sample templates:")
                for template in templates:
                    print(f"  - {template[0]}: {template[1]} ({template[2]})")
            else:
                print("No templates found in database")

        # Check template_data content
        if any(table[0] == 'template_data' for table in tables):
            print("\nChecking template_data table...")
            cur.execute('SELECT COUNT(*) FROM template_data')
            count = cur.fetchone()[0]
            print(f"Number of template data records: {count}")

        conn.close()
        print("\nDatabase check completed")

    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    check_database()
