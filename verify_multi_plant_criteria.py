import os
import sys
import json
import time
import datetime
import uuid
import random
import threading
import urllib.request
import urllib.error
import mysql.connector

# Load DB configuration
def load_db_config():
    if "MYSQLHOST" in os.environ:
        return {
            "host": os.environ.get("MYSQLHOST"),
            "port": int(os.environ.get("MYSQLPORT", 3306)),
            "user": os.environ.get("MYSQLUSER"),
            "password": os.environ.get("MYSQLPASSWORD"),
            "database": os.environ.get("MYSQLDATABASE", "utcl_bus_db"),
            "use_pure": True
        }
    try:
        cfg = json.load(open('db_config.json'))
        cfg['use_pure'] = True
        return cfg
    except Exception as e:
        print(f"Error loading db_config.json: {e}")
        sys.exit(1)

cfg = load_db_config()

def db_query(query, params=(), commit=False):
    conn = mysql.connector.connect(**cfg)
    cur = conn.cursor(dictionary=True)
    cur.execute(query, params)
    res = None
    if commit:
        conn.commit()
    else:
        res = cur.fetchall()
    cur.close()
    conn.close()
    return res

def login_and_get_cookie(ps_number, password):
    login_url = "http://127.0.0.1:8000/api/auth/login"
    payload = {"psNumber": ps_number, "password": password}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(login_url, data=data, method="POST")
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req) as response:
            headers = response.info()
            cookie_headers = headers.get_all('Set-Cookie', [])
            for cookie in cookie_headers:
                if 'utcl_session=' in cookie:
                    token = cookie.split('utcl_session=')[1].split(';')[0]
                    return f"utcl_session={token}"
    except Exception as e:
        print(f"Login failed for {ps_number}: {e}")
    return None

def post_json(url, payload, cookie=None):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header('Content-Type', 'application/json')
    if cookie:
        req.add_header('Cookie', cookie)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.code, {"message": str(e)}
    except urllib.error.URLError as e:
        return 0, {"message": str(e)}

def post_multipart(url, fields, files, cookie=None):
    import mimetypes
    boundary = f"----Boundary{uuid.uuid4().hex}"
    body = []
    
    for key, val in fields.items():
        body.append(f"--{boundary}".encode('utf-8'))
        body.append(f'Content-Disposition: form-data; name="{key}"'.encode('utf-8'))
        body.append(b'')
        body.append(str(val).encode('utf-8'))
        
    for key, (filename, file_bytes) in files.items():
        body.append(f"--{boundary}".encode('utf-8'))
        body.append(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"'.encode('utf-8'))
        mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        body.append(f'Content-Type: {mimetype}'.encode('utf-8'))
        body.append(b'')
        body.append(file_bytes)
        
    body.append(f"--{boundary}--".encode('utf-8'))
    body.append(b'')
    
    req = urllib.request.Request(url, data=b'\r\n'.join(body), method="POST")
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    if cookie:
        req.add_header('Cookie', cookie)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.code, {"message": str(e)}
    except urllib.error.URLError as e:
        return 0, {"message": str(e)}

def get_url(url, cookie=None):
    req = urllib.request.Request(url, method="GET")
    if cookie:
        req.add_header('Cookie', cookie)
    try:
        start_time = time.time()
        with urllib.request.urlopen(req) as response:
            latency = time.time() - start_time
            return response.status, json.loads(response.read().decode('utf-8')), latency
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8')), 0
        except Exception:
            return e.code, {"message": str(e)}, 0
    except urllib.error.URLError as e:
        return 0, {"message": str(e)}, 0


def run_tests():
    print("=== UTCL Multi-Plant Simultaneous Testing Script ===")
    
    # Check server availability
    status, _, _ = get_url("http://127.0.0.1:8000/api/db-status")
    if status != 200:
        print("Error: The local Flask server is not running on http://127.0.0.1:8000. Please start it first.")
        sys.exit(1)
        
    # Real-time interactive components run on a safe FUTURE date
    test_shift = "S1F"
    test_date = "2026-06-29"   
    test_month = "2026-06"
    test_seat = "33"
    
    # Payroll component runs explicitly on a completed PAST month
    payroll_month = "2026-05"
    
    # ── DB SETUP: Seed Test Users ──────────────────────────────────────────
    print("\n[DB Seeding] Preparing mock accounts...")
    
    # Clean old test data for BOTH test periods to avoid primary key overlaps
    db_query("DELETE FROM bookings WHERE travelDate = %s OR id LIKE 'bk_hist_%%'", (test_date,), commit=True)
    db_query("DELETE FROM bookings WHERE travelDate LIKE %s", (f"{payroll_month}%",), commit=True)
    db_query("DELETE FROM tickets WHERE travelDate = %s OR travelDate LIKE %s", (test_date, f"{payroll_month}%"), commit=True)
    db_query("DELETE FROM driver_attendance WHERE date = %s", (test_date,), commit=True)
    db_query("DELETE FROM fare_deductions WHERE periodMonth = %s OR periodMonth = %s", (test_month, payroll_month), commit=True)
    db_query("DELETE FROM payroll_periods WHERE periodMonth = %s OR periodMonth = %s", (test_month, payroll_month), commit=True)
    db_query("DELETE FROM users WHERE psNumber LIKE 'PS900%' OR psNumber LIKE 'PS800%'", commit=True)
    
    # Seed 10 Employees (5 Awalpur, 5 Manikgarh)
    employee_seeds = []
    for i in range(1, 6):
        employee_seeds.append((f"u_test_ap_{i}", f"Awalpur Tester {i}", f"PS9000{i}", "Awalpur"))
        employee_seeds.append((f"u_test_mg_{i}", f"Manikgarh Tester {i}", f"PS9001{i}", "Manikgarh"))
        
    hashed_pwd = "$2b$12$sD8Wpqqf40eGbtNwad2JEu3LxKcHikXkMWoUUmAiyXYqiJh74VN5a"
    for uid, name, ps, plant in employee_seeds:
        db_query(
            "INSERT INTO users (id, name, psNumber, password, role, isActive, plant) VALUES (%s, %s, %s, %s, 'EMPLOYEE', 1, %s)",
            (uid, name, ps, hashed_pwd, plant), commit=True
        )
        
    # Seed 5 Drivers
    for i in range(1, 6):
        db_query(
            "INSERT INTO users (id, name, psNumber, password, role, isActive, plant) VALUES (%s, %s, %s, %s, 'DRIVER', 1, 'Awalpur')",
            (f"u_test_dr_{i}", f"Driver Tester {i}", f"PS8000{i}", hashed_pwd), commit=True
        )
        
    print(f"Seeded 10 employee accounts (5 Awalpur, 5 Manikgarh) and 5 driver accounts.")
    
    # ──────────────────────────────────────────────────────────────────────────
    # TEST 1: Concurrency Booking Guard (Double Booking Guard)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n--- TEST 1: Concurrency Booking Guard (Double Booking Guard) ---")
    print(f"Pre-allocating 10 threads to attempt concurrent booking on Seat {test_seat}...")
    
    results = []
    threads = []
    
    def book_task(user_index, ps_num, name):
        booking_id = f"bk_{uuid.uuid4().hex[:12]}"
        ticket_id = f"tk_{uuid.uuid4().hex[:12]}"
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        
        payload = {
            "booking": {
                "id": booking_id,
                "shiftId": test_shift,
                "travelDate": test_date,
                "seatNumber": test_seat,
                "psNumber": ps_num,
                "employeeName": name,
                "boardingStopIndex": 0,
                "dropStopIndex": 3,
                "fareAmount": 20,
                "status": "CONFIRMED",
                "bookedAt": now_str
            },
            "ticket": {
                "id": ticket_id,
                "bookingId": booking_id,
                "ticketNumber": f"TKT{random.randint(10000, 99999)}",
                "employeeName": name,
                "psNumber": ps_num,
                "shiftCode": test_shift,
                "seatNumber": test_seat,
                "boardingStop": "Awalpur",
                "dropStop": "Manikgarh",
                "travelDate": test_date,
                "fare": 20,
                "departureTime": "05:30 AM",
                "generatedAt": now_str
            }
        }
        
        time.sleep(random.uniform(0.01, 0.05)) # align execution spikes
        cookie = login_and_get_cookie(ps_num, "password123")
        code, body = post_json("http://127.0.0.1:8000/api/booking/create", payload, cookie=cookie)
        results.append((ps_num, code, body))

    for i in range(10):
        ps_num = employee_seeds[i][2]
        name = employee_seeds[i][1]
        t = threading.Thread(target=book_task, args=(i, ps_num, name))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    success_count = 0
    conflict_count = 0
    other_count = 0
    
    for ps, code, body in results:
        status = body.get('status')
        if code == 201 and status == 'ok':
            print(f"  * User {ps} -> SUCCESS (HTTP 201)")
            success_count += 1
        elif code in [409, 400] or status == 'conflict':
            print(f"  * User {ps} -> REJECTED (HTTP {code}): {body.get('message')}")
            conflict_count += 1
        else:
            print(f"  * User {ps} -> ERROR (HTTP {code}): {body.get('message')}")
            other_count += 1
            
    print(f"Result Summary: Successes: {success_count}, Conflicts: {conflict_count}, Errors: {other_count}")
    assert success_count == 1, f"Expected exactly 1 success, got {success_count}!"
    assert conflict_count == 9, f"Expected exactly 9 conflicts, got {conflict_count}!"
    print("TEST 1 PASSED! Concurrency double-booking guard verified successfully.")
    
    # ──────────────────────────────────────────────────────────────────────────
    # TEST 2: Driver Selfie Upload Concurrency
    # ──────────────────────────────────────────────────────────────────────────
    print("\n--- TEST 2: Driver Selfie Upload Concurrency ---")
    print("Pre-allocating 5 driver threads to submit departure selfies concurrently...")
    
    upload_results = []
    upload_threads = []
    
    def upload_task(driver_index, ps_num):
        from PIL import Image
        import io
        img = Image.new('RGB', (10, 10), color='red')
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format='JPEG')
        photo_bytes = img_bytes_io.getvalue()
        
        fields = {
            'driverId': ps_num,
            'busId': 'b1',
            'shiftId': test_shift,
            'date': test_date,
            'time': datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        }
        files = {
            'departure_photo': (f"selfie_{ps_num}.jpg", photo_bytes)
        }
        cookie = login_and_get_cookie(ps_num, "password123")
        code, body = post_multipart("http://127.0.0.1:8000/api/driver/attendance/submit-departure", fields, files, cookie=cookie)
        upload_results.append((ps_num, code, body))
        
    for i in range(5):
        ps_num = f"PS8000{i+1}"
        t = threading.Thread(target=upload_task, args=(i, ps_num))
        upload_threads.append(t)
        t.start()
        
    for t in upload_threads:
        t.join()
        
    upload_success = 0
    for ps, code, body in upload_results:
        if code == 200 and body.get('status') == 'success':
            upload_success += 1
            print(f"  * Driver {ps} -> UPLOADED (HTTP 200)")
        else:
            print(f"  * Driver {ps} -> FAILED (HTTP {code}): {body.get('message')}")
            
    assert upload_success == 5, f"Expected 5 successful uploads, got {upload_success}!"
    print("TEST 2 PASSED! Driver selfie upload concurrency verified successfully.")
    
    # ──────────────────────────────────────────────────────────────────────────
    # TEST 3: Latency & WAN Simulation Burst
    # ──────────────────────────────────────────────────────────────────────────
    print("\n--- TEST 3: Latency & WAN Simulation Burst ---")
    print("Running 30 rapid GET /api/data requests to calculate latency metrics...")
    
    latencies = []
    latency_threads = []
    
    latency_cookie = login_and_get_cookie("PS90001", "password123")
    
    def latency_task():
        code, _, latency = get_url("http://127.0.0.1:8000/api/data", cookie=latency_cookie)
        if code == 200:
            latencies.append(latency)
            
    for i in range(30):
        t = threading.Thread(target=latency_task)
        latency_threads.append(t)
        t.start()
        
    for t in latency_threads:
        t.join()
        
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        min_latency = min(latencies)
        print(f"  * Total successful fetches: {len(latencies)} / 30")
        print(f"  * Minimum Latency         : {min_latency * 1000:.2f} ms")
        print(f"  * Average Latency         : {avg_latency * 1000:.2f} ms")
        print(f"  * Maximum Latency         : {max_latency * 1000:.2f} ms")
        assert avg_latency < 2.5, f"Average latency too high: {avg_latency:.2f}s"
        assert max_latency < 3.0, f"Max latency exceeded WAN threshold: {max_latency:.2f}s"
        print("TEST 3 PASSED! Intranet/WAN simulation latency verified successfully.")
    else:
        print("TEST 3 FAILED! No requests succeeded.")
        sys.exit(1)
        
    # ──────────────────────────────────────────────────────────────────────────
    # TEST 4: HR Payroll Segmentation
    # ──────────────────────────────────────────────────────────────────────────
    print("\n--- TEST 4: HR Payroll Segmentation ---")
    
    # Use payroll_month (May) to ensure historical logging criteria passes backend validation gates
    print(f"Seeding multi-plant travel history for completed month {payroll_month}...")
    dates = [f"{payroll_month}-10", f"{payroll_month}-12", f"{payroll_month}-14"]
    
    for i, date in enumerate(dates):
        # Awalpur employee PS90001
        bk_id_ap = f"bk_hist_ap_{i}"
        db_query(
            "INSERT INTO bookings (id, shiftId, psNumber, employeeName, seatNumber, boardingStopIndex, dropStopIndex, fareAmount, status, travelDate, bookedAt) "
            "VALUES (%s, 'S1F', 'PS90001', 'Awalpur Tester 1', '10', 0, 3, 20, 'CONFIRMED', %s, NOW())",
            (bk_id_ap, date), commit=True
        )
        # Manikgarh employee PS90011
        bk_id_mg = f"bk_hist_mg_{i}"
        db_query(
            "INSERT INTO bookings (id, shiftId, psNumber, employeeName, seatNumber, boardingStopIndex, dropStopIndex, fareAmount, status, travelDate, bookedAt) "
            "VALUES (%s, 'S1R', 'PS90011', 'Manikgarh Tester 1', '15', 3, 6, 20, 'CONFIRMED', %s, NOW())",
            (bk_id_mg, date), commit=True
        )
        
    # Trigger payroll generation via API
    print(f"Triggering payroll generation for period: {payroll_month}...")
    admin_cookie = login_and_get_cookie("PS00001", "password123")
    code, p_body = post_json("http://127.0.0.1:8000/api/payroll/generate", {"month": payroll_month, "adminPsNumber": "PS00001"}, cookie=admin_cookie)
    print(f"  * Generate payroll response: Code {code}, status: {p_body.get('status')}, message: {p_body.get('message', 'None')}")
    
    # Get payroll records details
    print("Fetching payroll period detailed deductions list...")
    period_id = f"payroll_{payroll_month.replace('-', '_')}"
    code, p_details, _ = get_url(f"http://127.0.0.1:8000/api/payroll/period/{period_id}", cookie=admin_cookie)
    
    ap_deductions = []
    mg_deductions = []
    
    if code == 200:
        deductions = p_details if isinstance(p_details, list) else (p_details.get('employees') or p_details.get('deductions', []))
        print(f"  * Total deductions returned: {len(deductions)}")
        
        for d in deductions:
            ps = d.get('psNumber')
            amount = d.get('totalAmount')
            rides = d.get('totalRides')
            if ps == 'PS90001':
                ap_deductions.append(d)
                print(f"    - Found Awalpur Tester (PS90001): {rides} rides, Billed: INR {amount}")
            elif ps == 'PS90011':
                mg_deductions.append(d)
                print(f"    - Found Manikgarh Tester (PS90011): {rides} rides, Billed: INR {amount}")
                
        assert len(ap_deductions) > 0, "Awalpur employees missing from payroll!"
        assert len(mg_deductions) > 0, "Manikgarh employees missing from payroll!"
        print("TEST 4 PASSED! Multi-plant employee records successfully captured in payroll period.")
    else:
        print(f"TEST 4 FAILED! Unable to retrieve payroll details: Code {code}, Details: {p_details}")
        sys.exit(1)
        
    # ── CLEANUP ─────────────────────────────────────────────────────────────
    print("\n[DB Cleanup] Reverting database changes...")
    db_query("DELETE FROM bookings WHERE travelDate = %s OR id LIKE 'bk_hist_%%'", (test_date,), commit=True)
    db_query("DELETE FROM bookings WHERE travelDate LIKE %s", (f"{payroll_month}%",), commit=True)
    db_query("DELETE FROM tickets WHERE travelDate = %s OR travelDate LIKE %s", (test_date, f"{payroll_month}%"), commit=True)
    db_query("DELETE FROM driver_attendance WHERE date = %s", (test_date,), commit=True)
    db_query("DELETE FROM fare_deductions WHERE periodMonth = %s OR periodMonth = %s", (test_month, payroll_month), commit=True)
    db_query("DELETE FROM payroll_periods WHERE periodMonth = %s OR periodMonth = %s", (test_month, payroll_month), commit=True)
    db_query("DELETE FROM users WHERE psNumber LIKE 'PS900%' OR psNumber LIKE 'PS800%'", commit=True)
    print("Database cleaned up successfully.")
    
    print("\n=== ALL MULTI-PLANT CRITERIA TESTS PASSED SUCCESSFULLY! ===")

if __name__ == '__main__':
    run_tests()