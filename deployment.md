# Deployment Guide: UTCL Bus Management System

This document outlines the steps to deploy the UTCL Bus Management System in a production environment. Since the application consists of a Python Flask API server and a MySQL database, it can be deployed on a local office server (Intranet), a cloud server (VPS/VM), or using Docker containers.

---

## 📋 Table of Contents
1. [Preparation & Configurations](#1-preparation--configurations)
2. [Option A: Docker Deployment (Recommended)](#option-a-docker-deployment-recommended)
3. [Option B: Local Intranet Deployment (Windows Server)](#option-b-local-intranet-deployment-windows-server)
4. [Option C: Production Cloud Deployment (Linux VPS + Nginx + Gunicorn)](#option-c-production-cloud-deployment-linux-vps--nginx--gunicorn)

---

## 1. Preparation & Configurations

Before deploying, make sure you configure your database connection parameters:
- Open [db_config.json](file:///d:/UTCL%20antigravity/db_config.json) (or create one on the host machine).
- Configure the production MySQL host, port, user, password, and database.

### Requirements Checklist
- Python 3.10+
- MySQL Server 8.0+
- System packages (usually pre-installed on servers)

---

## Option A: Docker Deployment (Recommended)

Docker is the easiest way to deploy because it packages the Python application and MySQL database together, ensuring they run exactly the same way anywhere.

### 1. Create a `Dockerfile`
Create a file named `Dockerfile` in the project root:
```dockerfile
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements
COPY .venv/../server.py .
COPY index.html .
COPY style.css .
COPY app.js .
COPY db_config.json .

# Install dependencies
RUN pip install --no-cache-dir flask mysql-connector-python

# Expose port
EXPOSE 8000

# Start server
CMD ["python", "server.py"]
```

### 2. Create a `docker-compose.yml`
Create a `docker-compose.yml` file to run both the Flask app and a MySQL container:
```yaml
version: '3.8'

services:
  db:
    image: mysql:8.0
    container_name: utcl_mysql
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: YourSecureRootPassword
      MYSQL_DATABASE: utcl_bus_db
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql

  web:
    build: .
    container_name: utcl_web
    restart: always
    ports:
      - "80:8000"
    depends_on:
      - db
    environment:
      # Pass database connection details (ensure db_config.json points to 'db' host)
      DB_HOST: db

volumes:
  mysql_data:
```

### 3. Deploy
Run the following command on your server to build and launch the application:
```bash
docker-compose up --build -d
```
The application will be running on port `80` (standard HTTP).

---

## Option B: Local Intranet Deployment (Windows Server)

If you are hosting this inside a local office network on a Windows Server:

### 1. Set Up Python & MySQL
1. Install **Python 3.12** (ensure "Add Python to PATH" is checked).
2. Install **MySQL Server 8.0** and set a secure root password.

### 2. Prepare the Files
1. Copy the project folder (`UTCL antigravity`) to the server (e.g., `C:\inetpub\UTCL-Bus-System`).
2. Open a command prompt inside the directory and create a virtual environment:
   ```cmd
   python -m venv .venv
   .\.venv\Scripts\python -m pip install flask mysql-connector-python
   ```

### 3. Configure Database
Update `db_config.json` with the local MySQL server root password.

### 4. Create a Windows Service (To keep the server running)
To keep the Flask server running in the background without needing a user logged in, use a service wrapper utility like **NSSM** (Non-Sucking Service Manager):
1. Download NSSM and run:
   ```cmd
   nssm install UTCLBusServer
   ```
2. In the GUI dialog, configure:
   - **Path**: `C:\inetpub\UTCL-Bus-System\.venv\Scripts\python.exe`
   - **Startup directory**: `C:\inetpub\UTCL-Bus-System`
   - **Arguments**: `server.py`
3. Click **Install service** and start the service.
4. Set the firewall on the server to allow incoming traffic on port `8000` (or reverse proxy to port `80` using IIS).

---

## Option C: Production Cloud Deployment (Linux VPS + Nginx + Gunicorn)

For maximum security, speed, and availability on a public Linux server (Ubuntu/Debian):

### 1. Set Up Packages
Install system dependencies:
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv mysql-server nginx git -y
```

### 2. Configure MySQL
Secure and log in to MySQL:
```bash
sudo mysql_secure_installation
sudo mysql
```
Create database and user:
```sql
CREATE DATABASE utcl_bus_db;
CREATE USER 'utcl_user'@'localhost' IDENTIFIED BY 'YourSecurePassword';
GRANT ALL PRIVILEGES ON utcl_bus_db.* TO 'utcl_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 3. Set Up Flask Application
Clone your repository and prepare the virtual environment:
```bash
git clone <your-repo-url> /var/www/utcl-bus-system
cd /var/www/utcl-bus-system
python3 -m venv .venv
source .venv/bin/activate
pip install flask mysql-connector-python gunicorn
```

Update `db_config.json` to connect using `'utcl_user'` and `'YourSecurePassword'`.

### 4. Configure Gunicorn Service
Create a Systemd service to manage Gunicorn:
```bash
sudo nano /etc/systemd/system/utcl.service
```
Paste the following:
```ini
[Unit]
Description=Gunicorn instance to serve UTCL Bus System
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/utcl-bus-system
Environment="PATH=/var/www/utcl-bus-system/.venv/bin"
ExecStart=/var/www/utcl-bus-system/.venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 server:app

[Install]
WantedBy=multi-user.target
```
Start and enable the service:
```bash
sudo systemctl start utcl
sudo systemctl enable utcl
```

### 5. Configure Nginx Reverse Proxy
Create Nginx configuration:
```bash
sudo nano /etc/nginx/sites-available/utcl
```
Paste the configuration:
```nginx
server {
    listen 80;
    server_name your_domain.com_or_server_ip;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Enable the site and reload Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/utcl /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```
The application is now securely exposed to the web!
