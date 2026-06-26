import os
import sys
import json
import random
import uuid
import time
import datetime
import io
import mysql.connector
from locust import HttpUser, task, between, events

# Configuration files
DB_CONFIG_FILE = 'db_config.json'

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
    if not os.path.exists(DB_CONFIG_FILE):
        return {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "",
            "database": "utcl_bus_db",
            "use_pure": True
        }
    with open(DB_CONFIG_FILE, 'r') as f:
        cfg = json.load(f)
        cfg['use_pure'] = True
        return cfg

# Global cache of users fetched from the DB
awalpur_employees = []
manikgarh_employees = []
drivers = []
admins = []

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    global awalpur_employees, manikgarh_employees, drivers, admins
    print("=== [Locust Init] Fetching User Accounts from MySQL ===")
    
    cfg = load_db_config()
    try:
        conn = mysql.connector.connect(**cfg)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT psNumber, name, role, plant FROM users WHERE isActive = 1")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        for r in rows:
            role = r['role']
            plant = r['plant']
            user_data = {
                "psNumber": r['psNumber'],
                "name": r['name']
            }
            if role == 'ADMIN':
                admins.append(user_data)
            elif role == 'DRIVER':
                drivers.append(user_data)
            elif role == 'EMPLOYEE':
                if plant.strip().lower() == 'manikgarh':
                    manikgarh_employees.append(user_data)
                else:
                    awalpur_employees.append(user_data)
                    
        print(f"Loaded {len(admins)} Admin(s)")
        print(f"Loaded {len(drivers)} Driver(s)")
        print(f"Loaded {len(awalpur_employees)} Awalpur Employee(s)")
        print(f"Loaded {len(manikgarh_employees)} Manikgarh Employee(s)")
        
    except Exception as e:
        print(f"Error fetching users from DB in Locust init: {e}")
        # Fallbacks to ensure tests run even if DB query fails initially
        admins = [{"psNumber": "PS00001", "name": "System Administrator"}]
        drivers = [{"psNumber": "PS20001", "name": "Rajesh Kumar"}, {"psNumber": "PS20002", "name": "Suresh Singh"}]
        awalpur_employees = [{"psNumber": "PS10001", "name": "Rohan Sharma"}, {"psNumber": "PS10002", "name": "Amit Verma"}]
        manikgarh_employees = [{"psNumber": "PS10003", "name": "Priya Patel"}, {"psNumber": "PS10004", "name": "Sanjay Gupta"}]


class BaseUTCLUser(HttpUser):
    abstract = True
    wait_time = between(1, 3)
    
    def on_start(self):
        self.ps_number = None
        self.name = None
        self.logged_in = False
        self.select_identity()
        self.login()

    def select_identity(self):
        pass

    def login(self):
        if not self.ps_number:
            return
            
        payload = {
            "psNumber": self.ps_number,
            "password": "password123"
        }
        
        with self.client.post("/api/auth/login", json=payload, catch_response=True) as response:
            if response.status_code == 200:
                res_data = response.json()
                if res_data.get("status") == "success":
                    self.logged_in = True
                    response.success()
                else:
                    response.failure(f"Login failed for PS {self.ps_number}: {res_data}")
            else:
                response.failure(f"Login request failed: status code {response.status_code}")

    @task(3)
    def view_dashboard(self):
        # Fetch initial dashboard view data
        self.client.get("/api/data")


class AwalpurEmployeeUser(BaseUTCLUser):
    weight = 40
    
    def select_identity(self):
        if awalpur_employees:
            identity = random.choice(awalpur_employees)
            self.ps_number = identity["psNumber"]
            self.name = identity["name"]
        else:
            self.ps_number = "PS10001"
            self.name = "Test Employee Awalpur"

    @task(2)
    def view_fares(self):
        current_month = datetime.date.today().strftime('%Y-%m')
        self.client.get(f"/api/payroll/my-fares?psNumber={self.ps_number}&month={current_month}")

    @task(1)
    def book_commute(self):
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        shift_id = "S1F"
        booking_id = f"bk_{uuid.uuid4().hex[:12]}"
        ticket_id = f"tk_{uuid.uuid4().hex[:12]}"
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        seat_num = str(random.randint(2, 50))
        
        booking_payload = {
            "booking": {
                "id": booking_id,
                "shiftId": shift_id,
                "travelDate": tomorrow,
                "seatNumber": seat_num,
                "psNumber": self.ps_number,
                "employeeName": self.name,
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
                "employeeName": self.name,
                "psNumber": self.ps_number,
                "shiftCode": shift_id,
                "seatNumber": seat_num,
                "boardingStop": "Awalpur",
                "dropStop": "Manikgarh",
                "travelDate": tomorrow,
                "fare": 20,
                "departureTime": "05:30 AM",
                "generatedAt": now_str
            }
        }
        
        with self.client.post("/api/booking/create", json=booking_payload, catch_response=True) as response:
            if response.status_code in [200, 201, 400, 409]:
                response.success()
            else:
                response.failure(f"Booking failed with code {response.status_code}: {response.text}")


class ManikgarhEmployeeUser(BaseUTCLUser):
    weight = 40
    
    def select_identity(self):
        if manikgarh_employees:
            identity = random.choice(manikgarh_employees)
            self.ps_number = identity["psNumber"]
            self.name = identity["name"]
        else:
            self.ps_number = "PS10003"
            self.name = "Test Employee Manikgarh"

    @task(2)
    def view_fares(self):
        current_month = datetime.date.today().strftime('%Y-%m')
        self.client.get(f"/api/payroll/my-fares?psNumber={self.ps_number}&month={current_month}")

    @task(1)
    def book_commute(self):
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        shift_id = "S1R"
        booking_id = f"bk_{uuid.uuid4().hex[:12]}"
        ticket_id = f"tk_{uuid.uuid4().hex[:12]}"
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        seat_num = str(random.randint(2, 50))
        
        booking_payload = {
            "booking": {
                "id": booking_id,
                "shiftId": shift_id,
                "travelDate": tomorrow,
                "seatNumber": seat_num,
                "psNumber": self.ps_number,
                "employeeName": self.name,
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
                "employeeName": self.name,
                "psNumber": self.ps_number,
                "shiftCode": shift_id,
                "seatNumber": seat_num,
                "boardingStop": "Chandrapur",
                "dropStop": "Manikgarh",
                "travelDate": tomorrow,
                "fare": 20,
                "departureTime": "08:00 AM",
                "generatedAt": now_str
            }
        }
        
        with self.client.post("/api/booking/create", json=booking_payload, catch_response=True) as response:
            if response.status_code in [200, 201, 400, 409]:
                response.success()
            else:
                response.failure(f"Booking failed with code {response.status_code}: {response.text}")


class DriverUser(BaseUTCLUser):
    weight = 15
    
    def select_identity(self):
        if drivers:
            identity = random.choice(drivers)
            self.ps_number = identity["psNumber"]
            self.name = identity["name"]
        else:
            self.ps_number = "PS20001"
            self.name = "Test Driver"

    @task(2)
    def check_attendance_status(self):
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        self.client.get(f"/api/driver/attendance/status?driverId={self.ps_number}&shiftId=S1F&date={current_date}")

    @task(1)
    def submit_departure_attendance(self):
        photo_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xbc\xbc\xbc\x00\x00\x02\x7f\x01\x00\x91\xd1\x11\xdd\x00\x00\x00\x00IEND\xaeB`\x82'
        
        files = {
            'departure_photo': ('departure_selfie.png', io.BytesIO(photo_bytes), 'image/png')
        }
        
        data = {
            'driverId': self.ps_number,
            'busId': 'b1',
            'shiftId': 'S1F',
            'date': datetime.date.today().strftime('%Y-%m-%d'),
            'time': datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        }
        
        with self.client.post("/api/driver/attendance/submit-departure", data=data, files=files, catch_response=True) as response:
            if response.status_code in [200, 400]:
                response.success()
            else:
                response.failure(f"Driver departure submission failed: {response.status_code}")


class AdminUser(BaseUTCLUser):
    weight = 5
    
    def select_identity(self):
        if admins:
            identity = random.choice(admins)
            self.ps_number = identity["psNumber"]
            self.name = identity["name"]
        else:
            self.ps_number = "PS00001"
            self.name = "Test Admin"

    @task(2)
    def view_payroll_summary(self):
        current_month = datetime.date.today().strftime('%Y-%m')
        self.client.get(f"/api/payroll/summary?month={current_month}")

    @task(1)
    def search_employees(self):
        self.client.get("/api/employees/search?query=Rohan")

    @task(1)
    def get_pending_attendances(self):
        self.client.get("/api/admin/attendance/pending")
