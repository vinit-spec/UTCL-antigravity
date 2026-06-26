import os
import sys

# Perform gevent monkey patching in production/Gunicorn environments before other modules are imported
if "PORT" in os.environ or "gunicorn" in sys.argv[0] or any("gunicorn" in arg for arg in sys.argv):
    try:
        from gevent import monkey
        monkey.patch_all()
    except ImportError:
        pass

import time
import threading
import json
import datetime
import random
import io
import uuid
from flask import Flask, request, jsonify, send_from_directory, make_response, g, abort, redirect
from flask_socketio import SocketIO, emit, join_room, leave_room
import mysql.connector
import bcrypt
from openpyxl import Workbook
from werkzeug.utils import secure_filename
from functools import wraps
from PIL import Image

import gzip

def normalize_date(val):
    if val is None or str(val).strip() in ('', 'None'):
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    try:
        return datetime.datetime.strptime(str(val).strip()[:10], '%Y-%m-%d').date()
    except ValueError:
        return str(val).strip()



app = Flask(__name__, static_folder='.', static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024  # 15 MB limit
app.config['DEBUG'] = False  # Production hardening: ensure debug mode is disabled

@app.after_request
def add_security_headers(response):
    """Inject security headers on every response to harden against clickjacking,
    MIME-sniffing, and XSS. HSTS is handled by Cloudflare in production."""
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-XSS-Protection', '1; mode=block')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
    
    # Restrict CSP to 'self' and local resource assets, removing external CDNs and enforcing object-src 'none'
    response.headers.setdefault('Content-Security-Policy',
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        "connect-src 'self' wss: ws:; "
        "object-src 'none'; "
        "base-uri 'self';"
    )
    
    # Strong HSTS policy
    response.headers.setdefault('Strict-Transport-Security', 'max-age=63072000; includeSubDomains; preload')
    
    # Cross-Origin Opener Policy & Cross-Origin Resource Policy
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
    response.headers.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
    
    return response

@app.after_request
def compress_response(response):
    """Automatically applies Gzip compression to text/html, text/css, and javascript responses."""
    content_type = response.headers.get('Content-Type', '')
    if not any(t in content_type for t in ['text/html', 'text/css', 'javascript']):
        return response

    accept_encoding = request.headers.get('Accept-Encoding', '')
    if 'gzip' not in accept_encoding.lower():
        return response

    # Don't compress very small responses
    content_length = response.headers.get('Content-Length')
    if content_length and int(content_length) < 500:
        return response

    if response.direct_passthrough:
        try:
            data = b"".join(response.response)
            response.direct_passthrough = False
        except Exception:
            return response
    else:
        try:
            data = response.get_data()
        except Exception:
            return response

    if len(data) < 500:
        return response

    compressed = gzip.compress(data)
    response.set_data(compressed)
    response.headers['Content-Encoding'] = 'gzip'
    response.headers['Content-Length'] = len(compressed)
    return response

import logging
from logging.handlers import RotatingFileHandler

# Configure rotating file logging
log_handler = RotatingFileHandler('server.log', maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.INFO)

# Apply to root logger and disable engineio/socketio chatty debugs
logging.getLogger().addHandler(log_handler)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger('werkzeug').addHandler(log_handler)
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)

class LoggerWriter:
    def __init__(self, writer, logger, level):
        self.writer = writer
        self.logger = logger
        self.level = level
        self.linebuf = ''

    def write(self, message):
        self.writer.write(message)
        self.linebuf += message
        if '\n' in self.linebuf:
            lines = self.linebuf.split('\n')
            for line in lines[:-1]:
                if line.strip():
                    self.logger.log(self.level, line.strip())
            self.linebuf = lines[-1]

    def flush(self):
        self.writer.flush()

# Redirect stdout and stderr to logging
sys.stdout = LoggerWriter(sys.stdout, logging.getLogger('stdout'), logging.INFO)
sys.stderr = LoggerWriter(sys.stderr, logging.getLogger('stderr'), logging.ERROR)

# Detect production / cloud deployment environment
is_production = 'PORT' in os.environ or 'gunicorn' in sys.argv[0] or any('gunicorn' in arg for arg in sys.argv)
async_mode = 'gevent' if is_production else 'threading'

# Fix #5: Restrict WebSocket CORS to a specific origin in production.
# Set ALLOWED_ORIGIN env var on Railway (e.g. https://your-app.railway.app).
_allowed_origin = os.environ.get('ALLOWED_ORIGIN', '*')
socketio = SocketIO(app, cors_allowed_origins=_allowed_origin, async_mode=async_mode, logger=False, engineio_logger=False)

# ---------------------------------------------------------------------------
# Fix #6: In-memory rate limiter for login / OTP brute-force protection.
# Works correctly with --workers 1 (Railway/Gunicorn Procfile).
# ---------------------------------------------------------------------------
import collections

_rate_limit_lock = threading.Lock()
# { ip -> deque of timestamps }
_login_attempts: dict = collections.defaultdict(collections.deque)
_otp_attempts: dict = collections.defaultdict(collections.deque)

RATE_LIMIT_LOGIN_MAX = 10        # max attempts
RATE_LIMIT_LOGIN_WINDOW = 300    # per 5 minutes (seconds)
RATE_LIMIT_OTP_MAX = 8           # max OTP guesses
RATE_LIMIT_OTP_WINDOW = 600      # per 10 minutes (seconds)

def _check_rate_limit(store: dict, ip: str, max_hits: int, window: int) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    now = time.time()
    with _rate_limit_lock:
        dq = store[ip]
        # Evict old entries
        while dq and dq[0] < now - window:
            dq.popleft()
        if len(dq) >= max_hits:
            return False
        dq.append(now)
        return True

# ---------------------------------------------------------------------------
# Fix #2: Block direct download of sensitive files served by Flask's static
# file handler (xlsx, py, json configs, logs, md, env files, etc.).
# API download endpoints use explicit routes and are unaffected.
# ---------------------------------------------------------------------------
_BLOCKED_STATIC_EXTENSIONS = {
    '.xlsx', '.xls', '.csv', '.py', '.pyc',
    '.json', '.log', '.env', '.md', '.txt', '.bat', '.sh',
    '.exe', '.zip', '.rar', '.tar', '.gz', '.bak'
}

@app.before_request
def redirect_to_https():
    """Redirect HTTP traffic to HTTPS in production environments."""
    if request.headers.get('X-Forwarded-Proto', 'http') == 'http':
        host = request.headers.get('Host', '')
        if not any(x in host for x in ['localhost', '127.0.0.1', '192.168.']):
            url = request.url.replace('http://', 'https://', 1)
            return redirect(url, code=301)

@app.before_request
def block_sensitive_static_files():
    """Prevent direct download of sensitive project files via static file handler."""
    # Allow all /api/ and /uploads/ routes through unconditionally
    if request.path.startswith('/api/') or request.path.startswith('/uploads/'):
        return None
    # Block dotfiles: .gitignore, .env, .htaccess, etc. (filename starts with dot)
    filename = os.path.basename(request.path)
    if filename.startswith('.'):
        abort(404)
    # Check extension for other sensitive file types
    ext = os.path.splitext(request.path)[1].lower()
    if ext in _BLOCKED_STATIC_EXTENSIONS:
        abort(404)

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({"status": "error", "message": "File size exceeds server-side limit (10 MB)"}), 413

is_production = 'PORT' in os.environ or 'gunicorn' in sys.argv[0] or any('gunicorn' in arg for arg in sys.argv)
UPLOAD_FOLDER = '/app/uploads' if is_production else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/uploads/<filename>')
def serve_upload(filename):
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename)

DB_CONFIG_FILE = 'db_config.json'
db_error_message = None
active_reset_tokens = {}

def is_shift_locked(departure_time_str, travel_date=None):
    if not travel_date:
        travel_date = datetime.date.today().strftime('%Y-%m-%d')
    try:
        dep_time_cleaned = departure_time_str.strip().upper()
        departure_dt = datetime.datetime.strptime(f"{travel_date} {dep_time_cleaned}", "%Y-%m-%d %I:%M %p")
        now_dt = datetime.datetime.now()
        return (departure_dt - now_dt).total_seconds() <= 300
    except Exception as e:
        print(f"[is_shift_locked Error] Failed to parse: {departure_time_str} on {travel_date}. Error: {e}")
        return False

def load_db_config():
    if "MYSQLHOST" in os.environ:
        return {
            "host": os.environ.get("MYSQLHOST"),
            "port": int(os.environ.get("MYSQLPORT", 3306)),
            "user": os.environ.get("MYSQLUSER"),
            "password": os.environ.get("MYSQLPASSWORD"),
            "database": os.environ.get("MYSQLDATABASE", "utcl_bus_db")
        }

    if not os.path.exists(DB_CONFIG_FILE):
        # Create default config if missing
        default_config = {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "",
            "database": "utcl_bus_db"
        }
        with open(DB_CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=2)
        return default_config
    
    with open(DB_CONFIG_FILE, 'r') as f:
        return json.load(f)

from mysql.connector import pooling as mysql_pooling

_db_pool = None
_db_pool_lock = threading.Lock()
_local_state = threading.local()

_data_cache_json = None
_data_cache_lock = threading.Lock()
_data_rebuild_lock = threading.Lock()

_employees_list = None
_employees_lock = threading.Lock()

_users_auth_cache = None
_users_auth_lock = threading.Lock()

def invalidate_data_cache():
    global _data_cache_json, _employees_list, _users_auth_cache
    with _data_cache_lock:
        _data_cache_json = None
    with _employees_lock:
        _employees_list = None
    with _users_auth_lock:
        _users_auth_cache = None

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        import decimal
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

class ConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn
    def __getattr__(self, name):
        return getattr(self._conn, name)
    def commit(self):
        res = self._conn.commit()
        invalidate_data_cache()
        return res
    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)
    def close(self):
        return self._conn.close()
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self._conn, '__exit__'):
            return self._conn.__exit__(exc_type, exc_val, exc_tb)
        self.close()

def get_db_pool():
    global _db_pool
    if _db_pool is None:
        with _db_pool_lock:
            if _db_pool is None:
                config = load_db_config()
                _local_state.initializing_pool = True
                try:
                    _db_pool = mysql_pooling.MySQLConnectionPool(
                        pool_name="utcl_pool",
                        pool_size=32,
                        pool_reset_session=True,
                        host=config['host'],
                        port=config['port'],
                        user=config['user'],
                        password=config['password'],
                        database=config.get('database', 'utcl_bus_db'),
                        use_pure=True
                    )
                finally:
                    _local_state.initializing_pool = False
    return _db_pool

_original_connect = mysql.connector.connect

def _pooled_connect(*args, **kwargs):
    kwargs['use_pure'] = True
    if getattr(_local_state, 'initializing_pool', False):
        return _original_connect(*args, **kwargs)
        
    if 'database' in kwargs or (len(args) > 4):
        try:
            pool = get_db_pool()
            # If the pool is exhausted, wait and retry to prevent overloading the DB
            for attempt in range(40):
                try:
                    conn = pool.get_connection()
                    return ConnectionWrapper(conn)
                except Exception as e:
                    if "pool exhausted" in str(e).lower():
                        time.sleep(0.05)  # Wait 50ms before retrying
                    else:
                        raise e
            # If still exhausted after 2 seconds, fallback to direct connection
            print("[Pool Warning] Connection pool exhausted after 2s. Falling back to direct connection.")
            return ConnectionWrapper(_original_connect(*args, **kwargs))
        except Exception as e:
            print(f"[Pool Error] Failed to connect: {e}")
            raise e
    else:
        return _original_connect(*args, **kwargs)

mysql.connector.connect = _pooled_connect

def get_db_connection():
    config = load_db_config()
    # Check if we are running in the cloud with environment variables
    if "MYSQLHOST" in os.environ:
        conn = _original_connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config['database'],
            use_pure=True
        )
        return conn, config
        
    # First, try to connect without a database name to verify connection and create DB if it doesn't exist
    conn = _original_connect(
        host=config['host'],
        port=config['port'],
        user=config['user'],
        password=config['password'],
        use_pure=True
    )
    return conn, config

def init_db():
    global db_error_message
    try:
        conn, config = get_db_connection()
        cursor = conn.cursor()
        
        # Create database if not exists
        db_name = config.get('database', 'utcl_bus_db')
        if "MYSQLHOST" not in os.environ:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
        cursor.execute(f"USE {db_name}")
        
        # Check if users table exists and has username column, drop if so to recreate clean
        cursor.execute("SHOW TABLES LIKE 'users'")
        if cursor.fetchone():
            cursor.execute("SHOW COLUMNS FROM users LIKE 'username'")
            if cursor.fetchone():
                print("Username column exists in users table. Dropping table to recreate...")
                cursor.execute("DROP TABLE users")
        
        # Create Tables
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id VARCHAR(50) PRIMARY KEY,
            name VARCHAR(100),
            psNumber VARCHAR(50) UNIQUE,
            password VARCHAR(100),
            role VARCHAR(20),
            isActive BOOLEAN,
            email VARCHAR(100) DEFAULT NULL,
            phone VARCHAR(20) DEFAULT NULL,
            plant VARCHAR(50) DEFAULT NULL
        )
        """)
        
        # Database schema migration for existing tables
        cursor.execute("SHOW COLUMNS FROM users LIKE 'plant'")
        if not cursor.fetchone():
            print("Adding plant column to users table...")
            cursor.execute("ALTER TABLE users ADD COLUMN plant VARCHAR(50) DEFAULT NULL")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS buses (
            id VARCHAR(50) PRIMARY KEY,
            identifier VARCHAR(50),
            isActive BOOLEAN
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id VARCHAR(50) PRIMARY KEY,
            busId VARCHAR(50),
            direction VARCHAR(20),
            departureTime VARCHAR(20),
            isActive BOOLEAN,
            stops JSON
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS driver_shifts (
            id VARCHAR(50) PRIMARY KEY,
            driverId VARCHAR(50),
            shiftId VARCHAR(50),
            date VARCHAR(20)
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS driver_attendance (
            id VARCHAR(50) PRIMARY KEY,
            driverId VARCHAR(50),
            busId VARCHAR(50),
            shiftId VARCHAR(50),
            date VARCHAR(20),
            departurePhotoUrl TEXT,
            departureTime VARCHAR(50),
            arrivalPhotoUrl TEXT,
            arrivalTime VARCHAR(50),
            status VARCHAR(20)
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance (
            id VARCHAR(50) PRIMARY KEY,
            busId VARCHAR(50),
            scheduledDate VARCHAR(20),
            description TEXT,
            status VARCHAR(20),
            actualCompletionDate VARCHAR(20)
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracking (
            busId VARCHAR(50) PRIMARY KEY,
            operationalStatus VARCHAR(50),
            currentShiftId VARCHAR(50),
            currentStopIndex INT,
            lastUpdated VARCHAR(50)
        )
        """)
        
        # Drop notifications if it has old columns
        cursor.execute("SHOW TABLES LIKE 'notifications'")
        if cursor.fetchone():
            cursor.execute("SHOW COLUMNS FROM notifications LIKE 'recipientUserId'")
            if not cursor.fetchone():
                cursor.execute("DROP TABLE IF EXISTS notifications")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id VARCHAR(50) PRIMARY KEY,
            recipientUserId VARCHAR(50),
            message TEXT,
            isRead BOOLEAN,
            createdAt VARCHAR(50)
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id VARCHAR(100) PRIMARY KEY,
            shiftId VARCHAR(50),
            psNumber VARCHAR(50),
            employeeName VARCHAR(100),
            seatNumber VARCHAR(100),
            boardingStopIndex INT,
            dropStopIndex INT,
            fareAmount INT,
            status VARCHAR(20),
            travelDate VARCHAR(20),
            bookedAt VARCHAR(50)
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id VARCHAR(100) PRIMARY KEY,
            bookingId VARCHAR(100),
            ticketNumber VARCHAR(50),
            employeeName VARCHAR(100),
            psNumber VARCHAR(50),
            shiftCode VARCHAR(50),
            seatNumber VARCHAR(100),
            boardingStop VARCHAR(100),
            dropStop VARCHAR(100),
            fare INT,
            departureTime VARCHAR(20),
            travelDate VARCHAR(20),
            generatedAt VARCHAR(50)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payroll_periods (
            id VARCHAR(50) PRIMARY KEY,
            periodMonth VARCHAR(10),
            totalAmount DECIMAL(10,2),
            employeeCount INT,
            status VARCHAR(20),
            generatedAt VARCHAR(50),
            processedAt VARCHAR(50),
            processedBy VARCHAR(50),
            notes TEXT
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fare_deductions (
            id VARCHAR(50) PRIMARY KEY,
            periodId VARCHAR(50),
            periodMonth VARCHAR(10),
            psNumber VARCHAR(50),
            employeeName VARCHAR(100),
            role VARCHAR(20),
            totalRides INT,
            totalAmount DECIMAL(10,2),
            status VARCHAR(20)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id VARCHAR(50) PRIMARY KEY,
            psNumber VARCHAR(50),
            token VARCHAR(6),
            expiresAt DATETIME,
            used BOOLEAN DEFAULT FALSE
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cancelled_shifts (
            id VARCHAR(50) PRIMARY KEY,
            shiftId VARCHAR(50),
            date VARCHAR(20),
            reason TEXT,
            cancelledAt VARCHAR(50),
            UNIQUE(shiftId, date)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token       VARCHAR(128) PRIMARY KEY,
            psNumber    VARCHAR(50)  NOT NULL,
            role        VARCHAR(20)  NOT NULL,
            created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
            expires_at  DATETIME     NOT NULL,
            INDEX idx_expires (expires_at)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payroll_plant_locks (
            id VARCHAR(50) PRIMARY KEY,
            periodId VARCHAR(50) NOT NULL,
            plant VARCHAR(50) NOT NULL,
            lockedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_period_plant (periodId, plant)
        )
        """)

        # Migration hook to alter INT columns to VARCHAR if needed
        db_name = config.get('database', 'utcl_bus_db')
        cursor.execute("SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'bookings' AND COLUMN_NAME = 'seatNumber'", (db_name,))
        res = cursor.fetchone()
        if res and res[0].lower() != 'varchar':
            print("Migrating bookings.seatNumber to VARCHAR(100)...")
            cursor.execute("ALTER TABLE bookings MODIFY COLUMN seatNumber VARCHAR(100)")
            
        cursor.execute("SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'tickets' AND COLUMN_NAME = 'seatNumber'", (db_name,))
        res = cursor.fetchone()
        if res and res[0].lower() != 'varchar':
            print("Migrating tickets.seatNumber to VARCHAR(100)...")
            cursor.execute("ALTER TABLE tickets MODIFY COLUMN seatNumber VARCHAR(100)")

        # Migration: add status column to tickets table if it doesn't exist
        cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'tickets' AND COLUMN_NAME = 'status'", (db_name,))
        if not cursor.fetchone():
            print("Migrating tickets table: adding status column...")
            cursor.execute("ALTER TABLE tickets ADD COLUMN status VARCHAR(20) DEFAULT 'ACTIVE'")

        # Migration: add cancelledAt column to bookings table if it doesn't exist
        cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'bookings' AND COLUMN_NAME = 'cancelledAt'", (db_name,))
        if not cursor.fetchone():
            print("Migrating bookings table: adding cancelledAt column...")
            cursor.execute("ALTER TABLE bookings ADD COLUMN cancelledAt VARCHAR(50) DEFAULT NULL")
        
        # Migration: add email column to users table if it doesn't exist
        cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'email'", (db_name,))
        if not cursor.fetchone():
            print("Migrating users table: adding email column...")
            cursor.execute("ALTER TABLE users ADD COLUMN email VARCHAR(100) DEFAULT NULL")

        # Migration: add phone column to users table if it doesn't exist
        cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'phone'", (db_name,))
        if not cursor.fetchone():
            print("Migrating users table: adding phone column...")
            cursor.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(20) DEFAULT NULL")

        # Migration: add UNIQUE constraint to users.psNumber if it doesn't exist
        cursor.execute("""
            SELECT psNumber, COUNT(*) as cnt
            FROM users
            GROUP BY psNumber
            HAVING COUNT(*) > 1
        """)
        duplicates = cursor.fetchall()
        if duplicates:
            print("Duplicate psNumbers found in users table:")
            for row in duplicates:
                print(f"  PS Number: {row[0]} - Count: {row[1]}", flush=True)
            print("WARNING: UNIQUE constraint migration was skipped due to existing duplicates that must be resolved manually.", flush=True)
            cursor.close()
            conn.close()
            return
        else:
            try:
                cursor.execute("ALTER TABLE users ADD CONSTRAINT psNumber_unique UNIQUE (psNumber)")
            except mysql.connector.Error as err:
                if err.errno == 1061:  # duplicate key name — constraint already exists
                    pass
                else:
                    raise

        # Migration: alter users.password column to VARCHAR(100)
        cursor.execute("SELECT CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'password'", (db_name,))
        res_pwd = cursor.fetchone()
        if res_pwd and res_pwd[0] < 100:
            print("Migrating users table: altering password column to VARCHAR(100)...")
            cursor.execute("ALTER TABLE users MODIFY COLUMN password VARCHAR(100)")

        # Migration: hash existing plaintext passwords
        cursor.execute("SELECT id, password FROM users")
        user_rows = cursor.fetchall()
        for uid, pwd in user_rows:
            if pwd and not pwd.startswith('$2b$') and not pwd.startswith('$2a$'):
                hashed_pwd = bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_pwd, uid))
                print(f"Migrated user ID {uid} password to bcrypt")

        # Pre-populate dummy emails for existing seeded users
        cursor.execute("UPDATE users SET email = 'admin@adityabirla.com' WHERE psNumber = 'PS00001' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'employee@adityabirla.com' WHERE psNumber = 'PS10001' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'amit.verma@adityabirla.com' WHERE psNumber = 'PS10002' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'priya.patel@adityabirla.com' WHERE psNumber = 'PS10003' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'sanjay.gupta@adityabirla.com' WHERE psNumber = 'PS10004' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'dhruve@adityabirla.com' WHERE psNumber = 'PS00666' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'shreya@adityabirla.com' WHERE psNumber = 'PS00012' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'vinit@adityabirla.com' WHERE psNumber = 'PS11111' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'sahil@adityabirla.com' WHERE psNumber = 'PS77777' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'rajesh@gmail.com' WHERE psNumber = 'PS20001' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'suresh@gmail.com' WHERE psNumber = 'PS20002' AND email IS NULL")
        cursor.execute("UPDATE users SET email = 'vikram@gmail.com' WHERE psNumber = 'PS20003' AND email IS NULL")
        
        # Ensure plant column is nullable and update super admin to NULL
        cursor.execute("ALTER TABLE users MODIFY COLUMN plant VARCHAR(50) NULL DEFAULT NULL")
        cursor.execute("UPDATE users SET plant = NULL WHERE psNumber = 'PS00001'")
        
        # Check if seeding is needed
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            print("Database empty. Seeding default tables...")
            
            def get_hashed(pw):
                return bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            # Seed users
            users = [
                ("u1", "System Administrator", "PS00001", get_hashed("password123"), "ADMIN", True, "admin@adityabirla.com", None, None),
                ("u2", "Rohan Sharma", "PS10001", get_hashed("password123"), "EMPLOYEE", True, "employee@adityabirla.com", None, "Awalpur"),
                ("u3", "Amit Verma", "PS10002", get_hashed("password123"), "EMPLOYEE", True, "amit.verma@adityabirla.com", None, "Awalpur"),
                ("u4", "Priya Patel", "PS10003", get_hashed("password123"), "EMPLOYEE", True, "priya.patel@adityabirla.com", None, "Manikgarh"),
                ("u5", "Sanjay Gupta", "PS10004", get_hashed("password123"), "EMPLOYEE", True, "sanjay.gupta@adityabirla.com", None, "Manikgarh"),
                ("u6", "Rajesh Kumar", "PS20001", get_hashed("password123"), "DRIVER", True, "rajesh@gmail.com", None, "Awalpur"),
                ("u7", "Suresh Singh", "PS20002", get_hashed("password123"), "DRIVER", True, "suresh@gmail.com", None, "Awalpur"),
                ("u8", "Vikram Rathore", "PS20003", get_hashed("password123"), "DRIVER", True, "vikram@gmail.com", None, "Manikgarh")
            ]
            cursor.executemany("INSERT INTO users (id, name, psNumber, password, role, isActive, email, phone, plant) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", users)
            
            # Seed buses
            buses = [
                ("b1", "Bus 1", True),
                ("b2", "Bus 2", True)
            ]
            cursor.executemany("INSERT IGNORE INTO buses (id, identifier, isActive) VALUES (%s, %s, %s)", buses)
            
            # Seed shifts
            stops_s1f = [
                {"index": 0, "name": "Awalpur", "arrival": "05:30 AM"},
                {"index": 1, "name": "Bibee", "arrival": "05:40 AM"},
                {"index": 2, "name": "Gadchandur", "arrival": "05:55 AM"},
                {"index": 3, "name": "Manikgarh", "arrival": "06:00 AM"},
                {"index": 4, "name": "Rajura", "arrival": "06:25 AM"},
                {"index": 5, "name": "Ballarsha", "arrival": "06:40 AM"},
                {"index": 6, "name": "Chandrapur", "arrival": "07:10 AM"}
            ]
            stops_s1r = [
                {"index": 0, "name": "Chandrapur", "arrival": "08:00 AM"},
                {"index": 1, "name": "Ballarsha", "arrival": "08:30 AM"},
                {"index": 2, "name": "Rajura", "arrival": "08:45 AM"},
                {"index": 3, "name": "Manikgarh", "arrival": "09:10 AM"},
                {"index": 4, "name": "Gadchandur", "arrival": "09:15 AM"},
                {"index": 5, "name": "Bibee", "arrival": "09:30 AM"},
                {"index": 6, "name": "Awalpur", "arrival": "09:40 AM"}
            ]
            stops_s2f = [
                {"index": 0, "name": "Awalpur", "arrival": "08:30 AM"},
                {"index": 1, "name": "Bibee", "arrival": "08:40 AM"},
                {"index": 2, "name": "Gadchandur", "arrival": "08:55 AM"},
                {"index": 3, "name": "Manikgarh", "arrival": "09:00 AM"},
                {"index": 4, "name": "Rajura", "arrival": "09:25 AM"},
                {"index": 5, "name": "Ballarsha", "arrival": "09:40 AM"},
                {"index": 6, "name": "Chandrapur", "arrival": "10:10 AM"}
            ]
            stops_s2r = [
                {"index": 0, "name": "Chandrapur", "arrival": "12:30 PM"},
                {"index": 1, "name": "Ballarsha", "arrival": "01:00 PM"},
                {"index": 2, "name": "Rajura", "arrival": "01:15 PM"},
                {"index": 3, "name": "Manikgarh", "arrival": "01:40 PM"},
                {"index": 4, "name": "Gadchandur", "arrival": "01:45 PM"},
                {"index": 5, "name": "Bibee", "arrival": "02:00 PM"},
                {"index": 6, "name": "Awalpur", "arrival": "02:10 PM"}
            ]
            stops_s3f = [
                {"index": 0, "name": "Awalpur", "arrival": "10:30 AM"},
                {"index": 1, "name": "Bibee", "arrival": "10:40 AM"},
                {"index": 2, "name": "Gadchandur", "arrival": "10:55 AM"},
                {"index": 3, "name": "Manikgarh", "arrival": "11:00 AM"},
                {"index": 4, "name": "Rajura", "arrival": "11:25 AM"},
                {"index": 5, "name": "Ballarsha", "arrival": "11:40 AM"},
                {"index": 6, "name": "Chandrapur", "arrival": "12:10 PM"}
            ]
            stops_s3r = [
                {"index": 0, "name": "Chandrapur", "arrival": "03:30 PM"},
                {"index": 1, "name": "Ballarsha", "arrival": "04:00 PM"},
                {"index": 2, "name": "Rajura", "arrival": "04:15 PM"},
                {"index": 3, "name": "Manikgarh", "arrival": "04:40 PM"},
                {"index": 4, "name": "Gadchandur", "arrival": "04:45 PM"},
                {"index": 5, "name": "Bibee", "arrival": "05:00 PM"},
                {"index": 6, "name": "Awalpur", "arrival": "05:10 PM"}
            ]
            stops_s4f = [
                {"index": 0, "name": "Awalpur", "arrival": "03:00 PM"},
                {"index": 1, "name": "Bibee", "arrival": "03:10 PM"},
                {"index": 2, "name": "Gadchandur", "arrival": "03:25 PM"},
                {"index": 3, "name": "Manikgarh", "arrival": "03:30 PM"},
                {"index": 4, "name": "Rajura", "arrival": "03:55 PM"},
                {"index": 5, "name": "Ballarsha", "arrival": "04:10 PM"},
                {"index": 6, "name": "Chandrapur", "arrival": "04:40 PM"}
            ]
            stops_s4r = [
                {"index": 0, "name": "Chandrapur", "arrival": "07:00 PM"},
                {"index": 1, "name": "Ballarsha", "arrival": "07:30 PM"},
                {"index": 2, "name": "Rajura", "arrival": "07:45 PM"},
                {"index": 3, "name": "Manikgarh", "arrival": "08:10 PM"},
                {"index": 4, "name": "Gadchandur", "arrival": "08:15 PM"},
                {"index": 5, "name": "Bibee", "arrival": "08:30 PM"},
                {"index": 6, "name": "Awalpur", "arrival": "08:40 PM"}
            ]
            
            shifts = [
                ("S1F", "b1", "FORWARD", "05:30 AM", True, json.dumps(stops_s1f)),
                ("S1R", "b1", "RETURN", "08:00 AM", True, json.dumps(stops_s1r)),
                ("S2F", "b2", "FORWARD", "08:30 AM", True, json.dumps(stops_s2f)),
                ("S2R", "b2", "RETURN", "12:30 PM", True, json.dumps(stops_s2r)),
                ("S3F", "b1", "FORWARD", "10:30 AM", True, json.dumps(stops_s3f)),
                ("S3R", "b1", "RETURN", "03:30 PM", True, json.dumps(stops_s3r)),
                ("S4F", "b2", "FORWARD", "03:00 PM", True, json.dumps(stops_s4f)),
                ("S4R", "b2", "RETURN", "07:00 PM", True, json.dumps(stops_s4r))
            ]
            cursor.executemany("INSERT IGNORE INTO shifts (id, busId, direction, departureTime, isActive, stops) VALUES (%s, %s, %s, %s, %s, %s)", shifts)
            
            # Seed driver_shifts
            today_str = datetime.date.today().strftime('%Y-%m-%d')
            driver_shifts = [
                ("da1", "u6", "S1F", today_str),
                ("da2", "u6", "S1R", today_str),
                ("da3", "u7", "S2F", today_str),
                ("da4", "u7", "S2R", today_str)
            ]
            cursor.executemany("INSERT IGNORE INTO driver_shifts (id, driverId, shiftId, date) VALUES (%s, %s, %s, %s)", driver_shifts)
            
            # Seed maintenance
            def get_rel_date(offset):
                return (datetime.date.today() + datetime.timedelta(days=offset)).strftime('%Y-%m-%d')
                
            maintenance = [
                ("m1", "b1", get_rel_date(-2), "Periodic engine tuning & filter replacement", "COMPLETED", get_rel_date(-2)),
                ("m2", "b2", get_rel_date(-5), "Brake pad renewal and fluid top-up", "COMPLETED", get_rel_date(-5)),
                ("m3", "b1", get_rel_date(3), "A/C service & refrigerant recharge", "SCHEDULED", None)
            ]
            cursor.executemany("INSERT IGNORE INTO maintenance (id, busId, scheduledDate, description, status, actualCompletionDate) VALUES (%s, %s, %s, %s, %s, %s)", maintenance)
            
            # Seed tracking
            now_iso = datetime.datetime.now().isoformat()
            tracking = [
                ("b1", "ACTIVE", "S1F", 3, now_iso),
                ("b2", "IDLE", None, None, now_iso)
            ]
            cursor.executemany("INSERT IGNORE INTO tracking (busId, operationalStatus, currentShiftId, currentStopIndex, lastUpdated) VALUES (%s, %s, %s, %s, %s)", tracking)
            
            # Seed mock bookings for analytics (approx ~350-400 records)
            random.seed(42)
            bookings_data = []
            tickets_data = []
            
            employees_list = [
                {"name": "Rohan Sharma", "psNumber": "PS10001"},
                {"name": "Amit Verma", "psNumber": "PS10002"},
                {"name": "Priya Patel", "psNumber": "PS10003"},
                {"name": "Sanjay Gupta", "psNumber": "PS10004"}
            ]
            
            shift_list = [
                {"id": "S1F", "departureTime": "05:30 AM", "stops": stops_s1f},
                {"id": "S1R", "departureTime": "08:00 AM", "stops": stops_s1r},
                {"id": "S2F", "departureTime": "08:30 AM", "stops": stops_s2f},
                {"id": "S2R", "departureTime": "12:30 PM", "stops": stops_s2r},
                {"id": "S3F", "departureTime": "10:30 AM", "stops": stops_s3f},
                {"id": "S3R", "departureTime": "03:30 PM", "stops": stops_s3r},
                {"id": "S4F", "departureTime": "03:00 PM", "stops": stops_s4f},
                {"id": "S4R", "departureTime": "07:00 PM", "stops": stops_s4r}
            ]
            
            for day_offset in range(15, -1, -1):
                date_str = get_rel_date(-day_offset)
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                is_weekend = (date_obj.weekday() >= 5)
                
                for sh in shift_list:
                    num_bookings = random.randint(1, 2) if is_weekend else random.randint(2, 3)
                    selected_seats = set()
                    
                    for _ in range(num_bookings):
                        emp = random.choice(employees_list)
                        seat_number = random.randint(2, 50)
                        while seat_number in selected_seats:
                            seat_number = random.randint(2, 50)
                        selected_seats.add(seat_number)
                        
                        boarding_idx = random.randint(0, 4)
                        drop_idx = random.randint(boarding_idx + 1, 6)
                        
                        booking_id = f"bk_{date_str}_{sh['id']}_{seat_number}"
                        ticket_id = f"tk_{date_str}_{sh['id']}_{seat_number}"
                        ticket_num = f"UTCL-{random.randint(10000, 99999)}"
                        
                        bookings_data.append((
                            booking_id, sh['id'], emp['psNumber'], emp['name'], seat_number,
                            boarding_idx, drop_idx, 20, "CONFIRMED", date_str, f"{date_str}T08:00:00Z"
                        ))
                        
                        tickets_data.append((
                            ticket_id, booking_id, ticket_num, emp['name'], emp['psNumber'],
                            sh['id'], seat_number, sh['stops'][boarding_idx]['name'], sh['stops'][drop_idx]['name'],
                            20, sh['departureTime'], date_str, f"{date_str}T08:05:00Z"
                        ))
            
            cursor.executemany("INSERT IGNORE INTO bookings (id, shiftId, psNumber, employeeName, seatNumber, boardingStopIndex, dropStopIndex, fareAmount, status, travelDate, bookedAt) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", bookings_data)
            cursor.executemany("INSERT IGNORE INTO tickets (id, bookingId, ticketNumber, employeeName, psNumber, shiftCode, seatNumber, boardingStop, dropStop, fare, departureTime, travelDate, generatedAt) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", tickets_data)
            
        conn.commit()
        cursor.close()
        conn.close()
        print("Database initialization and schema verification complete.")
        db_error_message = None
    except Exception as e:
        print(f"Error connecting to/initializing MySQL Database: {e}")
        db_error_message = str(e)

# Initialize database at startup (deferred to background thread at the end of the file)

def check_token_validity(token):
    if not token:
        return None
    try:
        pool = get_db_pool()
        conn = pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT s.psNumber, u.role, u.plant FROM sessions s JOIN users u ON s.psNumber = u.psNumber WHERE s.token = %s AND s.expires_at > NOW()",
            (token,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row
    except Exception as e:
        print(f"[Auth Error] {e}")
        return None

def require_auth(allowed_roles=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            token = request.cookies.get('utcl_session')
            if not token:
                return jsonify({"status": "error", "message": "Unauthorized"}), 401
                
            user_session = check_token_validity(token)
            if not user_session:
                return jsonify({"status": "error", "message": "Unauthorized"}), 401
                
            g.current_user = user_session
            
            if allowed_roles and user_session['role'] not in allowed_roles:
                return jsonify({"status": "error", "message": "Forbidden"}), 403
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Fix #7: Allowlist for query_db_table to prevent SQL injection if the
# function is ever called with user-controlled input.
_ALLOWED_QUERY_TABLES = frozenset({
    'users', 'buses', 'shifts', 'driver_shifts', 'driver_attendance',
    'maintenance', 'tracking', 'notifications', 'bookings', 'tickets',
    'payroll_periods', 'fare_deductions', 'password_reset_tokens',
    'cancelled_shifts', 'sessions'
})

def query_db_table(table_name):
    # Establish dynamic connection to prevent timeouts
    if table_name not in _ALLOWED_QUERY_TABLES:
        raise ValueError(f"[Security] Disallowed table query attempted: {table_name}")
    config = load_db_config()
    conn = mysql.connector.connect(
        host=config['host'],
        port=config['port'],
        user=config['user'],
        password=config['password'],
        database=config.get('database', 'utcl_bus_db')
    )
    cursor = conn.cursor(dictionary=True)
    # Table name is validated against allowlist above — safe to interpolate
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

# Helper to send OTP email (relying strictly on the Brevo HTTP API)
# Helper to send OTP email (relying strictly on the Brevo HTTP API using requests)
def send_otp_email(target_email, employee_name, otp_code):
    import requests
    import os
    import json

    brevo_api_key = os.environ.get('BREVO_API_KEY')
    brevo_sender_email = os.environ.get('BREVO_SENDER_EMAIL', 'utcl-bus-system@adityabirla.com')
    brevo_sender_name = os.environ.get('BREVO_SENDER_NAME', 'UTCL Bus System')

    brevo_config_file = 'brevo_config.json'
    if not brevo_api_key and os.path.exists(brevo_config_file):
        try:
            with open(brevo_config_file, 'r') as f:
                cfg = json.load(f)
                brevo_api_key = cfg.get('brevo_api_key', brevo_api_key)
                brevo_sender_email = cfg.get('sender_email', brevo_sender_email)
                brevo_sender_name = cfg.get('sender_name', brevo_sender_name)
        except Exception as e:
            print(f"[Brevo Config Error] Failed to read {brevo_config_file}: {e}", flush=True)

    if not brevo_api_key:
        print("[Brevo Error] BREVO_API_KEY is not configured. Cannot send OTP.", flush=True)
        return False

    # Outbound HTML payload: clean, professional corporate template highlighting the secure 6-digit verification token
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>UTCL Bus System - Password Reset OTP</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f4f6f9;
            margin: 0;
            padding: 0;
            color: #333333;
        }}
        .email-container {{
            max-width: 600px;
            margin: 40px auto;
            background: #ffffff;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            overflow: hidden;
            border: 1px solid #e1e4e8;
        }}
        .email-header {{
            background-color: #1e3a8a;
            color: #ffffff;
            padding: 24px;
            text-align: center;
        }}
        .email-header h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }}
        .email-body {{
            padding: 32px 24px;
            line-height: 1.6;
        }}
        .greeting {{
            font-size: 16px;
            margin-bottom: 16px;
        }}
        .instruction {{
            font-size: 15px;
            margin-bottom: 24px;
        }}
        .otp-container {{
            background-color: #f0f4ff;
            border: 1px dashed #3b82f6;
            border-radius: 6px;
            padding: 20px;
            text-align: center;
            margin: 24px 0;
        }}
        .otp-code {{
            font-size: 32px;
            font-weight: 700;
            color: #1e3a8a;
            letter-spacing: 6px;
            margin: 0;
        }}
        .expiry-note {{
            font-size: 13px;
            color: #6b7280;
            text-align: center;
            margin-top: 8px;
        }}
        .email-footer {{
            background-color: #f9fafb;
            padding: 20px;
            text-align: center;
            font-size: 12px;
            color: #9ca3af;
            border-top: 1px solid #f3f4f6;
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="email-header">
            <h1>UltraTech Cement Limited</h1>
        </div>
        <div class="email-body">
            <div class="greeting">Dear <strong>{employee_name}</strong>,</div>
            <div class="instruction">We received a request to reset your password for the UTCL Bus Management System. Please use the following 6-digit verification token to proceed:</div>
            <div class="otp-container">
                <div class="otp-code">{otp_code}</div>
                <div class="expiry-note">This OTP is valid for 10 minutes and can only be used once.</div>
            </div>
            <div class="instruction">If you did not make this request, please ignore this email or contact the UTCL IT Support team if you have concerns.</div>
        </div>
        <div class="email-footer">
            &copy; 2026 UltraTech Cement Limited. All rights reserved.<br>
            This is an automated operational notification. Please do not reply directly to this email.
        </div>
    </div>
</body>
</html>"""

    # Plain text fallback
    text_content = f"""Dear {employee_name},

Your One-Time Password (OTP) for resetting your password in the UTCL Bus System is:

{otp_code}

This OTP is valid for 10 minutes. If you did not request this, please ignore this email.

Best regards,
UTCL IT Team
"""

    print("=" * 60, flush=True)
    print(f"  Attempting to send OTP email to: {target_email} via Brevo HTTP API (requests)", flush=True)
    
    payload = {
        "sender": {
            "name": brevo_sender_name,
            "email": brevo_sender_email
        },
        "to": [
            {
                "email": target_email
            }
        ],
        "subject": f"UTCL Bus System - Password Reset OTP: {otp_code}",
        "htmlContent": html_content,
        "textContent": text_content
    }
    
    headers = {
        "accept": "application/json",
        "api-key": brevo_api_key,
        "content-type": "application/json"
    }
    
    try:
        response = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers, timeout=10)
        if response.status_code in (200, 201, 202):
            print(f"  [Brevo Success] Email sent successfully! Response: {response.text}", flush=True)
            print("=" * 60, flush=True)
            return True
        else:
            print(f"  [Brevo Fail] Status Code {response.status_code}. Detail: {response.text}", flush=True)
    except Exception as e:
        print(f"  [Brevo Fail] Unexpected error: {e}", flush=True)

    print("=" * 60, flush=True)
    return False

def get_users_auth_cache():
    global _users_auth_cache
    if _users_auth_cache is None:
        with _users_auth_lock:
            if _users_auth_cache is None:
                try:
                    config = load_db_config()
                    conn = mysql.connector.connect(
                        host=config['host'],
                        port=config['port'],
                        user=config['user'],
                        password=config['password'],
                        database=config.get('database', 'utcl_bus_db')
                    )
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute("SELECT * FROM users WHERE isActive = 1")
                    rows = cursor.fetchall()
                    cursor.close()
                    conn.close()
                    _users_auth_cache = {row['psNumber'].strip().upper(): row for row in rows}
                except Exception as e:
                    print(f"[Auth Cache Error] Failed to pre-fetch users: {e}")
                    return {}
    return _users_auth_cache

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    # Fix #6: Rate-limit login attempts to prevent brute force.
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
    print(f"[RATE_LIMIT_DEBUG] client_ip={client_ip}, remote_addr={request.remote_addr}, headers={dict(request.headers)}")
    is_local = (
        client_ip.startswith('127.') or
        client_ip.startswith('192.168.') or
        client_ip.startswith('10.') or
        client_ip.startswith('172.') or
        client_ip in ('::1', 'localhost', 'unknown')
    )
    if not is_local and not _check_rate_limit(_login_attempts, client_ip, RATE_LIMIT_LOGIN_MAX, RATE_LIMIT_LOGIN_WINDOW):
        return jsonify({"status": "error", "message": "Too many login attempts. Please wait 5 minutes before trying again."}), 429

    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        data = request.get_json() or {}
        ps_number = data.get('psNumber', '').strip().upper()
        password = data.get('password', '')
        
        if not ps_number or not password:
            return jsonify({"status": "error", "message": "PS Number and Password are required."}), 400
            
        if len(ps_number) > 10:
            return jsonify({"status": "invalid"}), 401
            
        users_cache = get_users_auth_cache()
        user = users_cache.get(ps_number)
        if not user:
            try:
                pool = get_db_pool()
                conn = pool.get_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM users WHERE psNumber = %s AND isActive = 1", (ps_number,))
                user = cursor.fetchone()
                cursor.close()
                conn.close()
                if user:
                    with _users_auth_lock:
                        if _users_auth_cache is not None:
                            _users_auth_cache[ps_number] = user
            except Exception as e:
                print(f"[Auth DB Fallback Error] Failed to query user {ps_number}: {e}")

            
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            # Success
            import uuid
            from datetime import datetime, timedelta
            from flask import make_response
            
            token = str(uuid.uuid4())
            # Fix #11: Extend session to 8 hours (was 30 min) for a corporate intranet tool.
            expires_at = datetime.now() + timedelta(hours=8)
            
            config = load_db_config()
            conn = mysql.connector.connect(
                host=config['host'],
                port=config['port'],
                user=config['user'],
                password=config['password'],
                database=config.get('database', 'utcl_bus_db')
            )
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO sessions (token, psNumber, role, expires_at) VALUES (%s, %s, %s, %s)",
                (token, user['psNumber'], user['role'], expires_at)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            resp = make_response(jsonify({
                "status": "success",
                "user": {
                    "id": user['id'],
                    "name": user['name'],
                    "psNumber": user['psNumber'],
                    "role": user['role'],
                    "plant": user['plant']
                }
            }), 200)
            
            # Fix #3: Use X-Forwarded-Proto to detect HTTPS behind Railway's proxy.
            # request.is_secure is always False at the Gunicorn layer since TLS
            # terminates at Railway's edge. X-Forwarded-Proto is the reliable signal.
            is_secure = request.headers.get('X-Forwarded-Proto', request.scheme) == 'https'
            resp.set_cookie(
                'utcl_session',
                value=token,
                httponly=True,
                secure=is_secure,
                samesite='Strict',
                max_age=28800  # 8 hours in seconds
            )
            return resp
        else:
            return jsonify({"status": "invalid"}), 401
            
    except Exception as e:
        print(f"Error in auth-login: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
@require_auth()
def auth_logout():
    try:
        from flask import make_response
        token = request.cookies.get('utcl_session')
        if token:
            config = load_db_config()
            conn = mysql.connector.connect(
                host=config['host'],
                port=config['port'],
                user=config['user'],
                password=config['password'],
                database=config.get('database', 'utcl_bus_db')
            )
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))
            conn.commit()
            cursor.close()
            conn.close()
            
        resp = make_response(jsonify({'success': True}), 200)
        resp.set_cookie('utcl_session', '', expires=0)
        return resp
    except Exception as e:
        print(f"Error in auth-logout: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/forgot-password', methods=['POST'])
def auth_forgot_password():
    # Fix #6: Rate-limit forgot-password to prevent OTP spam.
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
    if not _check_rate_limit(_otp_attempts, client_ip, RATE_LIMIT_OTP_MAX, RATE_LIMIT_OTP_WINDOW):
        return jsonify({"status": "error", "message": "Too many requests. Please wait 10 minutes before trying again."}), 429

    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        data = request.get_json() or {}
        ps_number = data.get('psNumber', '').strip().upper()
        if not ps_number:
            return jsonify({"status": "error", "message": "PS Number is required."}), 400
            
        if len(ps_number) > 10:
            return jsonify({"status": "user_not_found"}), 200
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # Check if user exists
        cursor.execute("SELECT * FROM users WHERE psNumber = %s", (ps_number,))
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            conn.close()
            return jsonify({"status": "user_not_found"}), 200
            
        email = user.get('email')
        if not email:
            cursor.close()
            conn.close()
            return jsonify({"status": "no_email"}), 200
            
        # Generate 6-digit OTP
        otp = f"{random.randint(100000, 999999)}"
        token_id = str(uuid.uuid4())
        # OTP expires in 10 minutes
        expires_at = datetime.datetime.now() + datetime.timedelta(minutes=10)
        expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')
        
        # Insert token into password_reset_tokens
        cursor.execute(
            """INSERT INTO password_reset_tokens (id, psNumber, token, expiresAt, used) 
               VALUES (%s, %s, %s, %s, FALSE)""",
            (token_id, ps_number, otp, expires_at_str)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        # Send email OTP via Brevo
        send_otp_email(email, user.get('name', 'Valued Employee'), otp)
        
        # Mask the email to return to frontend (e.g. r****@adityabirla.com)
        parts = email.split('@')
        if len(parts) == 2:
            name_part, domain_part = parts[0], parts[1]
            masked_name = name_part[0] + '*' * max(1, len(name_part) - 1)
            masked_email = f"{masked_name}@{domain_part}"
        else:
            masked_email = email
            
        return jsonify({"status": "success", "maskedEmail": masked_email}), 200
        
    except Exception as e:
        print(f"Error in forgot-password: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/verify-otp', methods=['POST'])
def auth_verify_otp():
    # Fix #6: Rate-limit OTP verification to prevent enumeration attacks.
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
    if not _check_rate_limit(_otp_attempts, client_ip, RATE_LIMIT_OTP_MAX, RATE_LIMIT_OTP_WINDOW):
        return jsonify({"status": "error", "message": "Too many attempts. Please wait 10 minutes before trying again."}), 429

    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        data = request.get_json() or {}
        ps_number = data.get('psNumber', '').strip().upper()
        otp = data.get('token', '').strip()
        
        if not ps_number or not otp:
            return jsonify({"status": "error", "message": "PS Number and OTP token are required."}), 400
            
        if len(ps_number) > 10:
            return jsonify({"status": "invalid"}), 200
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # Get latest active token for this PS number
        cursor.execute(
            """SELECT * FROM password_reset_tokens 
               WHERE psNumber = %s AND token = %s AND used = FALSE 
               ORDER BY expiresAt DESC LIMIT 1""",
            (ps_number, otp)
        )
        row = cursor.fetchone()
        
        if not row:
            cursor.close()
            conn.close()
            return jsonify({"status": "invalid"}), 200
            
        # Check expiry
        expires_at = row['expiresAt']
        if isinstance(expires_at, str):
            expires_at = datetime.datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S')
            
        if datetime.datetime.now() > expires_at:
            cursor.close()
            conn.close()
            return jsonify({"status": "expired"}), 200
            
        # Mark token as used
        cursor.execute("UPDATE password_reset_tokens SET used = TRUE WHERE id = %s", (row['id'],))
        
        # Generate a temporary resetToken
        reset_token = str(uuid.uuid4())
        global active_reset_tokens
        active_reset_tokens[ps_number] = {
            'token': reset_token,
            'expires': datetime.datetime.now() + datetime.timedelta(minutes=10)
        }
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({"status": "success", "resetToken": reset_token}), 200
        
    except Exception as e:
        print(f"Error in verify-otp: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/reset-password', methods=['POST'])
def auth_reset_password():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        data = request.get_json() or {}
        ps_number = data.get('psNumber', '').strip().upper()
        reset_token = data.get('resetToken', '').strip()
        new_password = data.get('newPassword', '').strip()
        
        if not ps_number or not reset_token or not new_password:
            return jsonify({"status": "error", "message": "All fields are required."}), 400
            
        if len(ps_number) > 10:
            return jsonify({"status": "invalid_token"}), 200
            
        global active_reset_tokens
        record = active_reset_tokens.get(ps_number)
        if not record or record['token'] != reset_token or datetime.datetime.now() > record['expires']:
            return jsonify({"status": "invalid_token"}), 200
            
        # Token is valid, perform reset
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor()
        hashed_pwd = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute("UPDATE users SET password = %s WHERE psNumber = %s", (hashed_pwd, ps_number))
        conn.commit()
        cursor.close()
        conn.close()
        
        # Clear reset token
        active_reset_tokens.pop(ps_number, None)
        
        # Broadcast notification via SocketIO
        socketio.emit('USER_UPDATED', {'psNumber': ps_number})
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        print(f"Error in reset-password: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/reset-user-password', methods=['POST'])
@require_auth(allowed_roles=['ADMIN'])
def admin_reset_user_password():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        data = request.get_json() or {}
        admin_ps = g.current_user['psNumber']
        target_ps = data.get('targetPsNumber', '').strip().upper()
        new_password = data.get('newPassword', '').strip()
        
        if not target_ps or not new_password:
            return jsonify({"status": "error", "message": "All fields are required."}), 400
            
        if len(admin_ps) > 10 or len(target_ps) > 10:
            return jsonify({"status": "error", "message": "Invalid PS Numbers."}), 400
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # Verify target user exists and get their plant
        cursor.execute("SELECT plant FROM users WHERE psNumber = %s", (target_ps,))
        target_row = cursor.fetchone()
        if not target_row:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Target user not found."}), 404
        
        target_plant = target_row.get('plant')
        
        # Block reset of super admin
        if target_plant is None:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Forbidden"}), 403
            
        # Block cross-plant reset
        admin_plant = g.current_user.get('plant')
        if admin_plant and target_plant != admin_plant:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Forbidden"}), 403
            
        # Reset password
        hashed_pwd = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute("UPDATE users SET password = %s WHERE psNumber = %s", (hashed_pwd, target_ps))
        
        # Create an in-app notification for the target user
        notif_id = f"nt_{int(time.time() * 1000)}"
        message = "Your password has been reset by the administrator."
        created_at = datetime.datetime.now().isoformat()
        cursor.execute(
            """INSERT INTO notifications (id, recipientUserId, message, isRead, createdAt) 
               VALUES (%s, %s, %s, FALSE, %s)""",
            (notif_id, target_ps, message, created_at)
        )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # Broadcast notification via SocketIO
        socketio.emit('USER_UPDATED', {'psNumber': target_ps})
        socketio.emit('NOTIFICATION_RECEIVED', {
            'recipientUserId': target_ps,
            'message': message,
            'createdAt': created_at
        }, room=target_ps)
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        print(f"Error in admin-reset-password: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/change-password', methods=['POST'])
@require_auth()
def auth_change_password():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        data = request.get_json() or {}
        ps_number = data.get('psNumber', '').strip().upper()
        current_password = data.get('currentPassword', '').strip()
        new_password = data.get('newPassword', '').strip()
        
        if not ps_number or not current_password or not new_password:
            return jsonify({"status": "error", "message": "All fields are required."}), 400
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # Verify current password
        cursor.execute("SELECT password FROM users WHERE psNumber = %s", (ps_number,))
        user = cursor.fetchone()
        
        if not user or not bcrypt.checkpw(current_password.encode('utf-8'), user['password'].encode('utf-8')):
            cursor.close()
            conn.close()
            return jsonify({"status": "wrong_current_password"}), 200
            
        if current_password == new_password:
            cursor.close()
            conn.close()
            return jsonify({"status": "same_password"}), 200
            
        # Update password
        hashed_pwd = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute("UPDATE users SET password = %s WHERE psNumber = %s", (hashed_pwd, ps_number))
        conn.commit()
        cursor.close()
        conn.close()
        
        # Broadcast notification via SocketIO
        socketio.emit('USER_UPDATED', {'psNumber': ps_number})
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        print(f"Error in change-password: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── Ticket Verification Page (QR Scan Target) ────────────────────────────────
@app.route('/verify')
def verify_ticket():
    ticket_number = request.args.get('t', '').strip()
    
    ticket = None
    error  = None
    
    if not ticket_number:
        error = 'No ticket number provided.'
    else:
        try:
            config = load_db_config()
            conn = mysql.connector.connect(
                host=config['host'], port=config['port'],
                user=config['user'], password=config['password'],
                database=config.get('database', 'utcl_bus_db')
            )
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM tickets WHERE ticketNumber = %s", (ticket_number,))
            ticket = cur.fetchone()
            cur.close()
            conn.close()
            if not ticket:
                error = f'Ticket "{ticket_number}" not found.'
        except Exception as e:
            error = f'Database error: {str(e)}'

    # ── Format shift label ──
    shift_label = ''
    if ticket:
        sc = ticket.get('shiftCode', '')
        parts = sc.split('_') if '_' in sc else [sc]
        direction = 'Return' if sc.upper().endswith('R') else 'Forward'
        bus_num   = ''.join(filter(str.isdigit, sc))
        shift_label = f'Bus {bus_num} – {direction}' if bus_num else sc

    # ── Format date ──
    def fmt_date(d):
        if not d: return ''
        try:
            import datetime as dt
            return dt.datetime.strptime(str(d), '%Y-%m-%d').strftime('%d %b %Y')
        except:
            return str(d)

    valid      = ticket is not None and not error
    status_txt = 'VALID' if valid else 'INVALID'
    status_cls = 'valid' if valid else 'invalid'

    # ── Inline HTML page ──
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ticket Verification – UTCL Bus System</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700;800&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Outfit', sans-serif;
    background: #0f172a;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }}
  .card {{
    background: #1e293b;
    border-radius: 24px;
    width: 100%;
    max-width: 420px;
    overflow: hidden;
    box-shadow: 0 25px 60px rgba(0,0,0,0.5);
    animation: slideUp 0.4s cubic-bezier(.16,1,.3,1);
  }}
  @keyframes slideUp {{
    from {{ opacity:0; transform:translateY(30px); }}
    to   {{ opacity:1; transform:translateY(0); }}
  }}
  /* Header */
  .header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    padding: 24px 24px 20px;
    display: flex;
    align-items: center;
    gap: 14px;
    border-bottom: 1px solid rgba(255,255,255,0.07);
  }}
  .logo-box {{
    background: #ffce00;
    border-radius: 12px;
    width: 52px; height: 52px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    font-size: 22px; font-weight: 800; color: #1a1a2e;
    letter-spacing: -1px;
  }}
  .header-text h1 {{
    font-size: 16px; font-weight: 700;
    color: #f1f5f9; line-height: 1.2;
  }}
  .header-text p {{
    font-size: 12px; color: #94a3b8; margin-top: 2px;
  }}
  /* Status badge */
  .status-section {{
    padding: 24px 24px 20px;
    text-align: center;
    border-bottom: 1px solid rgba(255,255,255,0.07);
  }}
  .status-badge {{
    display: inline-flex; align-items: center; gap: 10px;
    padding: 12px 28px;
    border-radius: 50px;
    font-size: 20px; font-weight: 800; letter-spacing: 2px;
  }}
  .status-badge.valid  {{ background: rgba(16,185,129,0.15); color: #10b981; border: 2px solid rgba(16,185,129,0.4); }}
  .status-badge.invalid {{ background: rgba(239,68,68,0.15);  color: #ef4444; border: 2px solid rgba(239,68,68,0.4);  }}
  .status-icon {{ font-size: 24px; }}
  .status-sub {{
    font-size: 13px; color: #64748b; margin-top: 8px;
  }}
  /* Ticket details */
  .details {{ padding: 20px 24px; }}
  .detail-row {{
    display: flex; justify-content: space-between; align-items: flex-start;
    padding: 11px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    gap: 12px;
  }}
  .detail-row:last-child {{ border-bottom: none; }}
  .detail-label {{
    font-size: 11px; font-weight: 600; color: #475569;
    text-transform: uppercase; letter-spacing: 0.8px;
    flex-shrink: 0;
  }}
  .detail-value {{
    font-size: 14px; font-weight: 600; color: #e2e8f0;
    text-align: right;
  }}
  .detail-value.highlight {{ color: #38bdf8; font-size: 15px; }}
  /* Route viz */
  .route-block {{
    margin: 0 24px 20px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 16px;
    display: flex; align-items: center; gap: 0;
  }}
  .stop {{ flex: 1; text-align: center; }}
  .stop-name {{ font-size: 13px; font-weight: 700; color: #f1f5f9; }}
  .stop-label {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.6px; margin-top: 3px; }}
  .route-arrow {{
    display: flex; flex-direction: column; align-items: center;
    padding: 0 12px; color: #38bdf8; flex-shrink: 0;
  }}
  .route-line {{
    width: 40px; height: 2px;
    background: linear-gradient(90deg, #38bdf8, #818cf8);
    border-radius: 2px; margin-bottom: 4px;
  }}
  .route-arrow-icon {{ font-size: 14px; color: #818cf8; margin-top: -6px; }}
  /* Ticket number */
  .ticket-num-block {{
    margin: 0 24px 20px;
    background: rgba(56,189,248,0.07);
    border: 1px solid rgba(56,189,248,0.2);
    border-radius: 12px;
    padding: 12px 16px;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .ticket-num-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }}
  .ticket-num-value {{ font-size: 15px; font-weight: 800; color: #38bdf8; letter-spacing: 1px; }}
  /* Fare */
  .fare-block {{
    margin: 0 24px 24px;
    background: rgba(251,191,36,0.07);
    border: 1px solid rgba(251,191,36,0.2);
    border-radius: 12px;
    padding: 12px 16px;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .fare-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }}
  .fare-value {{ font-size: 18px; font-weight: 800; color: #fbbf24; }}
  /* Error state */
  .error-body {{
    padding: 40px 24px;
    text-align: center;
  }}
  .error-icon {{ font-size: 48px; margin-bottom: 16px; }}
  .error-msg {{ color: #94a3b8; font-size: 15px; line-height: 1.6; }}
  .error-code {{ color: #ef4444; font-size: 13px; margin-top: 8px; }}
  /* Footer */
  .footer {{
    background: rgba(0,0,0,0.2);
    padding: 12px 24px;
    text-align: center;
    font-size: 11px; color: #334155;
    border-top: 1px solid rgba(255,255,255,0.05);
  }}
</style>
</head>
<body>
<div class="card">

  <!-- Header -->
  <div class="header">
    <div class="logo-box">UT</div>
    <div class="header-text">
      <h1>UltraTech Cement</h1>
      <p>Employee Transport – Ticket Verification</p>
    </div>
  </div>

  <!-- Status Badge -->
  <div class="status-section">
    <div class="status-badge {status_cls}">
      <span class="status-icon">{'✅' if valid else '❌'}</span>
      {status_txt}
    </div>
    <div class="status-sub">{'Ticket is verified and valid' if valid else (error or 'Invalid ticket')}</div>
  </div>

  { f"""
  <div class="ticket-num-block">
    <span class="ticket-num-label">Ticket Number</span>
    <span class="ticket-num-value">{ticket['ticketNumber']}</span>
  </div>

  <div class="details">
    <div class="detail-row">
      <span class="detail-label">Passenger</span>
      <span class="detail-value highlight">{ticket.get('employeeName','—')}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">PS Number</span>
      <span class="detail-value">{ticket.get('psNumber','—')}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Shift / Bus</span>
      <span class="detail-value">{shift_label}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Seat Number</span>
      <span class="detail-value highlight">{ticket.get('seatNumber','—')}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Departure</span>
      <span class="detail-value">{ticket.get('departureTime','—')}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">Travel Date</span>
      <span class="detail-value">{fmt_date(ticket.get('travelDate',''))}</span>
    </div>
  </div>

  <div class="route-block">
    <div class="stop">
      <div class="stop-name">{ticket.get('boardingStop','—')}</div>
      <div class="stop-label">Boarding</div>
    </div>
    <div class="route-arrow">
      <div class="route-line"></div>
      <div class="route-arrow-icon">▶</div>
    </div>
    <div class="stop">
      <div class="stop-name">{ticket.get('dropStop','—')}</div>
      <div class="stop-label">Drop-off</div>
    </div>
  </div>

  <div class="fare-block">
    <span class="fare-label">Fare Paid</span>
    <span class="fare-value">₹{ticket.get('fare', 0)}</span>
  </div>
  """ if valid else f"""
  <div class="error-body">
    <div class="error-icon">🎫</div>
    <div class="error-msg">This ticket could not be verified.</div>
    <div class="error-code">{error or 'Unknown error'}</div>
  </div>
  """ }

  <div class="footer">
    UTCL Internal Transport System &nbsp;•&nbsp; Scan verified at {datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')}
  </div>

</div>
</body>
</html>"""

    return make_response(html, 200 if valid else 404, {'Content-Type': 'text/html; charset=utf-8'})

@app.route('/<path:path>')
def serve_static(path):
    response = make_response(send_from_directory('.', path))
    # Cache static assets like JS, CSS, Fonts, Images for 1 year
    ext = os.path.splitext(path)[1].lower()
    if ext in ['.js', '.css', '.woff2', '.woff', '.ttf', '.png', '.jpg', '.jpeg', '.svg', '.ico']:
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    else:
        response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/api/db-status')
def db_status():
    global db_error_message
    # Retry connecting to MySQL in case connection properties were just updated in db_config.json
    if db_error_message is not None:
        init_db()
    
    if db_error_message:
        return jsonify({"status": "error", "message": db_error_message}), 500
    return jsonify({"status": "connected", "database": "utcl_bus_db"})

# ── WebSocket Room Handlers & Concurrency Holds ───────────────────────────────
import threading
import time

holds_lock = threading.Lock()
holds = {}
HOLD_DURATION = float(os.environ.get('HOLD_DURATION_TEST', '180.0'))

def release_hold_internal(shift_id, travel_date, seat_num, expired=False):
    room = f"{shift_id}_{travel_date}"
    with holds_lock:
        if room in holds and seat_num in holds[room]:
            hold_info = holds[room][seat_num]
            try:
                hold_info["timer"].cancel()
            except Exception:
                pass
            del holds[room][seat_num]
            if not holds[room]:
                del holds[room]
                
    # Broadcast hold release to all users
    socketio.emit('seat_released', {
        'shiftId': shift_id,
        'date': travel_date,
        'seatNumber': seat_num,
        'expired': expired
    }, room=room)

@socketio.on('join_seat_room')
def handle_join_room(data):
    """Client joins a room named '{shiftId}_{date}' to receive live seat updates."""
    room = data.get('room')
    if room:
        join_room(room)
        
        # Sync current active holds to this client immediately
        with holds_lock:
            active_holds = []
            if room in holds:
                for seat_num, hold_info in holds[room].items():
                    active_holds.append({
                        'seatNumber': seat_num,
                        'heldBy': hold_info['psNumber'],
                        'expiresAt': hold_info['expires_at']
                    })
            emit('current_holds', {
                'room': room,
                'holds': active_holds
            })

@socketio.on('leave_seat_room')
def handle_leave_room(data):
    """Client leaves the seat room when navigating away."""
    room = data.get('room')
    if room:
        leave_room(room)

@socketio.on('register_user')
def handle_register_user(data):
    """Client registers their userId and psNumber to join dynamic target notification rooms."""
    ps_number = data.get('psNumber')
    user_id = data.get('userId')
    role = data.get('role')
    if ps_number:
        join_room(ps_number)
    if user_id:
        join_room(user_id)
    if role:
        if role.upper() == 'EMPLOYEE':
            join_room('all_employees')
        elif role.upper() == 'DRIVER':
            join_room('all_drivers')
    print(f"[WS] Registered rooms for user: userId={user_id}, psNumber={ps_number}, role={role}")

@socketio.on('unregister_user')
def handle_unregister_user(data):
    """Client leaves target rooms when logging out."""
    ps_number = data.get('psNumber')
    user_id = data.get('userId')
    role = data.get('role')
    if ps_number:
        leave_room(ps_number)
    if user_id:
        leave_room(user_id)
    if role:
        if role.upper() == 'EMPLOYEE':
            leave_room('all_employees')
        elif role.upper() == 'DRIVER':
            leave_room('all_drivers')
    print(f"[WS] Unregistered rooms for user: userId={user_id}")

@socketio.on('select_seat')
def handle_select_seat(data):
    shift_id = data.get('shiftId')
    travel_date = data.get('date')
    try:
        seat_num = int(data.get('seatNumber'))
    except (TypeError, ValueError):
        return {'status': 'error', 'message': 'Invalid seat number'}
    ps_number = data.get('psNumber')
    sid = request.sid

    room = f"{shift_id}_{travel_date}"
    current_time = time.time()

    # 1. Verify that the seat is not permanently booked in MySQL database
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM bookings WHERE shiftId=%s AND travelDate=%s AND status='CONFIRMED' "
            "AND (seatNumber = %s OR FIND_IN_SET(%s, REPLACE(seatNumber, ' ', '')))",
            (shift_id, travel_date, str(seat_num), str(seat_num))
        )
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        if count > 0:
            return {'status': 'error', 'message': f'Seat {seat_num} is already permanently booked.'}
    except Exception as e:
        return {'status': 'error', 'message': f'Database error: {str(e)}'}

    # 2. Check and acquire the in-memory hold lock
    with holds_lock:
        if room not in holds:
            holds[room] = {}
            
        # Check if held by another user and not expired
        if seat_num in holds[room]:
            hold_info = holds[room][seat_num]
            if hold_info["expires_at"] > current_time:
                if hold_info["psNumber"] != ps_number:
                    return {'status': 'error', 'message': 'This seat was just held by another user.'}
                else:
                    return {'status': 'success'}  # Already held by this user

        # Create temporary hold timer
        expires_at = current_time + HOLD_DURATION
        
        def auto_release():
            release_hold_internal(shift_id, travel_date, seat_num, expired=True)
            
        t = threading.Timer(HOLD_DURATION, auto_release)
        t.start()
        
        holds[room][seat_num] = {
            "psNumber": ps_number,
            "socket_id": sid,
            "expires_at": expires_at,
            "timer": t
        }

    # 3. Broadcast hold event to all room users
    socketio.emit('seat_held', {
        'shiftId': shift_id,
        'date': travel_date,
        'seatNumber': seat_num,
        'heldBy': ps_number,
        'expiresAt': expires_at
    }, room=room)

    return {'status': 'success'}

@socketio.on('deselect_seat')
def handle_deselect_seat(data):
    shift_id = data.get('shiftId')
    travel_date = data.get('date')
    try:
        seat_num = int(data.get('seatNumber'))
    except (TypeError, ValueError):
        return
    ps_number = data.get('psNumber')
    room = f"{shift_id}_{travel_date}"

    with holds_lock:
        if room in holds and seat_num in holds[room]:
            hold_info = holds[room][seat_num]
            if hold_info["psNumber"] == ps_number:
                try:
                    hold_info["timer"].cancel()
                except Exception:
                    pass
                del holds[room][seat_num]
                if not holds[room]:
                    del holds[room]

    # Broadcast release
    socketio.emit('seat_released', {
        'shiftId': shift_id,
        'date': travel_date,
        'seatNumber': seat_num,
        'expired': False
    }, room=room)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    released_seats = []
    with holds_lock:
        for room, room_holds in list(holds.items()):
            for seat_num, hold_info in list(room_holds.items()):
                if hold_info.get("socket_id") == sid:
                    try:
                        hold_info["timer"].cancel()
                    except Exception:
                        pass
                    parts = room.split('_', 1)
                    if len(parts) >= 2:
                        released_seats.append((parts[0], parts[1], seat_num))
                    del room_holds[seat_num]
            if not room_holds:
                try:
                    del holds[room]
                except KeyError:
                    pass
                    
    # Broadcast releases to respective rooms
    for shift_id, travel_date, seat_num in released_seats:
        room = f"{shift_id}_{travel_date}"
        socketio.emit('seat_released', {
            'shiftId': shift_id,
            'date': travel_date,
            'seatNumber': seat_num,
            'expired': False
        }, room=room)

@app.route('/api/booking/release-holds', methods=['POST'])
def release_holds():
    try:
        data = request.get_json(force=True) or {}
        shift_id = data.get('shiftId')
        travel_date = data.get('date')
        seat_numbers = data.get('seatNumbers', [])
        
        for seat in seat_numbers:
            try:
                seat_num = int(seat)
                release_hold_internal(shift_id, travel_date, seat_num, expired=False)
            except (TypeError, ValueError):
                continue
    except Exception as e:
        print(f"[Release Holds Endpoint] Error releasing holds: {e}")
        
    return '', 204

@app.route('/api/data', methods=['GET'])
@require_auth()
def get_all_data():
    global db_error_message, _data_cache_json
    if db_error_message:
        # Retry connection once in case MySQL server just booted or config changed
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500

    admin_plant = g.current_user.get('plant')

    if _data_cache_json is None:
        with _data_rebuild_lock:
            if _data_cache_json is None:
                try:
                    # Load tables using a single connection from the pool to minimize latency
                    config = load_db_config()
                    conn_data = mysql.connector.connect(
                        host=config['host'],
                        port=config['port'],
                        user=config['user'],
                        password=config['password'],
                        database=config.get('database', 'utcl_bus_db')
                    )
                    cursor_data = conn_data.cursor(dictionary=True)
                    
                    cursor_data.execute("SELECT * FROM users")
                    users = cursor_data.fetchall()
                    
                    cursor_data.execute("SELECT * FROM buses")
                    buses = cursor_data.fetchall()
                    
                    cursor_data.execute("SELECT * FROM shifts")
                    shifts_raw = cursor_data.fetchall()
                    
                    cursor_data.execute("SELECT * FROM driver_shifts")
                    driver_shifts = cursor_data.fetchall()
                    
                    cursor_data.execute("SELECT * FROM maintenance")
                    maintenance = cursor_data.fetchall()
                    
                    cursor_data.execute("SELECT * FROM tracking")
                    tracking = cursor_data.fetchall()
                    
                    cursor_data.execute("SELECT * FROM notifications")
                    notifications = cursor_data.fetchall()
                    
                    # Filter bookings and tickets to rolling 60-day window
                    cutoff_date = (datetime.date.today() - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
                    cursor_data.execute("SELECT * FROM bookings WHERE travelDate >= %s", (cutoff_date,))
                    bookings = cursor_data.fetchall()
                    
                    cursor_data.execute("SELECT * FROM tickets WHERE travelDate >= %s", (cutoff_date,))
                    tickets = cursor_data.fetchall()
                    
                    cursor_data.execute("SELECT * FROM payroll_periods")
                    payroll_periods = cursor_data.fetchall()
                    
                    today_str = datetime.date.today().strftime('%Y-%m-%d')
                    cursor_data.execute("SELECT * FROM cancelled_shifts WHERE date >= %s", (today_str,))
                    cancelled_shifts = cursor_data.fetchall()
                    
                    cursor_data.close()
                    conn_data.close()
                    
                    # Convert MySQL boolean / JSON fields back to original types
                    for u in users:
                        u['isActive'] = bool(u['isActive'])
                        u.pop('password', None) # Strip password
                        
                    for b in buses:
                        b['isActive'] = bool(b['isActive'])
                        
                    shifts = []
                    for s in shifts_raw:
                        s['isActive'] = bool(s['isActive'])
                        if isinstance(s['stops'], str):
                            s['stops'] = json.loads(s['stops'])
                        shifts.append(s)
                        
                    for m in maintenance:
                        if m.get('actualCompletionDate') == '':
                            m['actualCompletionDate'] = None
                        
                    for t in tracking:
                        if t['currentStopIndex'] is not None:
                            t['currentStopIndex'] = int(t['currentStopIndex'])
                            
                    for n in notifications:
                        n['isRead'] = bool(n['isRead'])
                        
                    for bk in bookings:
                        bk['seatNumber'] = str(bk['seatNumber'])
                        bk['boardingStopIndex'] = int(bk['boardingStopIndex'])
                        bk['dropStopIndex'] = int(bk['dropStopIndex'])
                        bk['fareAmount'] = int(bk['fareAmount'])
                        
                    for tk in tickets:
                        tk['seatNumber'] = str(tk['seatNumber'])
                        tk['fare'] = int(tk['fare'])
                        
                    for p in payroll_periods:
                        p['totalAmount'] = float(p['totalAmount']) if p['totalAmount'] is not None else 0.0
                        p['employeeCount'] = int(p['employeeCount']) if p['employeeCount'] is not None else 0
                        
                    response_dict = {
                        "utcl_users": users,
                        "utcl_buses": buses,
                        "utcl_shifts": shifts,
                        "utcl_driver_shifts": driver_shifts,
                        "utcl_maintenance": maintenance,
                        "utcl_tracking": tracking,
                        "utcl_notifications": notifications,
                        "utcl_bookings": bookings,
                        "utcl_tickets": tickets,
                        "utcl_payroll_periods": payroll_periods,
                        "utcl_cancelled_shifts": cancelled_shifts
                    }
                    
                    # Pre-serialize to JSON string
                    serialized_json = json.dumps(response_dict, cls=DecimalEncoder)
                    
                    # Store in memory cache
                    with _data_cache_lock:
                        _data_cache_json = serialized_json
                except Exception as e:
                    return jsonify({"status": "error", "message": str(e)}), 500

    if admin_plant is None:
        response = make_response(_data_cache_json)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        import copy
        cached_dict = json.loads(_data_cache_json)
        filtered_dict = copy.deepcopy(cached_dict)
        filtered_dict["utcl_users"] = [u for u in filtered_dict.get("utcl_users", []) if u.get("plant") == admin_plant or u.get("role") == 'DRIVER']
        filtered_json = json.dumps(filtered_dict)
        response = make_response(filtered_json)
        response.headers['Content-Type'] = 'application/json'
        return response

def get_employees_list():
    global _employees_list
    if _employees_list is None:
        with _employees_lock:
            if _employees_list is None:
                try:
                    config = load_db_config()
                    conn = mysql.connector.connect(
                        host=config['host'],
                        port=config['port'],
                        user=config['user'],
                        password=config['password'],
                        database=config.get('database', 'utcl_bus_db')
                    )
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute("SELECT psNumber, name FROM users WHERE role = 'EMPLOYEE' AND isActive = 1")
                    _employees_list = cursor.fetchall()
                    cursor.close()
                    conn.close()
                except Exception as e:
                    print(f"[Search Cache Error] Failed to pre-fetch employees: {e}")
                    return []
    return _employees_list

@app.route('/api/employees/search', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def search_employees():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
    
    try:
        query = request.args.get('query', '').strip().upper()
        if not query:
            return jsonify([])
        
        employees = get_employees_list()
        matched = []
        for emp in employees:
            if emp['psNumber'].upper().startswith(query):
                matched.append(emp)
                if len(matched) >= 10:
                    break
        return jsonify(matched)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/recipients/search', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def search_recipients():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
    
    try:
        query = request.args.get('query', '').strip()
        if not query:
            return jsonify([])
        
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # Match starting characters of psNumber, active users only, role EMPLOYEE or DRIVER
        sql = """
            SELECT id, psNumber, name, role 
            FROM users 
            WHERE isActive = 1 
              AND (role = 'EMPLOYEE' OR role = 'DRIVER') 
              AND psNumber LIKE %s 
            LIMIT 10
        """
        cursor.execute(sql, (query + '%',))
        rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def get_shift_label(shift_id):
    mapping = {
        'S1F': 'Bus 1 - Forward',
        'S1R': 'Bus 1 - Return',
        'S2F': 'Bus 2 - Forward',
        'S2R': 'Bus 2 - Return',
        'S3F': 'Bus 3 - Forward',
        'S3R': 'Bus 3 - Return',
        'S4F': 'Bus 4 - Forward',
        'S4R': 'Bus 4 - Return'
    }
    return mapping.get(shift_id, shift_id)

def parse_departure_time(time_str):
    try:
        return datetime.datetime.strptime(time_str, "%I:%M %p").time()
    except Exception:
        return datetime.time(0, 0)

@app.route('/api/admin/shifts/<shift_id>/export-manifest', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def export_shift_manifest(shift_id):
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500

    travel_date = request.args.get('date', '').strip()
    if not travel_date:
        return jsonify({"status": "error", "message": "Missing date parameter"}), 400

    conn = None
    cursor = None
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)

        # 1. Fetch shift details
        cursor.execute("""
            SELECT s.id, s.departureTime, s.stops, s.busId, b.identifier AS bus_identifier
            FROM shifts s
            LEFT JOIN buses b ON s.busId = b.id
            WHERE s.id = %s
        """, (shift_id,))
        shift_row = cursor.fetchone()
        if not shift_row:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Shift not found"}), 404

        departure_time = shift_row['departureTime']
        bus_id = shift_row['bus_identifier'] if shift_row['bus_identifier'] else shift_row['busId']
        stops = []
        if shift_row['stops']:
            try:
                stops = json.loads(shift_row['stops']) if isinstance(shift_row['stops'], str) else shift_row['stops']
            except Exception as e:
                print(f"[Manifest Export] Failed to parse stops JSON: {e}")

        # 2. Fetch driver name
        cursor.execute("""
            SELECT u.name
            FROM driver_shifts ds
            JOIN users u ON ds.driverId = u.id
            WHERE ds.shiftId = %s AND ds.date = %s
        """, (shift_id, travel_date))
        driver_row = cursor.fetchone()
        driver_name = driver_row['name'] if driver_row else "Not Assigned"

        # 3. Fetch confirmed bookings
        cursor.execute("""
            SELECT b.id, b.psNumber, b.employeeName, b.seatNumber, b.boardingStopIndex, b.dropStopIndex,
                   b.fareAmount, u.name AS primary_name, u.role AS primary_role
            FROM bookings b
            LEFT JOIN users u ON UPPER(b.psNumber) = UPPER(u.psNumber)
            WHERE b.shiftId = %s AND b.travelDate = %s AND b.status = 'CONFIRMED'
            ORDER BY b.seatNumber ASC
        """, (shift_id, travel_date))
        bookings_rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Parse bookings into detailed passenger list
        passenger_list = []
        for bk in bookings_rows:
            seats = [s.strip() for s in str(bk['seatNumber']).split(',') if s.strip()]
            names = [n.strip() for n in str(bk['employeeName']).split(',') if n.strip()]
            
            # Align seats with passenger names
            for i in range(max(len(seats), len(names))):
                seat = seats[i] if i < len(seats) else ""
                name = names[i] if i < len(names) else ""
                
                # Check if this passenger is the primary booking employee
                is_primary = False
                if bk['primary_name']:
                    if name.lower() == bk['primary_name'].lower():
                        is_primary = True
                    elif i == 0 and len(names) > 0:
                        is_primary = True
                else:
                    if i == 0 and len(names) > 0:
                        is_primary = True
                
                role = bk['primary_role'] if is_primary else "FAMILY"
                ps_num = bk['psNumber'] if is_primary else f"{bk['psNumber']} (Family)"
                
                # Resolve stops
                boarding_stop = ""
                drop_stop = ""
                if stops:
                    b_idx = bk['boardingStopIndex']
                    d_idx = bk['dropStopIndex']
                    if 0 <= b_idx < len(stops):
                        boarding_stop = stops[b_idx].get('name', '') if isinstance(stops[b_idx], dict) else stops[b_idx]
                    if 0 <= d_idx < len(stops):
                        drop_stop = stops[d_idx].get('name', '') if isinstance(stops[d_idx], dict) else stops[d_idx]
                
                # Sort out empty strings
                if not boarding_stop and stops:
                    boarding_stop = stops[0].get('name', '') if isinstance(stops[0], dict) else stops[0]
                if not drop_stop and stops:
                    drop_stop = stops[-1].get('name', '') if isinstance(stops[-1], dict) else stops[-1]

                passenger_list.append({
                    'seat': seat,
                    'name': name,
                    'ps_number': ps_num,
                    'role': role,
                    'boarding': boarding_stop,
                    'drop': drop_stop,
                    'fare': bk.get('fareAmount', 20)
                })

        # Sort detailed list by seat number if possible
        def seat_key(p):
            try:
                return int(p['seat'])
            except ValueError:
                return 999
        passenger_list.sort(key=seat_key)

        total_passengers = len(passenger_list)

        # 4. Generate Workbook — single-sheet conductor checklist
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = "Passenger Manifest"

        # ── Colour palette ────────────────────────────────────────────────────
        GREEN_DARK   = "1A6B3C"   # header / title
        GREEN_MID    = "2E8B57"   # info-row key bg
        GREEN_LIGHT  = "E8F5EE"   # info-row value bg / alt data row
        AMBER        = "FF8C00"   # accent (departure time)
        WHITE        = "FFFFFF"
        GREY_HEADER  = "2C3E50"   # column header bg
        GREY_DARK    = "1A252F"   # column header font
        GREY_LINE    = "CBD5E1"   # thin border

        # ── Re-usable styles ──────────────────────────────────────────────────
        def thin_bdr(color=GREY_LINE):
            s = Side(style='thin', color=color)
            return Border(left=s, right=s, top=s, bottom=s)

        def medium_bdr():
            s = Side(style='medium', color="2E8B57")
            return Border(left=s, right=s, top=s, bottom=s)

        f_title   = Font(name="Calibri", size=18, bold=True,  color=GREEN_DARK)
        f_sub     = Font(name="Calibri", size=11, italic=True, color="64748B")
        f_key     = Font(name="Calibri", size=11, bold=True,  color=WHITE)
        f_val     = Font(name="Calibri", size=11,             color="1E293B")
        f_val_acc = Font(name="Calibri", size=11, bold=True,  color=AMBER)
        f_hdr     = Font(name="Calibri", size=11, bold=True,  color=WHITE)
        f_data    = Font(name="Calibri", size=10,             color="1E293B")
        f_data_b  = Font(name="Calibri", size=10, bold=True,  color=GREEN_DARK)
        f_foot    = Font(name="Calibri", size=10, italic=True, color="64748B")
        f_sign    = Font(name="Calibri", size=11, bold=True,  color="1E293B")

        fill_title   = PatternFill("solid", fgColor=GREEN_DARK)
        fill_key     = PatternFill("solid", fgColor=GREEN_MID)
        fill_val     = PatternFill("solid", fgColor=GREEN_LIGHT)
        fill_hdr     = PatternFill("solid", fgColor=GREY_HEADER)
        fill_alt     = PatternFill("solid", fgColor="F0FBF4")   # zebra stripe
        fill_white   = PatternFill("solid", fgColor=WHITE)

        center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left   = Alignment(horizontal="left",   vertical="center", wrap_text=True)
        right  = Alignment(horizontal="right",  vertical="center")

        NUM_COLS = 7   # S.No | Name | PS No | Seat | Boarding | Drop | Verified

        # ── Helper to set a full row background ───────────────────────────────
        def paint_row(row_num, fill, cols=NUM_COLS):
            for c in range(1, cols + 1):
                ws.cell(row=row_num, column=c).fill = fill

        # ═════════════════════════════════════════════════════════════════════
        # ROW 1-2 : Banner header
        # ═════════════════════════════════════════════════════════════════════
        ws.row_dimensions[1].height = 36
        ws.row_dimensions[2].height = 20

        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=NUM_COLS)
        c = ws.cell(row=1, column=1,
                    value="UltraTech Cement Limited — Transport Management System")
        c.font      = f_title
        c.fill      = fill_title
        c.alignment = center

        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=NUM_COLS)
        c = ws.cell(row=2, column=1,
                    value="CONDUCTOR PASSENGER VERIFICATION MANIFEST")
        c.font      = Font(name="Calibri", size=12, bold=True, color=WHITE)
        c.fill      = PatternFill("solid", fgColor="245C3A")
        c.alignment = center

        # ═════════════════════════════════════════════════════════════════════
        # ROWS 3 blank separator
        # ═════════════════════════════════════════════════════════════════════
        ws.row_dimensions[3].height = 8
        paint_row(3, fill_white)

        # ═════════════════════════════════════════════════════════════════════
        # ROWS 4-9 : Shift info block  (key | value | key | value)
        # ═════════════════════════════════════════════════════════════════════
        def info_pair(row, col_k, col_v, key, value, accent=False):
            ws.row_dimensions[row].height = 22
            ck = ws.cell(row=row, column=col_k, value=key)
            ck.font = f_key;  ck.fill = fill_key;  ck.alignment = left
            ck.border = thin_bdr()
            cv = ws.cell(row=row, column=col_v, value=value)
            cv.font = f_val_acc if accent else f_val
            cv.fill = fill_val;  cv.alignment = left
            cv.border = thin_bdr()

        # Left pair: cols 1-2, Right pair: cols 4-5   (col 3 is spacer)
        info_pairs_left  = [
            ("Shift",          get_shift_label(shift_id)),
            ("Travel Date",    travel_date),
            ("Departure Time", departure_time),
        ]
        info_pairs_right = [
            ("Bus",            bus_id),
            ("Driver",         driver_name),
            ("Total Pax",      f"{total_passengers} passengers"),
        ]

        for i, ((lk, lv), (rk, rv)) in enumerate(zip(info_pairs_left, info_pairs_right)):
            row = 4 + i
            ws.row_dimensions[row].height = 24
            # Left: key = cols 1-2 (wide enough for "Departure Time"), value = cols 3-4
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
            ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
            info_pair(row, 1, 3, lk, lv, accent=(lk == "Departure Time"))
            # Right: key = col 5, value = cols 6-7
            ws.merge_cells(start_row=row, start_column=5, end_row=row, end_column=5)
            ws.merge_cells(start_row=row, start_column=6, end_row=row, end_column=7)
            info_pair(row, 5, 6, rk, rv, accent=(rk == "Total Pax"))

        # ═════════════════════════════════════════════════════════════════════
        # ROW 7 : blank gap
        # ═════════════════════════════════════════════════════════════════════
        ws.row_dimensions[7].height = 10
        paint_row(7, fill_white)

        # ═════════════════════════════════════════════════════════════════════
        # ROW 8 : Passenger table column headers
        # ═════════════════════════════════════════════════════════════════════
        HEADER_ROW = 8
        ws.row_dimensions[HEADER_ROW].height = 28
        col_headers = [
            "S.No", "Employee Name", "PS Number",
            "Seat", "Boarding Stop", "Drop Stop",
            "Verified ✓/✗"
        ]
        for ci, h in enumerate(col_headers, 1):
            c = ws.cell(row=HEADER_ROW, column=ci, value=h)
            c.font      = f_hdr
            c.fill      = fill_hdr
            c.alignment = center
            c.border    = thin_bdr("FFFFFF")

        # Freeze panes so header stays visible when scrolling
        ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=1)

        # ═════════════════════════════════════════════════════════════════════
        # ROWS 9+ : Passenger data rows
        # ═════════════════════════════════════════════════════════════════════
        for idx, p in enumerate(passenger_list, 1):
            row = HEADER_ROW + idx
            ws.row_dimensions[row].height = 20
            is_alt = (idx % 2 == 0)
            row_fill = fill_alt if is_alt else fill_white

            values = [
                idx,
                p['name'],
                p['ps_number'],
                p['seat'],
                p['boarding'],
                p['drop'],
                ""            # blank for conductor to mark
            ]
            for ci, val in enumerate(values, 1):
                c = ws.cell(row=row, column=ci, value=val)
                c.fill   = row_fill
                c.border = thin_bdr()
                if ci in [1, 4, 7]:             # centered cols
                    c.alignment = center
                    c.font = f_data_b if ci == 4 else f_data
                elif ci == 2:                    # name — bold + green
                    c.font      = f_data_b
                    c.alignment = left
                else:
                    c.font      = f_data
                    c.alignment = left

        # ═════════════════════════════════════════════════════════════════════
        # Footer rows
        # ═════════════════════════════════════════════════════════════════════
        last_data_row = HEADER_ROW + len(passenger_list)
        gap_row       = last_data_row + 1
        sig_row       = last_data_row + 2
        foot_row      = last_data_row + 3

        ws.row_dimensions[gap_row].height  = 16
        ws.row_dimensions[sig_row].height  = 36
        ws.row_dimensions[foot_row].height = 18

        paint_row(gap_row, fill_white)

        # Signature block
        ws.merge_cells(start_row=sig_row, start_column=1, end_row=sig_row, end_column=3)
        cs = ws.cell(row=sig_row, column=1, value="Conductor Signature: _______________________")
        cs.font = f_sign;  cs.alignment = left
        cs.border = Border(bottom=Side(style='medium', color=GREEN_DARK))

        ws.merge_cells(start_row=sig_row, start_column=6, end_row=sig_row, end_column=7)
        cs2 = ws.cell(row=sig_row, column=6, value="Date & Time: ___________________________")
        cs2.font = f_sign;  cs2.alignment = left
        cs2.border = Border(bottom=Side(style='medium', color=GREEN_DARK))

        # Footer note
        ws.merge_cells(start_row=foot_row, start_column=1, end_row=foot_row, end_column=NUM_COLS)
        cf = ws.cell(row=foot_row, column=1,
                     value=f"Generated by UTCL Internal Transport System  |  {datetime.datetime.now().strftime('%d-%b-%Y %I:%M %p')}  |  CONFIDENTIAL — For Conductor Use Only")
        cf.font = f_foot;  cf.alignment = center

        # ═════════════════════════════════════════════════════════════════════
        # Column widths
        # ═════════════════════════════════════════════════════════════════════
        col_widths = {1: 6, 2: 30, 3: 14, 4: 8, 5: 24, 6: 24, 7: 16}
        for col_num, width in col_widths.items():
            ws.column_dimensions[get_column_letter(col_num)].width = width

        # Print settings (A4 landscape, fit to 1 page wide)
        ws.page_setup.orientation      = "landscape"
        ws.page_setup.paperSize        = 9   # A4
        ws.page_setup.fitToPage        = True
        ws.page_setup.fitToWidth       = 1
        ws.page_setup.fitToHeight      = 0
        ws.print_title_rows            = f"{HEADER_ROW}:{HEADER_ROW}"

        # Write to memory stream
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        filename = f"UTCL_Manifest_{shift_id}_{travel_date}.xlsx"
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"status": "error", "message": f"Export failed: {str(e)}"}), 500

@app.route('/api/bookings/export', methods=['GET'])
@require_auth()
def export_bookings_excel():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        ps_number = request.args.get('psNumber', '').strip()
        if not ps_number:
            return jsonify({"status": "error", "message": "Missing psNumber parameter"}), 400
            
        if g.current_user['role'] != 'ADMIN' and g.current_user['psNumber'].strip().upper() != ps_number.strip().upper():
            return jsonify({"status": "error", "message": "Forbidden"}), 403
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # 1. Get all shifts to resolve stop names and departure times
        cursor.execute("SELECT id, departureTime, stops FROM shifts")
        shifts_rows = cursor.fetchall()
        shifts_map = {}
        for s in shifts_rows:
            stops_list = s['stops']
            if isinstance(stops_list, str):
                stops_list = json.loads(stops_list)
            shifts_map[s['id']] = {
                'departureTime': s['departureTime'],
                'stops': {stop['index']: stop['name'] for stop in stops_list}
            }
            
        # 2. Get bookings matching psNumber
        if ps_number == 'ALL':
            sql = "SELECT travelDate, shiftId, seatNumber, boardingStopIndex, dropStopIndex, fareAmount, status FROM bookings WHERE status = 'CONFIRMED'"
            cursor.execute(sql)
        else:
            sql = "SELECT travelDate, shiftId, seatNumber, boardingStopIndex, dropStopIndex, fareAmount, status FROM bookings WHERE psNumber = %s AND status = 'CONFIRMED'"
            cursor.execute(sql, (ps_number,))
            
        bookings_rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # 3. Sort by travelDate and departure time (descending)
        def sort_bookings_key(b):
            try:
                dt = datetime.datetime.strptime(b['travelDate'], "%Y-%m-%d").date()
            except Exception:
                dt = datetime.date(1970, 1, 1)
            
            dep_time = datetime.time(0, 0)
            shift = shifts_map.get(b['shiftId'])
            if shift:
                dep_time = parse_departure_time(shift['departureTime'])
            
            return datetime.datetime.combine(dt, dep_time)

        bookings_rows.sort(key=sort_bookings_key, reverse=True)
        
        # 4. Create Workbook and write data
        wb = Workbook()
        ws = wb.active
        ws.title = "Booking History"
        
        # Headers
        headers = ['Travel Date', 'Shift', 'Seat No', 'Boarding Stop', 'Drop Stop', 'Fare', 'Status']
        ws.append(headers)
        
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        
        for b in bookings_rows:
            s_id = b['shiftId']
            shift_info = shifts_map.get(s_id, {})
            dep_time = shift_info.get('departureTime', '')
            stops = shift_info.get('stops', {})
            
            shift_col = f"{get_shift_label(s_id)} ({dep_time})" if dep_time else get_shift_label(s_id)
            boarding_stop = stops.get(b['boardingStopIndex'], f"Stop {b['boardingStopIndex']}")
            drop_stop = stops.get(b['dropStopIndex'], f"Stop {b['dropStopIndex']}")
            
            is_active = b['travelDate'] >= today_str
            status_text = "Active" if is_active else "Past"
            
            row_data = [
                b['travelDate'],
                shift_col,
                f"Seat {b['seatNumber']}",
                boarding_stop,
                drop_stop,
                f"₹{b['fareAmount']}",
                status_text
            ]
            ws.append(row_data)
            
        # Set column widths
        widths = {'A': 14, 'B': 30, 'C': 10, 'D': 20, 'E': 20, 'F': 8, 'G': 12}
        for col_letter, width in widths.items():
            ws.column_dimensions[col_letter].width = width
            
        # Write to BytesIO stream
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        # Return as binary response stream
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = 'attachment; filename="booking_history.xlsx"'
        return response
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/booking/create', methods=['POST'])
@require_auth()
def create_booking():
    """Atomically creates a booking + ticket in MySQL using a row-level transaction lock,
    then broadcasts the update to all LAN clients viewing the same shift+date seat map."""
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500

    conn = None
    cursor = None
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON payload received"}), 400

        booking  = data.get('booking', {})
        ticket   = data.get('ticket', {})

        shift_id    = booking.get('shiftId', '')
        travel_date = booking.get('travelDate', '')
        seat_str    = str(booking.get('seatNumber', ''))
        ps_number   = booking.get('psNumber', '')

        if g.current_user['role'] != 'ADMIN' and g.current_user['psNumber'].strip().upper() != ps_number.strip().upper():
            return jsonify({"status": "error", "message": "Forbidden"}), 403

        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        # Start the transaction explicitly
        conn.start_transaction()
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")

        # ── Check if the shift has been cancelled for the selected date ───────
        cursor.execute(
            "SELECT id FROM cancelled_shifts WHERE shiftId = %s AND date = %s",
            (shift_id, travel_date)
        )
        if cursor.fetchone():
            conn.rollback()
            return jsonify({
                "status": "error",
                "message": "Cannot book — this shift has been cancelled for the selected date."
            }), 400

        # ── Check if payroll period is processed/locked ────────────────────────
        month_prefix = travel_date[:7]
        cursor.execute("SELECT status FROM payroll_periods WHERE periodMonth = %s", (month_prefix,))
        period_row = cursor.fetchone()
        if period_row and period_row['status'] == 'PROCESSED':
            conn.rollback()
            return jsonify({
                "status": "error",
                "message": f"Cannot book — payroll for {month_prefix} has already been processed and locked."
            }), 400

        # ── Row Lock the Shift Row to serialize bookings for this shift ───────
        cursor.execute("SELECT id, departureTime FROM shifts WHERE id = %s FOR UPDATE", (shift_id,))
        shift_row = cursor.fetchone()
        if shift_row:
            dep_time_str = shift_row.get('departureTime')
            if dep_time_str and is_shift_locked(dep_time_str, travel_date):
                conn.rollback()
                return jsonify({
                    "status": "error",
                    "message": "Cannot book — this shift is locked (within 5 minutes of departure or already departed)."
                }), 400

        # ── Verify requested seats are still free (serial check) ──────────────
        requested_seats = [int(s.strip()) for s in seat_str.split(',') if s.strip().isdigit()]
        
        # Validation for 50-seat bus layout (passenger seats must be in range 2-50, seat 1 is conductor only)
        if requested_seats:
            for s in requested_seats:
                if s == 1:
                    conn.rollback()
                    return jsonify({
                        "status": "error",
                        "message": "Cannot book seat 1 — it is reserved for the conductor."
                    }), 400
                if s < 2 or s > 50:
                    conn.rollback()
                    return jsonify({
                        "status": "error",
                        "message": "Invalid seat number. Valid passenger seats are 2 to 50."
                    }), 400

        if requested_seats:
            cursor.execute(
                "SELECT seatNumber FROM bookings "
                "WHERE shiftId=%s AND travelDate=%s AND status='CONFIRMED' FOR UPDATE",
                (shift_id, travel_date)
            )
            taken_rows = cursor.fetchall()
            taken_seats = []
            for row in taken_rows:
                for s in str(row['seatNumber']).split(','):
                    s = s.strip()
                    if s.isdigit():
                        taken_seats.append(int(s))

            conflicts = [s for s in requested_seats if s in taken_seats]
            if conflicts:
                conn.rollback()
                conflict_str = ', '.join(str(c) for c in conflicts)
                return jsonify({
                    "status": "conflict",
                    "message": f"Seat(s) {conflict_str} {'was' if len(conflicts)==1 else 'were'} just booked by another user. Please select a different seat.",
                    "conflictSeats": conflicts
                }), 409

            # Also check holds dictionary to ensure no other user holds these seats
            with holds_lock:
                room = f"{shift_id}_{travel_date}"
                if room in holds:
                    for seat_num in requested_seats:
                        if seat_num in holds[room]:
                            hold_info = holds[room][seat_num]
                            if hold_info["psNumber"] != ps_number and hold_info["expires_at"] > time.time():
                                conn.rollback()
                                return jsonify({
                                    "status": "conflict",
                                    "message": f"Seat {seat_num} is currently held by another user.",
                                    "conflictSeats": [seat_num]
                                }), 409

        # ── Insert booking ────────────────────────────────────────────────────
        bk_stmt = (
            "INSERT INTO bookings (id, shiftId, psNumber, employeeName, seatNumber, "
            "boardingStopIndex, dropStopIndex, fareAmount, status, travelDate, bookedAt) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        cursor.execute(bk_stmt, (
            booking.get('id'), shift_id, ps_number,
            booking.get('employeeName'), seat_str,
            int(booking.get('boardingStopIndex', 0)),
            int(booking.get('dropStopIndex', 0)),
            int(booking.get('fareAmount', 20)),
            booking.get('status', 'CONFIRMED'),
            travel_date, booking.get('bookedAt')
        ))

        # ── Insert ticket ─────────────────────────────────────────────────────
        tk_stmt = (
            "INSERT INTO tickets (id, bookingId, ticketNumber, employeeName, psNumber, "
            "shiftCode, seatNumber, boardingStop, dropStop, fare, departureTime, travelDate, generatedAt) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        cursor.execute(tk_stmt, (
            ticket.get('id'), ticket.get('bookingId'), ticket.get('ticketNumber'),
            ticket.get('employeeName'), ticket.get('psNumber'),
            ticket.get('shiftCode'), str(ticket.get('seatNumber')),
            ticket.get('boardingStop'), ticket.get('dropStop'),
            int(ticket.get('fare', 20)), ticket.get('departureTime'),
            ticket.get('travelDate'), ticket.get('generatedAt')
        ))

        conn.commit()

        # ── Release temporary holds since they are now booked permanently ─────
        with holds_lock:
            room = f"{shift_id}_{travel_date}"
            if room in holds:
                for seat_num in requested_seats:
                    if seat_num in holds[room]:
                        try:
                            holds[room][seat_num]["timer"].cancel()
                        except Exception:
                            pass
                        del holds[room][seat_num]
                if not holds[room]:
                    del holds[room]

        # ── Broadcast to all seat-map viewers for this shift+date ─────────────
        room_name = f"{shift_id}_{travel_date}"
        socketio.emit('seat_booked', {
            'shiftId':    shift_id,
            'date':       travel_date,
            'seats':      requested_seats,
            'bookedBy':   ps_number
        }, room=room_name)

        socketio.emit('SEAT_COUNT_UPDATED', {
            'shiftId':    shift_id,
            'date':       travel_date
        })

        return jsonify({"status": "ok", "ticket": ticket}), 201

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

@app.route('/api/booking/cancel/<booking_id>', methods=['POST'])
@require_auth()
def cancel_booking(booking_id):
    """Cancel an active booking. Validates shift has not departed, marks booking
    and ticket as CANCELLED in DB, then broadcasts BOOKING_CANCELLED via WebSocket."""
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500

    conn = None
    cursor = None
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        conn.start_transaction()
        cursor = conn.cursor(dictionary=True, buffered=True)

        # Fetch the booking
        cursor.execute("SELECT * FROM bookings WHERE id = %s FOR UPDATE", (booking_id,))
        booking = cursor.fetchone()

        if not booking:
            conn.rollback()
            return jsonify({"status": "error", "message": "Booking not found."}), 404

        if g.current_user['role'] != 'ADMIN' and g.current_user['psNumber'].strip().upper() != booking['psNumber'].strip().upper():
            conn.rollback()
            return jsonify({"status": "error", "message": "Forbidden"}), 403

        # ── Check if payroll period is processed/locked ────────────────────────
        travel_date = booking['travelDate']
        month_prefix = travel_date[:7]
        cursor.execute("SELECT status FROM payroll_periods WHERE periodMonth = %s", (month_prefix,))
        period_row = cursor.fetchone()
        if period_row and period_row['status'] == 'PROCESSED':
            conn.rollback()
            return jsonify({
                "status": "error",
                "message": f"Cannot cancel booking — payroll for {month_prefix} has already been processed and locked."
            }), 400

        if booking['status'] == 'CANCELLED':
            conn.rollback()
            return jsonify({"status": "error", "message": "This booking is already cancelled."}), 400

        shift_id    = booking['shiftId']
        travel_date = booking['travelDate']
        seat_str    = str(booking.get('seatNumber', ''))
        ps_number   = booking['psNumber']

        # ── Departure Guard: reject if shift has already departed or is locked ──
        cursor.execute("SELECT departureTime FROM shifts WHERE id = %s", (shift_id,))
        shift_row = cursor.fetchone()
        if shift_row:
            dep_time_str = shift_row['departureTime']
            if dep_time_str and is_shift_locked(dep_time_str, travel_date):
                conn.rollback()
                return jsonify({"status": "error", "message": "Cannot cancel — booking is locked because departure is within 5 minutes or has already occurred."}), 400

        # ── Mark booking as CANCELLED ────────────────────────────────────────
        cancelled_at = datetime.datetime.now().isoformat()
        cursor.execute(
            "UPDATE bookings SET status='CANCELLED', cancelledAt=%s WHERE id=%s",
            (cancelled_at, booking_id)
        )

        # ── Mark linked ticket as CANCELLED ──────────────────────────────────
        cursor.execute(
            "UPDATE tickets SET status='CANCELLED' WHERE bookingId=%s",
            (booking_id,)
        )

        conn.commit()

        # ── Parse seats for broadcast ────────────────────────────────────────
        released_seats = [int(s.strip()) for s in seat_str.split(',') if s.strip().isdigit()]

        # ── Broadcast BOOKING_CANCELLED globally (single emission, client guards duplicates) ──
        # Emitting to both a room AND globally caused ~8 UI refreshes per cancellation.
        # The client BOOKING_CANCELLED handler has isAlreadyCancelled guards, so one
        # global broadcast is sufficient for all connected users.
        socketio.emit('BOOKING_CANCELLED', {
            'bookingId':  booking_id,
            'shiftId':    shift_id,
            'travelDate': travel_date,
            'seats':      released_seats,
            'psNumber':   ps_number
        })

        # ── Broadcast SEAT_COUNT_UPDATED so shift cards update availability ──
        socketio.emit('SEAT_COUNT_UPDATED', {
            'shiftId':    shift_id,
            'date':       travel_date
        })

        return jsonify({
            "status": "ok",
            "bookingId": booking_id,
            "shiftId": shift_id,
            "travelDate": travel_date,
            "seats": released_seats
        }), 200

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


@app.route('/api/sync', methods=['POST'])
@require_auth()
def sync_table():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    role = g.current_user['role']
    conn = None
    cursor = None
    transaction_started = False

    try:
        req_data = request.get_json() or {}
        key = req_data.get('key')  # e.g. 'utcl_users'
        data_list = req_data.get('data', [])  # array of records
        generated_passwords = {}
        
        # Map frontend key to table name
        table_mapping = {
            'utcl_users': 'users',
            'utcl_buses': 'buses',
            'utcl_shifts': 'shifts',
            'utcl_driver_shifts': 'driver_shifts',
            'utcl_maintenance': 'maintenance',
            'utcl_tracking': 'tracking',
            'utcl_notifications': 'notifications',
            'utcl_bookings': 'bookings',
            'utcl_tickets': 'tickets',
            'utcl_cancelled_shifts': 'cancelled_shifts'
        }
        
        table_name = table_mapping.get(key)
        if not table_name:
            return jsonify({"status": "error", "message": f"Unknown synchronization key: {key}"}), 400
            
        # Role-based authorization checks
        if table_name in ('users', 'buses', 'shifts', 'cancelled_shifts'):
            if role != 'ADMIN':
                return jsonify({'error': 'Forbidden'}), 403
        elif table_name == 'maintenance':
            if role not in ('DRIVER', 'ADMIN'):
                return jsonify({'error': 'Forbidden'}), 403
        elif table_name in ('driver_shifts', 'tracking'):
            if role not in ('DRIVER', 'ADMIN'):
                return jsonify({'error': 'Forbidden'}), 403
        elif table_name in ('bookings', 'tickets', 'notifications'):
            pass
        else:
            return jsonify({'error': 'Forbidden'}), 403
            
        # Perform transactional sync: delete all from table, and bulk insert
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        conn.autocommit = False
        transaction_started = True
        cursor = conn.cursor()
        
        # User validation check: query user record to fetch internal user id from psNumber
        cursor.execute("SELECT id FROM users WHERE psNumber = %s", (g.current_user['psNumber'],))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Forbidden'}), 403
        driver_id = row[0]
        
        admin_plant = g.current_user.get('plant')
        if table_name == 'users':
            if admin_plant is not None:
                for u in data_list:
                    if u.get('role') != 'DRIVER':
                        if u.get('plant') != admin_plant:
                            cursor.close()
                            conn.close()
                            return jsonify({'error': 'Forbidden: plant mismatch'}), 403
                    if u.get('role') not in ('EMPLOYEE', 'DRIVER'):
                        cursor.close()
                        conn.close()
                        return jsonify({'error': 'Forbidden: role assignment not allowed'}), 403
        
        # Driver maintenance sync validation
        # Drivers can ONLY set records to PENDING_CONFIRMATION.
        # All other records in the payload are silently ignored (handles stale local state).
        if table_name == 'maintenance' and role == 'DRIVER':
            MAX_DRIVER_SYNC_RECORDS = 50
            if len(data_list) > MAX_DRIVER_SYNC_RECORDS:
                cursor.close()
                conn.close()
                return jsonify({'error': 'Payload size limit exceeded'}), 400

            try:
                today_str = datetime.date.today().isoformat()
                cursor.execute("""
                    SELECT DISTINCT s.busId 
                    FROM driver_shifts ds 
                    JOIN shifts s ON ds.shiftId = s.id 
                    WHERE ds.driverId = %s AND ds.date >= %s
                """, (driver_id, today_str))
                assigned_buses = {r[0] for r in cursor.fetchall()}

                for m in data_list:
                    mid = m.get('id')
                    if not mid and mid != 0:
                        cursor.close()
                        conn.close()
                        return jsonify({'error': 'Bad Request. Missing or invalid ID.'}), 400

                    payload_status = m.get('status')

                    # Only validate records the driver is trying to confirm.
                    # All other statuses (SCHEDULED, COMPLETED, etc.) are ignored — they
                    # are present in the payload due to client sending the full array but
                    # must not be written back to DB (prevents stale-cache overwrites).
                    if payload_status != 'PENDING_CONFIRMATION':
                        continue

                    cursor.execute("SELECT busId, status FROM maintenance WHERE id = %s", (mid,))
                    db_row = cursor.fetchone()
                    if not db_row:
                        cursor.close()
                        conn.close()
                        return jsonify({'error': 'Forbidden. Record not found.'}), 403

                    db_busId, db_status = db_row

                    # Already processed — skip silently (idempotent)
                    if db_status in ('PENDING_CONFIRMATION', 'COMPLETED'):
                        continue

                    # Authorization: driver must be assigned to this bus today
                    if db_busId not in assigned_buses:
                        cursor.close()
                        conn.close()
                        return jsonify({'error': 'Forbidden. Driver not assigned to this bus.'}), 403

                    # Valid transition: SCHEDULED or OVERDUE -> PENDING_CONFIRMATION only
                    if db_status not in ('SCHEDULED', 'OVERDUE'):
                        cursor.close()
                        conn.close()
                        return jsonify({'error': f'Forbidden. Invalid status transition from {db_status}.'}), 403

            except Exception as e:
                print(f"[Sync Error] Driver maintenance validation failed: {e}")
                cursor.close()
                conn.close()
                return jsonify({'error': 'Internal server error during validation.'}), 500
        
        # Fetch existing passwords to avoid wiping them out on user sync
        existing_passwords = {}
        existing_ps_numbers = set()
        if table_name == 'users':
            try:
                cursor.execute("SELECT id, password, psNumber FROM users")
                for row in cursor.fetchall():
                    if row[0]:
                        existing_passwords[row[0]] = row[1]
                    if row[2]:
                        existing_ps_numbers.add(row[2].strip().upper())
            except Exception as e:
                print(f"[WS Warning] Failed to query existing passwords: {e}")

        # Fetch existing notification IDs to identify new notifications on synchronization
        existing_notification_ids = set()
        if table_name == 'notifications':
            try:
                cursor.execute("SELECT id FROM notifications")
                existing_notification_ids = {row[0] for row in cursor.fetchall()}
            except Exception as e:
                print(f"[WS Warning] Failed to query existing notifications: {e}")
        
        # Fetch existing shifts to identify which shift got modified
        existing_shifts = {}
        if table_name == 'shifts':
            try:
                cursor.execute("SELECT id, stops FROM shifts")
                existing_shifts = {row[0]: row[1] for row in cursor.fetchall()}
            except Exception as e:
                print(f"[WS Warning] Failed to query existing shifts: {e}")
        
        # 1. Truncate table (except for transaction/dynamic tables)

        if table_name not in ('bookings', 'tickets', 'notifications', 'tracking'):
            if not (table_name == 'maintenance' and role == 'DRIVER'):
                if not (table_name == 'users' and admin_plant is not None):
                    cursor.execute(f"DELETE FROM {table_name}")
        
        # 2. Insert/Upsert rows
        if data_list:
            if table_name == 'users':
                if admin_plant is None:
                    stmt = "INSERT INTO users (id, name, psNumber, password, role, isActive, email, phone, plant) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                else:
                    stmt = """INSERT INTO users (id, name, psNumber, password, role, isActive, email, phone, plant)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                              ON DUPLICATE KEY UPDATE
                                  name = VALUES(name),
                                  isActive = VALUES(isActive),
                                  email = VALUES(email),
                                  phone = VALUES(phone),
                                  plant = VALUES(plant)"""
                rows = []
                for u in data_list:
                    uid = u.get('id')
                    pwd = u.get('password')
                    
                    # If password is empty/None/missing, merge with existing password
                    if not pwd or pwd == "":
                        pwd = existing_passwords.get(uid)
                    
                    # If password is missing (brand-new user synced without a password),
                    # generate a random secure 8-character temporary password server-side.
                    if not pwd or pwd == "":
                        import secrets, string
                        alphabet = string.ascii_letters + string.digits
                        temp_password = ''.join(secrets.choice(alphabet) for _ in range(8))
                        
                        generated_passwords[u.get('psNumber', uid)] = temp_password
                        pwd = bcrypt.hashpw(temp_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                        print(f"[Security] New user synced without password — generated 8-char temporary password for PS Number: {u.get('psNumber')}")
                    # If it is a plain text password (doesn't start with bcrypt header), hash it!
                    elif not pwd.startswith('$2b$') and not pwd.startswith('$2a$'):
                        pwd = bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                        
                    ps_num = u.get('psNumber', '')
                    if ps_num:
                        ps_num = ps_num[:10]
                    rows.append((uid, u.get('name'), ps_num, pwd, u.get('role'), bool(u.get('isActive')), u.get('email'), u.get('phone'), u.get('plant')))
                cursor.executemany(stmt, rows)
                
            elif table_name == 'buses':
                stmt = "INSERT INTO buses (id, identifier, isActive) VALUES (%s, %s, %s)"
                rows = [(b.get('id'), b.get('identifier'), bool(b.get('isActive'))) for b in data_list]
                cursor.executemany(stmt, rows)
                
            elif table_name == 'shifts':
                stmt = "INSERT INTO shifts (id, busId, direction, departureTime, isActive, stops) VALUES (%s, %s, %s, %s, %s, %s)"
                rows = [(s.get('id'), s.get('busId'), s.get('direction'), s.get('departureTime'), bool(s.get('isActive')), json.dumps(s.get('stops'))) for s in data_list]
                cursor.executemany(stmt, rows)
                
            elif table_name == 'driver_shifts':
                stmt = "INSERT INTO driver_shifts (id, driverId, shiftId, date) VALUES (%s, %s, %s, %s)"
                rows = [(ds.get('id'), ds.get('driverId'), ds.get('shiftId'), ds.get('date')) for ds in data_list]
                cursor.executemany(stmt, rows)
                
            elif table_name == 'maintenance':
                if role == 'DRIVER':
                    # Only update records the driver explicitly set to PENDING_CONFIRMATION.
                    # Use WHERE status IN ('SCHEDULED','OVERDUE') as a DB-level safety guard
                    # so that even if validation is bypassed, completed records are never overwritten.
                    for m in data_list:
                        if m.get('status') == 'PENDING_CONFIRMATION':
                            cursor.execute(
                                "UPDATE maintenance SET status = 'PENDING_CONFIRMATION' "
                                "WHERE id = %s AND status IN ('SCHEDULED', 'OVERDUE')",
                                (m.get('id'),)
                            )
                else:
                    stmt = "INSERT INTO maintenance (id, busId, scheduledDate, description, status, actualCompletionDate) VALUES (%s, %s, %s, %s, %s, %s)"
                    rows = [(m.get('id'), m.get('busId'), m.get('scheduledDate'), m.get('description'), m.get('status'), m.get('actualCompletionDate')) for m in data_list]
                    cursor.executemany(stmt, rows)
                    
            elif table_name == 'cancelled_shifts':
                stmt = "INSERT INTO cancelled_shifts (id, shiftId, date, reason, cancelledAt) VALUES (%s, %s, %s, %s, %s)"
                rows = [(cs.get('id'), cs.get('shiftId'), cs.get('date'), cs.get('reason'), cs.get('cancelledAt')) for cs in data_list]
                cursor.executemany(stmt, rows)
                
            elif table_name == 'tracking':
                stmt = """INSERT INTO tracking (busId, operationalStatus, currentShiftId, currentStopIndex, lastUpdated) 
                          VALUES (%s, %s, %s, %s, %s)
                          ON DUPLICATE KEY UPDATE 
                          operationalStatus=VALUES(operationalStatus), currentShiftId=VALUES(currentShiftId), 
                          currentStopIndex=VALUES(currentStopIndex), lastUpdated=VALUES(lastUpdated)"""
                rows = [(t.get('busId'), t.get('operationalStatus'), t.get('currentShiftId'), t.get('currentStopIndex'), t.get('lastUpdated')) for t in data_list]
                cursor.executemany(stmt, rows)
                
            elif table_name == 'notifications':
                stmt = """INSERT INTO notifications (id, recipientUserId, message, isRead, createdAt) 
                          VALUES (%s, %s, %s, %s, %s)
                          ON DUPLICATE KEY UPDATE
                          recipientUserId=VALUES(recipientUserId), message=VALUES(message), 
                          isRead=VALUES(isRead), createdAt=VALUES(createdAt)"""
                rows = [(n.get('id'), n.get('recipientUserId'), n.get('message'), bool(n.get('isRead')), n.get('createdAt')) for n in data_list]
                cursor.executemany(stmt, rows)
                
            elif table_name == 'bookings':
                filtered_data = [bk for bk in data_list if bk and not str(bk.get('id', '')).startswith('ws_') and bk.get('psNumber') != 'PHANTOM']
                if filtered_data:
                    stmt = """INSERT INTO bookings (id, shiftId, psNumber, employeeName, seatNumber, boardingStopIndex, dropStopIndex, fareAmount, status, travelDate, bookedAt) 
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                              ON DUPLICATE KEY UPDATE
                              shiftId=VALUES(shiftId), psNumber=VALUES(psNumber), employeeName=VALUES(employeeName),
                              seatNumber=VALUES(seatNumber), boardingStopIndex=VALUES(boardingStopIndex), 
                              dropStopIndex=VALUES(dropStopIndex), fareAmount=VALUES(fareAmount), 
                              status=VALUES(status), travelDate=VALUES(travelDate), bookedAt=VALUES(bookedAt)"""
                    rows = [(
                        bk.get('id'), bk.get('shiftId'), bk.get('psNumber'), bk.get('employeeName'),
                        str(bk.get('seatNumber')), int(bk.get('boardingStopIndex')), int(bk.get('dropStopIndex')),
                        int(bk.get('fareAmount', 20)), bk.get('status'), bk.get('travelDate'), bk.get('bookedAt')
                    ) for bk in filtered_data]
                    cursor.executemany(stmt, rows)
                
            elif table_name == 'tickets':
                filtered_data = [tk for tk in data_list if tk and not str(tk.get('bookingId', '')).startswith('ws_') and tk.get('psNumber') != 'PHANTOM']
                if filtered_data:
                    stmt = """INSERT INTO tickets (id, bookingId, ticketNumber, employeeName, psNumber, shiftCode, seatNumber, boardingStop, dropStop, fare, departureTime, travelDate, generatedAt) 
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                              ON DUPLICATE KEY UPDATE
                              bookingId=VALUES(bookingId), ticketNumber=VALUES(ticketNumber), employeeName=VALUES(employeeName),
                              psNumber=VALUES(psNumber), shiftCode=VALUES(shiftCode), seatNumber=VALUES(seatNumber),
                              boardingStop=VALUES(boardingStop), dropStop=VALUES(dropStop), fare=VALUES(fare),
                              departureTime=VALUES(departureTime), travelDate=VALUES(travelDate), generatedAt=VALUES(generatedAt)"""
                    rows = [(
                        tk.get('id'), tk.get('bookingId'), tk.get('ticketNumber'), tk.get('employeeName'), tk.get('psNumber'),
                        tk.get('shiftCode'), str(tk.get('seatNumber')), tk.get('boardingStop'), tk.get('dropStop'),
                        int(tk.get('fare', 20)), tk.get('departureTime'), tk.get('travelDate'), tk.get('generatedAt')
                    ) for tk in filtered_data]
                    cursor.executemany(stmt, rows)
                
        conn.commit()
        invalidate_data_cache()
        transaction_started = False
        cursor.close()
        conn.close()

        # Emit Socket.IO events for real-time synchronization
        if table_name == 'notifications':
            for n in data_list:
                nid = n.get('id')
                if nid not in existing_notification_ids:
                    recipient = n.get('recipientUserId')
                    payload = {
                        'id': nid,
                        'recipientUserId': recipient,
                        'message': n.get('message'),
                        'isRead': bool(n.get('isRead')),
                        'createdAt': n.get('createdAt')
                    }
                    if recipient == 'all_employees':
                        socketio.emit('NEW_NOTIFICATION', payload, room='all_employees')
                    elif recipient == 'all_drivers':
                        socketio.emit('NEW_NOTIFICATION', payload, room='all_drivers')
                    elif recipient:
                        socketio.emit('NEW_NOTIFICATION', payload, room=recipient)
                    else:
                        socketio.emit('NEW_NOTIFICATION', payload)

        elif table_name == 'users':
            socketio.emit('USER_UPDATED', {'table': 'users'})

        elif table_name in ['bookings', 'tickets']:
            socketio.emit('BOOKING_UPDATED', {'table': table_name})

        elif table_name == 'tracking':
            socketio.emit('TRACKING_UPDATED', {'table': 'tracking'})

        elif table_name in ['buses', 'shifts', 'driver_shifts', 'cancelled_shifts']:
            socketio.emit('SCHEDULE_UPDATED', {'table': table_name})
            if table_name == 'shifts':
                modified_shift_id = None
                for s in data_list:
                    sid = s.get('id')
                    if sid in existing_shifts:
                        # Compare stops database representation with local changes
                        try:
                            db_stops = json.loads(existing_shifts[sid]) if isinstance(existing_shifts[sid], str) else existing_shifts[sid]
                        except:
                            db_stops = existing_shifts[sid]
                        new_stops = s.get('stops')
                        if db_stops != new_stops:
                            modified_shift_id = sid
                            break
                # Fallback to the first shift if comparison wasn't conclusive
                if not modified_shift_id and data_list:
                    modified_shift_id = data_list[0].get('id')
                socketio.emit('SHIFT_SCHEDULE_UPDATED', {
                    'table': table_name,
                    'shiftId': modified_shift_id
                })

        elif table_name == 'maintenance':
            socketio.emit('MAINTENANCE_UPDATED', {'table': 'maintenance'})

        response_payload = {
            "status": "success",
            "message": f"Successfully synchronized {len(data_list)} rows in {table_name} table."
        }
        if table_name == 'users' and generated_passwords:
            response_payload["tempPasswords"] = generated_passwords
        return jsonify(response_payload)
    except Exception as e:
        import traceback
        print(traceback.format_exc(), flush=True)
        if conn:
            try:
                if transaction_started:
                    conn.rollback()
            except Exception:
                pass
            try:
                if cursor:
                    cursor.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
        return jsonify({"status": "error", "message": str(e)}), 500

import uuid

@app.route('/api/driver/attendance/status', methods=['GET'])
@require_auth()
def get_attendance_status():
    driver_id = request.args.get('driverId')
    shift_id = request.args.get('shiftId')
    date = request.args.get('date')
    if not driver_id or not shift_id or not date:
        return jsonify({"status": "error", "message": "Missing query parameters"}), 400
        
    if g.current_user['role'] != 'ADMIN' and g.current_user['psNumber'].strip().upper() != driver_id.strip().upper():
        return jsonify({"status": "error", "message": "Forbidden"}), 403
        
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM driver_attendance WHERE driverId=%s AND shiftId=%s AND date=%s",
            (driver_id, shift_id, date)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            return jsonify({"status": "success", "attendance": row})
        else:
            return jsonify({"status": "success", "attendance": None})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------------------------------------------------------------------------
# Attendance photo compressor
# Drivers upload raw camera images (up to 15 MB). The admin only needs to
# verify the photo and read the GPS geotag — not full resolution.
# This helper:
#   - Caps resolution at 1280×960 (clear enough for verification)
#   - Preserves the full EXIF block (GPS coordinates stay intact)
#   - Re-saves as JPEG at quality=72  →  ~150–350 KB regardless of input size
#   - Never writes the raw file to disk; only the compressed version is saved
# ---------------------------------------------------------------------------
def compress_attendance_photo(file_storage, dest_path: str) -> int:
    """
    Read an uploaded image from a Werkzeug FileStorage, compress it while
    preserving EXIF/GPS metadata, and write the result to dest_path.

    Returns the compressed file size in bytes.
    Raises on invalid image content.
    """
    import gc
    
    # Explicitly enforce directory check loop first
    os.makedirs('/app/uploads', exist_ok=True)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    # Read the image stream into memory
    raw_bytes = file_storage.read()
    img = Image.open(io.BytesIO(raw_bytes))

    # Preserve original EXIF block (contains GPS geotag)
    exif_bytes = img.info.get('exif', b'')

    # Convert to RGB so we can always JPEG-save (handles RGBA/P/etc.)
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    # Downscale excessively large dimensions to a maximum width/height of 1080 pixels
    # using high-quality downsampling (Image.Resampling.LANCZOS)
    if img.width > 1080 or img.height > 1080:
        if hasattr(Image, 'Resampling'):
            resample_filter = Image.Resampling.LANCZOS
        else:
            resample_filter = Image.LANCZOS
        img.thumbnail((1080, 1080), resample_filter)

    # Save compressed JPEG at quality=75 and optimize=True
    save_kwargs = {'format': 'JPEG', 'quality': 75, 'optimize': True}
    if exif_bytes:
        save_kwargs['exif'] = exif_bytes

    img.save(dest_path, **save_kwargs)
    
    # Discard the raw stream from memory instantly
    img.close()
    del raw_bytes
    gc.collect()

    return os.path.getsize(dest_path)

@app.route('/api/driver/attendance/submit-departure', methods=['POST'])
@require_auth()
def submit_departure_attendance():
    driver_id = request.form.get('driverId')
    bus_id = request.form.get('busId')
    shift_id = request.form.get('shiftId')
    date = request.form.get('date')
    
    if not driver_id:
        return jsonify({"status": "error", "message": "Missing driverId"}), 400
        
    if g.current_user['role'] != 'ADMIN' and g.current_user['psNumber'].strip().upper() != driver_id.strip().upper():
        return jsonify({"status": "error", "message": "Forbidden"}), 403
        
    if 'departure_photo' not in request.files:
        return jsonify({"status": "error", "message": "No photo file uploaded"}), 400
        
    file = request.files['departure_photo']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No file selected"}), 400
        
    if not allowed_file(file.filename):
        return jsonify({"status": "error", "message": "Invalid file extension"}), 400
        
    try:
        file.seek(0)
        img = Image.open(io.BytesIO(file.read()))
        img.verify()
        file.seek(0)
    except Exception:
        return jsonify({"status": "error", "message": "Invalid image content"}), 400
        
    try:
        # Save compressed JPEG (GPS EXIF preserved, ~150-350 KB regardless of input)
        filename = secure_filename(f"dep_{int(time.time())}_{driver_id}.jpg")
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.seek(0)
        compressed_size = compress_attendance_photo(file, file_path)
        print(f"[Photo] Departure photo compressed: {compressed_size // 1024} KB saved to {filename}")

        photo_url = f"/uploads/{filename}"
        dep_time = datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        record_id = f"att_{uuid.uuid4().hex[:8]}"
        
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor()
        
        # Check if record already exists
        cursor.execute(
            "SELECT id FROM driver_attendance WHERE driverId=%s AND shiftId=%s AND date=%s",
            (driver_id, shift_id, date)
        )
        exists = cursor.fetchone()
        
        if exists:
            # Update existing
            cursor.execute(
                "UPDATE driver_attendance SET departurePhotoUrl=%s, departureTime=%s, status='InTransit' WHERE id=%s",
                (photo_url, dep_time, exists[0])
            )
        else:
            # Insert new
            cursor.execute(
                "INSERT INTO driver_attendance (id, driverId, busId, shiftId, date, departurePhotoUrl, departureTime, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'InTransit')",
                (record_id, driver_id, bus_id, shift_id, date, photo_url, dep_time)
            )
            
        conn.commit()
        cursor.close()
        conn.close()
        socketio.emit('ATTENDANCE_UPDATED', {
            'action': 'SUBMIT_DEPARTURE',
            'driverId': driver_id,
            'shiftId': shift_id,
            'date': date
        })
        return jsonify({"status": "success", "message": "Departure attendance submitted successfully", "departureTime": dep_time, "photoUrl": photo_url})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/driver/attendance/submit-arrival', methods=['POST'])
@require_auth()
def submit_arrival_attendance():
    driver_id = request.form.get('driverId')
    shift_id = request.form.get('shiftId')
    date = request.form.get('date')
    
    if not driver_id:
        return jsonify({"status": "error", "message": "Missing driverId"}), 400
        
    if g.current_user['role'] != 'ADMIN' and g.current_user['psNumber'].strip().upper() != driver_id.strip().upper():
        return jsonify({"status": "error", "message": "Forbidden"}), 403
        
    if 'arrival_photo' not in request.files:
        return jsonify({"status": "error", "message": "No photo file uploaded"}), 400
        
    file = request.files['arrival_photo']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No file selected"}), 400
        
    if not allowed_file(file.filename):
        return jsonify({"status": "error", "message": "Invalid file extension"}), 400
        
    try:
        file.seek(0)
        img = Image.open(io.BytesIO(file.read()))
        img.verify()
        file.seek(0)
    except Exception:
        return jsonify({"status": "error", "message": "Invalid image content"}), 400
        
    try:
        # Save compressed JPEG (GPS EXIF preserved, ~150-350 KB regardless of input)
        filename = secure_filename(f"arr_{int(time.time())}_{driver_id}.jpg")
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.seek(0)
        compressed_size = compress_attendance_photo(file, file_path)
        print(f"[Photo] Arrival photo compressed: {compressed_size // 1024} KB saved to {filename}")

        photo_url = f"/uploads/{filename}"
        arr_time = datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor()
        
        # Check if record exists
        cursor.execute(
            "SELECT id FROM driver_attendance WHERE driverId=%s AND shiftId=%s AND date=%s",
            (driver_id, shift_id, date)
        )
        exists = cursor.fetchone()
        
        if not exists:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Departure attendance must be marked before arrival."}), 400
            
        cursor.execute(
            "UPDATE driver_attendance SET arrivalPhotoUrl=%s, arrivalTime=%s, status='Pending' WHERE id=%s",
            (photo_url, arr_time, exists[0])
        )
        conn.commit()
        cursor.close()
        conn.close()
        socketio.emit('ATTENDANCE_UPDATED', {
            'action': 'SUBMIT_ARRIVAL',
            'driverId': driver_id,
            'shiftId': shift_id,
            'date': date
        })
        return jsonify({"status": "success", "message": "Arrival attendance submitted successfully", "arrivalTime": arr_time, "photoUrl": photo_url})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/attendance/pending', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def get_pending_attendance():
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        # Fetch pending attendance records and join with users to get the driver name
        cursor.execute(
            "SELECT a.*, u.name AS driverName FROM driver_attendance a "
            "LEFT JOIN users u ON a.driverId = u.psNumber "
            "WHERE a.status = 'Pending'"
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "attendance": rows})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/attendance/<id>', methods=['PATCH'])
@require_auth(allowed_roles=['ADMIN'])
def patch_attendance_status(id):
    try:
        data = request.get_json()
        if not data or 'status' not in data:
            return jsonify({"status": "error", "message": "Missing status in request body"}), 400
            
        status = data['status']
        if status not in ['Approved', 'Rejected']:
            return jsonify({"status": "error", "message": "Invalid status value. Must be Approved or Rejected"}), 400
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor()
        
        # Query details before update to target the correct driver's socket room
        cursor.execute("SELECT driverId, shiftId, date FROM driver_attendance WHERE id=%s", (id,))
        rec = cursor.fetchone()
        
        cursor.execute(
            "UPDATE driver_attendance SET status=%s WHERE id=%s",
            (status, id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        if rec:
            driver_id, shift_id, travel_date = rec
            socketio.emit('ATTENDANCE_STATUS_CHANGED', {
                'id': id,
                'driverId': driver_id,
                'shiftId': shift_id,
                'date': travel_date,
                'status': status
            }, to=driver_id)
            
            socketio.emit('ATTENDANCE_UPDATED', {
                'action': 'REVIEW',
                'id': id,
                'driverId': driver_id,
                'shiftId': shift_id,
                'date': travel_date,
                'status': status
            })
            
        return jsonify({"status": "success", "message": f"Attendance record successfully {status.lower()}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/drivers/search', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def search_drivers():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
    
    try:
        query = request.args.get('query', '').strip()
        if not query:
            return jsonify([])
        
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        sql = "SELECT psNumber, name FROM users WHERE role = 'DRIVER' AND psNumber LIKE %s LIMIT 10"
        cursor.execute(sql, (query + '%',))
        rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/attendance/history', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def get_attendance_history():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        driver_id = request.args.get('driverId', '').strip()
        start_date = request.args.get('startDate', '').strip()
        end_date = request.args.get('endDate', '').strip()
        
        try:
            page = int(request.args.get('page', 1))
            if page < 1: page = 1
        except ValueError:
            page = 1
            
        try:
            limit = int(request.args.get('limit', 10))
            if limit < 1: limit = 10
        except ValueError:
            limit = 10
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # Base query parts
        query_parts = ["a.status IN ('Approved', 'Rejected')"]
        query_params = []
        
        if driver_id:
            query_parts.append("a.driverId = %s")
            query_params.append(driver_id)
            
        if start_date:
            query_parts.append("a.date >= %s")
            query_params.append(start_date)
            
        if end_date:
            query_parts.append("a.date <= %s")
            query_params.append(end_date)
            
        where_clause = " AND ".join(query_parts)
        
        # Get count
        count_sql = f"SELECT COUNT(*) as total FROM driver_attendance a WHERE {where_clause}"
        cursor.execute(count_sql, tuple(query_params))
        total_records = cursor.fetchone()['total']
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Fetch records
        records_sql = f"""
            SELECT a.*, u.name AS driverName 
            FROM driver_attendance a 
            LEFT JOIN users u ON a.driverId = u.psNumber 
            WHERE {where_clause}
            ORDER BY a.date DESC, a.departureTime DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(records_sql, tuple(query_params) + (limit, offset))
        rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        total_pages = (total_records + limit - 1) // limit
        
        return jsonify({
            "status": "success",
            "attendance": rows,
            "pagination": {
                "page": page,
                "limit": limit,
                "totalRecords": total_records,
                "totalPages": total_pages
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/attendance/record/<id>', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def get_attendance_record(id):
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT a.*, u.name AS driverName FROM driver_attendance a "
            "LEFT JOIN users u ON a.driverId = u.psNumber "
            "WHERE a.id = %s",
            (id,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            return jsonify({"status": "success", "attendance": row})
            
        return jsonify({"status": "error", "message": "Record not found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/attendance/history/export', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def export_driver_attendance_excel():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        driver_id = request.args.get('driverId', '').strip()
        start_date = request.args.get('startDate', '').strip()
        end_date = request.args.get('endDate', '').strip()
        
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # Base query parts
        query_parts = ["a.status IN ('Approved', 'Rejected')"]
        query_params = []
        
        if driver_id:
            query_parts.append("a.driverId = %s")
            query_params.append(driver_id)
            
        if start_date:
            query_parts.append("a.date >= %s")
            query_params.append(start_date)
            
        if end_date:
            query_parts.append("a.date <= %s")
            query_params.append(end_date)
            
        where_clause = " AND ".join(query_parts)
        
        records_sql = f"""
            SELECT a.*, u.name AS driverName 
            FROM driver_attendance a 
            LEFT JOIN users u ON a.driverId = u.psNumber 
            WHERE {where_clause}
            ORDER BY a.date DESC, a.departureTime DESC
        """
        cursor.execute(records_sql, tuple(query_params))
        rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Create Workbook and write data
        wb = Workbook()
        ws = wb.active
        ws.title = "Driver Attendance History"
        
        # Headers
        headers = ['Date', 'Driver PS Number', 'Driver Name', 'Bus ID', 'Shift', 'Departure Time', 'Arrival Time', 'Status']
        ws.append(headers)
        
        for r in rows:
            bus_label = 'Bus 1' if r['busId'] == 'b1' else ('Bus 2' if r['busId'] == 'b2' else r['busId'])
            shift_label = get_shift_label(r['shiftId'])
            
            row_data = [
                r['date'],
                r['driverId'],
                r['driverName'] or '',
                bus_label,
                shift_label,
                r['departureTime'] or '--',
                r['arrivalTime'] or '--',
                r['status']
            ]
            ws.append(row_data)
            
        # Set column widths
        widths = {'A': 14, 'B': 20, 'C': 25, 'D': 12, 'E': 20, 'F': 25, 'G': 25, 'H': 15}
        for col_letter, width in widths.items():
            ws.column_dimensions[col_letter].width = width
            
        # Write to BytesIO stream
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        # Return as binary response stream
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = 'attachment; filename="Driver_Attendance_History.xlsx"'
        return response
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

        return jsonify({"status": "error", "message": str(e)}), 500

# -------------------------------------------------------------
# Payroll Deduction Endpoints (Option 3 — Salary Deduction)
# -------------------------------------------------------------

@app.route('/api/payroll/summary', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def get_payroll_summary():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
    
    month = request.args.get('month', '').strip()
    plant = request.args.get('plant', 'All').strip()
    if not month:
        return jsonify({"status": "error", "message": "Month parameter is required."}), 400
        
    admin_plant = g.current_user.get('plant')
    if admin_plant is not None:
        plant = admin_plant
        
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # Check if this month's period already exists
        cursor.execute("SELECT id, status FROM payroll_periods WHERE periodMonth = %s", (month,))
        period_row = cursor.fetchone()
        
        # Determine lock status per plant
        plants_to_query = [plant] if plant in ['Awalpur', 'Manikgarh'] else ['Awalpur', 'Manikgarh']
        
        plant_locks = {}
        for pl in ['Awalpur', 'Manikgarh']:
            locked = False
            if period_row:
                if period_row['status'] == 'PROCESSED':
                    locked = True
                else:
                    cursor.execute(
                        "SELECT 1 FROM payroll_plant_locks WHERE periodId = %s AND plant = %s",
                        (period_row['id'], pl)
                    )
                    locked = (cursor.fetchone() is not None)
            plant_locks[pl] = locked
            
        all_employees = {}
        for pl in plants_to_query:
            if plant_locks.get(pl, False):
                # Stored snapshot from fare_deductions
                cursor.execute(
                    """
                    SELECT fd.psNumber, fd.employeeName, fd.role, fd.totalRides, fd.totalAmount, 'PROCESSED' as status 
                    FROM fare_deductions fd
                    LEFT JOIN users u ON fd.psNumber = u.psNumber
                    WHERE fd.periodMonth = %s AND u.plant = %s
                    """,
                    (month, pl)
                )
                rows = cursor.fetchall()
            else:
                # Dynamic live calculation
                sql = """
                    SELECT 
                        b.psNumber,
                        COALESCE(MAX(u.name), MAX(b.employeeName)) as employeeName,
                        COALESCE(MAX(u.role), 'EMPLOYEE') as role,
                        COUNT(b.id) as totalRides,
                        SUM(b.fareAmount) as totalAmount,
                        'PENDING' as status
                    FROM bookings b
                    LEFT JOIN users u ON b.psNumber = u.psNumber
                    WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
                      AND u.plant = %s
                    GROUP BY b.psNumber
                """
                cursor.execute(sql, (month + '%', pl))
                rows = cursor.fetchall()
                
            for r in rows:
                ps = r['psNumber']
                r['totalAmount'] = float(r['totalAmount']) if r['totalAmount'] is not None else 0.0
                r['totalRides'] = int(r['totalRides'])
                if ps in all_employees:
                    all_employees[ps]['totalRides'] += r['totalRides']
                    all_employees[ps]['totalAmount'] += r['totalAmount']
                else:
                    all_employees[ps] = r
                    
        employees_list = list(all_employees.values())
        total_rides = sum(e['totalRides'] for e in employees_list)
        total_amount = sum(e['totalAmount'] for e in employees_list)
        employee_count = len(employees_list)
        
        cursor.close()
        conn.close()
        
        all_locked = all(plant_locks.get(pl, False) for pl in plants_to_query)
        ret_status = "PENDING"
        if all_locked:
            ret_status = "PROCESSED"
        elif period_row:
            ret_status = "GENERATED_PENDING"
            
        return jsonify({
            "status": ret_status,
            "month": month,
            "employees": employees_list,
            "totals": {
                "totalRides": total_rides,
                "totalAmount": total_amount,
                "employeeCount": employee_count
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/payroll/generate', methods=['POST'])
@require_auth(allowed_roles=['ADMIN'])
def generate_payroll_period():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        data = request.get_json() or {}
        month = data.get('month', '').strip()
        admin_ps = g.current_user['psNumber']
        
        if not month:
            return jsonify({"status": "error", "message": "Month is required."}), 400
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        conn.start_transaction()
        cursor = conn.cursor(dictionary=True)
        
        # Check if period already exists
        cursor.execute("SELECT * FROM payroll_periods WHERE periodMonth = %s", (month,))
        existing = cursor.fetchone()
        if existing:
            conn.rollback()
            cursor.close()
            conn.close()
            return jsonify({
                "status": "ok",
                "message": "Payroll period already generated.",
                "periodId": existing['id'],
                "status": existing['status']
            }), 200
            
        # Get live data for insert
        sql = """
            SELECT 
                b.psNumber,
                COALESCE(MAX(u.name), MAX(b.employeeName)) as employeeName,
                COALESCE(MAX(u.role), 'EMPLOYEE') as role,
                COUNT(b.id) as totalRides,
                SUM(b.fareAmount) as totalAmount
            FROM bookings b
            LEFT JOIN users u ON b.psNumber = u.psNumber
            WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
            GROUP BY b.psNumber
        """
        cursor.execute(sql, (month + '%',))
        rows = cursor.fetchall()
        
        for r in rows:
            r['totalAmount'] = float(r['totalAmount']) if r['totalAmount'] is not None else 0.0
            r['totalRides'] = int(r['totalRides'])
            
        total_rides = sum(r['totalRides'] for r in rows)
        total_amount = sum(r['totalAmount'] for r in rows)
        employee_count = len(rows)
        
        period_id = f"payroll_{month.replace('-', '_')}"
        generated_at = datetime.datetime.now().isoformat()
        
        # Insert payroll_period
        cursor.execute(
            """INSERT INTO payroll_periods 
               (id, periodMonth, totalAmount, employeeCount, status, generatedAt, processedAt, processedBy, notes)
               VALUES (%s, %s, %s, %s, 'PENDING', %s, NULL, NULL, NULL)""",
            (period_id, month, total_amount, employee_count, generated_at)
        )
        
        # Insert initial fare_deductions
        for r in rows:
            deduction_id = f"deduct_{period_id}_{r['psNumber']}"
            cursor.execute(
                """INSERT INTO fare_deductions 
                   (id, periodId, periodMonth, psNumber, employeeName, role, totalRides, totalAmount, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')""",
                (deduction_id, period_id, month, r['psNumber'], r['employeeName'], r['role'], r['totalRides'], r['totalAmount'])
            )
            
        conn.commit()
        cursor.close()
        conn.close()
        
        # Broadcast socket event
        socketio.emit('PAYROLL_UPDATED', {
            'action': 'GENERATED',
            'periodId': period_id,
            'month': month
        })
        
        return jsonify({
            "status": "ok",
            "message": "Payroll period generated successfully.",
            "periodId": period_id
        }), 201
        
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/payroll/periods', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def get_payroll_periods():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM payroll_periods ORDER BY periodMonth DESC")
        periods = cursor.fetchall()
        
        admin_plant = g.current_user.get('plant')
        for p in periods:
            p['totalAmount'] = float(p['totalAmount'])
            if admin_plant is not None:
                is_plant_locked = False
                if p['status'] == 'PROCESSED':
                    is_plant_locked = True
                else:
                    cursor.execute(
                        "SELECT 1 FROM payroll_plant_locks WHERE periodId = %s AND plant = %s",
                        (p['id'], admin_plant)
                    )
                    is_plant_locked = (cursor.fetchone() is not None)
                
                if is_plant_locked:
                    cursor.execute(
                        """
                        SELECT SUM(fd.totalAmount) as totalAmount, COUNT(DISTINCT fd.psNumber) as employeeCount
                        FROM fare_deductions fd
                        LEFT JOIN users u ON fd.psNumber = u.psNumber
                        WHERE fd.periodId = %s AND u.plant = %s
                        """,
                        (p['id'], admin_plant)
                    )
                    row = cursor.fetchone()
                    p['totalAmount'] = float(row['totalAmount']) if (row and row['totalAmount'] is not None) else 0.0
                    p['employeeCount'] = int(row['employeeCount']) if (row and row['employeeCount'] is not None) else 0
                else:
                    month = p['periodMonth']
                    sql = """
                        SELECT 
                            SUM(b.fareAmount) as totalAmount,
                            COUNT(DISTINCT b.psNumber) as employeeCount
                        FROM bookings b
                        LEFT JOIN users u ON b.psNumber = u.psNumber
                        WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
                          AND u.plant = %s
                    """
                    cursor.execute(sql, (month + '%', admin_plant))
                    live = cursor.fetchone()
                    p['totalAmount'] = float(live['totalAmount']) if (live and live['totalAmount'] is not None) else 0.0
                    p['employeeCount'] = int(live['employeeCount']) if (live and live['employeeCount'] is not None) else 0
                
                p['status'] = 'PROCESSED' if is_plant_locked else 'PENDING'
            else:
                if p['status'] == 'PENDING':
                    month = p['periodMonth']
                    sql = """
                        SELECT 
                            SUM(b.fareAmount) as totalAmount,
                            COUNT(DISTINCT b.psNumber) as employeeCount
                        FROM bookings b
                        LEFT JOIN users u ON b.psNumber = u.psNumber
                        WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
                    """
                    cursor.execute(sql, (month + '%',))
                    live = cursor.fetchone()
                    if live:
                        p['totalAmount'] = float(live['totalAmount']) if live['totalAmount'] is not None else 0.0
                        p['employeeCount'] = int(live['employeeCount']) if live['employeeCount'] is not None else 0
                        
        cursor.close()
        conn.close()
        return jsonify(periods)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/payroll/period/<period_id>', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def get_payroll_period_detail(period_id):
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM payroll_periods WHERE id = %s", (period_id,))
        period = cursor.fetchone()
        
        if not period:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Period not found."}), 404
            
        period['totalAmount'] = float(period['totalAmount'])
        month = period['periodMonth']
        
        admin_plant = g.current_user.get('plant')
        is_plant_locked = False
        if period['status'] == 'PROCESSED':
            is_plant_locked = True
        elif admin_plant is not None:
            cursor.execute(
                "SELECT 1 FROM payroll_plant_locks WHERE periodId = %s AND plant = %s",
                (period_id, admin_plant)
            )
            is_plant_locked = (cursor.fetchone() is not None)
            
        if admin_plant is not None:
            if is_plant_locked:
                cursor.execute(
                    """
                    SELECT fd.psNumber, fd.employeeName, fd.role, fd.totalRides, fd.totalAmount, fd.status 
                    FROM fare_deductions fd
                    LEFT JOIN users u ON fd.psNumber = u.psNumber
                    WHERE fd.periodId = %s AND u.plant = %s
                    """,
                    (period_id, admin_plant)
                )
                rows = cursor.fetchall()
            else:
                sql = """
                    SELECT 
                        b.psNumber,
                        COALESCE(MAX(u.name), MAX(b.employeeName)) as employeeName,
                        COALESCE(MAX(u.role), 'EMPLOYEE') as role,
                        COUNT(b.id) as totalRides,
                        SUM(b.fareAmount) as totalAmount,
                        'PENDING' as status
                    FROM bookings b
                    LEFT JOIN users u ON b.psNumber = u.psNumber
                    WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
                      AND u.plant = %s
                    GROUP BY b.psNumber
                """
                cursor.execute(sql, (month + '%', admin_plant))
                rows = cursor.fetchall()
                
            for r in rows:
                r['totalAmount'] = float(r['totalAmount']) if r['totalAmount'] is not None else 0.0
                
            total_amount = sum(r['totalAmount'] for r in rows)
            employee_count = len(rows)
            
            period['totalAmount'] = total_amount
            period['employeeCount'] = employee_count
            period['status'] = 'PROCESSED' if is_plant_locked else 'PENDING'
            
        else:
            if period['status'] == 'PROCESSED':
                cursor.execute("SELECT psNumber, employeeName, role, totalRides, totalAmount, status FROM fare_deductions WHERE periodId = %s", (period_id,))
                rows = cursor.fetchall()
                for r in rows:
                    r['totalAmount'] = float(r['totalAmount']) if r['totalAmount'] is not None else 0.0
            else:
                plant_locks = {}
                for pl in ['Awalpur', 'Manikgarh']:
                    cursor.execute(
                        "SELECT 1 FROM payroll_plant_locks WHERE periodId = %s AND plant = %s",
                        (period_id, pl)
                    )
                    plant_locks[pl] = (cursor.fetchone() is not None)
                
                all_employees = {}
                for pl in ['Awalpur', 'Manikgarh']:
                    if plant_locks[pl]:
                        cursor.execute(
                            """
                            SELECT fd.psNumber, fd.employeeName, fd.role, fd.totalRides, fd.totalAmount, 'PROCESSED' as status
                            FROM fare_deductions fd
                            LEFT JOIN users u ON fd.psNumber = u.psNumber
                            WHERE fd.periodId = %s AND u.plant = %s
                            """,
                            (period_id, pl)
                        )
                        p_rows = cursor.fetchall()
                    else:
                        sql = """
                            SELECT 
                                b.psNumber,
                                COALESCE(MAX(u.name), MAX(b.employeeName)) as employeeName,
                                COALESCE(MAX(u.role), 'EMPLOYEE') as role,
                                COUNT(b.id) as totalRides,
                                SUM(b.fareAmount) as totalAmount,
                                'PENDING' as status
                            FROM bookings b
                            LEFT JOIN users u ON b.psNumber = u.psNumber
                            WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
                              AND u.plant = %s
                            GROUP BY b.psNumber
                        """
                        cursor.execute(sql, (month + '%', pl))
                        p_rows = cursor.fetchall()
                        
                    for r in p_rows:
                        ps = r['psNumber']
                        r['totalAmount'] = float(r['totalAmount']) if r['totalAmount'] is not None else 0.0
                        r['totalRides'] = int(r['totalRides'])
                        if ps in all_employees:
                            all_employees[ps]['totalRides'] += r['totalRides']
                            all_employees[ps]['totalAmount'] += r['totalAmount']
                        else:
                            all_employees[ps] = r
                rows = list(all_employees.values())
                
            total_amount = sum(r['totalAmount'] for r in rows)
            employee_count = len(rows)
            period['totalAmount'] = total_amount
            period['employeeCount'] = employee_count
            
        cursor.close()
        conn.close()
        return jsonify({
            "period": period,
            "employees": rows
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/payroll/period/<period_id>/mark-processed', methods=['PATCH'])
@require_auth(allowed_roles=['ADMIN'])
def mark_payroll_period_processed(period_id):
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        data = request.get_json() or {}
        admin_ps = g.current_user['psNumber']
        notes = data.get('notes', '').strip()
        target_plant = data.get('plant', '').strip()
            
        admin_plant = g.current_user.get('plant')
        if admin_plant is not None:
            target_plant = admin_plant
        if not target_plant:
            target_plant = 'All'
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        conn.start_transaction()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM payroll_periods WHERE id = %s FOR UPDATE", (period_id,))
        period = cursor.fetchone()
        
        if not period:
            conn.rollback()
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Period not found."}), 404
            
        month = period['periodMonth']
        processed_at = datetime.datetime.now().isoformat()
        
        if target_plant == 'All':
            if period['status'] == 'PROCESSED':
                conn.rollback()
                cursor.close()
                conn.close()
                return jsonify({"status": "error", "message": "Period is already processed."}), 400
                
            for pl in ['Awalpur', 'Manikgarh']:
                lock_id = f"lock_{period_id}_{pl}"
                cursor.execute(
                    """INSERT INTO payroll_plant_locks (id, periodId, plant)
                       VALUES (%s, %s, %s)
                       ON DUPLICATE KEY UPDATE lockedAt=VALUES(lockedAt)""",
                    (lock_id, period_id, pl)
                )
                
            sql = """
                SELECT 
                    b.psNumber,
                    COALESCE(MAX(u.name), MAX(b.employeeName)) as employeeName,
                    COALESCE(MAX(u.role), 'EMPLOYEE') as role,
                    COUNT(b.id) as totalRides,
                    SUM(b.fareAmount) as totalAmount
                FROM bookings b
                LEFT JOIN users u ON b.psNumber = u.psNumber
                WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
                GROUP BY b.psNumber
            """
            cursor.execute(sql, (month + '%',))
            rows = cursor.fetchall()
            for r in rows:
                r['totalAmount'] = float(r['totalAmount']) if r['totalAmount'] is not None else 0.0
                r['totalRides'] = int(r['totalRides'])
                
            total_amount = sum(r['totalAmount'] for r in rows)
            employee_count = len(rows)
            
            cursor.execute(
                """UPDATE payroll_periods 
                   SET status = 'PROCESSED', totalAmount = %s, employeeCount = %s, processedAt = %s, processedBy = %s, notes = %s
                   WHERE id = %s""",
                (total_amount, employee_count, processed_at, admin_ps, notes, period_id)
            )
            
            cursor.execute("DELETE FROM fare_deductions WHERE periodId = %s", (period_id,))
            for r in rows:
                deduction_id = f"deduct_{period_id}_{r['psNumber']}"
                cursor.execute(
                    """INSERT INTO fare_deductions 
                       (id, periodId, periodMonth, psNumber, employeeName, role, totalRides, totalAmount, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'DEDUCTED')""",
                    (deduction_id, period_id, month, r['psNumber'], r['employeeName'], r['role'], r['totalRides'], r['totalAmount'])
                )
        else:
            if period['status'] == 'PROCESSED':
                conn.rollback()
                cursor.close()
                conn.close()
                return jsonify({"status": "error", "message": f"Payroll for {target_plant} is already locked (period processed)."}), 400
                
            cursor.execute(
                "SELECT 1 FROM payroll_plant_locks WHERE periodId = %s AND plant = %s",
                (period_id, target_plant)
            )
            if cursor.fetchone() is not None:
                conn.rollback()
                cursor.close()
                conn.close()
                return jsonify({"status": "error", "message": f"Payroll for {target_plant} is already locked."}), 400
                
            lock_id = f"lock_{period_id}_{target_plant}"
            cursor.execute(
                """INSERT INTO payroll_plant_locks (id, periodId, plant)
                   VALUES (%s, %s, %s)""",
                (lock_id, period_id, target_plant)
            )
            
            sql = """
                SELECT 
                    b.psNumber,
                    COALESCE(MAX(u.name), MAX(b.employeeName)) as employeeName,
                    COALESCE(MAX(u.role), 'EMPLOYEE') as role,
                    COUNT(b.id) as totalRides,
                    SUM(b.fareAmount) as totalAmount
                FROM bookings b
                LEFT JOIN users u ON b.psNumber = u.psNumber
                WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
                  AND u.plant = %s
                GROUP BY b.psNumber
            """
            cursor.execute(sql, (month + '%', target_plant))
            rows = cursor.fetchall()
            for r in rows:
                r['totalAmount'] = float(r['totalAmount']) if r['totalAmount'] is not None else 0.0
                r['totalRides'] = int(r['totalRides'])
                
            cursor.execute(
                """DELETE fd FROM fare_deductions fd
                   JOIN users u ON fd.psNumber = u.psNumber
                   WHERE fd.periodId = %s AND u.plant = %s""",
                (period_id, target_plant)
            )
            
            for r in rows:
                deduction_id = f"deduct_{period_id}_{r['psNumber']}"
                cursor.execute(
                    """INSERT INTO fare_deductions 
                       (id, periodId, periodMonth, psNumber, employeeName, role, totalRides, totalAmount, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'DEDUCTED')""",
                    (deduction_id, period_id, month, r['psNumber'], r['employeeName'], r['role'], r['totalRides'], r['totalAmount'])
                )
                
            cursor.execute(
                "SELECT COUNT(DISTINCT plant) as count_locked FROM payroll_plant_locks WHERE periodId = %s",
                (period_id,)
            )
            count_locked = cursor.fetchone()['count_locked']
            
            if count_locked >= 2:
                cursor.execute(
                    """SELECT SUM(totalAmount) as totalAmount, COUNT(id) as employeeCount
                       FROM fare_deductions
                       WHERE periodId = %s""",
                    (period_id,)
                )
                total_row = cursor.fetchone()
                total_amount = float(total_row['totalAmount']) if total_row['totalAmount'] is not None else 0.0
                employee_count = int(total_row['employeeCount']) if total_row['employeeCount'] is not None else 0
                
                cursor.execute(
                    """UPDATE payroll_periods 
                       SET status = 'PROCESSED', totalAmount = %s, employeeCount = %s, processedAt = %s, processedBy = %s, notes = %s
                       WHERE id = %s""",
                    (total_amount, employee_count, processed_at, admin_ps, notes, period_id)
                )
                
        conn.commit()
        cursor.close()
        conn.close()
        
        socketio.emit('PAYROLL_UPDATED', {
            'action': 'PROCESSED',
            'periodId': period_id,
            'month': month
        })
        
        return jsonify({
            "status": "ok",
            "message": "Payroll period marked as processed."
        })
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/payroll/period/<period_id>/unlock', methods=['PATCH'])
@require_auth(allowed_roles=['ADMIN'])
def unlock_payroll_period(period_id):
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        data = request.get_json() or {}
        admin_ps = g.current_user['psNumber']
        target_plant = data.get('plant', '').strip()
            
        admin_plant = g.current_user.get('plant')
        if admin_plant is not None:
            target_plant = admin_plant
        if not target_plant:
            target_plant = 'All'
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        conn.start_transaction()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM payroll_periods WHERE id = %s FOR UPDATE", (period_id,))
        period = cursor.fetchone()
        
        if not period:
            conn.rollback()
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Period not found."}), 404
            
        month = period['periodMonth']
        
        # Check lock status
        is_locked = False
        if period['status'] == 'PROCESSED':
            is_locked = True
        else:
            if target_plant in ['Awalpur', 'Manikgarh']:
                cursor.execute(
                    "SELECT 1 FROM payroll_plant_locks WHERE periodId = %s AND plant = %s",
                    (period_id, target_plant)
                )
                is_locked = (cursor.fetchone() is not None)
                
        if not is_locked:
            conn.rollback()
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Only processed and locked periods can be unlocked."}), 400
            
        if target_plant == 'All':
            # Unlock both / all plants
            cursor.execute("DELETE FROM payroll_plant_locks WHERE periodId = %s", (period_id,))
            cursor.execute("DELETE FROM fare_deductions WHERE periodId = %s", (period_id,))
            cursor.execute(
                """UPDATE payroll_periods 
                   SET status = 'PENDING', processedAt = NULL, processedBy = NULL
                   WHERE id = %s""",
                (period_id,)
            )
        else:
            # Specific plant unlock
            cursor.execute("DELETE FROM payroll_plant_locks WHERE periodId = %s AND plant = %s", (period_id, target_plant))
            cursor.execute(
                """DELETE fd FROM fare_deductions fd
                   JOIN users u ON fd.psNumber = u.psNumber
                   WHERE fd.periodId = %s AND u.plant = %s""",
                (period_id, target_plant)
            )
            if period['status'] == 'PROCESSED':
                cursor.execute(
                    """UPDATE payroll_periods 
                       SET status = 'PENDING', processedAt = NULL, processedBy = NULL
                       WHERE id = %s""",
                    (period_id,)
                )
                
        conn.commit()
        cursor.close()
        conn.close()
        
        socketio.emit('PAYROLL_UPDATED', {
            'action': 'UNLOCKED',
            'periodId': period_id,
            'month': month
        })
        
        return jsonify({
            "status": "ok",
            "message": "Payroll period unlocked successfully."
        })
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/payroll/period/<period_id>/export', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def export_payroll_period(period_id):
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    try:
        plant = request.args.get('plant', 'All').strip()
        admin_plant = g.current_user.get('plant')
        if admin_plant is not None:
            plant = admin_plant
            
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM payroll_periods WHERE id = %s", (period_id,))
        period = cursor.fetchone()
        
        if not period:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Period not found."}), 404
            
        month = period['periodMonth']
        status = period['status']
        
        # Helper function to query summary and details for a given plant (or all plants)
        def fetch_payroll_data(target_plant):
            # target_plant is always Awalpur or Manikgarh when called
            is_locked = False
            if status == 'PROCESSED':
                is_locked = True
            else:
                cursor.execute(
                    "SELECT 1 FROM payroll_plant_locks WHERE periodId = %s AND plant = %s",
                    (period_id, target_plant)
                )
                is_locked = (cursor.fetchone() is not None)
                
            # 1. Fetch Summary
            if is_locked:
                sql_summary = """
                    SELECT fd.psNumber, fd.employeeName, fd.role, fd.totalRides, fd.totalAmount, fd.status 
                    FROM fare_deductions fd
                    LEFT JOIN users u ON fd.psNumber = u.psNumber
                    WHERE fd.periodId = %s AND u.plant = %s
                """
                cursor.execute(sql_summary, (period_id, target_plant))
            else:
                sql_summary = """
                    SELECT 
                        b.psNumber,
                        COALESCE(MAX(u.name), MAX(b.employeeName)) as employeeName,
                        COALESCE(MAX(u.role), 'EMPLOYEE') as role,
                        COUNT(b.id) as totalRides,
                        SUM(b.fareAmount) as totalAmount,
                        'PENDING' as status
                    FROM bookings b
                    LEFT JOIN users u ON b.psNumber = u.psNumber
                    WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
                      AND u.plant = %s
                    GROUP BY b.psNumber
                """
                cursor.execute(sql_summary, (month + '%', target_plant))
                
            summary_rows = cursor.fetchall()
            for r in summary_rows:
                r['totalAmount'] = float(r['totalAmount']) if r['totalAmount'] is not None else 0.0
                r['totalRides'] = int(r['totalRides'])
                
            # 2. Fetch Details
            sql_detail = """
                SELECT 
                    b.id as bookingId,
                    b.travelDate,
                    b.psNumber,
                    b.employeeName,
                    b.shiftId,
                    b.seatNumber,
                    b.fareAmount
                FROM bookings b
                LEFT JOIN users u ON b.psNumber = u.psNumber
                WHERE b.travelDate LIKE %s AND b.status = 'CONFIRMED' AND (u.role IS NULL OR u.role != 'DRIVER')
                  AND u.plant = %s
                ORDER BY b.travelDate ASC, b.psNumber ASC
            """
            cursor.execute(sql_detail, (month + '%', target_plant))
            detail_rows = cursor.fetchall()
            return summary_rows, detail_rows

        wb = Workbook()
        
        if plant in ['Awalpur', 'Manikgarh']:
            summary_rows, detail_rows = fetch_payroll_data(plant)
            
            ws1 = wb.active
            ws1.title = "Deductions Summary"
            ws1.append(["Employee Name", "PS Number", "Role", "Total Rides", "Amount Due (₹)", "Status"])
            for r in summary_rows:
                ws1.append([r['employeeName'], r['psNumber'], r['role'], r['totalRides'], r['totalAmount'], r['status']])
                
            ws2 = wb.create_sheet(title="Booking Details")
            ws2.append(["Booking ID", "Travel Date", "PS Number", "Employee Name", "Shift ID", "Seat Number", "Fare (₹)"])
            for d in detail_rows:
                ws2.append([d['bookingId'], d['travelDate'], d['psNumber'], d['employeeName'], d['shiftId'], d['seatNumber'], d['fareAmount']])
            
            sheets_to_format = [ws1, ws2]
            filename = f"UTCL_Payroll_Deductions_{plant}_{month.replace('-', '_')}.xlsx"
        else:
            # Combined / All Plants: Generate 4 sheets
            # Awalpur
            awalpur_summary, awalpur_details = fetch_payroll_data('Awalpur')
            ws1 = wb.active
            ws1.title = "Awalpur Summary"
            ws1.append(["Employee Name", "PS Number", "Role", "Total Rides", "Amount Due (₹)", "Status"])
            for r in awalpur_summary:
                ws1.append([r['employeeName'], r['psNumber'], r['role'], r['totalRides'], r['totalAmount'], r['status']])
                
            ws2 = wb.create_sheet(title="Awalpur Details")
            ws2.append(["Booking ID", "Travel Date", "PS Number", "Employee Name", "Shift ID", "Seat Number", "Fare (₹)"])
            for d in awalpur_details:
                ws2.append([d['bookingId'], d['travelDate'], d['psNumber'], d['employeeName'], d['shiftId'], d['seatNumber'], d['fareAmount']])
                
            # Manikgarh
            manikgarh_summary, manikgarh_details = fetch_payroll_data('Manikgarh')
            ws3 = wb.create_sheet(title="Manikgarh Summary")
            ws3.append(["Employee Name", "PS Number", "Role", "Total Rides", "Amount Due (₹)", "Status"])
            for r in manikgarh_summary:
                ws3.append([r['employeeName'], r['psNumber'], r['role'], r['totalRides'], r['totalAmount'], r['status']])
                
            ws4 = wb.create_sheet(title="Manikgarh Details")
            ws4.append(["Booking ID", "Travel Date", "PS Number", "Employee Name", "Shift ID", "Seat Number", "Fare (₹)"])
            for d in manikgarh_details:
                ws4.append([d['bookingId'], d['travelDate'], d['psNumber'], d['employeeName'], d['shiftId'], d['seatNumber'], d['fareAmount']])
                
            sheets_to_format = [ws1, ws2, ws3, ws4]
            filename = f"UTCL_Payroll_Deductions_Combined_{month.replace('-', '_')}.xlsx"
            
        cursor.close()
        conn.close()
        
        # Autofit column widths
        for ws in sheets_to_format:
            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = col[0].column_letter
                ws.column_dimensions[col_letter].width = max(max_len + 3, 12)
                
        # Write to BytesIO stream
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        # Return as binary response stream
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/payroll/my-fares', methods=['GET'])
@require_auth()
def get_my_fares():
    global db_error_message
    if db_error_message:
        init_db()
        if db_error_message:
            return jsonify({"status": "error", "message": f"Database not connected: {db_error_message}"}), 500
            
    ps_number = request.args.get('psNumber', '').strip()
    month = request.args.get('month', '').strip()
    
    if not ps_number or not month:
        return jsonify({"status": "error", "message": "psNumber and month are required."}), 400
        
    if g.current_user['role'] != 'ADMIN' and g.current_user['psNumber'].strip().upper() != ps_number.strip().upper():
        return jsonify({"status": "error", "message": "Forbidden"}), 403
        
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # 1. Query all CONFIRMED bookings of this user for this month
        sql = """
            SELECT id, shiftId, seatNumber, boardingStopIndex, dropStopIndex, fareAmount, travelDate, bookedAt
            FROM bookings
            WHERE psNumber = %s AND travelDate LIKE %s AND status = 'CONFIRMED'
            ORDER BY travelDate ASC
        """
        cursor.execute(sql, (ps_number, month + '%'))
        bookings = cursor.fetchall()
        
        for b in bookings:
            b['fareAmount'] = int(b['fareAmount'])
            
        total_amount = sum(b['fareAmount'] for b in bookings)
        total_rides = len(bookings)
        
        if total_rides == 0:
            cursor.close()
            conn.close()
            return jsonify({
                "status": "NO_TRIPS",
                "deductionStatus": "NO_TRIPS",
                "totalRides": 0,
                "totalAmount": 0,
                "bookings": []
            })
            
        # 2. Query payroll_periods for this month
        cursor.execute("SELECT * FROM payroll_periods WHERE periodMonth = %s", (month,))
        period = cursor.fetchone()
        
        if not period:
            deduction_status = "NOT_GENERATED"
        elif period['status'] == 'PENDING':
            deduction_status = "PENDING"
        elif period['status'] == 'PROCESSED':
            deduction_status = "DEDUCTED"
        else:
            deduction_status = "PENDING"
            
        cursor.close()
        conn.close()
        
        return jsonify({
            "month": month,
            "psNumber": ps_number,
            "deductionStatus": deduction_status,
            "totalRides": total_rides,
            "totalAmount": total_amount,
            "bookings": bookings
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# -------------------------------------------------------------
# Photo Retention Background Cleanup Scheduler (30-day)
# -------------------------------------------------------------
def cleanup_old_photos():
    """Finds photos older than 30 days, physically deletes them from disk,
    and updates the database fields to NULL while keeping the attendance record."""
    try:
        # Calculate the threshold date (30 days ago)
        threshold_date = (datetime.date.today() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')
        print(f"[Photo Cleanup] Running cleanup. Threshold date: {threshold_date}")
        
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cursor = conn.cursor(dictionary=True)
        
        # Clean up expired sessions
        try:
            cursor.execute("DELETE FROM sessions WHERE expires_at < NOW()")
            conn.commit()
            print("[Session Cleanup] Expired sessions cleaned up successfully.")
        except Exception as se:
            print(f"[Session Cleanup] Error: {se}")
        
        # Select records older than 30 days that still have photos
        cursor.execute(
            "SELECT id, departurePhotoUrl, arrivalPhotoUrl FROM driver_attendance "
            "WHERE date < %s AND (departurePhotoUrl IS NOT NULL OR arrivalPhotoUrl IS NOT NULL)",
            (threshold_date,)
        )
        records = cursor.fetchall()
        
        if not records:
            print("[Photo Cleanup] No old photos to delete.")
            cursor.close()
            conn.close()
            return
            
        deleted_files_count = 0
        updated_records_count = 0
        
        for row in records:
            record_id = row['id']
            dep_url = row['departurePhotoUrl']
            arr_url = row['arrivalPhotoUrl']
            
            # Check files and delete
            for url in [dep_url, arr_url]:
                if url:
                    # e.g., URL is '/uploads/dep_...' -> we want the filename part
                    filename = url.split('/')[-1]
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            deleted_files_count += 1
                        except Exception as e:
                            print(f"[Photo Cleanup] Failed to delete file {file_path}: {e}")
                            
            # Update database
            cursor.execute(
                "UPDATE driver_attendance SET departurePhotoUrl = NULL, arrivalPhotoUrl = NULL WHERE id = %s",
                (record_id,)
            )
            updated_records_count += 1
            
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[Photo Cleanup] Successfully deleted {deleted_files_count} photo files and updated {updated_records_count} attendance records.")
        
    except Exception as e:
        print(f"[Photo Cleanup] Error running cleanup: {e}")

def run_shift_lock_broadcaster():
    """Background worker that runs every 30 seconds to check for active shifts that cross
    the 5-minute pre-departure window, and emits 'SHIFT_LOCKED' event to all connected clients."""
    print("[Shift Lock Broadcaster] Worker started.")
    emitted_locks = set()
    
    while True:
        try:
            today_str = datetime.date.today().strftime('%Y-%m-%d')
            config = load_db_config()
            conn = mysql.connector.connect(
                host=config['host'],
                port=config['port'],
                user=config['user'],
                password=config['password'],
                database=config.get('database', 'utcl_bus_db')
            )
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id, departureTime FROM shifts WHERE isActive = 1")
            active_shifts = cursor.fetchall()
            cursor.close()
            conn.close()
            
            for shift in active_shifts:
                shift_id = shift['id']
                dep_time_str = shift['departureTime']
                
                key = (today_str, shift_id)
                if key not in emitted_locks:
                    if is_shift_locked(dep_time_str, today_str):
                        print(f"[Shift Lock Broadcaster] Shift {shift_id} (departure: {dep_time_str} on {today_str}) is locked. Broadcasting SHIFT_LOCKED.")
                        socketio.emit('SHIFT_LOCKED', {'shiftId': shift_id})
                        emitted_locks.add(key)
            
            # Prune old dates
            emitted_locks = {k for k in emitted_locks if k[0] == today_str}
            
        except Exception as e:
            print(f"[Shift Lock Broadcaster] Error in loop: {e}")
            
        socketio.sleep(30)

def start_shift_lock_broadcaster():
    socketio.start_background_task(run_shift_lock_broadcaster)

def run_scheduler_loop():
    # Run once at startup after a short delay to let database settle
    time.sleep(5)
    cleanup_old_photos()
    
    # Sleep and run daily (every 24 hours)
    while True:
        time.sleep(24 * 3600)
        cleanup_old_photos()

def start_photo_cleanup_scheduler():
    t = threading.Thread(target=run_scheduler_loop, daemon=True)
    t.start()



# ── Admin: Shift Cancellation ────────────────────────────────────────────────

@app.route('/api/admin/shifts/booking-count', methods=['GET'])
@require_auth(allowed_roles=['ADMIN'])
def admin_shift_booking_count():
    """Return the number of CONFIRMED bookings for a given shiftId + date."""
    shift_id   = request.args.get('shiftId', '').strip()
    travel_date = request.args.get('date', '').strip()
    if not shift_id or not travel_date:
        return jsonify({'status': 'error', 'message': 'shiftId and date are required'}), 400
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'], port=config['port'],
            user=config['user'], password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM bookings "
            "WHERE shiftId = %s AND travelDate = %s AND status = 'CONFIRMED'",
            (shift_id, travel_date)
        )
        row   = cur.fetchone()
        count = row['cnt'] if row else 0
        cur.close()
        conn.close()
        return jsonify({'status': 'ok', 'count': count})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/admin/shifts/cancel-for-day', methods=['POST'])
@require_auth(allowed_roles=['ADMIN'])
def admin_cancel_shift_for_day():
    """Cancel all CONFIRMED bookings/tickets for a shift on a given date and notify passengers."""
    data        = request.get_json(force=True) or {}
    shift_id    = data.get('shiftId', '').strip()
    travel_date = data.get('date', '').strip()
    reason      = data.get('reason', 'Shift cancelled for the day').strip()
    if not shift_id or not travel_date:
        return jsonify({'status': 'error', 'message': 'shiftId and date are required'}), 400
    try:
        config = load_db_config()
        conn = mysql.connector.connect(
            host=config['host'], port=config['port'],
            user=config['user'], password=config['password'],
            database=config.get('database', 'utcl_bus_db')
        )
        cur = conn.cursor(dictionary=True)

        # Fetch affected bookings (to get user IDs for notifications)
        cur.execute(
            "SELECT b.id AS bookingId, b.psNumber, u.id AS userId "
            "FROM bookings b "
            "LEFT JOIN users u ON u.psNumber = b.psNumber "
            "WHERE b.shiftId = %s AND b.travelDate = %s AND b.status = 'CONFIRMED'",
            (shift_id, travel_date)
        )
        affected = cur.fetchall()

        # Cancel bookings
        cur.execute(
            "UPDATE bookings SET status = 'CANCELLED' "
            "WHERE shiftId = %s AND travelDate = %s AND status = 'CONFIRMED'",
            (shift_id, travel_date)
        )

        # Cancel tickets
        cur.execute(
            "UPDATE tickets SET status = 'CANCELLED' "
            "WHERE shiftCode = %s AND travelDate = %s AND status = 'CONFIRMED'",
            (shift_id, travel_date)
        )

        # Create notifications for each affected user
        import uuid, datetime
        notif_msg = (
            f"Shift Cancellation: Shift {shift_id} on {travel_date} has been cancelled. "
            f"Reason: {reason}. Your booking has been cancelled and will not appear on payroll."
        )
        for row in affected:
            if row.get('userId'):
                cur.execute(
                    "INSERT INTO notifications (id, recipientUserId, message, isRead, createdAt) "
                    "VALUES (%s, %s, %s, 0, %s)",
                    (
                        f"nt_{uuid.uuid4().hex[:12]}",
                        row['userId'],
                        notif_msg,
                        datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    )
                )

        # Log cancellation in cancelled_shifts table for date-specific checking
        cancelled_shift_id = f"cs_{uuid.uuid4().hex[:12]}"
        cancelled_at_str = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute(
            "INSERT IGNORE INTO cancelled_shifts (id, shiftId, date, reason, cancelledAt) "
            "VALUES (%s, %s, %s, %s, %s)",
            (cancelled_shift_id, shift_id, travel_date, reason, cancelled_at_str)
        )

        conn.commit()
        cur.close()
        conn.close()

        # ── WebSocket Broadcasts ──────────────────────────────────────────────
        # 1. Global broadcast so every connected tab syncs state immediately
        socketio.emit('SHIFT_CANCELLED_FOR_DAY', {
            'shiftId': shift_id,
            'travelDate': travel_date,
            'reason': reason,
            'cancelledCount': len(affected)
        })

        # 2. Per-user NOTIFICATION_RECEIVED so each affected passenger's bell
        #    lights up and a toast is shown — without any page refresh
        notif_payload_base = {
            'message': notif_msg,
            'createdAt': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        }
        for row in affected:
            if row.get('userId'):
                socketio.emit('NOTIFICATION_RECEIVED', {
                    **notif_payload_base,
                    'recipientUserId': row['userId']
                }, room=row['userId'])

        return jsonify({'status': 'ok', 'cancelled': len(affected), 'message': 'Shift cancelled successfully.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/')
@app.route('/index.html')
def serve_index():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    idx_path  = os.path.join(base_dir, 'index.html')
    with open(idx_path, 'r', encoding='utf-8') as f:
        html = f.read()
    resp = make_response(html, 200)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    # Prevent caching so a stale copy without watermark can't be served
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp

# Fix #9: Health check endpoint — Railway uses this to verify the service
# is up after deployments. Returns 200 with DB connectivity status.
@app.route('/api/health', methods=['GET'])
def health_check():
    db_ok = False
    try:
        pool = get_db_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        db_ok = True
    except Exception as e:
        print(f"[Health] DB check failed: {e}")
    status = "ok" if db_ok else "degraded"
    # Return 200 always to prevent Railway deployment rollback loops when DB is booting
    http_code = 200
    return jsonify({
        "status": status,
        "db": "connected" if db_ok else "disconnected",
        "version": "1.0"
    }), http_code
# =============================================================================

# Run database and scheduler initialization in a deferred background thread.
# This prevents Gunicorn's import phase from blocking, allowing Gunicorn to enter
# the event loop and accept connections immediately before executing heavy startup operations.
def deferred_startup():
    time.sleep(2)
    print("[Startup] Running deferred database and scheduler initialization...")
    init_db()
    start_photo_cleanup_scheduler()
    start_shift_lock_broadcaster()
    print("[Startup] Deferred initialization complete.")

threading.Thread(target=deferred_startup, daemon=True).start()

if __name__ == '__main__':

    print("=" * 60)
    print("  UTCL Bus Management System - Real-Time Server")
    print("=" * 60)
    print(f"  Protocol: HTTP + WebSocket (Flask-SocketIO / threading)")
    print(f"  Server  : http://0.0.0.0:8000")
    print(f"  LAN URL : Check run.bat for your machine name")
    print(f"  Status  : Running (Press Ctrl+C to stop)")
    print("=" * 60)
    
    # Bind to PORT from environment or fallback to 8000
    port = int(os.environ.get('PORT', 8000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
