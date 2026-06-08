import sqlite3

conn = sqlite3.connect("db/justo_pricing.db")
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("SQLite tables:")
for r in cur.fetchall():
    print(r[0])
conn.close()

