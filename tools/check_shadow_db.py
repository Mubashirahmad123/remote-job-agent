import sqlite3
conn = sqlite3.connect('data/matching_shadow.db')
c = conn.cursor()
c.execute('SELECT name FROM sqlite_master WHERE type="table"')
print(c.fetchall())
c.execute('SELECT * FROM run_status WHERE run_id LIKE "b84f9c%"')
print(c.fetchall())
c.execute('SELECT * FROM run_status ORDER BY run_id DESC LIMIT 20')
for r in c.fetchall():
    print(dict(r))