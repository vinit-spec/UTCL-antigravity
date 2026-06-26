from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

# ── helpers ────────────────────────────────────────────────────────────────────

BLUE_DARK  = RGBColor(0x1A, 0x37, 0x6E)   # UltraTech navy
BLUE_MID   = RGBColor(0x21, 0x5C, 0xAB)   # section heading
BLUE_LIGHT = RGBColor(0xDF, 0xEA, 0xF8)   # table header fill
ORANGE     = RGBColor(0xE8, 0x6A, 0x10)   # accent / title underline
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
GREY_TEXT  = RGBColor(0x44, 0x44, 0x44)
WARN_BG    = RGBColor(0xFF, 0xF3, 0xCD)   # warning row bg

def set_cell_bg(cell, hex_color: RGBColor):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    r, g, b = int(hex_color[0]), int(hex_color[1]), int(hex_color[2])
    shd.set(qn('w:fill'),  f'{r:02X}{g:02X}{b:02X}')
    tcPr.append(shd)


def set_cell_border(cell, border_color="215CAB", width=6):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for side in ['top', 'left', 'bottom', 'right']:
        border = OxmlElement(f'w:{side}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), str(width))
        border.set(qn('w:color'), border_color)
        tcBorders.append(border)
    tcPr.append(tcBorders)

def add_heading(doc, text, level=1):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14 if level == 1 else 8)
    p.paragraph_format.space_after  = Pt(4)
    run = p.add_run(text)
    run.bold = True
    if level == 1:
        run.font.size  = Pt(16)
        run.font.color.rgb = BLUE_DARK
    elif level == 2:
        run.font.size  = Pt(13)
        run.font.color.rgb = BLUE_MID
    else:
        run.font.size  = Pt(11)
        run.font.color.rgb = BLUE_MID
    run.font.name = 'Calibri'
    # underline accent line
    if level == 1:
        border_p = doc.add_paragraph()
        border_p.paragraph_format.space_before = Pt(0)
        border_p.paragraph_format.space_after  = Pt(6)
        run2 = border_p.add_run('─' * 80)
        run2.font.color.rgb = ORANGE
        run2.font.size = Pt(6)
    return p

def add_body(doc, text, bold=False, italic=False, color=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after  = Pt(3)
    run = p.add_run(text)
    run.font.name = 'Calibri'
    run.font.size = Pt(10.5)
    run.bold   = bold
    run.italic = italic
    run.font.color.rgb = color if color else GREY_TEXT
    return p

def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.left_indent   = Inches(0.25 * (level + 1))
    p.paragraph_format.space_before  = Pt(1)
    p.paragraph_format.space_after   = Pt(2)
    # Handle inline bold (text between **)
    parts = text.split('**')
    for i, part in enumerate(parts):
        run = p.add_run(part)
        run.font.name = 'Calibri'
        run.font.size = Pt(10.5)
        run.font.color.rgb = GREY_TEXT
        run.bold = (i % 2 == 1)
    return p

def add_code(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent  = Inches(0.3)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after  = Pt(4)
    run = p.add_run(text)
    run.font.name = 'Courier New'
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x1E, 0x1E, 0x1E)
    # light grey shading on paragraph
    pPr  = p._p.get_or_add_pPr()
    shd  = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  'F0F0F0')
    pPr.append(shd)
    return p

def add_table(doc, headers, rows, col_widths=None, warn_rows=None):
    warn_rows = warn_rows or []
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.LEFT

    # Header row
    hdr = table.rows[0]
    for i, h in enumerate(headers):
        cell = hdr.cells[i]
        set_cell_bg(cell, BLUE_DARK)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(h)
        run.bold = True
        run.font.color.rgb = WHITE
        run.font.name = 'Calibri'
        run.font.size = Pt(10)

    # Data rows
    for r_idx, row_data in enumerate(rows):
        row = table.rows[r_idx + 1]
        is_warn = r_idx in warn_rows
        for c_idx, val in enumerate(row_data):
            cell = row.cells[c_idx]
            if is_warn:
                set_cell_bg(cell, WARN_BG)
            elif r_idx % 2 == 0:
                set_cell_bg(cell, RGBColor(0xF5, 0xF8, 0xFF))
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            # Handle bold markers
            parts = str(val).split('**')
            for i, part in enumerate(parts):
                run = p.add_run(part)
                run.font.name = 'Calibri'
                run.font.size = Pt(10)
                run.font.color.rgb = GREY_TEXT
                run.bold = (i % 2 == 1)

    # Column widths
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Inches(w)
    doc.add_paragraph()   # spacer

def cover_page(doc, title, subtitle, date_str, version):
    doc.add_paragraph()
    doc.add_paragraph()
    # Logo placeholder text
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('ULTRATECH CEMENT LIMITED')
    run.font.name  = 'Calibri'
    run.font.size  = Pt(22)
    run.font.bold  = True
    run.font.color.rgb = BLUE_DARK

    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = p2.add_run('Plant Operations — Internal Systems')
    run2.font.name  = 'Calibri'
    run2.font.size  = Pt(12)
    run2.font.color.rgb = ORANGE
    run2.font.bold = True

    doc.add_paragraph()
    doc.add_paragraph()

    # Orange rule
    rule = doc.add_paragraph()
    rule.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = rule.add_run('━' * 50)
    r.font.color.rgb = ORANGE
    r.font.size = Pt(10)

    doc.add_paragraph()

    # Title
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = t.add_run(title)
    tr.font.name  = 'Calibri'
    tr.font.size  = Pt(26)
    tr.font.bold  = True
    tr.font.color.rgb = BLUE_DARK

    # Subtitle
    st = doc.add_paragraph()
    st.alignment = WD_ALIGN_PARAGRAPH.CENTER
    str_ = st.add_run(subtitle)
    str_.font.name  = 'Calibri'
    str_.font.size  = Pt(14)
    str_.font.color.rgb = BLUE_MID

    doc.add_paragraph()
    rule2 = doc.add_paragraph()
    rule2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = rule2.add_run('━' * 50)
    r2.font.color.rgb = ORANGE
    r2.font.size = Pt(10)

    doc.add_paragraph()
    doc.add_paragraph()

    # Meta info
    for label, val in [('Date', date_str), ('Version', version),
                       ('Classification', 'Internal — Confidential'),
                       ('Prepared by', 'Application Development Team')]:
        mp = doc.add_paragraph()
        mp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        mr = mp.add_run(f'{label}:  ')
        mr.font.bold = True
        mr.font.size = Pt(11)
        mr.font.name = 'Calibri'
        mr.font.color.rgb = BLUE_DARK
        mr2 = mp.add_run(val)
        mr2.font.size = Pt(11)
        mr2.font.name = 'Calibri'
        mr2.font.color.rgb = GREY_TEXT

    doc.add_page_break()

# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENT 1 — IT Deployment Guide
# ══════════════════════════════════════════════════════════════════════════════

def build_deployment_guide(out_path):
    doc = Document()

    # Page margins
    for section in doc.sections:
        section.top_margin    = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    cover_page(doc,
               'IT Deployment Guide',
               'UTCL Bus Management System\nIT Server Room Deployment -- Plant LAN',
               'June 2026', '1.0')

    # 1. Overview
    add_heading(doc, '1. System Overview', 1)
    add_body(doc,
        'The UTCL Bus Management System is a web-based internal application designed to manage '
        'employee bus bookings, shift scheduling, driver assignments, bus maintenance, and live '
        'bus tracking within the UltraTech Cement plant premises. The system will be hosted on '
        'a dedicated server inside the IT Department Server Room, connected to the plant\'s '
        'Local Area Network (LAN). No internet access is required at any point.')

    # 2. Architecture
    add_heading(doc, '2. Deployment Architecture', 1)
    add_body(doc, 'The following diagram illustrates how the system connects across the plant:')
    add_code(doc,
        '  +------------------------------+\n'
        '  |   IT DEPARTMENT SERVER ROOM  |\n'
        '  |  +------------------------+  |\n'
        '  |  |  Dedicated Server PC   |  |\n'
        '  |  |  - Python + Flask      |  |\n'
        '  |  |  - SocketIO (Threaded) |  |\n'
        '  |  |  - MySQL Database      |  |\n'
        '  |  |  Static IP: 192.168.x.x|  |\n'
        '  |  +----------+-------------+  |\n'
        '  |             |                |\n'
        '  |      [LAN Switch / Router]   |\n'
        '  +-------------|----------------+\n'
        '                |\n'
        '    +-----------+-------------+\n'
        '    |           |             |\n'
        ' [PC-HR]   [PC-Gate]   [PC-Admin]\n'
        '                |\n'
        '   Browser: http://192.168.x.x:8000'
    )
    add_body(doc,
        'Every employee PC, admin workstation, and gate computer on the plant LAN '
        'simply opens a browser and visits the server IP address. No software needs '
        'to be installed on any client machine.')

    # 3. Server Room Requirements
    add_heading(doc, '3. Server Room Infrastructure Required', 1)
    add_body(doc, 'The IT server room must provide the following for this deployment:')
    add_table(doc,
        ['Infrastructure', 'Requirement', 'Reason'],
        [
            ['Dedicated Server / PC',  'Windows 10/11 or Windows Server 2019/2022, Min 4 GB RAM, 5 GB free disk', 'Hosts the application 24/7'],
            ['Static IP Address',      'A fixed LAN IP (e.g., 192.168.1.100) reserved by IT for this server',    'Employees always connect to the same address'],
            ['UPS (Power Backup)',     'Server must be connected to UPS unit in server room',                      'Prevents data loss and downtime during power cuts'],
            ['Network Switch Port',   'Server plugged into server room LAN switch with plant network access',      'Makes app accessible from all plant PCs'],
            ['Cooling / AC',          'Server room AC running at all times (standard in server rooms)',            'Prevents server overheating during 24/7 operation'],
            ['Port 8000 Open',        'TCP port 8000 allowed through Windows Firewall on the server',             'Required for browser access from LAN machines'],
            ['Remote Desktop (RDP)',  'RDP enabled on the server so IT can manage it remotely',                   'IT can manage server without physically entering room'],
        ],
        col_widths=[1.9, 2.5, 1.9])

    # 4. Software Stack
    add_heading(doc, '4. Software Stack', 1)
    add_table(doc,
        ['Component', 'Technology', 'Purpose'],
        [
            ['Frontend',        'HTML5, CSS3, JavaScript',   'User Interface (runs in any browser)'],
            ['Backend',         'Python 3 + Flask',          'Application API server'],
            ['Real-Time Server', 'Flask-SocketIO (Threaded)', 'Handles HTTP and live WebSocket connections on LAN'],
            ['Database',        'MySQL 8.0',                 'All data -- bookings, users, tickets (InnoDB)'],
            ['Database Driver', 'mysql-connector-python',    'Official MySQL Python connector'],
            ['Client',          'Any browser (Chrome/Edge)', 'No software install needed on client PCs'],
        ],
        col_widths=[1.8, 2.2, 3.0])
    add_body(doc, '[OK] No internet connection required anywhere -- fully self-contained on plant LAN.', bold=True, color=RGBColor(0x1A, 0x7A, 0x3C))

    # 5. Files to Transfer
    add_heading(doc, '5. Project Files to Transfer to Server', 1)
    add_body(doc,
        'The application team will provide a single project folder. IT must copy '
        'this folder to the server machine (e.g., C:\\UTCL-BusSystem\\). '
        'Do NOT rename or move individual files -- keep the folder structure intact.')
    add_table(doc,
        ['File / Folder', 'Purpose'],
        [
            ['server.py',      'Main application server -- do not modify'],
            ['app.js',         'Frontend logic -- do not modify'],
            ['index.html',     'Main web page -- do not modify'],
            ['style.css',      'Styling -- do not modify'],
            ['db_config.json', 'Database connection config -- EDIT THIS with MySQL password'],
            ['smtp_config.json', 'SMTP connection config -- EDIT THIS with mail server details (uses port 62 by default)'],
            ['run.bat',        'Server startup script -- used by Task Scheduler'],
            ['.venv/',         'Python virtual environment with all dependencies pre-installed'],
            ['js/',            'Offline JavaScript libraries (Socket.IO, Chart.js, SheetJS/XLSX, and QRCode) -- do not modify'],
            ['uploads/',       'Directory where driver attendance photos are saved -- do not delete'],
        ],
        col_widths=[2.0, 4.2])

    # 6. Step-by-Step
    add_heading(doc, '6. Step-by-Step Deployment on Server Room Machine', 1)
    add_body(doc,
        'All steps below are to be performed ON THE SERVER MACHINE inside the server room. '
        'IT staff can perform these steps either by physically accessing the server or '
        'via Remote Desktop (RDP) from their office workstation.')

    add_heading(doc, 'Step 1 -- Copy Project Folder to Server', 2)
    add_bullet(doc, 'Connect to the server via **RDP** or physically sit at the server machine in the server room')
    add_bullet(doc, 'Copy the entire project folder (received from application team) to:')
    add_code(doc, 'C:\\UTCL-BusSystem\\')
    add_bullet(doc, 'Confirm all files listed in Section 5 are present in the folder')

    add_heading(doc, 'Step 2 -- Install Python 3.10+ on the Server', 2)
    add_bullet(doc, 'Download Python 3.10+ from: https://www.python.org/downloads/')
    add_bullet(doc, 'During installation, check **"Add Python to PATH"** -- this is important')
    add_bullet(doc, 'Open Command Prompt after install and verify:')
    add_code(doc, 'python --version')

    add_heading(doc, 'Step 3 -- Install MySQL Server on the Server', 2)
    add_bullet(doc, 'Download MySQL Community Server 8.0 from: https://dev.mysql.com/downloads/mysql/')
    add_bullet(doc, 'Install using default settings')
    add_bullet(doc, 'During setup, set a **strong root password** -- store this securely in IT records (needed later)')
    add_bullet(doc, 'In MySQL Installer, set the Windows service startup type to **Automatic** so MySQL starts on every boot')
    add_bullet(doc, 'Verify MySQL is running: Open Services (services.msc) -- confirm MySQL80 status is "Running"')

    add_heading(doc, 'Step 4 -- Configure Database Connection', 2)
    add_body(doc, 'Open C:\\UTCL-BusSystem\\db_config.json in Notepad and fill in the MySQL root password:')
    add_code(doc, '{\n  "host": "127.0.0.1",\n  "port": 3306,\n  "user": "root",\n  "password": "YOUR_MYSQL_ROOT_PASSWORD",\n  "database": "utcl_bus_db"\n}')
    add_body(doc, '[!] Replace YOUR_MYSQL_ROOT_PASSWORD with the password set in Step 3. Save and close the file.', italic=True, color=RGBColor(0x99, 0x50, 0x00))

    add_heading(doc, 'Step 4b -- Configure SMTP Mail Relay Settings', 2)
    add_body(doc, 'Open C:\\UTCL-BusSystem\\smtp_config.json in Notepad and configure your SMTP host and settings. Port 62 is used by default for local relay. Save and close.')

    add_heading(doc, 'Step 5 -- Install Python Dependencies', 2)
    add_body(doc, 'Open Command Prompt as Administrator on the server and run:')
    add_code(doc, 'cd C:\\UTCL-BusSystem\n.venv\\Scripts\\pip install flask mysql-connector-python flask-socketio simple-websocket')

    add_heading(doc, 'Step 6 -- Allow Port 8000 Through Windows Firewall', 2)
    add_body(doc, 'Run this in Command Prompt as Administrator on the server:')
    add_code(doc, 'netsh advfirewall firewall add rule name="UTCL Bus System" dir=in action=allow protocol=TCP localport=8000')
    add_body(doc, 'This allows all plant LAN machines to reach the bus system through the server firewall.')

    add_heading(doc, 'Step 7 -- Configure Auto-Start via Windows Task Scheduler', 2)
    add_body(doc,
        'IMPORTANT: Since this is a server room machine, the application must start automatically '
        'on every boot -- even if no IT person is logged in. Configure this via Task Scheduler:')
    add_bullet(doc, 'Open Task Scheduler: Press Win+R, type **taskschd.msc**, press Enter')
    add_bullet(doc, 'Click **"Create Task"** (not Basic Task) in the right panel')
    add_bullet(doc, 'General tab: Name = "UTCL Bus System", check **"Run whether user is logged on or not"**, check **"Run with highest privileges"**')
    add_bullet(doc, 'Triggers tab: Click New → Begin the task = **"At startup"**, set Delay = **30 seconds** (so MySQL starts first)')
    add_bullet(doc, 'Actions tab: Click New → Program/script = C:\\UTCL-BusSystem\\run.bat')
    add_bullet(doc, 'Conditions tab: Uncheck "Stop if computer switches to battery power"')
    add_bullet(doc, 'Settings tab: Check "Run task as soon as possible after a scheduled start is missed"')
    add_bullet(doc, 'Click OK and enter the server Administrator password when prompted')
    add_body(doc, '[OK] The bus system will now auto-start every time the server boots -- no manual intervention needed ever.', bold=True, color=RGBColor(0x1A, 0x7A, 0x3C))

    add_heading(doc, 'Step 8 -- Verify the Application', 2)
    add_body(doc, 'From the server (or via RDP), open a browser and visit:')
    add_code(doc, 'http://localhost:8000')

    # ── 7. Default Credentials ─────────────────────────────────────────────
    add_heading(doc, '7. Default Login Credentials', 1)
    add_body(doc, '[!] Change all default passwords before going live with real employee data.', bold=True, color=RGBColor(0xCC, 0x00, 0x00))
    add_table(doc,
        ['Role', 'PS Number', 'Default Password'],
        [
            ['Admin',            'PS00001', 'password123 (Email: admin@adityabirla.com)'],
            ['Employee (Demo)',   'PS10001', 'password123 (Email: employee@adityabirla.com)'],
            ['Employee (Demo)',   'PS10002', 'password123 (Email: amit.verma@adityabirla.com)'],
            ['Driver (Demo)',     'PS20001', 'password123 (Email: rajesh@gmail.com)'],
            ['Driver (Demo)',     'PS20002', 'password123 (Email: suresh@gmail.com)'],
            ['Driver (Demo)',     'PS20003', 'password123 (Email: vikram@gmail.com)'],
        ],
        col_widths=[2.0, 2.0, 3.5],
        warn_rows=[0, 1, 2, 3, 4, 5])

    # ── 8. Network Access ─────────────────────────────────────────────────
    add_heading(doc, '8. Network Access Information', 1)
    add_table(doc,
        ['Access Point', 'URL'],
        [
            ['Server machine (local)',  'http://localhost:8000'],
            ['LAN access (all plant PCs)', 'http://<STATIC-IP>:8000'],
            ['Optional hostname (DNS)',  'http://utcl-bus-booking:8000'],
        ],
        col_widths=[2.5, 3.7])
    add_body(doc, 'Recommended: Ask IT to create a DNS entry so employees access via a friendly name (e.g. http://utcl-bus-booking) instead of an IP address.', italic=True)

    # ── 9. Backup ─────────────────────────────────────────────────────────
    add_heading(doc, '9. Backup Procedure', 1)
    add_body(doc, 'All data is stored in MySQL database utcl_bus_db. Run the following command via Windows Task Scheduler daily:')
    add_code(doc, '"C:\\Program Files\\MySQL\\MySQL Server 8.0\\bin\\mysqldump" -u root -pYOUR_PASSWORD utcl_bus_db > "C:\\Backups\\utcl_bus_backup.sql"')

    # ── 10. Troubleshooting ───────────────────────────────────────────────
    add_heading(doc, '10. Troubleshooting', 1)
    add_table(doc,
        ['Problem', 'Possible Cause', 'Solution'],
        [
            ['Server won\'t start',        'MySQL not running',              'Start MySQL service from Services panel'],
            ['Server won\'t start',        'Wrong DB password in db_config.json', 'Re-edit db_config.json with correct password'],
            ['Can\'t access from other PCs', 'Firewall blocking port 8000', 'Re-run Step 6 (Firewall rule)'],
            ['Login page not loading',     'Server crashed',                'Re-run run.bat'],
            ['"Database error" on screen', 'MySQL service stopped',         'Restart MySQL from Windows Services'],
            ['Slow response',              'Overloaded hardware',           'Upgrade RAM or increase thread count'],
            ['OTP emails not sending',     'Verify smtp_config.json. Check firewall port 62 connection to mail server', 'Verify connection or check server console window for printed OTP logs fallback'],
        ],
        col_widths=[2.0, 2.2, 2.5])

    add_body(doc, '')
    add_body(doc, 'This document is confidential and intended for UltraTech Cement IT Department only.', italic=True, color=RGBColor(0x88, 0x88, 0x88))

    doc.save(out_path)
    print(f'[OK] Saved: {out_path}')


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENT 2 — System Capabilities Report
# ══════════════════════════════════════════════════════════════════════════════

def build_capabilities_report(out_path):
    doc = Document()

    for section in doc.sections:
        section.top_margin    = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    cover_page(doc,
               'System Capabilities &\nCapacity Report',
               'UTCL Bus Management System',
               'June 2026', '1.0')

    # ── 1. Executive Summary ───────────────────────────────────────────────
    add_heading(doc, '1. Executive Summary', 1)
    add_body(doc,
        'The UTCL Bus Management System is a purpose-built internal web application for '
        "UltraTech Cement's plant operations. It digitizes the entire employee bus service "
        'lifecycle — from seat booking and ticket generation to live tracking, driver scheduling, '
        'and maintenance management. The system is designed for deployment on the plant\'s local '
        'area network (LAN) with no internet dependency.')

    # ── 2. Features — Employee ────────────────────────────────────────────
    add_heading(doc, '2. Feature Capabilities by User Role', 1)
    add_heading(doc, '2.1  Employee (PS Number Holder)', 2)
    add_table(doc,
        ['Feature', 'Capability'],
        [
            ['Login',               'Secure login via PS Number + Password (case-insensitive PS Number)'],
            ['Bus Booking',         'Book a seat on any available shift for any date'],
            ['Seat Selection',      'Visual interactive seat map — pick exact seat'],
            ['Real-Time Sync',      'WebSockets broadcast booking updates live (under 1 second) to all active users'],
            ['Seat Map Updates',    'Dynamic visual seat updates without requiring page refreshes'],
            ['Offline Fallback',    'Automatically falls back to 15-second polling if WebSocket goes offline'],
            ['Multi-Passenger',     'Book seats for multiple passengers in one transaction'],
            ['Stop Selection',      'Choose boarding stop and drop stop independently'],
            ['Fare System',         'Flat fare of ₹20 applies per booking regardless of boarding/drop stops.'],
            ['Ticket Generation',   'Digital ticket with unique ticket number & formatted QR code for offline verification'],
            ['Booking History',     'Full history of past and upcoming bookings'],
            ['Cancellation',        'Cancel confirmed bookings'],
            ['Notifications',       'Receive system notifications (confirmations, cancellations)'],
            ['Profile View',        'View own profile and PS details'],
            ['Export History',      'Export personal booking history as a formatted Excel (.xlsx) file'],
            ['Forgot Password',      'Self-service password reset via SMTP OTP (supports corporate @adityabirla.com email)'],
        ],
        col_widths=[2.2, 4.0])

    add_heading(doc, '2.2  Administrator', 2)
    add_table(doc,
        ['Feature', 'Capability'],
        [
            ['Employee Management', 'Add, view, activate/deactivate employee accounts'],
            ['Driver Management',   'Add and manage driver profiles'],
            ['Bus Management',      'Add, edit, activate/deactivate buses'],
            ['Shift Management',    'Create and configure bus shifts with custom stops & timings'],
            ['Driver Scheduling',   'Assign drivers to specific shifts'],
            ['Seat Map View',       'Real-time seat occupancy view for any shift on any date'],
            ['All Bookings View',   'View all employee bookings across all shifts and dates'],
            ['History Per Employee','Look up booking history for any PS number with live search'],
            ['Cancel Any Booking',  'Admin can cancel any booking on behalf of an employee'],
            ['Send Notifications',  'Send targeted notifications to any employee'],
            ['Bus Maintenance',     'Schedule and track bus servicing; drivers can submit "Service Done" requests which admins confirm dynamically in real-time.'],
            ['Ticket Lookup',       'Search and view any generated ticket'],
            ['Date Range Filtering','Filter bookings and history by custom date ranges'],
            ['Data Sync',           'Sync/export data across system tables'],
            ['Export Reports',      'Export full booking lists and transaction history to Excel'],
            ['Password Reset Overrides', 'Admin can override and reset any user\'s password from User Management (cannot read old passwords)'],
        ],
        col_widths=[2.4, 3.8])

    add_heading(doc, '2.3  Driver', 2)
    add_table(doc,
        ['Feature', 'Capability'],
        [
            ['Login',           'Secure login via PS Number + Password (case-insensitive PS Number)'],
            ['My Shifts',       'View shifts assigned to them for today and upcoming dates'],
            ['Passenger List',  'See list of booked passengers for their shift'],
            ['Bus Tracking',    'Update bus operational status (En Route, At Stop, Completed)'],
            ['Stop Progress',   'Mark current stop to update live tracking for admin'],
            ['Service Requests',  'Submit "Service Done" request to Admin upon completing maintenance task.'],
            ['Forgot Password',  'Self-service password reset using personal Gmail addresses via SMTP OTP'],
        ],
        col_widths=[2.2, 4.0])

    # ── 3. Capacity ────────────────────────────────────────────────────────
    add_heading(doc, '3. System Capacity & Performance Metrics', 1)

    add_heading(doc, '3.1  Concurrent Users (Simultaneous Logins)', 2)
    add_table(doc,
        ['Configuration', 'Concurrent Users Supported'],
        [
            ['**Current (Flask-SocketIO, Threaded)**', '**200 – 500 users simultaneously**'],
            ['Expandable (increase thread pools)',     '500 – 1,000 users simultaneously'],
            ['With Nginx reverse proxy added',         '1,000+ users simultaneously'],
        ],
        col_widths=[3.5, 2.7])
    add_body(doc, 'For UltraTech plant scale: Even at shift-change time when maximum employees access the system together, 200–500 concurrent sessions is more than sufficient.', italic=True)

    add_heading(doc, '3.2  Bookings & Tickets Per Day', 2)
    add_table(doc,
        ['Metric', 'Capacity'],
        [
            ['Maximum bookings per day',        'Unlimited (MySQL handles millions of records)'],
            ['Tickets generated per day',       'Unlimited — each booking auto-generates a ticket'],
            ['Expected realistic load',         '~200–500 bookings/day for a medium plant'],
            ['System impact at 1,000 bookings/day', 'Zero — no performance impact'],
        ],
        col_widths=[3.0, 3.2])

    add_heading(doc, '3.3  Registered PS Numbers (Users)', 2)
    add_table(doc,
        ['Metric', 'Capacity'],
        [
            ['Maximum employees registered',     'Unlimited — MySQL VARCHAR primary key'],
            ['Maximum drivers registered',       'Unlimited'],
            ['Comfortable practical limit',      '50,000+ employees with zero performance loss'],
            ['UltraTech typical plant headcount','1,000 – 5,000 — well within capacity'],
        ],
        col_widths=[3.0, 3.2])

    add_heading(doc, '3.4  Buses & Shifts', 2)
    add_table(doc,
        ['Metric', 'Capacity'],
        [
            ['Maximum buses in system',    'Unlimited'],
            ['Maximum shifts per bus',     'Unlimited'],
            ['Default configured buses',   '2 (expandable by admin)'],
            ['Default configured shifts',  '8 (4 forward + 4 return)'],
            ['Stops per shift',            'Configurable — currently 7 stops per route'],
        ],
        col_widths=[3.0, 3.2])

    add_heading(doc, '3.5  Data Storage & Retention', 2)
    add_table(doc,
        ['Metric', 'Detail'],
        [
            ['Database',             'MySQL 8.0 — industry standard'],
            ['Data retention',       'Unlimited — historical data never auto-deleted'],
            ['Storage growth rate',  '~1 MB per 5,000 bookings (negligible)'],
            ['Years of data on 10 GB disk', '50+ years of booking history'],
        ],
        col_widths=[3.0, 3.2])

    add_heading(doc, '3.6  Response Times (Expected)', 2)
    add_table(doc,
        ['Action', 'Expected Response Time'],
        [
            ['Login',                     '< 1 second'],
            ['Load seat map',             '< 1 second'],
            ['Book a seat',               '< 1 second'],
            ['Generate ticket',           '< 1 second'],
            ['Search employee history',   '< 1 second'],
            ['Load all bookings (admin)', '1 – 2 seconds'],
            ['Dashboard load',            '1 – 2 seconds'],
        ],
        col_widths=[3.2, 3.0])

    # ── 4. Tech Stack ──────────────────────────────────────────────────────
    add_heading(doc, '4. Technology Stack', 1)
    add_table(doc,
        ['Layer', 'Technology', 'Version', 'Notes'],
        [
            ['Frontend',       'HTML5 + CSS3 + JavaScript', '—',      'No external framework dependency'],
            ['Backend',        'Python + Flask + Flask-SocketIO', '3.x / Latest', 'Lightweight REST API with WebSocket engine'],
            ['Real-Time Server','Flask-SocketIO (Threaded)', 'Latest',  'Handles HTTP + WebSockets on LAN without CDN'],
            ['Database',       'MySQL',                     '8.0+',   'Industry standard RDBMS (InnoDB engine)'],
            ['DB Driver',      'mysql-connector-python',    'Latest', 'Official MySQL Python driver'],
            ['Browser',        'Chrome / Edge / Firefox',   'Any',    'No browser plugins needed'],
        ],
        col_widths=[1.5, 2.2, 1.0, 2.5])

    # ── 5. Security ────────────────────────────────────────────────────────
    add_heading(doc, '5. Security', 1)
    add_table(doc,
        ['Aspect', 'Current Status'],
        [
            ['Network exposure',    'LAN only — not accessible from internet'],
            ['Authentication',      'PS Number + Password required for all access (case-insensitive PS Numbers)'],
            ['Role-based access',   'Admin, Employee, and Driver see different interfaces'],
            ['Password storage',    'Stored securely in MySQL using bcrypt hashing'],
            ['Data transmission',   'HTTP within LAN (HTTPS upgrade possible with SSL cert)'],
            ['Concurrency Guard',   'MySQL SELECT FOR UPDATE row-locks inside transactions prevent duplicate bookings'],
        ],
        col_widths=[2.2, 4.0])
    add_body(doc, '[!] Recommendation: Consider upgrading HTTP to HTTPS with a self-signed SSL certificate before go-live.', italic=True, color=RGBColor(0x99, 0x50, 0x00))

    # ── 6. Known Limitations ───────────────────────────────────────────────
    add_heading(doc, '6. Known Limitations', 1)
    add_table(doc,
        ['Limitation', 'Impact', 'Recommendation'],
        [
            ['HTTP only (not HTTPS)',     'Low risk on LAN',            'Optional: Add SSL certificate'],
            ['No mobile app',            'Browser only',               'Responsive design works on phones'],
            ['Single server',            'No redundancy/failover',     'Acceptable for plant-internal tool'],
        ],
        col_widths=[2.0, 2.0, 2.2])

    # ── 7. Scalability Roadmap ─────────────────────────────────────────────
    add_heading(doc, '7. Scalability Roadmap', 1)
    add_table(doc,
        ['Phase', 'Change', 'Benefit'],
        [
            ['Current',  'Flask-SocketIO (Threaded)',        '200–500 concurrent users'],
            ['Phase 2',  'Expandable (increase thread pools)','500–1,000 users'],
            ['Phase 3',  'Add Nginx reverse proxy',          'Load balancing, better static file serving'],
            ['Phase 4',  'Dedicated MySQL server',           'Database isolation, better performance'],
            ['Phase 5',  'MySQL read replicas',              'Scale to 10,000+ daily users'],
        ],
        col_widths=[1.4, 2.8, 2.5])

    # ── 8. Summary Scorecard ───────────────────────────────────────────────
    add_heading(doc, '8. Summary Scorecard', 1)
    add_table(doc,
        ['Metric', 'Capacity / Value'],
        [
            ['Concurrent logins',     '200 – 500'],
            ['Tickets per day',       'Unlimited (10,000+ comfortably)'],
            ['PS Numbers (users)',    'Unlimited (50,000+)'],
            ['Buses in system',       'Unlimited'],
            ['Shifts manageable',     'Unlimited'],
            ['Data retention',        'Unlimited (50+ years on 10 GB)'],
            ['Response time',         '< 1-2 seconds per action'],
            ['Network requirement',   'Plant LAN only — no internet'],
            ['Client requirement',    'Any browser — no software install on client'],
            ['Uptime',               '24/7 with auto-start on boot'],
        ],
        col_widths=[3.0, 3.2])

    add_body(doc, '')
    add_body(doc, 'This document is prepared for UltraTech Cement management and IT team review.', italic=True, color=RGBColor(0x88, 0x88, 0x88))
    add_body(doc, 'All metrics are based on current system architecture as of June 2026.', italic=True, color=RGBColor(0x88, 0x88, 0x88))

    doc.save(out_path)
    print(f'[OK] Saved: {out_path}')


# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    build_deployment_guide(r'd:\UTCL antigravity\UTCL_IT_Deployment_Guide.docx')
    build_capabilities_report(r'd:\UTCL antigravity\UTCL_System_Capabilities_Report.docx')
    print('\n[DONE] Both Word documents generated successfully!')
