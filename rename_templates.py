#!/usr/bin/env python3
"""
Script to rename ACORD templates with proper descriptive names
"""

import psycopg2
from psycopg2.extras import RealDictCursor

# Database credentials
DB_HOST = "cee3ebbhveeoab.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com"
DB_DATABASE = "da08fj903lnieb"
DB_USER = "ud42f690nq7vcd"
DB_PORT = "5432"
DB_PASSWORD = "pd700ef90b356bf40cd4d8a555b7976ca7cef9f67c0176e82a6659199bb174ff2"

# Template rename mappings
TEMPLATE_RENAMES = {
    "acord130": "ACORD 130 - Evidence of Commercial Property Insurance",
    "acord140": "ACORD 140 - Evidence of Commercial Property Insurance (Broad Form)",
    "acord30": "ACORD 30 - Evidence of Property Insurance",
    "acord35": "ACORD 35 - Evidence of Commercial Property Insurance",
    "acord36": "ACORD 36 - Agent of Record Change",
    "acord37": "ACORD 37 - Statement of No Loss"
}

def rename_templates():
    """Rename templates in the database with proper descriptive names"""
    conn = None
    try:
        print("Connecting to Heroku PostgreSQL database...")
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_DATABASE,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            sslmode='require'
        )
        cur = conn.cursor()
        print("SUCCESS: Connected successfully!")
        print("==================================================")

        # Get current templates
        cur.execute("SELECT id, template_name FROM master_templates ORDER BY template_name")
        current_templates = cur.fetchall()
        
        print(f"Found {len(current_templates)} templates in database:")
        for template in current_templates:
            print(f"  - {template[1]} (ID: {template[0]})")
        
        print("\nRenaming templates...")
        
        renamed_count = 0
        for template_type, new_name in TEMPLATE_RENAMES.items():
            try:
                # Update template name based on template type
                cur.execute(
                    """
                    UPDATE master_templates
                    SET template_name = %s,
                        updated_at = NOW()
                    WHERE LOWER(template_type) = %s
                    """,
                    (new_name, template_type.lower())
                )
                
                if cur.rowcount > 0:
                    print(f"SUCCESS: Template type '{template_type}' renamed to '{new_name}'")
                    renamed_count += 1
                else:
                    print(f"WARNING: No template found for type: '{template_type}'")
                    
            except Exception as e:
                print(f"FAILED: Could not rename template type '{template_type}': {e}")
        
        # Commit changes
        conn.commit()
        
        print(f"\n==================================================")
        print(f"SUCCESS: Successfully renamed {renamed_count} templates!")
        
        # Show updated templates
        print("\nUpdated template list:")
        cur.execute("SELECT template_name FROM master_templates ORDER BY template_name")
        updated_templates = cur.fetchall()
        
        for i, template in enumerate(updated_templates, 1):
            print(f"  {i:2d}. {template[0]}")
            
    except Exception as e:
        print(f"ERROR: Error during template rename: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == '__main__':
    rename_templates()
    print("\nSUCCESS: Template renaming complete!")
    print("Visit your app: https://pdfeditorsalesforce-49dc376497fd.herokuapp.com/001000000000001")
