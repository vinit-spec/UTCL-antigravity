"""
UTCL Internship Report Generator — Portrait Print-Ready Edition
All tables have locked column widths summing to the exact A4 printable width.
Page: A4 Portrait | Margins: 2.0cm × 2.5cm | Printable width: ~16.5cm / 6.50in
"""

import sys
from docx import Document
from docx.shared import Pt, Inches, RGBColor, Cm, Twips
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ─── Brand Colors ─────────────────────────────────────────────────────────────
UTCL_GREY   = RGBColor(0x58, 0x59, 0x5B)
UTCL_BLUE   = RGBColor(0x00, 0x57, 0xA8)
UTCL_YELLOW = RGBColor(0xFB, 0xB0, 0x40)
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)
DARK        = RGBColor(0x1A, 0x1A, 0x2E)
MID_GREY    = RGBColor(0x44, 0x44, 0x55)

# A4 Portrait printable width at 2.5cm L/R margins = 21 - 5 = 16 cm = 9072 twips
PAGE_W_TWIPS = 9072   # 6.30 inches in twentieths-of-a-point (twips)
PAGE_W_IN    = 6.30   # inches

# ─── XML/Layout Helpers ───────────────────────────────────────────────────────

def _set_cell_bg(cell, hex6: str):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    # Remove existing shd
    for old in tcPr.findall(qn('w:shd')):
        tcPr.remove(old)
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  hex6)
    tcPr.append(shd)

def _set_cell_borders(cell, color="C5D3E8", sz=4):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for old in tcPr.findall(qn('w:tcBorders')):
        tcPr.remove(old)
    tcBorders = OxmlElement('w:tcBorders')
    for side in ('top', 'left', 'bottom', 'right'):
        b = OxmlElement(f'w:{side}')
        b.set(qn('w:val'),   'single')
        b.set(qn('w:sz'),    str(sz))
        b.set(qn('w:space'), '0')
        b.set(qn('w:color'), color)
        tcBorders.append(b)
    tcPr.append(tcBorders)

def _cell_no_wrap(cell):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    noW = OxmlElement('w:noWrap')
    tcPr.append(noW)

def _lock_table_width(table, twips=None):
    """Force table to an exact width and disable autofit."""
    twips = twips or PAGE_W_TWIPS
    tbl   = table._tbl
    # CT_Tbl does not have get_or_add_tblPr — find or create manually
    tblPr = tbl.find(qn('w:tblPr'))
    if tblPr is None:
        tblPr = OxmlElement('w:tblPr')
        tbl.insert(0, tblPr)
    # Remove old tblW
    for old in tblPr.findall(qn('w:tblW')):
        tblPr.remove(old)
    tblW = OxmlElement('w:tblW')
    tblW.set(qn('w:w'),    str(twips))
    tblW.set(qn('w:type'), 'dxa')
    tblPr.append(tblW)
    # Disable autofit
    for old in tblPr.findall(qn('w:tblLayout')):
        tblPr.remove(old)
    tblLayout = OxmlElement('w:tblLayout')
    tblLayout.set(qn('w:type'), 'fixed')
    tblPr.append(tblLayout)


def _set_col_width(table, col_idx, twips):
    """Set every cell in a column to the exact twip width."""
    for cell in table.columns[col_idx].cells:
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        for old in tcPr.findall(qn('w:tcW')):
            tcPr.remove(old)
        tcW = OxmlElement('w:tcW')
        tcW.set(qn('w:w'),    str(twips))
        tcW.set(qn('w:type'), 'dxa')
        tcPr.append(tcW)

def _apply_col_widths(table, widths_in):
    """Apply a list of inch-based widths to columns.  Widths must sum <= PAGE_W_IN."""
    _lock_table_width(table)
    for i, w in enumerate(widths_in):
        _set_col_width(table, i, int(w * 1440))   # 1 inch = 1440 twips

def _para_spacing(para, before=0, after=0):
    pPr  = para._p.get_or_add_pPr()
    for old in pPr.findall(qn('w:spacing')):
        pPr.remove(old)
    sp = OxmlElement('w:spacing')
    sp.set(qn('w:before'), str(before))
    sp.set(qn('w:after'),  str(after))
    pPr.append(sp)

def _add_run(para, text, bold=False, italic=False,
             color=None, size=None, font="Calibri"):
    r = para.add_run(text)
    r.bold       = bold
    r.italic     = italic
    r.font.name  = font
    if color: r.font.color.rgb = color
    if size:  r.font.size      = Pt(size)
    return r

def _yellow_rule(doc, thickness=18):
    p    = doc.add_paragraph()
    pPr  = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bot  = OxmlElement('w:bottom')
    bot.set(qn('w:val'),   'single')
    bot.set(qn('w:sz'),    str(thickness))
    bot.set(qn('w:space'), '1')
    bot.set(qn('w:color'), 'FBB040')
    pBdr.append(bot); pPr.append(pBdr)
    _para_spacing(p, before=40, after=100)

def _blue_rule(doc, thickness=8):
    p    = doc.add_paragraph()
    pPr  = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bot  = OxmlElement('w:bottom')
    bot.set(qn('w:val'),   'single')
    bot.set(qn('w:sz'),    str(thickness))
    bot.set(qn('w:space'), '1')
    bot.set(qn('w:color'), '0057A8')
    pBdr.append(bot); pPr.append(pBdr)
    _para_spacing(p, before=40, after=60)

# ─── High-Level Building Blocks ───────────────────────────────────────────────

def heading(doc, text, color=UTCL_BLUE, size=13, bold=True,
            before=200, after=80, align=WD_ALIGN_PARAGRAPH.LEFT):
    p = doc.add_paragraph()
    p.alignment = align
    _para_spacing(p, before=before, after=after)
    _add_run(p, text, bold=bold, color=color, size=size)
    return p

def subheading(doc, text, color=UTCL_GREY, size=10.5, before=160, after=40):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _para_spacing(p, before=before, after=after)
    _add_run(p, text, bold=True, color=color, size=size)
    return p

def body(doc, text, size=9.5, before=0, after=80):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    _para_spacing(p, before=before, after=after)
    _add_run(p, text, size=size, color=DARK)
    return p

def bullet(doc, text, size=9.5):
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.left_indent = Inches(0.25)
    _para_spacing(p, before=0, after=50)
    _add_run(p, text, size=size, color=DARK)
    return p

# ─── Table Builders ───────────────────────────────────────────────────────────
# All column widths in every table sum to exactly PAGE_W_IN (6.30 in)

def kv_table(doc, rows, w1=2.00, w2=4.30):
    """Two-column key-value info table. w1+w2 must equal PAGE_W_IN."""
    assert abs(w1 + w2 - PAGE_W_IN) < 0.05, f"KV table widths {w1+w2} != {PAGE_W_IN}"
    tbl = doc.add_table(rows=len(rows), cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    _apply_col_widths(tbl, [w1, w2])
    for i, (k, v) in enumerate(rows):
        row = tbl.rows[i]
        # key
        kc = row.cells[0]
        _set_cell_bg(kc,    "E8EEF6")
        _set_cell_borders(kc, "C5D3E8")
        kp = kc.paragraphs[0]
        kp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _para_spacing(kp, before=50, after=50)
        _add_run(kp, k, bold=True, color=UTCL_BLUE, size=9)
        # value
        vc = row.cells[1]
        _set_cell_bg(vc,    "FFFFFF")
        _set_cell_borders(vc, "C5D3E8")
        vp = vc.paragraphs[0]
        vp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _para_spacing(vp, before=50, after=50)
        _add_run(vp, v, size=9, color=DARK)
    doc.add_paragraph()

def data_table(doc, headers, rows, col_widths_in):
    """Multi-column data table with a solid-blue header row.
       col_widths_in must be a list that sums to PAGE_W_IN."""
    assert abs(sum(col_widths_in) - PAGE_W_IN) < 0.06, \
        f"Table widths {sum(col_widths_in):.2f} != {PAGE_W_IN}"
    tbl = doc.add_table(rows=1 + len(rows), cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    _apply_col_widths(tbl, col_widths_in)
    # Header row
    hrow = tbl.rows[0]
    for ci, h in enumerate(headers):
        c = hrow.cells[ci]
        _set_cell_bg(c,      "0057A8")
        _set_cell_borders(c, "0057A8")
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _para_spacing(p, before=55, after=55)
        _add_run(p, h, bold=True, color=WHITE, size=8.5)
    # Data rows
    for ri, row_data in enumerate(rows):
        bg = "FFFFFF" if ri % 2 == 0 else "EDF2FA"
        drow = tbl.rows[ri + 1]
        for ci, val in enumerate(row_data):
            c = drow.cells[ci]
            _set_cell_bg(c,      bg)
            _set_cell_borders(c, "C5D3E8")
            p = c.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _para_spacing(p, before=40, after=40)
            _add_run(p, val, size=8.5, color=DARK)
    doc.add_paragraph()


# ─── COVER PAGE ───────────────────────────────────────────────────────────────

def cover(doc):
    # Top brand bar
    bar = doc.add_table(rows=1, cols=1)
    _apply_col_widths(bar, [PAGE_W_IN])
    c = bar.rows[0].cells[0]
    _set_cell_bg(c, "58595B")
    p = c.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_spacing(p, before=220, after=220)
    _add_run(p, "ADITYA BIRLA GROUP   |   ULTRATECH CEMENT LIMITED",
             bold=True, color=UTCL_YELLOW, size=11.5)

    # Yellow accent rule
    _yellow_rule(doc, 24)

    sp = doc.add_paragraph()
    _para_spacing(sp, before=80, after=80)

    # Report type label
    rt = doc.add_paragraph()
    rt.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_spacing(rt, before=160, after=40)
    _add_run(rt, "INTERNSHIP COMPLETION REPORT", bold=True, color=UTCL_GREY, size=12)

    # Main title
    mt = doc.add_paragraph()
    mt.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_spacing(mt, before=60, after=40)
    _add_run(mt, "IT Automation & Software Engineering Internship",
             bold=True, color=UTCL_BLUE, size=20)

    # Subtitle
    st = doc.add_paragraph()
    st.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_spacing(st, before=40, after=200)
    _add_run(st, "Awarpur Cement Works — Integrated Unit 03",
             italic=False, color=UTCL_GREY, size=12)

    _blue_rule(doc, 10)

    # Intern details table
    kv_table(doc, [
        ("Intern Name",          "Mr. Vinit Deogade"),
        ("Institution",          "Universal AI University — B.Tech, Artificial Intelligence & Machine Learning (AIML)"),
        ("Organization",         "UltraTech Cement Limited, Aditya Birla Group"),
        ("Plant / Unit",         "Awarpur Cement Works (ACW) — Integrated Unit Designation 03"),
        ("Department",           "Information Technology Department"),
        ("Reporting HOD",        "Mr. Parmil (HOD, IT)  |  Section Head: Mr. Manish (IT)"),
        ("Internship Period",     "11 May 2026 – 10 July 2026   (60 Working Days)"),
        ("Blood Group",          "B+VE"),
    ])

    _blue_rule(doc, 8)

    foot = doc.add_paragraph()
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_spacing(foot, before=160, after=0)
    _add_run(foot,
             "Awarpur Cement Works  ·  Post: Awarpur  ·  Dist. Chandrapur (M.S.)  ·  Pin: 442917",
             italic=True, color=UTCL_GREY, size=8.5)

    doc.add_page_break()


# ─── SECTION 1 — Executive Summary ───────────────────────────────────────────

def executive_summary(doc):
    heading(doc, "1.   EXECUTIVE SUMMARY", size=13)
    _yellow_rule(doc)

    body(doc,
        "This report documents the complete 60-day IT Automation & Software Engineering Internship "
        "undertaken by Mr. Vinit Deogade at UltraTech Cement Limited's Awarpur Cement Works (ACW), "
        "a flagship Integrated Manufacturing Unit of the Aditya Birla Group. The internship spanned "
        "two distinct operational phases: Month 1 — enterprise IT infrastructure deployment, "
        "industrial networking, and systems administration across active manufacturing zones; "
        "Month 2 — full-stack design, development, and delivery of a production-grade enterprise "
        "software product: the UTCL Bus Management System.")

    body(doc,
        "During the infrastructure phase, the intern executed enterprise IT operations including "
        "bare-metal endpoint provisioning, Active Directory domain integration, Cisco Catalyst "
        "switch configuration via serial console, OFC fiber patching, server room audits, and "
        "industrial OT/IT network topology analysis across a 74-switch managed switching fabric. "
        "Direct production-floor deployment was achieved under strict industrial PPE protocols "
        "inside the Central Control Room (CCR) of an active cement manufacturing plant.")

    body(doc,
        "During the software engineering phase, the intern independently architected, engineered, "
        "and delivered the UTCL Bus Management System — a full-stack enterprise SPA comprising a "
        "Python Flask REST API, MySQL relational database (13 tables), real-time WebSocket engine, "
        "Bcrypt authentication, Excel export pipelines, SMTP OTP recovery, and three role-based "
        "access portals (Admin, Employee, Driver). The system is production-live.")

    subheading(doc, "Key Outcome Metrics", before=180, after=60)
    data_table(doc,
        ["Metric", "Value"],
        [
            ("Total Internship Duration",           "60 Days — 11 May to 10 July 2026"),
            ("Infrastructure Deployment Phase",     "~Month 1 (20 Working Days)"),
            ("Software Engineering Phase",          "~Month 2 (40 Working Days)"),
            ("Managed Network Scope",               "74 Switches + Multiple Firewalls + OFC Backbone"),
            ("Endpoints Provisioned",               "Multiple Windows 11 Pro Workstations — AD Domain-Joined"),
            ("Cisco Switches Configured",           "Multiple Catalyst Units via PuTTY Serial Console + Web GUI"),
            ("Enterprise Software Delivered",       "UTCL Bus Management System (Production-Live)"),
            ("REST API Endpoints",                  "30+ Endpoints across 6 Functional Domains"),
            ("Database Tables Designed",            "13 Relational Tables — MySQL (utcl_bus_db)"),
            ("WebSocket Event Types",               "11 Bi-Directional Real-Time Events"),
            ("Role-Based Portals",                  "3 — Admin · Employee · Driver"),
            ("Deployment Architectures Documented", "3 — Docker / Windows NSSM / Linux Nginx + Gunicorn"),
        ],
        [3.10, 3.20]
    )
    doc.add_page_break()


# ─── SECTION 2 — Month 1 ─────────────────────────────────────────────────────

def month1(doc):
    heading(doc, "2.   MONTH 1 — INFRASTRUCTURE, NETWORKING & SYSTEMS DEPLOYMENT", size=13)
    _yellow_rule(doc)

    body(doc,
        "The first month was conducted under the direct supervision of HOD Parmil and "
        "Section Head Manish. The intern was embedded into active enterprise IT operations, "
        "performing real-world tasks across hardware servicing, network configuration, endpoint "
        "provisioning, and industrial infrastructure management within UltraTech's Awarpur Cement "
        "Works — one of India's most sophisticated integrated cement manufacturing facilities.")

    # 2.1
    subheading(doc, "2.1   Week 1 — Induction, Orientation & Infrastructure Familiarization")

    subheading(doc, "Day 1 — Corporate Induction & EHS Safety Orientation", color=UTCL_BLUE, size=9.5, before=120, after=30)
    body(doc,
        "Completed the formal corporate induction program, analyzing UltraTech's national industrial "
        "footprint: 23 Integrated Units, 23 Grinding Units, and 07 Bulk Terminals. Awarpur Cement "
        "Works identified as Integrated Unit Designation 03. Completed mandatory EHS induction "
        "for active manufacturing zone access, covering kiln and packing plant protocols, PPE "
        "requirements, and emergency response procedures.")

    subheading(doc, "Day 2 — IT Department Onboarding & Network Access Control Policy", color=UTCL_BLUE, size=9.5, before=100, after=30)
    body(doc,
        "Formally onboarded into the IT Department. Processed hardware asset gate passes. "
        "Studied strict Layer 2 port security and Network Access Control (NAC) policies enforcing "
        "personal device restrictions on physical Ethernet infrastructure — a critical industrial "
        "cybersecurity control separating corporate IT from manufacturing OT networks.")

    subheading(doc, "Day 3 — Identity Access Management (IAM) Integration", color=UTCL_BLUE, size=9.5, before=100, after=30)
    body(doc,
        "Integrated physical identity profiles into the Time Office IAM system. Executed facial "
        "telemetry biometric registration enabling automated single-occupancy access control for "
        "secured administrative zones and automated entry gates within the plant campus.")

    subheading(doc, "Day 4 — Hardware Servicing & Network Printer Provisioning", color=UTCL_BLUE, size=9.5, before=100, after=30)
    body(doc,
        "Performed bare-metal workstation hardware diagnostics: disassembled chassis units, mapped "
        "CPU socket types, motherboard form factors, and DRAM slot configurations. Executed legacy "
        "system optimization via SSD upgrades. Provisioned enterprise multi-function departmental "
        "network printers via static IP addressing (10.145.2.82).")

    subheading(doc, "Day 5 — SAP ERP Modules & Plant-Wide Network Topology Analysis", color=UTCL_BLUE, size=9.5, before=100, after=30)
    body(doc,
        "Analyzed SAP ERP deployment modules (Functional, Technical, Hybrid). Reviewed the "
        "plant's macro-level network topology — a 74-switch managed fabric with multiple firewall "
        "appliances enforcing a boundary between corporate IT (Plant Core Boundary) and industrial "
        "OT networks (ACW Overall Boundary), preserving SCADA and DCS system integrity.")

    # 2.2
    subheading(doc, "2.2   Week 2 — Enterprise Endpoint Provisioning & Domain Integration")

    subheading(doc, "Days 8–10 — Bare-Metal Workstation Provisioning", color=UTCL_BLUE, size=9.5, before=120, after=30)
    for b in [
        "Clean OS installs: Windows 11 Pro via F9 boot menu (UEFI/Legacy); storage partition table configuration.",
        "Standardized corporate asset naming syntax applied (e.g., UTCACWHDDTO138 — plant/department/sequence encoded).",
        "Active Directory (AD) domain join for centralized user management and Group Policy Object enforcement.",
        ".NET Framework runtime enablement via Windows Features (appwiz.cpl).",
        "Full enterprise software stack deployment: Microsoft Office 2024, SAP GUI (BD-Presentation paths), Zscaler Zero Trust Client, SummitAssetAgent inventory tracker.",
    ]:
        bullet(doc, b)

    subheading(doc, "Days 11–12 — IT Asset Logistics & Preventive Endpoint Maintenance", color=UTCL_BLUE, size=9.5, before=100, after=30)
    body(doc,
        "Managed receipt and staging of high-value corporate-grade managed switches (~₹1 Lakh "
        "each) into the IT Training Room. Executed daily preventive maintenance rotations: booting "
        "stored laptops to force network check-ins for OS security patches, GPO enforcement, and "
        "battery charge conditioning.")

    subheading(doc, "Day 15 — Laptop Power Subsystem Diagnostics & Battery Electronics", color=UTCL_BLUE, size=9.5, before=100, after=30)
    body(doc,
        "Collaborated with an HP field service technician on a dead charging port diagnosis. "
        "Studied motherboard parallel power-rail switching (no-battery boot bypass). Examined "
        "internal battery 3-Series (3S) lithium cell topology and the embedded Battery Management "
        "System (BMS) controller — analyzing overcharge protection and thermal runaway prevention.")

    # 2.3
    subheading(doc, "2.3   Week 3 — Cisco Switch Configuration & Production Network Deployment")

    subheading(doc, "Day 16 — Cisco Catalyst Switch Configuration via Serial Console", color=UTCL_BLUE, size=9.5, before=120, after=30)
    for b in [
        "PuTTY serial console sessions (RS-232, 9600 baud) — escalated to privileged EXEC mode; assigned global Enable Secret Keys.",
        "Provisioned static management IP addresses on VLAN interfaces for Layer 3 management plane access.",
        "Verified Layer 3 connectivity via continuous ping testing (ping -t); monitored active ports via Cisco Device Manager Web GUI.",
        "Reviewed OFC backbone standards and SFP transceiver specifications for inter-switch uplink connections.",
    ]:
        bullet(doc, b)

    subheading(doc, "Day 17 — Production-Floor Switch Hot-Swap Deployment (Central Control Room)", color=UTCL_BLUE, size=9.5, before=100, after=30)
    body(doc,
        "Executed a live production network switch hot-swap inside the Central Control Room (CCR) — "
        "a secured zone requiring industrial PPE (helmet, reflective jacket, steel-toe boots) and "
        "biometric single-occupancy face recognition access. Removed legacy hardware, installed "
        "new Cisco Catalyst units, re-terminated OFC patch cables, and verified link re-establishment. "
        "Finalized formal corporate change-management email documentation with static IPs and timestamps.")

    # 2.4
    subheading(doc, "2.4   Week 4 — AV Operations, Server Room Audits & EHS Compliance")

    subheading(doc, "Days 18–20 — AV Infrastructure Operations & First Aid Training Program", color=UTCL_BLUE, size=9.5, before=120, after=30)
    body(doc,
        "Managed full AV operations at Manthan Conference Hall for a 3-day plant-wide First Aid "
        "External Training Program hosted by MediHSE Training Academy LLP: system setup, microphone "
        "calibration, projection alignment, and live technical monitoring. Concurrently attended "
        "emergency response, occupational hazard identification, and first aid modules.")

    subheading(doc, "Month-End Supplemental Operations", color=UTCL_BLUE, size=9.5, before=100, after=30)
    for b in [
        "Print Services Logistics: Toner cartridge inventory tracking and replacement workflows across departmental printers.",
        "Server Room Audits: Monitored redundant HVAC cooling, humidity control, and UPS battery bank backup capacity.",
        "EHS Theme Alignment: Aligned IT operations with UltraTech's Monthly EHS operational theme, reinforcing ISO-aligned safety culture.",
    ]:
        bullet(doc, b)

    subheading(doc, "Month 1 — Technology & Skills Matrix", before=180, after=60)
    data_table(doc,
        ["Domain", "Technologies & Skills Applied"],
        [
            ("Operating Systems",           "Windows 11 Pro · UEFI Boot Management · Active Directory Domain Services"),
            ("Networking",                  "Cisco Catalyst Switches · PuTTY Serial Console · Layer 2/3 Config · OFC/SFP"),
            ("Security",                    "NAC Policy · Layer 2 Port Security · Zscaler Zero Trust · Biometric IAM"),
            ("Hardware",                    "Bare-Metal Servicing · SSD Upgrades · Battery Electronics · BMS · Printer Provisioning"),
            ("Enterprise Software",         "SAP GUI · Microsoft Office 2024 · SummitAssetAgent · GPO · .NET Framework"),
            ("Infrastructure Management",   "Server Room Audits · UPS/HVAC Monitoring · Asset Logistics · Change Management"),
            ("EHS / Compliance",            "Industrial PPE · EHS Induction · MediHSE First Aid · ISO Safety Culture"),
        ],
        [2.00, 4.30]
    )
    doc.add_page_break()


# ─── SECTION 3 — Month 2 ─────────────────────────────────────────────────────

def month2(doc):
    heading(doc, "3.   MONTH 2 — FULL-STACK SOFTWARE ENGINEERING", size=13)
    _yellow_rule(doc)

    body(doc,
        "The second month transitioned into full-stack enterprise software engineering. The intern "
        "independently conceived, designed, architected, and delivered the UTCL Bus Management "
        "System — a production-grade enterprise transit management platform addressing a genuine "
        "operational requirement: digitizing and automating the management of 2 physical corporate "
        "buses operating 8 daily shifts across a 7-stop fixed bidirectional route.")

    # 3.1 Project Overview
    subheading(doc, "3.1   Project Overview — UTCL Bus Management System")
    kv_table(doc, [
        ("Project Title",        "UTCL Bus Management System"),
        ("Project Type",         "Enterprise Internal Transport Management Platform (Production-Live)"),
        ("Architecture",         "Single Page Application (SPA) — Client-Server + WebSocket Real-Time Engine"),
        ("Backend Stack",        "Python 3 · Flask REST API · Flask-SocketIO · Bcrypt · openpyxl"),
        ("Frontend Stack",       "Vanilla JS (SPA Router) · HTML5 · Custom CSS · Chart.js · Socket.IO Client"),
        ("Database",             "MySQL 8.0 — utcl_bus_db  (13 Relational Tables · 32-Thread Connection Pool)"),
        ("Authentication",       "Bcrypt Password Hashing + SMTP OTP 6-Digit Password Recovery"),
        ("Access Control",       "Role-Based Access Control (RBAC) — Admin · Employee · Driver"),
        ("Route",                "Awalpur ↔ Bibee ↔ Gadchandur ↔ Manikgarh ↔ Rajura ↔ Ballarsha ↔ Chandrapur"),
        ("Fleet",                "2 Buses · 8 Daily Shifts (4 Forward + 4 Return) · 40 Seats per Bus"),
        ("Fare",                 "Flat ₹20 per Booking — independent of boarding / drop stop selection"),
        ("Deployment Status",    "Production-Live — 3 Deployment Architectures Documented"),
    ])

    # 3.2 Architecture
    subheading(doc, "3.2   System Architecture")
    for b in [
        "Zero-Page-Reload SPA: The entire frontend operates as a single index.html. Navigation is handled by a client-side JS router via DOM class manipulation — eliminating full-page loads entirely.",
        "WebSocket Real-Time State Engine: All seat availability, booking confirmations, shift cancellations, driver attendance, payroll updates, and live tracking broadcast instantly via 11 Socket.IO event types to all connected clients.",
        "32-Thread MySQL Connection Pool: mysql.connector.pooling maintains 32 persistent connections — preventing connection overhead and pool exhaustion under concurrent multi-user load, with automatic retry fallback.",
        "Rotating File Audit Logger: All API activity captured via Python RotatingFileHandler — 5 MB rotation, full operational audit trail.",
        "Threaded Flask Server: Runs in threaded mode enabling concurrent HTTP and WebSocket handling without request blocking.",
    ]:
        bullet(doc, b)

    # 3.3 Database Schema
    subheading(doc, "3.3   Database Schema — 13 Relational Tables (utcl_bus_db)", before=180)
    body(doc,
        "All schema creation, index provisioning, and constraint definition execute automatically "
        "on server startup via idempotent CREATE TABLE IF NOT EXISTS statements.")
    data_table(doc,
        ["Table", "Purpose", "Key Fields"],
        [
            ("users",                  "User registry — employees, admins, drivers",         "id, psNumber (UNIQUE), role, password (bcrypt), plant"),
            ("buses",                  "Fleet inventory",                                      "id, identifier, isActive"),
            ("shifts",                 "Daily schedules with JSON stop arrays",                "id, busId, direction, departureTime, stops (JSON)"),
            ("driver_shifts",          "Driver-to-shift roster assignments",                   "driverId, shiftId, date"),
            ("driver_attendance",      "Clock-in/out with photo URL verification",             "departurePhotoUrl, arrivalPhotoUrl, status"),
            ("bookings",               "Passenger seat reservation ledger",                    "shiftId, psNumber, seatNumber, fareAmount, status"),
            ("tickets",                "Virtual boarding passes with unique serial codes",     "ticketNumber (UNIQUE), boardingStop, dropStop, fare"),
            ("maintenance",            "Fleet servicing schedule and history",                  "busId, scheduledDate, description, status"),
            ("tracking",               "Live bus operational status and last known stop",      "busId (PK), operationalStatus, currentStopIndex"),
            ("notifications",          "In-app passenger message center",                      "recipientUserId, message, isRead, createdAt"),
            ("payroll_periods",        "Monthly payroll cycle aggregation headers",             "periodMonth, totalAmount, status (DRAFT/PROCESSED/LOCKED)"),
            ("fare_deductions",        "Per-employee monthly billing line items",               "psNumber, totalRides, totalAmount"),
            ("password_reset_tokens",  "SMTP OTP authentication tokens",                       "psNumber, token (6-digit), expiresAt, used"),
        ],
        [1.55, 1.95, 2.80]
    )

    # 3.4 REST API
    subheading(doc, "3.4   REST API Architecture — 30+ Endpoints across 6 Domains", before=180)
    data_table(doc,
        ["Domain", "Key Endpoints", "Description"],
        [
            ("Authentication",     "POST /api/auth/login\nPOST /api/auth/forgot-password\nPOST /api/auth/verify-otp\nPOST /api/auth/reset-password",
             "Session auth, 6-digit SMTP OTP recovery, token verification, password operations."),
            ("Global Sync",        "POST /api/sync\nGET /api/db-status\nGET /api/data",
             "Bulk DB hydration in a single request, connectivity diagnostics, active schedule fetch."),
            ("Employee Booking",   "POST /api/booking/create\nPOST /api/booking/cancel/<id>\nGET /api/bookings/export\nGET /api/employees/search",
             "Atomic seat reservation with duplicate prevention, cancellation, PS-number lookup, Excel export."),
            ("Driver Portal",      "GET /api/driver/attendance/status\nPOST /api/driver/attendance/submit-departure\nPOST /api/driver/attendance/submit-arrival",
             "Duty roster status and dual-photo shift clock-in/clock-out with image upload."),
            ("Admin Operations",   "PATCH /api/admin/attendance/<id>\nPOST /api/admin/shifts/cancel-for-day\nGET /api/admin/shifts/<id>/export-manifest\nPOST /api/admin/reset-user-password",
             "Attendance approval, bulk shift cancellation cascade with auto-notifications, manifest generation."),
            ("Payroll Services",   "POST /api/payroll/generate\nPATCH /api/payroll/period/<id>/mark-processed\nPATCH /api/payroll/period/<id>/unlock\nGET /api/payroll/period/<id>/export\nGET /api/payroll/my-fares",
             "Monthly fare aggregation, DRAFT→PROCESSED→LOCKED lifecycle, Excel export, employee fare history."),
        ],
        [1.35, 2.35, 2.60]
    )

    doc.add_page_break()

    # 3.5 WebSocket Events
    subheading(doc, "3.5   Real-Time WebSocket Event Protocol — 11 Events", before=160)
    data_table(doc,
        ["Event", "Scope", "Effect"],
        [
            ("seat_held",               "Seat Room",    "Renders seat yellow on all clients during selection window."),
            ("seat_released",           "Seat Room",    "Returns seat to green (available) on deselection."),
            ("seat_booked",             "Seat Room",    "Permanently marks seat red (occupied) after confirmed booking."),
            ("SEAT_COUNT_UPDATED",      "Global",       "Decrements available seat counter on all schedule panels."),
            ("SHIFT_LOCKED",            "Global",       "Locks booking UI when departure window has passed."),
            ("SHIFT_CANCELLED_FOR_DAY", "Global",       "Cancels shift globally on all client views."),
            ("TRACKING_UPDATED",        "Global",       "Refreshes live bus position on admin tracking panel."),
            ("NEW_NOTIFICATION",        "User Room",    "Increments notification bell badge on target passenger."),
            ("NOTIFICATION_RECEIVED",   "User Room",    "Triggers instant in-app toast alert for target passenger."),
            ("ATTENDANCE_UPDATED",      "Global",       "Refreshes admin pending attendance and approval lists."),
            ("PAYROLL_UPDATED",         "Global",       "Updates payroll statistics and deduction ledger views."),
        ],
        [1.90, 1.10, 3.30]
    )

    # 3.6 Key Features
    subheading(doc, "3.6   Key Feature Implementations", before=180)

    subheading(doc, "A — Employee Ticket Booking & Virtual Boarding Pass", color=UTCL_BLUE, size=9.5, before=120, after=30)
    for b in [
        "Multi-step booking wizard: Schedule → Stop Validation → 40-Seat Grid → PS Number Verification → Confirmation → Ticket Generation.",
        "Atomic server-side transaction: checks seat availability, prevents duplicate shift/date bookings, commits only on full success.",
        "Virtual ticket with unique serial (UTCL-XXXXX), barcode rendering, boarding/drop stop, fare, and departure time.",
        "Real-time seat grid: Green (available) → Yellow (held, via seat_held WebSocket) → Red (occupied, via seat_booked).",
    ]:
        bullet(doc, b)

    subheading(doc, "B — Shift Cancellation & Automatic Notification Cascade", color=UTCL_BLUE, size=9.5, before=100, after=30)
    for b in [
        "Admin cancels a shift for a specific date with a reason string.",
        "Atomic DB transaction: batch-updates all confirmed bookings and tickets to CANCELLED status.",
        "Per-passenger: inserts notification record + emits NOTIFICATION_RECEIVED WebSocket event (instant toast alert).",
        "Emits SHIFT_CANCELLED_FOR_DAY globally — synchronizes all connected client views without manual refresh.",
    ]:
        bullet(doc, b)

    subheading(doc, "C — Driver Attendance with Photographic Verification", color=UTCL_BLUE, size=9.5, before=100, after=30)
    for b in [
        "Drivers submit departure and arrival selfies via the portal camera interface.",
        "Photos stored server-side with URL references in driver_attendance table.",
        "Admin reviews pending submissions and approves or rejects via PATCH request.",
        "Status transitions: PENDING → APPROVED / REJECTED — full history exportable to Excel.",
    ]:
        bullet(doc, b)

    subheading(doc, "D — Payroll Deduction & Monthly Billing Engine", color=UTCL_BLUE, size=9.5, before=100, after=30)
    for b in [
        "Admin triggers payroll generation for any calendar month — aggregates CONFIRMED bookings, computes per-employee totals (rides × ₹20).",
        "Payroll cycle lifecycle: DRAFT → PROCESSED → LOCKED — with unlock capability for HR amendments.",
        "Generates Excel spreadsheets (openpyxl) for submission to HR / Finance departments.",
        "Employees access personal fare deduction history via self-service /api/payroll/my-fares endpoint.",
    ]:
        bullet(doc, b)

    subheading(doc, "E — Live Bus Tracking & Fleet Status Panel", color=UTCL_BLUE, size=9.5, before=100, after=30)
    for b in [
        "Admin panel shows real-time operational status per bus: ACTIVE, IDLE, or UNDER_MAINTENANCE.",
        "Active buses display current shift assignment and last scanned route stop index.",
        "Status updates broadcast via TRACKING_UPDATED WebSocket event to all admin sessions.",
    ]:
        bullet(doc, b)

    subheading(doc, "F — UTCL Corporate Branding & UI Design System", color=UTCL_BLUE, size=9.5, before=100, after=30)
    for b in [
        "Primary palette: Grey #58595B (headers/panels) · Blue #0057A8 (actions/links) · Yellow #FBB040 (highlights/CTAs).",
        "Typography: Outfit (geometric sans-serif for headers, matching UTCL logo) + Inter (body and analytics text).",
        "Status semantics: Emerald #10B981 (success) · Amber #F59E0B (warning/pending) · Crimson #EF4444 (occupied/cancelled).",
        "Revenue and occupancy analytics rendered via Chart.js with dynamic date-range filtering.",
    ]:
        bullet(doc, b)

    # 3.7 Deployment
    subheading(doc, "3.7   Multi-Mode Deployment Architecture", before=180)
    data_table(doc,
        ["Option", "Stack", "Use Case"],
        [
            ("A — Docker Compose",         "Docker + MySQL 8.0 Container + Python 3.12-slim",      "Cloud hosting — full isolation, one-command deployment."),
            ("B — Windows NSSM Intranet",  "NSSM Windows Service + Local MySQL + Python venv",     "Plant intranet LAN — persistent Windows background service, no user login required."),
            ("C — Linux VPS + Nginx",       "Gunicorn (3 workers) + Nginx Reverse Proxy + Systemd", "High-availability public cloud — SSL termination and WebSocket upgrade proxy headers."),
        ],
        [1.65, 2.35, 2.30]
    )

    # 3.8 Additional Deliverables
    subheading(doc, "3.8   Additional Project Deliverables", before=160)
    for b in [
        "System Blueprint & Technical Specification (blueprint.md) — 400+ line reference covering architecture, DB schema ERD, API registry, WebSocket protocol, and deployment options.",
        "Requirements Document (requirements.md) — 13-requirement formal specification with SHALL/IF/WHEN acceptance criteria.",
        "User Guide (user_guide.md / user_guide.pdf) — End-user operational documentation for all three portal workflows.",
        "Load Testing Suite (locustfile.py) — Locust-based performance testing for API endpoint stress testing and concurrent user simulation.",
        "Data Import Utilities (import_users.py) — Bulk employee data import pipeline from Excel to MySQL user registry.",
        "B2B SaaS Commercial Proposal (PDF) — Formal commercial proposal positioning the system for replicable multi-plant deployment across UltraTech's national network.",
        "Audit & Verification Tooling (audit_app.py, verify_multi_plant_criteria.py, db_cleanup.py) — Database integrity, multi-plant validation, and operational audit scripts.",
    ]:
        bullet(doc, b)

    doc.add_page_break()


# ─── SECTION 4 — Skills Matrix ────────────────────────────────────────────────

def skills_section(doc):
    heading(doc, "4.   TECHNICAL SKILLS ACQUIRED", size=13)
    _yellow_rule(doc)

    data_table(doc,
        ["Skill Category", "Technologies & Competencies"],
        [
            ("Backend Engineering",       "Python · Flask REST API · Flask-SocketIO · Bcrypt · SMTP OTP · openpyxl · RotatingFileHandler"),
            ("Database Engineering",      "MySQL 8.0 · Relational Schema Design · Connection Pooling · Atomic Transactions · JSON Columns"),
            ("Frontend Engineering",      "Vanilla JavaScript SPA Architecture · DOM Routing · Socket.IO Client · Chart.js · CSS Design Systems"),
            ("Real-Time Systems",         "WebSocket Bi-Directional Events · Room-Based Broadcasting · Live State Synchronization"),
            ("Enterprise Networking",     "Cisco Catalyst Switch Configuration · PuTTY Serial Console · Layer 2/3 Management · OFC/SFP"),
            ("Systems Administration",    "Windows 11 Pro Provisioning · Active Directory Domain Join · GPO · Zscaler Zero Trust"),
            ("Industrial IT Operations",  "IT/OT Network Segmentation · NAC Policy · SCADA Boundary Architecture · Server Room Auditing"),
            ("Hardware Engineering",      "Bare-Metal Workstation Servicing · SSD Upgrades · BMS / Battery Electronics · Power Subsystems"),
            ("DevOps & Deployment",       "Docker Compose · NSSM Windows Services · Gunicorn WSGI · Nginx Reverse Proxy · Systemd"),
            ("Enterprise Software",       "SAP GUI · Microsoft Office 2024 · SummitAssetAgent · Corporate Asset Naming Conventions"),
            ("Project Delivery",          "Requirements Analysis · System Architecture Design · Technical Documentation · B2B Proposal Writing"),
            ("Safety & Compliance",       "EHS Industrial Safety · Industrial PPE · MediHSE First Aid · ISO Safety Culture Alignment"),
        ],
        [2.10, 4.20]
    )
    doc.add_page_break()


# ─── SECTION 5 — Conclusion ───────────────────────────────────────────────────

def conclusion(doc):
    heading(doc, "5.   CONCLUSIONS & PROFESSIONAL OUTCOMES", size=13)
    _yellow_rule(doc)

    body(doc,
        "The 60-day internship at UltraTech Cement Limited's Awarpur Cement Works delivered "
        "comprehensive, industry-grade professional exposure spanning two equally demanding "
        "engineering disciplines: enterprise IT infrastructure operations and full-stack "
        "enterprise product software engineering.")

    body(doc,
        "In Month 1, the intern operated as a functional member of the ACW IT Department — "
        "performing real production-critical tasks under actual enterprise constraints, "
        "including live network switch deployments inside an active industrial manufacturing "
        "plant. This phase instilled operational discipline, industrial safety awareness, "
        "and a deep understanding of enterprise IT infrastructure architecture at scale.",
        before=80)

    body(doc,
        "In Month 2, the intern demonstrated the ability to independently scope, design, "
        "architect, build, test, document, and deliver a complete enterprise software product "
        "from zero — within a real organizational context, for real operational use. The UTCL "
        "Bus Management System is not a prototype or academic exercise; it is a production-deployed "
        "enterprise application with a relational database backend, real-time WebSocket engine, "
        "multi-role access control, financial reporting pipeline, and documented multi-mode "
        "deployment architecture.",
        before=80)

    body(doc,
        "This internship established Vinit Deogade as a practitioner-level engineer with "
        "validated competencies across both IT infrastructure operations and enterprise full-stack "
        "software development — a rare combination directly aligned with the requirements of "
        "AI & ML engineering roles demanding both data systems depth and applied software "
        "engineering proficiency.",
        before=80)

    subheading(doc, "Declaration", before=280, after=60)
    body(doc,
        "I hereby declare that the information contained in this report is a true and accurate "
        "account of the work performed during my internship at UltraTech Cement Limited, "
        "Awarpur Cement Works, from 11 May 2026 to 10 July 2026.")

    kv_table(doc, [
        ("Intern Name",        "Mr. Vinit Deogade"),
        ("Institution",        "Universal AI University — B.Tech Artificial Intelligence & Machine Learning"),
        ("Internship Period",  "11 May 2026 – 10 July 2026   (60 Days)"),
        ("Date of Report",     "10 July 2026"),
        ("Signature",          ""),
    ])

    _blue_rule(doc, 8)

    foot = doc.add_paragraph()
    foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_spacing(foot, before=200, after=0)
    _add_run(foot,
             "UltraTech Cement Limited   |   Awarpur Cement Works   |   Aditya Birla Group\n"
             "Post: Awarpur, Dist. Chandrapur (M.S.) — Pin: 442917",
             italic=True, color=UTCL_GREY, size=8.5)


# ─── CERTIFICATE PAGE ───────────────────────────────────────────────────────────

def certificate_page(doc):
    """Company + Academic certificate placeholders on a single page."""

    # ── Company Certificate ─────────────────────────────────────────────────
    bar = doc.add_table(rows=1, cols=1)
    _apply_col_widths(bar, [PAGE_W_IN])
    c = bar.rows[0].cells[0]
    _set_cell_bg(c, "0057A8")
    p = c.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_spacing(p, before=180, after=180)
    _add_run(p, "COMPANY INTERNSHIP CERTIFICATE", bold=True, color=WHITE, size=13)
    doc.add_paragraph()

    body(doc,
        "This is to certify that Mr. Vinit Deogade, a student of B.Tech in Artificial Intelligence "
        "& Machine Learning at Universal AI University, has successfully completed his internship "
        "training at UltraTech Cement Limited, Awarpur Cement Works, Dist. Chandrapur (M.S.) — "
        "an Integrated Unit of the Aditya Birla Group — for a period of 60 days "
        "from 11 May 2026 to 10 July 2026.",
        before=120, after=80)

    body(doc,
        "During the internship, he was assigned to the Information Technology Department and "
        "demonstrated commendable initiative, technical competence, and professional conduct. "
        "He actively participated in enterprise IT infrastructure operations and independently "
        "developed the UTCL Bus Management System (Project Code: UTCL-PRAVAS) — a production-grade "
        "enterprise transit management platform for the Awarpur Cement Works campus, which has been "
        "successfully deployed to the Railway cloud hosting platform.",
        after=80)

    body(doc,
        "The system is live and accessible at the following production URL:",
        after=40)

    # Live deployment URL — highlighted box
    url_tbl = doc.add_table(rows=1, cols=1)
    _apply_col_widths(url_tbl, [PAGE_W_IN])
    uc = url_tbl.rows[0].cells[0]
    _set_cell_bg(uc, "E8F0FE")
    _set_cell_borders(uc, "0057A8", 6)
    up = uc.paragraphs[0]
    up.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_spacing(up, before=100, after=100)
    _add_run(up, "Live Production URL:  ", bold=True, color=UTCL_GREY, size=9.5)
    _add_run(up, "https://utcl-pravas.up.railway.app/", bold=True, color=UTCL_BLUE, size=10)
    doc.add_paragraph()

    body(doc,
        "We wish him all the best in his future academic and professional endeavors.",
        after=200)


    # Signature block — Company
    sig = doc.add_table(rows=1, cols=2)
    _apply_col_widths(sig, [3.15, 3.15])
    _lock_table_width(sig)
    for ci, (lbl, val) in enumerate([
        ("Company Guide / HOD IT", "Mr. Parmil"),
        ("Authorized Signatory",  "UltraTech Cement Limited\nAwarpur Cement Works"),
    ]):
        cell = sig.rows[0].cells[ci]
        _set_cell_bg(cell, "F0F4FA")
        _set_cell_borders(cell, "C5D3E8", 4)
        cp = cell.paragraphs[0]
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _para_spacing(cp, before=80, after=0)
        _add_run(cp, lbl + "\n", bold=True, color=UTCL_BLUE, size=9)
        _add_run(cp, val, bold=False, color=DARK, size=9)
    doc.add_paragraph()

    # Stamp / Date row
    stamp = doc.add_table(rows=1, cols=2)
    _apply_col_widths(stamp, [3.15, 3.15])
    _lock_table_width(stamp)
    for ci, (lbl, val) in enumerate([
        ("Date",  "10 July 2026"),
        ("Seal",  "[Official Company Seal]"),
    ]):
        cell = stamp.rows[0].cells[ci]
        _set_cell_bg(cell, "FFFFFF")
        _set_cell_borders(cell, "C5D3E8", 4)
        sp = cell.paragraphs[0]
        sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _para_spacing(sp, before=60, after=60)
        _add_run(sp, lbl + ": ", bold=True, color=UTCL_GREY, size=9)
        _add_run(sp, val, color=DARK, size=9)

    _blue_rule(doc, 6)

    # ── Academic Certificate ─────────────────────────────────────────────────
    bar2 = doc.add_table(rows=1, cols=1)
    _apply_col_widths(bar2, [PAGE_W_IN])
    c2 = bar2.rows[0].cells[0]
    _set_cell_bg(c2, "58595B")
    p2 = c2.paragraphs[0]
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _para_spacing(p2, before=180, after=180)
    _add_run(p2, "ACADEMIC INSTITUTION CERTIFICATE", bold=True, color=UTCL_YELLOW, size=13)
    doc.add_paragraph()

    body(doc,
        "This is to certify that Mr. Vinit Deogade (Enrollment No.: ____________), "
        "a student of B.Tech — Artificial Intelligence & Machine Learning (Semester ___) "
        "at Universal AI University, has undertaken an industrial internship at "
        "UltraTech Cement Limited, Awarpur Cement Works from 11 May 2026 to 10 July 2026 "
        "as a partial fulfillment of the curriculum requirements.",
        before=100, after=80)

    body(doc,
        "The internship report submitted by him has been reviewed and is hereby certified "
        "as an authentic and original record of work carried out during the internship period "
        "under the guidance of the undersigned.",
        after=200)

    # Academic sig block
    asig = doc.add_table(rows=1, cols=2)
    _apply_col_widths(asig, [3.15, 3.15])
    _lock_table_width(asig)
    for ci, (lbl, val) in enumerate([
        ("Academic / Internal Guide", "Prof. ____________\nUniversal AI University"),
        ("Head of Department",        "Prof. ____________\nDept. of AIML"),
    ]):
        cell = asig.rows[0].cells[ci]
        _set_cell_bg(cell, "F0F4FA")
        _set_cell_borders(cell, "C5D3E8", 4)
        cp = cell.paragraphs[0]
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _para_spacing(cp, before=80, after=0)
        _add_run(cp, lbl + "\n", bold=True, color=UTCL_GREY, size=9)
        _add_run(cp, val, bold=False, color=DARK, size=9)
    doc.add_paragraph()

    astamp = doc.add_table(rows=1, cols=2)
    _apply_col_widths(astamp, [3.15, 3.15])
    _lock_table_width(astamp)
    for ci, (lbl, val) in enumerate([
        ("Date",  "10 July 2026"),
        ("Seal",  "[University Seal / Stamp]"),
    ]):
        cell = astamp.rows[0].cells[ci]
        _set_cell_bg(cell, "FFFFFF")
        _set_cell_borders(cell, "C5D3E8", 4)
        sp = cell.paragraphs[0]
        sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _para_spacing(sp, before=60, after=60)
        _add_run(sp, lbl + ": ", bold=True, color=UTCL_GREY, size=9)
        _add_run(sp, val, color=DARK, size=9)

    doc.add_page_break()


# ─── ACKNOWLEDGMENTS & DECLARATION ───────────────────────────────────────────

def acknowledgments(doc):
    heading(doc, "ACKNOWLEDGMENTS", size=15, before=120, after=80)
    _yellow_rule(doc)

    body(doc,
        "I would like to express my sincere gratitude to UltraTech Cement Limited for providing "
        "me with the opportunity to undertake this internship at the Awarpur Cement Works. "
        "This experience has been instrumental in bridging the gap between academic knowledge "
        "and real-world industrial engineering practice.",
        before=100, after=80)

    body(doc,
        "I am deeply grateful to Mr. Parmil, Head of Department — Information Technology, "
        "for his leadership, mentorship, and trust in assigning me meaningful, production-critical "
        "responsibilities throughout the internship. His industry perspective and guidance shaped "
        "my understanding of enterprise IT operations at scale.",
        after=80)

    body(doc,
        "I extend my sincere thanks to Mr. Manish, Section Head — IT, for his patient technical "
        "guidance, for supervising my day-to-day operational tasks, and for creating a professional "
        "environment that encouraged learning and initiative. His mentorship during the networking "
        "and infrastructure deployment phases was invaluable.",
        after=80)

    body(doc,
        "I am grateful to the entire IT Department team at Awarpur Cement Works for their "
        "warm welcome and collaborative support — for patiently explaining processes, sharing "
        "expertise, and making me feel a valued member of the team from Day 1.",
        after=80)

    body(doc,
        "I would also like to acknowledge the on-site HP field service technician for the "
        "technical knowledge shared during the laptop power subsystem diagnostics session, "
        "and MediHSE Training Academy LLP for the comprehensive First Aid training program.",
        after=80)

    body(doc,
        "Finally, I thank Universal AI University and my academic guide for their continued "
        "support and for facilitating this industrial internship as part of the B.Tech "
        "curriculum — enabling practical exposure that no classroom alone can replicate.",
        after=200)

    _blue_rule(doc, 8)

    # Declaration of Originality
    heading(doc, "DECLARATION OF ORIGINALITY", size=13, before=160, after=80)
    _yellow_rule(doc)

    body(doc,
        "I, Vinit Deogade, hereby solemnly declare that the internship report entitled "
        "\"IT Automation & Software Engineering Internship — UltraTech Cement Limited, "
        "Awarpur Cement Works\" is an original piece of work prepared by me based on my "
        "personal observations, hands-on work, and experiences during the internship period "
        "from 11 May 2026 to 10 July 2026.",
        before=80, after=80)

    body(doc,
        "I further declare that:",
        after=30)

    for b in [
        "This report has not been submitted previously for any degree, diploma, or examination at any university or institution.",
        "All technical descriptions, architectural diagrams, database schemas, API designs, and software implementations described herein are the result of my original work during the internship.",
        "All references to external tools, technologies, and organizational information have been duly acknowledged.",
        "The source code for the UTCL Bus Management System was independently developed by me and is the intellectual property of UltraTech Cement Limited.",
        "I have not misrepresented any information relating to the internship organization, my role, or the work performed.",
    ]:
        bullet(doc, b)

    body(doc, "", after=160)

    # Signature table
    kv_table(doc, [
        ("Name",             "Mr. Vinit Deogade"),
        ("Enrollment No.",   "____________"),
        ("Program",          "B.Tech — Artificial Intelligence & Machine Learning"),
        ("Institution",      "Universal AI University"),
        ("Date",             "10 July 2026"),
        ("Place",            "Awarpur Cement Works, Chandrapur, Maharashtra"),
        ("Signature",        ""),
    ])

    doc.add_page_break()


# ─── TABLE OF CONTENTS ────────────────────────────────────────────────────────

def table_of_contents(doc):
    heading(doc, "TABLE OF CONTENTS", size=15, before=120, after=80)
    _yellow_rule(doc)

    # Manual TOC table: chapter title + page reference column
    toc_entries = [
        # (indent_level, label, page_hint)
        (0, "PRELIMINARY PAGES",                                       ""),
        (1, "Cover & Title Page",                                       "i"),
        (1, "Company & Academic Certificates",                          "ii"),
        (1, "Acknowledgments & Declaration of Originality",             "iii"),
        (1, "Table of Contents",                                        "iv"),
        (0, "",                                                         ""),
        (0, "1.   Executive Summary",                                    "1"),
        (0, "",                                                         ""),
        (0, "2.   Month 1 — Infrastructure, Networking & Systems Deployment",   "3"),
        (1, "2.1  Week 1 — Induction, Orientation & Infrastructure Familiarization", "3"),
        (1, "2.2  Week 2 — Enterprise Endpoint Provisioning & Domain Integration",   "4"),
        (1, "2.3  Week 3 — Cisco Switch Configuration & Production Network Deployment", "5"),
        (1, "2.4  Week 4 — AV Operations, Server Room Audits & EHS Compliance",     "6"),
        (0, "",                                                         ""),
        (0, "3.   Month 2 — Full-Stack Software Engineering",           "8"),
        (1, "3.1  Project Overview — UTCL Bus Management System",       "8"),
        (1, "3.2  System Architecture",                                  "9"),
        (1, "3.3  Database Schema — 13 Relational Tables",               "9"),
        (1, "3.4  REST API Architecture — 30+ Endpoints",                "10"),
        (1, "3.5  Real-Time WebSocket Event Protocol — 11 Events",       "11"),
        (1, "3.6  Key Feature Implementations",                          "12"),
        (1, "3.7  Multi-Mode Deployment Architecture",                   "14"),
        (1, "3.8  Additional Project Deliverables",                      "14"),
        (0, "",                                                         ""),
        (0, "4.   Technical Skills Acquired",                           "15"),
        (0, "",                                                         ""),
        (0, "5.   Conclusions & Professional Outcomes",                  "16"),
        (0, "",                                                         ""),
    ]

    # Spacer row at top
    sp = doc.add_paragraph()
    _para_spacing(sp, before=60, after=0)

    for (indent, label, pg) in toc_entries:
        if label == "":
            # blank divider row
            blank = doc.add_paragraph()
            _para_spacing(blank, before=0, after=30)
            continue

        toc_row = doc.add_table(rows=1, cols=2)
        _apply_col_widths(toc_row, [5.70, 0.60])
        _lock_table_width(toc_row)

        # Remove table borders (invisible table)
        tbl_xml = toc_row._tbl
        tblPr = tbl_xml.find(qn('w:tblPr'))
        if tblPr is None:
            tblPr = OxmlElement('w:tblPr')
            tbl_xml.insert(0, tblPr)
        tblBdr = OxmlElement('w:tblBorders')
        for side in ('top','left','bottom','right','insideH','insideV'):
            b = OxmlElement(f'w:{side}')
            b.set(qn('w:val'),   'none')
            b.set(qn('w:sz'),    '0')
            b.set(qn('w:space'), '0')
            b.set(qn('w:color'), 'auto')
            tblBdr.append(b)
        for old in tblPr.findall(qn('w:tblBorders')):
            tblPr.remove(old)
        tblPr.append(tblBdr)

        is_chapter = (indent == 0)

        # Label cell
        lc = toc_row.rows[0].cells[0]
        _set_cell_bg(lc, "FFFFFF")
        lp = lc.paragraphs[0]
        lp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _para_spacing(lp, before=30, after=30)
        indent_str = "       " if indent == 1 else ""
        _add_run(lp, indent_str + label,
                 bold=is_chapter,
                 color=UTCL_BLUE if is_chapter else DARK,
                 size=10 if is_chapter else 9.5)

        # Page cell
        pc = toc_row.rows[0].cells[1]
        _set_cell_bg(pc, "FFFFFF")
        pp = pc.paragraphs[0]
        pp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _para_spacing(pp, before=30, after=30)
        _add_run(pp, pg,
                 bold=is_chapter,
                 color=UTCL_BLUE if is_chapter else DARK,
                 size=10 if is_chapter else 9.5)

    # List of Tables section
    _blue_rule(doc, 6)
    heading(doc, "LIST OF TABLES", size=11, color=UTCL_GREY, before=120, after=60)

    tables_list = [
        ("Table 1",  "Key Outcome Metrics",                                    "1"),
        ("Table 2",  "Month 1 — Technology & Skills Matrix",                   "6"),
        ("Table 3",  "UTCL Bus Management System — Project Overview",          "8"),
        ("Table 4",  "Database Schema — 13 Relational Tables (utcl_bus_db)",   "9"),
        ("Table 5",  "REST API Architecture — 30+ Endpoints across 6 Domains", "10"),
        ("Table 6",  "Real-Time WebSocket Event Protocol — 11 Events",         "11"),
        ("Table 7",  "Multi-Mode Deployment Architecture",                      "14"),
        ("Table 8",  "Technical Skills Acquired — Complete Matrix",             "15"),
    ]

    for (num, title, pg) in tables_list:
        trow = doc.add_table(rows=1, cols=2)
        _apply_col_widths(trow, [5.70, 0.60])
        _lock_table_width(trow)
        tbl_xml2 = trow._tbl
        tblPr2 = tbl_xml2.find(qn('w:tblPr'))
        if tblPr2 is None:
            tblPr2 = OxmlElement('w:tblPr')
            tbl_xml2.insert(0, tblPr2)
        tblBdr2 = OxmlElement('w:tblBorders')
        for side in ('top','left','bottom','right','insideH','insideV'):
            b = OxmlElement(f'w:{side}')
            b.set(qn('w:val'),   'none')
            b.set(qn('w:sz'),    '0')
            b.set(qn('w:space'), '0')
            b.set(qn('w:color'), 'auto')
            tblBdr2.append(b)
        for old in tblPr2.findall(qn('w:tblBorders')):
            tblPr2.remove(old)
        tblPr2.append(tblBdr2)

        lc2 = trow.rows[0].cells[0]
        _set_cell_bg(lc2, "FFFFFF")
        lp2 = lc2.paragraphs[0]
        lp2.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _para_spacing(lp2, before=25, after=25)
        _add_run(lp2, f"{num}:  {title}", size=9, color=DARK)

        pc2 = trow.rows[0].cells[1]
        _set_cell_bg(pc2, "FFFFFF")
        pp2 = pc2.paragraphs[0]
        pp2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _para_spacing(pp2, before=25, after=25)
        _add_run(pp2, pg, size=9, color=DARK)

    doc.add_page_break()


# ─── Main Builder ─────────────────────────────────────────────────────────────

def build():
    doc = Document()

    # ── Page setup: A4 Portrait ──────────────────────────────────────────────
    section = doc.sections[0]
    section.page_height    = Cm(29.7)
    section.page_width     = Cm(21.0)
    section.left_margin    = Cm(2.5)
    section.right_margin   = Cm(2.5)
    section.top_margin     = Cm(2.0)
    section.bottom_margin  = Cm(2.0)
    section.header_distance = Cm(1.0)
    section.footer_distance = Cm(1.0)

    # ── Default body style ───────────────────────────────────────────────────
    normal = doc.styles['Normal']
    normal.font.name = 'Calibri'
    normal.font.size = Pt(9.5)

    # ── Footer ───────────────────────────────────────────────────────────────
    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_run(fp,
             "UltraTech Cement Limited  —  Awarpur Cement Works  |  Vinit Deogade Internship Report  |  2026",
             size=7.5, color=UTCL_GREY, italic=True)

    # ── Build sections ───────────────────────────────────────────────────────
    # Preliminary Pages
    cover(doc)
    certificate_page(doc)
    acknowledgments(doc)
    table_of_contents(doc)
    # Main Report Body
    executive_summary(doc)
    month1(doc)
    month2(doc)
    skills_section(doc)
    conclusion(doc)

    out = r"d:\UTCL antigravity\Vinit_Deogade_Internship_Report_UTCL_2026.docx"
    doc.save(out)
    print(f"[OK] Saved: {out}")


if __name__ == "__main__":
    build()
