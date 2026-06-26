# UTCL Bus Management System: Operations & User Guide

Welcome to the **UTCL (UltraTech Cement Limited) Bus Management System User Guide**. This document outlines detailed, step-by-step operating instructions for the **Employee**, **Driver**, and **Admin** portals, including system rules, verification workflows, and troubleshooting tips.

---

## 📋 Table of Contents
1. [System Overview & Architecture](#-system-overview--architecture)
2. [General Navigation & Security](#-general-navigation--security)
3. [Employee Portal (Passenger Guide)](#-employee-portal-passenger-guide)
4. [Driver Portal (Operator Guide)](#-driver-portal-operator-guide)
5. [Admin Portal (Control Center Guide)](#-admin-portal-control-center-guide)
6. [Data Sync Hardening Rules & Limits](#-data-sync-hardening-rules--limits)
7. [System Rules & Validation Logic](#-system-rules--validation-logic)
8. [Troubleshooting & FAQs](#-troubleshooting--faqs)

---

## 🏗️ System Overview & Architecture

The UTCL Bus Management System is a real-time tracking, scheduling, and seat-booking platform designed to coordinate transport logistics between the **Awalpur** and **Manikgarh** cement plants and the surrounding region (Chandrapur).

```
[Client Portals (Employee, Driver, Admin)]
        │ (HTTP REST APIs & WebSockets)
        ▼
   [Flask Server] <──> [WebSocket Broadcaster]
        │
        ▼ (SQL Transactions)
   [MySQL Database]
```

---

## 🔑 General Navigation & Security

### Logging In
1. Open the application in Google Chrome or Microsoft Edge.
2. Select your designated role using the selector toggle at the top of the login card: **Employee**, **Driver**, or **Admin**.
3. Input your credentials:
   * **Username / PS Number** (e.g., `PS10001` or `PS20001`)
   * **Password**
4. Click **LOGIN**.

### ⏱️ Session Expiration & Warnings
To prevent unauthorized access, the system enforces session limits:
* **Timeout**: Sessions automatically expire after **30 minutes** of inactivity.
* **Inactivity Warning**: An alert modal appears at **25 minutes** of inactivity. You can click **Stay Logged In** to refresh the token, or click **Logout** to exit immediately.

### 🔒 Password Recovery (Forgot Password)
1. On the login screen, click **Forgot Password?**.
2. Input your registered **PS Number** and click **Send OTP**.
3. Retrieve the **6-digit verification code** sent to your corporate email.
4. Input the code, specify your new password, and click **Confirm Reset**.

---

## 📱 Employee Portal (Passenger Guide)

The Employee Portal allows verified UTCL staff to book seats, manage virtual tickets, check timetables, and configure plant preferences.

```
[Employee Dashboard]
  ├── Book a Commute (4-Step Flow)
  ├── My Tickets (Active/Past passes with barcode printing)
  ├── Bus Timetables (Full schedule lookup)
  └── Profile Settings (Update email, phone, and plant location)
```

### 📅 Booking a Commute (Step-by-Step)

* A flat fare of **₹20** is billed automatically via payroll deductions for every completed journey.

1. **Step 1: Shift Selection**
   * Select a calendar date (today or future dates).
   * Choose an active shift from the listed grid (e.g., *Bus 1 - Forward (05:30 AM)*) and click **Select**.
2. **Step 2: Stops & Passenger Info**
   * Choose your **Boarding Stop** (origin) and **Drop-Off Stop** (destination).
   * Enter the passenger's **Full Name** and **PS Number**.
   * *Note: The boarding stop must precede the drop stop in the direction of travel.*
3. **Step 3: Interactive Seat Map**
   * A 40-seat grid will load dynamically.
   * **Colors**:
     * 🟢 **Green**: Available. Click to select.
     * 🟡 **Yellow**: Held by another passenger (real-time lock).
     * 🔴 **Red**: Already booked/occupied.
   * Click on an available seat to lock it.
4. **Step 4: Ticket Confirmation**
   * Review the final summary card.
   * Click **CONFIRM BOOKING**. Your virtual ticket is generated.

### 🎫 Managing Virtual Tickets & Cancellations
* **Virtual Ticket**: View active trips in **My Tickets**. Click on a ticket to show a barcode pass. You can print or download this barcode card directly from the browser to scan when boarding.
* **Cancellations**:
  * Locate the ticket in **My Tickets** under **Active**.
  * Click **Cancel Ticket** before the shift departure time.
  * The seat is released immediately, and notifications update in real-time.

---

## 🚛 Driver Portal (Operator Guide)

The Driver Portal provides operators with daily assignments, duty timetables, attendance clock-ins, and vehicle maintenance logs.

### 📋 Duty Assignments & Schedules
* Your assigned vehicle (e.g., `Bus 1`) is displayed at the top of the dashboard.
* The **Active Shifts** tab displays your route timelines, departure times, and list of stops for the day.

### 🤳 Clocking In (Selfie-Based Attendance)
Drivers must submit physical verification photos at departure and arrival:
1. **At Shift Departure**:
   * Navigate to **Shift Attendance**.
   * Click **Submit Departure Selfie** to open your device camera.
   * Capture a clear photo of yourself inside/next to the bus and click **Submit**.
   * Your status changes to `Departure Submitted (Pending Admin Approval)`.
2. **At Shift Arrival**:
   * Once you arrive at the terminal stop, click **Submit Arrival Selfie**.
   * Capture a verification photo and submit.

### 🔧 Maintenance Notices & Syncing
* Navigate to **Maintenance Notices**.
* Review upcoming inspections, brake checks, or oil changes assigned to your physical bus.
* Drivers can sync and change a maintenance status to `PENDING_CONFIRMATION` to notify the admin when work is completed.

---

## 👑 Admin Portal (Control Center Guide)

The Admin Portal is the control center for fleet management, rosters, financial audits, and emergency shifts.

### 👥 User Registry Management
* **Create Account**: Go to **User Management** -> **Create Account**. Enter Name, PS Number, Email, and Role.
* **Search / Edit**: Filter users dynamically by typing names or PS numbers in the search bar. You can reset passwords or toggle account activity.
* **Security Action**: Deactivating a user automatically cancels all their future bookings.

### 🚍 Bus & Driver Rosters
1. **Roster Scheduling**:
   * Navigate to **Bus & Driver Assignments**.
   * Assign a driver to a shift (e.g., `S1F`) for a calendar date.
   * *Conflict Warning*: If the driver has another shift on the same day, the system raises a warning.
2. **Shift Route Modification**:
   * Go to **Modify Shifts** -> select shift.
   * Update specific arrival times at stop points.
   * Saving changes automatically notifies all passengers who have booked seats on that shift.

### 🤳 Approving Driver Attendance
* Navigate to **Driver Attendance Audit**.
* View submitted departure/arrival photos.
* Click **Approve** to verify attendance, or **Reject** to trigger driver alerts.

### 🚨 Emergency Cancel Shift
If a bus breaks down or is otherwise unavailable, you can cancel its shifts for the day:
1. Go to **Schedule Management** -> select the shift and date.
2. Click **Cancel Shift for Day**.
3. An **Integrated Summary Card** calculates the real-time impact, displaying affected bookings and passengers.
4. Input the cancellation reason (e.g., *Engine overheat breakdown*) and click **CANCEL SHIFT**.
5. **The system automatically**:
   * Cancels all affected bookings and tickets.
   * Fires real-time WebSocket alerts to all active screens.
   * Updates passenger notification bells with a descriptive message.

### 📊 Financial & Occupancy Analytics
1. **Revenue Reports**: Filter by dates to check total fare revenues.
2. **Occupancy Graphs**: Check weekday vs. weekend averages to spot low/high travel slots.
3. **Print Passenger Manifest**: Go to shifts -> select date -> click **Export Manifest** to generate a pre-formatted Excel passenger log for the driver.

### 💰 Payroll & Fare Deductions
At the end of the month, the system calculates payroll ride billing:
1. Navigate to **Payroll Audits**.
2. Click **Generate Draft Payroll** for the target calendar month.
3. The system aggregates all completed passenger rides (`ride count * ₹20 flat rate`).
4. Click **Export Report** to download the Excel sheet for corporate accounting.
5. Click **Lock Period** to confirm processing. If corrections are needed, click **Unlock Period**.

---

## 🔒 Data Sync Hardening Rules & Limits

To prevent unauthorized changes or data exfiltration, the synchronization API (`/api/sync`) enforces strict constraints based on role:

### 1. Driver Limitations (Maintenance Table)

* **No Inserts or Deletes**: Drivers are strictly blocked from adding new records or deleting existing ones from the database.
* **Field Whitelist**: Drivers can only modify the `status` field. Attempting to modify `busId`, `scheduledDate`, `description`, or `actualCompletionDate` results in a `403 Forbidden`.
* **State Machine Guard**: Drivers can only perform specific status transitions:
  * `SCHEDULED` ➔ `PENDING_CONFIRMATION` (or stay `SCHEDULED`)
  * `OVERDUE` ➔ `PENDING_CONFIRMATION` (or stay `OVERDUE`)
  * Any other transitions are rejected.
* **Dynamic Bus Assignment Check**: Drivers can only sync maintenance records for buses they are assigned to in `driver_shifts` for **today or future dates**.
* **Payload Limit**: Driver payloads are restricted to a maximum of **50 records**. Exceeding this limit immediately rejects the request with a `400 Bad Request` (`Payload size limit exceeded`).

### 2. Admin Permissions
* Administrators bypass all driver constraints: they can sync any fields, insert new tasks, delete records, and modify the `cancelled_shifts` table.

---

## ⚙️ System Rules & Validation Logic

* **Directional Validation**: Passengers cannot book boarding stops that occur *after* drop-off stops in the shift route sequence.
* **Locked Commutes**: Shift bookings lock **5 minutes** prior to departure time, after which seats can no longer be booked or cancelled by employees.
* **Flat Fares**: All passenger fares are fixed at **₹20** regardless of distance.
* **Duplicate Bookings**: An employee cannot make two active bookings for the same shift on the same date.

---

## ❓ Troubleshooting & FAQs

#### Q: The seat map is not loading.
* **A**: Verify that the server is running and the database connection is healthy in **Admin DB Status**. If using a corporate network, ensure WebSocket connections (Port 8000) are not blocked by local firewalls.

#### Q: A driver was assigned to a shift, but it isn't showing on their dashboard.
* **A**: Check that the date of assignment matches the current calendar day. Ensure the driver account is set to `Active` in the User Registry.

#### Q: How do we handle refunds for cancelled shifts?
* **A**: Shift cancellations automatically mark bookings as `CANCELLED`. Because corporate deductions are aggregated at the end of the month based *only* on completed bookings (`CONFIRMED`), cancelled rides are automatically omitted from the employee's payroll deduction total.
