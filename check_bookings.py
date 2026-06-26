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

cur.execute("SELECT id, psNumber, employeeName, seatNumber, boardingStopIndex, dropStopIndex, fareAmount, travelDate, shiftId, status FROM bookings WHERE travelDate = '2026-06-22' ORDER BY id")
rows = cur.fetchall()
print(f"\nToday's bookings ({len(rows)} total):")
for r in rows:
    print(r)

cur.execute("SELECT id, bookingId, ticketNumber, employeeName, seatNumber, boardingStop, dropStop, travelDate FROM tickets WHERE travelDate = '2026-06-22' ORDER BY id")
trows = cur.fetchall()
print(f"\nToday's tickets ({len(trows)} total):")
for r in trows:
    print(r)

conn.close()
