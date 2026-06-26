import mysql.connector
import json
import urllib.request
import urllib.error

# Load DB configuration
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
    try:
        cfg = json.load(open('db_config.json'))
        cfg['use_pure'] = True
    except Exception as e:
        print(f"Error loading db_config.json: {e}")
        exit(1)

def run_test():
    print("=== STARTING ADMIN SHIFT CANCELLATION VERIFICATION ===")
    
    # 1. Establish Database connection
    try:
        conn = mysql.connector.connect(**cfg)
        cur = conn.cursor(dictionary=True)
        print("Database connection established successfully.")
    except Exception as e:
        print(f"Database connection failed: {e}")
        return

    # Use a specific test shift and date
    test_shift = "S1F" # Bus 1 - Forward (assuming this exists)
    test_date = "2026-06-25"
    
    try:
        # Pre-cleanup in case of old runs
        cur.execute("DELETE FROM bookings WHERE travelDate = %s AND shiftId = %s", (test_date, test_shift))
        cur.execute("DELETE FROM tickets WHERE travelDate = %s AND shiftCode = %s", (test_date, test_shift))
        conn.commit()

        # Seed test user if they don't exist
        cur.execute("SELECT id, psNumber FROM users WHERE psNumber = 'PS99999'")
        test_user = cur.fetchone()
        if not test_user:
            cur.execute(
                "INSERT INTO users (id, psNumber, name, role, password, plant, isActive) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                ("u_test_99999", "PS99999", "Test Employee", "EMPLOYEE", "password123", "Awalpur", 1)
            )
            conn.commit()
            print("Seeded test user PS99999.")

        # Seed test bookings
        cur.execute(
            "INSERT INTO bookings (id, psNumber, employeeName, seatNumber, boardingStopIndex, dropStopIndex, fareAmount, travelDate, shiftId, status, bookedAt) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            ("bk_test_1", "PS99999", "Test Employee", "1,2", 0, 1, 40, test_date, test_shift, "CONFIRMED")
        )
        cur.execute(
            "INSERT INTO tickets (id, bookingId, ticketNumber, employeeName, psNumber, seatNumber, boardingStop, dropStop, travelDate, shiftCode, departureTime, fare, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            ("tk_test_1", "bk_test_1", "TKT99999", "Test Employee", "PS99999", "1,2", "Stop A", "Stop B", test_date, test_shift, "06:00 AM", 40, "CONFIRMED")
        )
        conn.commit()
        print(f"Seeded 1 test booking (2 seats) and 1 ticket for shift {test_shift} on {test_date}.")

        # 2. Test booking-count API
        print("\n--- Testing GET /api/admin/shifts/booking-count ---")
        url_count = f"http://localhost:8000/api/admin/shifts/booking-count?shiftId={test_shift}&date={test_date}"
        try:
            req = urllib.request.Request(url_count, method="GET")
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                print("Response:", res_data)
                assert res_data.get("status") == "ok", "Expected status ok"
                assert res_data.get("count") == 1, f"Expected count of 1 booking, got {res_data.get('count')}"
                print("GET booking-count verified successfully!")
        except urllib.error.URLError as e:
            print(f"Failed to request booking-count API (is server running?): {e}")
            return

        # 3. Test cancel-for-day API
        print("\n--- Testing POST /api/admin/shifts/cancel-for-day ---")
        url_cancel = "http://localhost:8000/api/admin/shifts/cancel-for-day"
        post_data = json.dumps({
            "shiftId": test_shift,
            "date": test_date,
            "reason": "Test breakdown cancellation"
        }).encode('utf-8')
        
        try:
            req = urllib.request.Request(url_cancel, data=post_data, method="POST")
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                print("Response:", res_data)
                assert res_data.get("status") in ["ok", "success"], "Expected status ok/success"
                print("POST cancel-for-day API request successful!")
        except urllib.error.URLError as e:
            print(f"Failed to request cancel-for-day API: {e}")
            return

        # 4. Verify DB State & Test synchronization logic
        print("\n--- Verifying Database state updates & new cancel sync behavior ---")
        
        # Verify booking is CANCELLED
        cur.execute("SELECT status FROM bookings WHERE id = 'bk_test_1'")
        bk_status = cur.fetchone()["status"]
        print(f"Booking bk_test_1 status: {bk_status}")
        assert bk_status == "CANCELLED", "Booking should be CANCELLED"
        
        # Verify ticket is CANCELLED
        cur.execute("SELECT status FROM tickets WHERE id = 'tk_test_1'")
        tk_status = cur.fetchone()["status"]
        print(f"Ticket tk_test_1 status: {tk_status}")
        assert tk_status == "CANCELLED", "Ticket should be CANCELLED"
        
        # Verify notification created
        cur.execute("SELECT message FROM notifications WHERE recipientUserId = 'u_test_99999' ORDER BY createdAt DESC LIMIT 1")
        notif = cur.fetchone()
        print(f"Notification message: {notif['message'] if notif else 'None'}")
        assert notif is not None, "Notification should have been created for recipient"
        assert "cancelled" in notif["message"].lower(), "Notification message should mention cancellation"
        
        # Verify cancelled_shifts record created
        cur.execute("SELECT COUNT(*) AS cnt FROM cancelled_shifts WHERE shiftId = %s AND date = %s", (test_shift, test_date))
        cs_count = cur.fetchone()["cnt"]
        print(f"Cancelled shift count in DB: {cs_count}")
        assert cs_count == 1, f"Expected 1 cancelled shift record, got {cs_count}"

        # Test idempotency: Call POST cancel-for-day again
        print("\n--- Testing POST /api/admin/shifts/cancel-for-day again (Idempotency) ---")
        try:
            req = urllib.request.Request(url_cancel, data=post_data, method="POST")
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                print("Response:", res_data)
                assert res_data.get("status") in ["ok", "success"], "Expected status ok/success"
            
            # Assert count is still exactly 1
            cur.execute("SELECT COUNT(*) AS cnt FROM cancelled_shifts WHERE shiftId = %s AND date = %s", (test_shift, test_date))
            cs_count_again = cur.fetchone()["cnt"]
            print(f"Cancelled shift count in DB after second cancel call: {cs_count_again}")
            assert cs_count_again == 1, f"Expected count to remain 1 after second cancel call, got {cs_count_again}"
        except urllib.error.URLError as e:
            print(f"Failed to request cancel-for-day API during idempotency check: {e}")
            return

        # Test booking block: Try booking the cancelled shift
        print("\n--- Testing POST /api/booking/create rejection for cancelled shift ---")
        url_book = "http://localhost:8000/api/booking/create"
        book_data = json.dumps({
            "booking": {
                "id": "bk_test_2",
                "shiftId": test_shift,
                "psNumber": "PS99999",
                "employeeName": "Test Employee",
                "seatNumber": "5",
                "boardingStopIndex": 0,
                "dropStopIndex": 1,
                "fareAmount": 20,
                "status": "CONFIRMED",
                "travelDate": test_date,
                "bookedAt": "2026-06-22T10:00:00Z"
            },
            "ticket": {
                "id": "tk_test_2",
                "bookingId": "bk_test_2",
                "ticketNumber": "TKT88888",
                "employeeName": "Test Employee",
                "psNumber": "PS99999",
                "shiftCode": test_shift,
                "seatNumber": "5",
                "boardingStop": "Stop A",
                "dropStop": "Stop B",
                "fare": 20,
                "departureTime": "06:00 AM",
                "travelDate": test_date,
                "generatedAt": "2026-06-22T10:05:00Z"
            }
        }).encode('utf-8')

        try:
            req = urllib.request.Request(url_book, data=book_data, method="POST")
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                print("Response (unexpected success):", res_data)
                raise AssertionError("Booking creation should have been rejected for cancelled shift, but succeeded")
        except urllib.error.HTTPError as e:
            print(f"Booking creation rejected as expected with HTTP status code: {e.code}")
            assert e.code == 400, f"Expected HTTP status code 400, got {e.code}"
            error_body = json.loads(e.read().decode('utf-8'))
            print("Error message:", error_body)
            assert "cancelled" in error_body.get("message", "").lower(), "Error message should mention cancellation"
        except urllib.error.URLError as e:
            print(f"Failed to request booking create API: {e}")
            return

        # Test api/data contains the cancellation record
        print("\n--- Testing GET /api/data contains cancelled shift record ---")
        url_data = "http://localhost:8000/api/data"
        try:
            req = urllib.request.Request(url_data, method="GET")
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                assert "utcl_cancelled_shifts" in res_data, "Response should contain utcl_cancelled_shifts"
                cancelled_list = res_data["utcl_cancelled_shifts"]
                print(f"Cancelled shifts returned: {cancelled_list}")
                matching_records = [cs for cs in cancelled_list if cs["shiftId"] == test_shift and cs["date"] == test_date]
                assert len(matching_records) == 1, f"Expected exactly 1 matching cancelled shift record in sync data, got {len(matching_records)}"
                print("GET /api/data verification successful!")
        except urllib.error.URLError as e:
            print(f"Failed to request /api/data: {e}")
            return
        
        print("\nDatabase integrity & synchronization checks PASSED!")
        
        # Clean up
        cur.execute("DELETE FROM bookings WHERE travelDate = %s AND shiftId = %s", (test_date, test_shift))
        cur.execute("DELETE FROM tickets WHERE travelDate = %s AND shiftCode = %s", (test_date, test_shift))
        cur.execute("DELETE FROM notifications WHERE recipientUserId = 'u_test_99999'")
        cur.execute("DELETE FROM cancelled_shifts WHERE shiftId = %s AND date = %s", (test_shift, test_date))
        conn.commit()
        print("Cleanup done.")
        print("\n=== ALL TESTS PASSED SUCCESSFULLY! ===")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_test()
