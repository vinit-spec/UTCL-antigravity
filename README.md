# 🚌 UTCL Transit Management System

An end-to-end, multi-plant corporate bus and transit management application built for **UltraTech Cement Limited (UTCL)**. The platform provides real-time shift bus booking, dynamic QR code ticket generation, driver selfie attendance verification, multi-plant employee access control, and automated monthly HR payroll fare deductions.

---

## 🌟 Key Features

- **📱 Multi-Role Web Dashboard**: Dedicated role-based interfaces for **Employees**, **Drivers**, and **Administrators / HR Managers**.
- **🎫 Dynamic QR Ticket Generation & Scanning**: Digital bus tickets generated dynamically with offline/online verification and QR scanning support.
- **🤳 Driver Selfie & Shift Attendance**: Driver departure and arrival selfie photo verification with location & timestamps to prevent proxy attendance.
- **🏢 Multi-Plant Operations Support**: Multi-tenant plant management (e.g., Awalpur, Manikgarh) with isolated shift schedules, stop routes, and employee assignment.
- **💰 HR Payroll & Fare Deduction Automation**: Automated calculation of monthly employee transit rides, fare rules, and exportable payroll deduction logs.
- **📊 Real-time Analytics & Fleet Monitoring**: Live stats, booking trends, capacity utilization, and system operational metrics.
- **🔒 Robust Security & Authentication**: Role-based access control (RBAC), bcrypt password hashing, session tokens, and Brevo HTTP API-backed OTP password resets.

---

## 🛠️ Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Backend API Server** | Python 3.12, Flask, Gevent WSGI server |
| **Database** | MySQL 8.0+ / MariaDB with connection pooling |
| **Frontend UI** | HTML5, CSS3 (Custom Responsive System), Vanilla JavaScript |
| **Real-time Engine** | Socket.IO (WebSockets / HTTP long-polling fallback) |
| **Client Utilities** | Chart.js (Analytics), QRCode.js (Ticket QR rendering), SheetJS XLSX |
| **Testing & Verification** | Locust (Load testing), Python unittest / criteria verification scripts |

---

## 📂 Project Structure

```text
UTCL antigravity/
├── app.js                          # Frontend client logic & event handlers
├── index.html                      # Single Page Application (SPA) container
├── style.css                       # Responsive UI stylesheet & design system
├── server.py                       # Core Flask API backend & database connector
├── requirements.txt                # Python dependencies
├── Procfile                        # Deployment process manager config
├── railway.toml                    # Railway platform deployment settings
├── .env.example                    # Environment variable template
├── db_config.json.example          # Local MySQL configuration template
├── smtp_config.json.example        # Local SMTP configuration template
├── js/                             # Bundled client libraries (Chart.js, QRCode, SheetJS)
├── fonts/                          # Self-hosted typography (Inter & Outfit fonts)
├── uploads/                        # User verification uploads (.gitignore protected)
├── verify_multi_plant_criteria.py  # System integration & criteria test suite
└── locustfile.py                   # Load & stress testing script
```

---

## 🚀 Getting Started

### Prerequisites

- **Python**: Version 3.10 or higher
- **MySQL Database**: MySQL 8.0+ server running locally or on a cloud database service
- **Git**

### Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-username/utcl-transit-management-system.git
   cd utcl-transit-management-system
   ```

2. **Set Up Python Virtual Environment**:
   ```bash
   # On Windows
   python -m venv .venv
   .venv\Scripts\activate

   # On Linux/macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Copy `.env.example` to `.env` and fill in your database credentials:
   ```bash
   cp .env.example .env
   ```
   Alternatively, copy `db_config.json.example` to `db_config.json`:
   ```json
   {
     "host": "127.0.0.1",
     "port": 3306,
     "user": "root",
     "password": "YOUR_MYSQL_PASSWORD",
     "database": "utcl_bus_db"
   }
   ```

5. **Initialize Database**:
   Create the database in MySQL:
   ```sql
   CREATE DATABASE utcl_bus_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```
   The application server automatically creates required tables and seeds default initial accounts upon first startup.

6. **Run Development Server**:
   ```bash
   python server.py
   ```
   Access the web application at `http://localhost:8000`.

---

## 🔐 Environment Variables

The server dynamically evaluates configuration from environment variables (preferred for cloud hosting) or local `.json` configuration files:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `PORT` | Web server listening port | `8000` |
| `ALLOWED_ORIGIN` | CORS allowed origin configuration | `*` |
| `MYSQLHOST` | MySQL Server Hostname | `127.0.0.1` |
| `MYSQLPORT` | MySQL Server Port | `3306` |
| `MYSQLUSER` | Database username | `root` |
| `MYSQLPASSWORD` | Database user password | `""` |
| `MYSQLDATABASE` | Database name | `utcl_bus_db` |
| `BREVO_API_KEY` | Brevo HTTP API Key for OTP Emails | Optional |
| `BREVO_SENDER_EMAIL` | Sender Email Address for Brevo OTP | `utcl-bus-system@example.com` |

---

## 🧪 Testing & Verification

### Integration Test Suite
To execute the multi-plant criteria verification test suite:
```bash
python verify_multi_plant_criteria.py
```

### Load Testing with Locust
To launch a load test simulation:
```bash
locust -f locustfile.py --host http://localhost:8000
```
Open `http://localhost:8089` in your web browser to configure virtual users and request rates.

---

## 🛡️ Security & Best Practices

- **Zero Hardcoded Secrets**: Secret keys, database credentials, and external API tokens are strictly injected via environment variables or git-ignored configuration files.
- **Input Validation**: Sanitize and validate all payload parameters at HTTP boundary.
- **Vulnerability Reporting**: See [SECURITY.md](SECURITY.md) for details on security policies and reporting vulnerabilities.

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for more information.

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before submitting Pull Requests.
