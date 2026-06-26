import mysql.connector
import json
import sys

def main():
    print("=== UTCL Bus System Audit and Integrity Check ===")
    
    # Load configuration
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
        print(f"Using environment database configuration. Host: {cfg.get('host')}, Database: {cfg.get('database')}")
    else:
        try:
            cfg = json.load(open('db_config.json'))
            cfg['use_pure'] = True
            print(f"Loaded database configuration. Host: {cfg.get('host')}, Database: {cfg.get('database')}")
        except Exception as e:
            print(f"Error loading db_config.json: {e}")
            sys.exit(1)
        
    # Connect to database
    try:
        conn = mysql.connector.connect(**cfg)
        cursor = conn.cursor(dictionary=True)
        print("Connected to MySQL database successfully.")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)
        
    errors_found = 0
    warnings_found = 0
    
    # 1. Verify all tables exist
    expected_tables = [
        'users', 'bookings', 'tickets', 'shifts', 'buses', 
        'driver_shifts', 'maintenance', 'tracking', 'notifications', 'payroll_periods',
        'cancelled_shifts'
    ]
    cursor.execute("SHOW TABLES")
    existing_tables = [list(r.values())[0] for r in cursor.fetchall()]
    
    print("\n[1] Checking Tables:")
    for t in expected_tables:
        if t in existing_tables:
            print(f"  - Table '{t}': EXISTS")
        else:
            print(f"  - Table '{t}': MISSING")
            errors_found += 1
            
    # 2. Check User Roles and Plant counts
    print("\n[2] Checking Users:")
    cursor.execute("SELECT role, COUNT(*) as count FROM users GROUP BY role")
    role_counts = cursor.fetchall()
    for r in role_counts:
        print(f"  - Role '{r['role']}': {r['count']} users")
        
    cursor.execute("SELECT plant, COUNT(*) as count FROM users GROUP BY plant")
    plant_counts = cursor.fetchall()
    for p in plant_counts:
        print(f"  - Plant '{p['plant']}': {p['count']} users")
        
    # Check for empty passwords or invalid passwords
    cursor.execute("SELECT id, name, psNumber, role FROM users WHERE password IS NULL OR password = ''")
    stale_users = cursor.fetchall()
    if stale_users:
        print(f"  - WARNING: Found {len(stale_users)} users with empty passwords:")
        for u in stale_users:
            print(f"    * ID: {u['id']}, Name: {u['name']}, PS: {u['psNumber']}, Role: {u['role']}")
        warnings_found += len(stale_users)
    else:
        print("  - Passwords: OK (No empty passwords)")
        
    # 3. Check for Duplicate active bookings (same shift, date, seat, not cancelled)
    print("\n[3] Checking for Double-Booked Seats (Duplicate active bookings for same seat/shift/date):")
    cursor.execute("""
        SELECT shiftId, travelDate, seatNumber, COUNT(*) as booking_count, GROUP_CONCAT(id) as booking_ids
        FROM bookings
        WHERE status != 'CANCELLED'
        GROUP BY shiftId, travelDate, seatNumber
        HAVING booking_count > 1
    """)
    double_bookings = cursor.fetchall()
    if double_bookings:
        print(f"  - ERROR: Found {len(double_bookings)} double-booked seats:")
        for db in double_bookings:
            print(f"    * Shift: {db['shiftId']}, Date: {db['travelDate']}, Seat: {db['seatNumber']}, Bookings: {db['booking_ids']}")
        errors_found += len(double_bookings)
    else:
        print("  - Double-bookings: OK (None found)")
        
    # 4. Check for Orphaned Bookings (points to non-existent user or shift)
    print("\n[4] Checking for Orphaned Bookings:")
    cursor.execute("""
        SELECT b.id, b.psNumber, b.employeeName 
        FROM bookings b
        LEFT JOIN users u ON b.psNumber = u.psNumber
        WHERE u.id IS NULL AND b.psNumber != 'PHANTOM'
    """)
    orphaned_users = cursor.fetchall()
    if orphaned_users:
        print(f"  - WARNING: Found {len(orphaned_users)} bookings referencing missing PS Numbers:")
        for ou in orphaned_users[:10]:
            print(f"    * Booking ID: {ou['id']}, Missing PS Number: {ou['psNumber']}, Name: {ou['employeeName']}")
        if len(orphaned_users) > 10:
            print(f"    * ... and {len(orphaned_users) - 10} more")
        warnings_found += len(orphaned_users)
    else:
        print("  - Booking PS Numbers: OK")
        
    cursor.execute("""
        SELECT b.id, b.shiftId, b.travelDate 
        FROM bookings b
        LEFT JOIN shifts s ON b.shiftId = s.id
        WHERE s.id IS NULL
    """)
    orphaned_shifts = cursor.fetchall()
    if orphaned_shifts:
        print(f"  - WARNING: Found {len(orphaned_shifts)} bookings referencing missing Shifts:")
        for os in orphaned_shifts[:10]:
            print(f"    * Booking ID: {os['id']}, Missing Shift ID: {os['shiftId']}")
        if len(orphaned_shifts) > 10:
            print(f"    * ... and {len(orphaned_shifts) - 10} more")
        warnings_found += len(orphaned_shifts)
    else:
        print("  - Booking Shift IDs: OK")
        
    # 5. Check for Orphaned Tickets (tickets with no booking or pointing to missing booking)
    print("\n[5] Checking for Orphaned Tickets:")
    cursor.execute("""
        SELECT t.id, t.bookingId, t.ticketNumber, t.employeeName
        FROM tickets t
        LEFT JOIN bookings b ON t.bookingId = b.id
        WHERE b.id IS NULL
    """)
    orphaned_tickets = cursor.fetchall()
    if orphaned_tickets:
        print(f"  - ERROR: Found {len(orphaned_tickets)} tickets referencing non-existent bookings:")
        for ot in orphaned_tickets[:10]:
            print(f"    * Ticket ID: {ot['id']}, Ticket No: {ot['ticketNumber']}, Booking ID: {ot['bookingId']}, Name: {ot['employeeName']}")
        if len(orphaned_tickets) > 10:
            print(f"    * ... and {len(orphaned_tickets) - 10} more")
        errors_found += len(orphaned_tickets)
    else:
        print("  - Ticket references: OK")

    # 6. Check for Phantom ws_ bookings
    print("\n[6] Checking for Phantom (ws_) bookings:")
    cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE id LIKE 'ws_%'")
    phantom_count = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE psNumber = 'PHANTOM'")
    phantom_ps_count = cursor.fetchone()['count']
    print(f"  - 'ws_' prefix bookings: {phantom_count}")
    print(f"  - 'PHANTOM' psNumber bookings: {phantom_ps_count}")
    if phantom_count > 0:
        print("  - NOTE: Phantom bookings with 'ws_' prefix exist. If they have active tickets, they might show up.")
        
    # 7. Check Driver Shift assignments
    print("\n[7] Checking Driver Shifts and Attendance:")
    cursor.execute("""
        SELECT ds.id, ds.driverId, ds.shiftId, ds.date 
        FROM driver_shifts ds
        LEFT JOIN users u ON ds.driverId = u.id AND u.role = 'DRIVER'
        WHERE u.id IS NULL
    """)
    invalid_drivers = cursor.fetchall()
    if invalid_drivers:
        print(f"  - WARNING: Found {len(invalid_drivers)} driver shift entries referencing invalid or non-existent drivers:")
        for idr in invalid_drivers[:10]:
            print(f"    * ID: {idr['id']}, Driver ID: {idr['driverId']}, Shift ID: {idr['shiftId']}, Date: {idr['date']}")
        warnings_found += len(invalid_drivers)
    else:
        print("  - Driver shift assignments: OK")
        
    # Close connection
    conn.close()
    
    print("\n=== Audit Summary ===")
    print(f"Errors found  : {errors_found}")
    print(f"Warnings found: {warnings_found}")
    if errors_found == 0:
        print("The database integrity is healthy!")
    else:
        print("WARNING: Integrity issues detected in the database. Please investigate.")

if __name__ == '__main__':
    main()
