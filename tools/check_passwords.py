from argon2 import PasswordHasher
import sqlite3

ph = PasswordHasher()
conn = sqlite3.connect('data/apply_submit.db')
c = conn.cursor()

# Test testuser
c.execute("SELECT username, password_hash FROM users WHERE username='testuser'")
row = c.fetchone()
if row:
    print(f"Testing testuser...")
    for pwd in ['s3cretPass1', 'testuser', 'password', 'admin', 'Mubashir']:
        try:
            ph.verify(row[1], pwd)
            print(f"  Password is: {pwd}")
            break
        except:
            pass
    else:
        print("  Password not found in common guesses")

# Test Mubashir
c.execute("SELECT username, password_hash FROM users WHERE username='Mubashir'")
row = c.fetchone()
if row:
    print(f"Testing Mubashir...")
    for pwd in ['s3cretPass1', 'Mubashir', 'mubashir', 'password', 'admin']:
        try:
            ph.verify(row[1], pwd)
            print(f"  Password is: {pwd}")
            break
        except:
            pass
    else:
        print("  Password not found in common guesses")