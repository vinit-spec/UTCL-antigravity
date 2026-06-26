import mysql.connector
import json

def load_db_config():
    import os
    if "MYSQLHOST" in os.environ:
        return {
            "host": os.environ.get("MYSQLHOST"),
            "port": int(os.environ.get("MYSQLPORT", 3306)),
            "user": os.environ.get("MYSQLUSER"),
            "password": os.environ.get("MYSQLPASSWORD"),
            "database": os.environ.get("MYSQLDATABASE", "utcl_bus_db"),
            "use_pure": True
        }
    with open('db_config.json', 'r') as f:
        cfg = json.load(f)
        cfg['use_pure'] = True
        return cfg

def main():
    cfg = load_db_config()
    conn = mysql.connector.connect(**cfg)
    cur = conn.cursor()

    # Show all users first
    cur.execute("SELECT id, name, psNumber, role, plant, email FROM users ORDER BY id")
    all_users = cur.fetchall()

    print(f"\nTotal users: {len(all_users)}")
    print("\n--- ALL USERS ---")
    for u in all_users:
        print(u)

    # Identify mock/test users: id starts with 'emp_' OR (name matches 'Employee N' pattern with generic emails)
    mock_users = []
    real_users = []

    for u in all_users:
        uid, name, ps, role, plant, email = u
        # emp_ prefix = seeded test users
        if uid.startswith('emp_'):
            mock_users.append(u)
        # u_ prefix with "Employee N" name and employee@plant.com email = seeded test data
        elif uid.startswith('u_') and name and name.startswith('Employee ') and email and '@awalpur.com' in email or \
             uid.startswith('u_') and name and name.startswith('Employee ') and email and '@manikgarh.com' in email:
            mock_users.append(u)
        else:
            real_users.append(u)

    print(f"\n--- MOCK/TEST USERS TO DELETE ({len(mock_users)}) ---")
    for u in mock_users:
        print(u)

    print(f"\n--- REAL USERS TO KEEP ({len(real_users)}) ---")
    for u in real_users:
        print(u)

    confirm = input("\nProceed with deleting mock users? (yes/no): ").strip().lower()
    if confirm == 'yes':
        ids_to_delete = [u[0] for u in mock_users]
        placeholders = ', '.join(['%s'] * len(ids_to_delete))
        cur.execute(f"DELETE FROM users WHERE id IN ({placeholders})", ids_to_delete)
        conn.commit()
        print(f"\nDeleted {cur.rowcount} mock/test users.")
    else:
        print("Aborted. No changes made.")

    cur.close()
    conn.close()

if __name__ == '__main__':
    main()
