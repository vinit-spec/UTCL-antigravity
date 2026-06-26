import mysql.connector
import json
import sys

def main():
    print("=== UTCL Database Cleanup Script ===")
    
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
        except Exception as e:
            print(f"Error loading db_config.json: {e}")
            sys.exit(1)
        
    # Connect to database
    try:
        conn = mysql.connector.connect(**cfg)
        cursor = conn.cursor(dictionary=True)
        print("Connected to MySQL database.")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    try:
        # Get list of valid user PS numbers and driver IDs
        cursor.execute("SELECT psNumber FROM users")
        valid_ps_numbers = {row['psNumber'].strip().upper() for row in cursor.fetchall() if row['psNumber']}
        
        cursor.execute("SELECT id FROM users WHERE role = 'DRIVER'")
        valid_driver_ids = {row['id'] for row in cursor.fetchall()}
        
        print(f"Valid PS Numbers in DB: {len(valid_ps_numbers)}")
        print(f"Valid Driver IDs in DB: {len(valid_driver_ids)}")
        
        # 1. Delete phantom ws_ bookings from bookings table
        cursor.execute("DELETE FROM bookings WHERE id LIKE 'ws_%' OR psNumber = 'PHANTOM'")
        phantom_bookings_deleted = cursor.rowcount
        print(f"1. Deleted {phantom_bookings_deleted} phantom bookings (ws_* or PHANTOM).")
        
        # 2. Delete bookings referencing missing users (deleted mock users)
        # Fetch current bookings
        cursor.execute("SELECT id, psNumber FROM bookings")
        all_bookings = cursor.fetchall()
        bookings_to_delete = []
        for b in all_bookings:
            ps = b['psNumber']
            if ps and ps.strip().upper() not in valid_ps_numbers:
                bookings_to_delete.append(b['id'])
                
        if bookings_to_delete:
            format_strings = ','.join(['%s'] * len(bookings_to_delete))
            cursor.execute(f"DELETE FROM bookings WHERE id IN ({format_strings})", tuple(bookings_to_delete))
            orphaned_bookings_deleted = cursor.rowcount
            print(f"2. Deleted {orphaned_bookings_deleted} orphaned bookings referencing deleted mock users.")
        else:
            print("2. No orphaned bookings found.")
            
        # 3. Delete tickets referencing missing bookings or users
        cursor.execute("SELECT id, bookingId, psNumber FROM tickets")
        all_tickets = cursor.fetchall()
        
        # Fetch active booking IDs
        cursor.execute("SELECT id FROM bookings")
        active_booking_ids = {row['id'] for row in cursor.fetchall()}
        
        tickets_to_delete = []
        for t in all_tickets:
            ps = t['psNumber']
            bid = t['bookingId']
            if (ps and ps.strip().upper() not in valid_ps_numbers) or (bid not in active_booking_ids):
                tickets_to_delete.append(t['id'])
                
        if tickets_to_delete:
            format_strings = ','.join(['%s'] * len(tickets_to_delete))
            cursor.execute(f"DELETE FROM tickets WHERE id IN ({format_strings})", tuple(tickets_to_delete))
            orphaned_tickets_deleted = cursor.rowcount
            print(f"3. Deleted {orphaned_tickets_deleted} orphaned/mock tickets.")
        else:
            print("3. No orphaned tickets found.")
            
        # 4. Delete driver shift entries referencing non-existent drivers
        cursor.execute("SELECT id, driverId FROM driver_shifts")
        all_driver_shifts = cursor.fetchall()
        ds_to_delete = []
        for ds in all_driver_shifts:
            d_id = ds['driverId']
            if d_id not in valid_driver_ids:
                ds_to_delete.append(ds['id'])
                
        if ds_to_delete:
            format_strings = ','.join(['%s'] * len(ds_to_delete))
            cursor.execute(f"DELETE FROM driver_shifts WHERE id IN ({format_strings})", tuple(ds_to_delete))
            invalid_driver_shifts_deleted = cursor.rowcount
            print(f"4. Deleted {invalid_driver_shifts_deleted} stale driver shift assignments.")
        else:
            print("4. No stale driver shift assignments found.")
            
        # Commit the transaction
        conn.commit()
        print("\nDatabase cleanup committed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"\nError during cleanup: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    main()
