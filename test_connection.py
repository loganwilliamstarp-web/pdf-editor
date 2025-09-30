import psycopg2
import os

def test_connection():
    try:
        conn = psycopg2.connect(
            host="db.lpvzcfvcfckgdeuhzhrj.supabase.co",
            port="5432",
            database="postgres",
            user="postgres",
            password="DJyX-3pAu6+85+6",
            sslmode="require"
        )
        
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"Connection successful! PostgreSQL version: {version[0]}")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Connection failed: {e}")
        return False

if __name__ == "__main__":
    test_connection()
