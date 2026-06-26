import os
import sys
import uuid
import json
import bcrypt
import mysql.connector
from openpyxl import load_workbook

# Default configuration files
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
        print(f"Error: {DB_CONFIG_FILE} not found. Make sure you run this from the project root.")
        sys.exit(1)
    with open(DB_CONFIG_FILE, 'r') as f:
        cfg = json.load(f)
        cfg['use_pure'] = True
        return cfg

def get_hashed(pw):
    return bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# Helper to normalize headers
def normalize_header(header):
    if not header:
        return ""
    return str(header).strip().lower().replace(" ", "").replace("_", "")

def import_plant_excel(cursor, file_path, plant_name):
    print(f"\nProcessing {plant_name} Excel: {file_path}...")
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} does not exist. Skipping.")
        return
        
    try:
        wb = load_workbook(file_path, read_only=True)
        sheet = wb.active
        
        # Read header row
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            print("Error: Excel sheet is empty.")
            return
            
        header_row = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
        normalized_headers = [normalize_header(h) for h in header_row]
        
        # Find indices
        ps_idx = -1
        name_idx = -1
        email_idx = -1
        phone_idx = -1
        role_idx = -1
        
        # Try different names for headers
        for idx, h in enumerate(normalized_headers):
            if h in ['psnumber', 'ps', 'employeeid', 'id', 'psno']:
                ps_idx = idx
            elif h in ['name', 'employeename', 'nameofrider', 'fullname']:
                name_idx = idx
            elif h in ['email', 'emailaddress', 'corporateemail', 'mail']:
                email_idx = idx
            elif h in ['phone', 'phonenumber', 'mobile', 'contact']:
                phone_idx = idx
            elif h in ['role', 'designation', 'usertype']:
                role_idx = idx
                
        if ps_idx == -1:
            print("Error: Could not find 'PS Number' or 'PS' column in the header row.")
            print("Expected headers: PS Number, Name, Email, Phone (optional), Role (optional)")
            return
        if name_idx == -1:
            print("Error: Could not find 'Name' or 'Employee Name' column.")
            return
            
        default_pwd_hash = get_hashed("password123")
        count = 0
        
        for row in rows[1:]:
            # Skip empty rows
            if not row or row[ps_idx] is None:
                continue
                
            ps_num = str(row[ps_idx]).strip().upper()[:10]
            if not ps_num:
                continue
                
            # Skip seeding if it is the System Admin to protect login
            if ps_num == 'PS00001':
                print("Skipping override of System Administrator (PS00001) to protect credentials.")
                continue
                
            name = str(row[name_idx]).strip() if row[name_idx] is not None else "Unknown"
            email = str(row[email_idx]).strip() if (email_idx != -1 and row[email_idx] is not None) else None
            phone = str(row[phone_idx]).strip() if (phone_idx != -1 and row[phone_idx] is not None) else None
            
            # Extract role
            role = "EMPLOYEE"
            if role_idx != -1 and row[role_idx] is not None:
                role_val = str(row[role_idx]).strip().upper()
                if role_val in ['ADMIN', 'EMPLOYEE', 'DRIVER']:
                    role = role_val
            
            # Generate UUID if not exists
            user_id = f"u_import_{uuid.uuid4().hex[:12]}"
            
            # Insert or Update on duplicate PS number
            # We use COALESCE(password, VALUES(password)) to keep their set password if they already registered one!
            sql = """
                INSERT INTO users (id, name, psNumber, password, role, isActive, email, phone, plant)
                VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    role = VALUES(role),
                    isActive = VALUES(isActive),
                    email = VALUES(email),
                    phone = VALUES(phone),
                    plant = VALUES(plant)
            """
            cursor.execute(sql, (user_id, name, ps_num, default_pwd_hash, role, email, phone, plant_name))
            count += 1
            
        print(f"Successfully processed {count} records for {plant_name}.")
        
    except Exception as e:
        print(f"Error importing sheet: {e}")

def main():
    if len(sys.argv) < 3:
        print("UTCL Bus System - Excel User Importer")
        print("=====================================")
        print("Usage:")
        print("  .venv\\Scripts\\python.exe import_users.py <awalpur_excel> <manikgarh_excel>")
        print("\nExample:")
        print("  .venv\\Scripts\\python.exe import_users.py awalpur_employees.xlsx manikgarh_employees.xlsx")
        sys.exit(1)
        
    awalpur_file = sys.argv[1]
    manikgarh_file = sys.argv[2]
    
    config = load_db_config()
    try:
        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()
        
        # Process Awalpur
        import_plant_excel(cursor, awalpur_file, "Awalpur")
        
        # Process Manikgarh
        import_plant_excel(cursor, manikgarh_file, "Manikgarh")
        
        conn.commit()
        cursor.close()
        conn.close()
        print("\nAll database changes committed successfully!")
        
    except Exception as e:
        print(f"Database connection error: {e}")

if __name__ == '__main__':
    main()
