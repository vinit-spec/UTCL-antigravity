import mysql.connector
import json
import os

if "MYSQLHOST" in os.environ:
    cfg = {
        "host": os.environ.get("MYSQLHOST"),
        "port": int(os.environ.get("MYSQLPORT", 3306)),
        "user": os.environ.get("MYSQLUSER"),
        "password": os.environ.get("MYSQLPASSWORD"),
        "database": os.environ.get("MYSQLDATABASE", "utcl_bus_db"),
        "use_pure": True
    }
else:
    cfg = json.load(open('db_config.json'))
    cfg['use_pure'] = True

conn = mysql.connector.connect(**cfg)
cur = conn.cursor(dictionary=True)

# Find and delete ws_ phantom bookings
cur.execute("SELECT id, psNumber, employeeName, seatNumber, travelDate FROM bookings WHERE id LIKE 'ws_%'")
phantoms = cur.fetchall()
print(f"Found {len(phantoms)} phantom ws_ bookings:")
for p in phantoms:
    print(p)

if phantoms:
    cur.execute("DELETE FROM bookings WHERE id LIKE 'ws_%'")
    print(f"\nDeleted {cur.rowcount} phantom bookings.")
    conn.commit()
else:
    print("No phantom bookings to delete.")

conn.close()
print("Done.")
