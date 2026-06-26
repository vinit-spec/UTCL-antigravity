# Requirements Document

> [!NOTE]
> **Implementation Status**: All of the following functional requirements are fully implemented in a zero-dependency client-side Single Page Application (SPA) using HTML, custom Vanilla CSS, and JavaScript. Runtimes and database tables are simulated locally via `localStorage` state persistence.

## Introduction

The UTCL Bus Management System is a web-based internal transport management platform for Ultratech Cement Ltd (UTCL) employees. The system manages 2 physical buses operating on dual shifts (4 scheduled routes per day) along a fixed bidirectional route between Awalpur and Chandrapur. It provides three role-based portals — Admin, Employee (User), and Driver — enabling ticket booking, schedule visibility, driver assignment, maintenance tracking, and revenue/occupancy analytics. Only verified UTCL employees (identified by PS number) may book seats. A flat fare of ₹20 applies per booking regardless of boarding or drop-off stop.

---

## Glossary

- **System**: The UTCL Bus Management System web application.
- **Admin**: A UTCL staff member with full administrative privileges over the system.
- **Employee**: A UTCL staff member who books bus seats; also referred to as "User".
- **Driver**: A UTCL staff member assigned to operate a bus on a scheduled route.
- **PS Number**: The unique employee identification number issued by UTCL, used to verify employment.
- **Bus Schedule**: A defined timed sequence of stops for a single bus trip (forward or return).
- **Route**: The fixed bidirectional path: Awalpur ↔ Bibee ↔ Gadchandur ↔ Manikgarh ↔ Rajura ↔ Ballarsha ↔ Chandrapur.
- **Stop**: A designated pickup/drop-off point along the Route.
- **Boarding Stop**: The Stop at which an Employee boards the bus.
- **Drop Stop**: The Stop at which an Employee exits the bus.
- **Seat**: A numbered position inside a bus available for booking.
- **Virtual Ticket**: A digitally generated booking confirmation containing trip details.
- **Fare**: The fixed cost of ₹20 per booking, regardless of distance.
- **Shift**: One of the four daily bus schedule slots (Bus 1, Bus 2, Bus 3, Bus 4).
- **Maintenance Schedule**: A planned servicing event assigned to a physical bus by the Admin.
- **Occupancy**: The ratio of booked seats to total available seats on a given bus trip.
- **Revenue**: The total fare collected across all bookings within a given period.
- **Booking**: A confirmed seat reservation made by an Employee for a specific bus trip.
- **Active Shift**: A Shift whose scheduled departure time has not yet passed.

---

## Requirements

### Requirement 1: Role-Based Authentication

**User Story:** As a UTCL staff member, I want to log in with my designated role, so that I can access only the features relevant to my responsibilities.

#### Acceptance Criteria

1. THE System SHALL provide three separate login portals: Admin, Employee, and Driver.
2. WHEN an Admin submits a username and password that match a registered Admin account, THE System SHALL establish a complete Admin session, set the role to ADMIN, and grant access to the Admin Dashboard.
3. WHEN an Employee submits a username and password that match a registered Employee account, THE System SHALL set the role to EMPLOYEE, grant access to the Employee Dashboard, and activate the session.
4. WHEN a Driver submits a username and password that match a registered Driver account, THE System SHALL set the role to DRIVER, grant access to the Driver Dashboard, and activate the session.
5. IF a user submits credentials that do not match any registered account for the selected portal, THEN THE System SHALL display an error message indicating the credentials are invalid without specifying which field is incorrect, and deny access.
6. IF an authenticated user attempts to access a URL or feature belonging to a different role, THEN THE System SHALL redirect the user to their designated dashboard and display an access-denied message.
7. WHEN a user logs out, THE System SHALL terminate the session and redirect to the login portal for that user's role.
8. WHEN a session has been inactive for 30 minutes, THE System SHALL automatically terminate the session and redirect the user to the login portal for their role.

---

### Requirement 2: Employee Ticket Booking

**User Story:** As a UTCL Employee, I want to search and book a bus seat, so that I can reserve my travel on the company bus.

#### Acceptance Criteria

1. WHEN an Employee accesses the booking interface, THE System SHALL display all available bus schedules for the current day with departure times and available seat counts.
2. WHEN an Employee selects a bus schedule whose departure time has already passed for the current day, THE System SHALL prevent selection and display a message indicating the schedule is no longer available for booking.
3. WHEN an Employee selects an active bus schedule, THE System SHALL display the full list of Stops along the Route with their scheduled arrival times.
4. WHEN an Employee selects a Boarding Stop and a Drop Stop, THE System SHALL validate that the Boarding Stop precedes the Drop Stop in the direction of travel.
5. IF an Employee selects a Boarding Stop that does not precede the Drop Stop in the direction of travel, THEN THE System SHALL display a validation error and prevent booking.
6. WHEN an Employee selects a valid Boarding Stop and Drop Stop and validation passes, THE System SHALL automatically display the seat selection interface showing available and occupied seats.
7. IF a bus schedule has zero available seats, THEN THE System SHALL display it as fully booked and prevent seat selection.
8. WHEN an Employee selects an available Seat, THE System SHALL display the Fare of ₹20 and a booking confirmation prompt.
9. THE System SHALL accept the Employee's name (maximum 100 characters) and PS Number during the booking flow, and SHALL validate the PS Number before displaying the seat selection interface.
10. WHEN a PS Number is submitted, THE System SHALL validate it against the UTCL employee registry before allowing booking to proceed.
11. IF a PS Number is not found in the UTCL employee registry, THEN THE System SHALL reject the booking and display an error message.
12. WHEN an Employee confirms a booking, THE System SHALL record the Booking and mark the selected Seat as occupied for that trip.
13. IF a selected Seat becomes occupied between selection and confirmation, THEN THE System SHALL notify the Employee and prompt re-selection.
14. IF an Employee with a given PS Number already has a confirmed Booking for the same Shift, THEN THE System SHALL prevent a duplicate Booking and display an error message.

---

### Requirement 3: Virtual Ticket Generation

**User Story:** As a UTCL Employee, I want to receive a virtual ticket after booking, so that I have a digital record of my reservation.

#### Acceptance Criteria

1. WHEN a Booking is confirmed, THE System SHALL generate a Virtual Ticket containing: Employee name, PS Number, Bus number (Shift), Seat number, Boarding Stop, Drop Stop, Fare (₹20), and scheduled departure time before recording the Booking as confirmed.
2. IF Virtual Ticket generation fails, THEN THE System SHALL roll back the Booking, display an error message indicating the booking could not be completed, and notify the Employee.
3. WHEN a Virtual Ticket is successfully generated, THE System SHALL display it to the Employee within 3 seconds of booking confirmation.
4. WHEN an Employee navigates to their booking history, THE System SHALL display all Bookings associated with their PS Number, sorted by scheduled departure time with the most recent first, excluding rolled-back Bookings.
5. WHEN an Employee views their booking history, THE System SHALL label each Booking as "Active" if the scheduled departure is today or in the future, or "Past" if the scheduled departure has already occurred.

---

### Requirement 4: Bus Schedule Display

**User Story:** As a UTCL Employee, I want to view all bus timings and route information, so that I can plan my travel.

#### Acceptance Criteria

1. WHEN an Employee accesses the Bus Schedule Display, THE System SHALL show the four daily Shifts with their complete stop-by-stop schedules as defined below:

   **Bus 1 – Forward (Awalpur → Chandrapur):**
   Awalpur 5:30 AM → Bibee 5:40 AM → Gadchandur 5:55 AM → Manikgarh 6:00 AM → Rajura 6:25 AM → Ballarsha 6:40 AM → Chandrapur 7:10 AM

   **Bus 1 – Return (Chandrapur → Awalpur):**
   Chandrapur 8:00 AM → Ballarsha 8:30 AM → Rajura 8:45 AM → Manikgarh 9:10 AM → Gadchandur 9:15 AM → Bibee 9:30 AM → Awalpur 9:40 AM

   **Bus 2 – Forward (Awalpur → Chandrapur):**
   Awalpur 8:30 AM → Bibee 8:40 AM → Gadchandur 8:55 AM → Manikgarh 9:00 AM → Rajura 9:25 AM → Ballarsha 9:40 AM → Chandrapur 10:10 AM

   **Bus 2 – Return (Chandrapur → Awalpur):**
   Chandrapur 12:30 PM → Ballarsha 1:00 PM → Rajura 1:15 PM → Manikgarh 1:40 PM → Gadchandur 1:45 PM → Bibee 2:00 PM → Awalpur 2:10 PM

   **Bus 3 – Forward (Awalpur → Chandrapur):**
   Awalpur 10:30 AM → Bibee 10:40 AM → Gadchandur 10:55 AM → Manikgarh 11:00 AM → Rajura 11:25 AM → Ballarsha 11:40 AM → Chandrapur 12:10 PM

   **Bus 3 – Return (Chandrapur → Awalpur):**
   Chandrapur 3:30 PM → Ballarsha 4:00 PM → Rajura 4:15 PM → Manikgarh 4:40 PM → Gadchandur 4:45 PM → Bibee 5:00 PM → Awalpur 5:10 PM

   **Bus 4 – Forward (Awalpur → Chandrapur):**
   Awalpur 3:00 PM → Bibee 3:10 PM → Gadchandur 3:25 PM → Manikgarh 3:30 PM → Rajura 3:55 PM → Ballarsha 4:10 PM → Chandrapur 4:40 PM

   **Bus 4 – Return (Chandrapur → Awalpur):**
   Chandrapur 7:00 PM → Ballarsha 7:30 PM → Rajura 7:45 PM → Manikgarh 8:10 PM → Gadchandur 8:15 PM → Bibee 8:30 PM → Awalpur 8:40 PM

2. WHEN an Employee views a Shift, THE System SHALL display the Fare as ₹20 applicable to all bookings on that Shift.
3. IF schedule data is unavailable for a Shift, THEN THE System SHALL display an error message for that Shift indicating the schedule could not be loaded, without affecting the display of other Shifts.

---

### Requirement 5: Fare Management

**User Story:** As a UTCL Employee, I want to know the fare before booking, so that I can make an informed decision.

#### Acceptance Criteria

1. THE System SHALL apply a flat Fare of ₹20 per Booking regardless of the Boarding Stop or Drop Stop selected.
2. WHEN an Employee views the booking summary, THE System SHALL display the Fare as ₹20 before confirmation.
3. WHEN a Booking is confirmed, THE System SHALL record the Fare amount of ₹20 against that Booking for revenue reporting purposes.
4. THE System SHALL include the Fare of ₹20 on the Virtual Ticket generated for each confirmed Booking.

---

### Requirement 6: Driver Dashboard

**User Story:** As a Driver, I want to view my assigned bus schedule and maintenance information, so that I can prepare for my duties.

#### Acceptance Criteria

1. WHEN a Driver views their dashboard, THE System SHALL display the bus number assigned to that Driver.
2. IF a Driver has no bus assigned, THEN THE System SHALL display a message indicating no bus is currently assigned and SHALL NOT display schedule or maintenance sections.
3. WHEN a Driver views their schedule, THE System SHALL display all Active Shifts assigned to them including all Stop names and scheduled arrival times.
4. IF a Driver has no assigned Active Shifts, THEN THE System SHALL display a message indicating no shifts are currently assigned.
5. WHEN a Driver views their dashboard, THE System SHALL display all upcoming Maintenance Schedules (scheduled date on or after the current date) for their assigned bus, including the scheduled date and maintenance description.
6. IF no upcoming Maintenance Schedule exists for the Driver's assigned bus, THEN THE System SHALL display a message indicating no upcoming maintenance.

---

### Requirement 7: Admin – User and Driver Management

**User Story:** As an Admin, I want to manage Employee and Driver accounts, so that I can control system access and assignments.

#### Acceptance Criteria

1. WHEN an Admin creates a new Employee account, THE System SHALL require a name, PS Number, and role designation (one of: Admin, Employee, or Driver).
2. WHEN an Admin creates a new Driver account, THE System SHALL require a name and PS Number; the role designation SHALL be set to Driver automatically.
3. IF an Admin submits a PS Number that already exists in the system during account creation, THEN THE System SHALL reject the request and display an error indicating the PS Number is already registered.
4. WHEN an Admin removes an Employee account, THE System SHALL deactivate the account, cancel any Active Bookings associated with that Employee, and prevent future logins with those credentials.
5. WHEN an Admin removes a Driver account, THE System SHALL deactivate the account and unassign the Driver from any Active Shifts.
6. WHEN an Admin views the user management section, THE System SHALL display a list of all Employee and Driver accounts with their name, PS Number, role, and status (active or inactive).

---

### Requirement 8: Admin – Bus and Schedule Management

**User Story:** As an Admin, I want to add, remove, and configure buses and their schedules, so that I can manage the fleet and daily operations.

#### Acceptance Criteria

1. WHEN an Admin adds a new bus, THE System SHALL require a unique bus identifier and, upon successful creation, make the bus available for Shift assignment.
2. IF an Admin submits a bus identifier that already exists, THEN THE System SHALL reject the request and display an error indicating the identifier is already in use.
3. WHEN an Admin removes a bus, THE System SHALL deactivate the bus and cancel all Bookings with a scheduled departure after the removal timestamp.
4. IF an Admin removes a bus that has Bookings with a scheduled departure after the removal timestamp, THEN THE System SHALL send an in-system notification to each affected Employee containing the cancellation details before completing deactivation.
5. WHEN an Admin assigns a Driver to a Shift, THE System SHALL record the assignment and make it visible on the Driver's dashboard.
6. IF an Admin attempts to assign a Driver who is already assigned to a Shift that shares any time within the same calendar day, THEN THE System SHALL display a conflict warning and require the Admin to explicitly confirm before proceeding.
7. WHEN an Admin modifies a Shift schedule, THE System SHALL update all affected stop times and reflect the changes in the Employee and Driver dashboards.
8. WHEN an Admin modifies a Shift schedule that has existing Bookings, THE System SHALL send an in-system notification to each affected Employee with the updated departure time.

---

### Requirement 9: Admin – Maintenance Scheduling

**User Story:** As an Admin, I want to schedule bus servicing, so that I can ensure the fleet remains in safe operating condition.

#### Acceptance Criteria

1. WHEN an Admin creates a Maintenance Schedule for a bus, THE System SHALL record the bus identifier, scheduled date, and maintenance description (maximum 500 characters).
2. WHEN a Maintenance Schedule is created, THE System SHALL display it on the dashboard of all Drivers who have Active Shifts assigned to that bus.
3. IF a Maintenance Schedule date falls on the same date as an Active Shift for the same bus, THEN THE System SHALL display a conflict warning to the Admin before saving; the Admin may still proceed after acknowledging the warning.
4. WHEN a Maintenance Schedule's scheduled date passes without being manually marked complete, THE System SHALL update its status to "Overdue".
5. WHEN an Admin marks a Maintenance Schedule as complete, THE System SHALL record the actual completion date and update the status to "Completed".

---

### Requirement 10: Admin – Revenue Analytics

**User Story:** As an Admin, I want to view revenue reports, so that I can track fare collection and financial performance.

#### Acceptance Criteria

1. WHEN an Admin views the Revenue Analytics dashboard, THE System SHALL default to displaying data for the current calendar month and show total Revenue, total Bookings count, and a per-Shift revenue breakdown in both chart and tabular formats.
2. WHEN an Admin selects a date range filter, THE System SHALL update the Revenue Analytics display to reflect only confirmed Bookings within that range; the chart and tabular formats SHALL show the same revenue total.
3. IF an Admin submits a date range where the start date is after the end date, THEN THE System SHALL display a validation error and retain the previously displayed data.
4. IF there are no confirmed Bookings within the selected date range, THEN THE System SHALL display a message indicating no revenue data is available for that period.
5. THE System SHALL calculate total Revenue as ₹20 multiplied by the count of all confirmed Bookings within the selected date range.

---

### Requirement 11: Admin – Occupancy Analysis

**User Story:** As an Admin, I want to view bus occupancy trends, so that I can identify underutilised and overutilised trips.

#### Acceptance Criteria

1. THE System SHALL calculate Occupancy for each Shift as: (count of confirmed Bookings for that trip) ÷ (total available Seats on that bus) × 100, expressed as a percentage.
2. WHEN an Admin views the Occupancy Analysis dashboard, THE System SHALL display Occupancy percentages per Shift for the current calendar month by default, segmented into weekday (Monday–Friday) and weekend (Saturday–Sunday) averages.
3. THE System SHALL visually distinguish high-Occupancy trips (≥80%) from low-Occupancy trips (≤40%) using distinct visual indicators (e.g., colour coding or icons) in the Occupancy Analysis display.
4. WHEN an Admin selects a specific Shift, THE System SHALL display historical Occupancy data for that Shift over a selected date range of up to 365 days.

---

### Requirement 12: Admin – Bus Tracking Overview

**User Story:** As an Admin, I want a bus scanning and tracking overview, so that I can monitor fleet status in real time.

#### Acceptance Criteria

1. WHEN an Admin views the Bus Tracking Overview, THE System SHALL display the current operational status of each bus as one of: active, idle, or under maintenance.
2. WHEN a bus has status "active", THE System SHALL display the most recently recorded Shift and Stop information for that bus.
3. IF only one of Shift or Stop information is available for an active bus, THEN THE System SHALL display the available information and indicate that the other is unavailable.
4. IF neither Shift nor Stop information is available for an active bus, THEN THE System SHALL display a message indicating location data is currently unavailable for that bus.
5. WHEN a bus status changes (via a scan event or manual Admin update), THE System SHALL update the Bus Tracking Overview within 60 seconds.

---

### Requirement 13: Corporate Branding and UI Theme

**User Story:** As a UTCL stakeholder, I want the system to reflect UTCL's corporate identity, so that it feels consistent with company standards.

#### Acceptance Criteria

1. THE System SHALL apply the UTCL corporate colour palette (primary grey: #58595B, primary blue: #0057A8) consistently across all UI elements in all dashboards and portals.
2. THE System SHALL display the UTCL (Ultratech Cement Ltd) logo on the login portal and in the header of every dashboard page, visible without scrolling.
3. WHEN any page is rendered across the Admin, Employee, and Driver portals, THE System SHALL apply the same header layout, typography, and colour scheme so that all portals are visually consistent with each other.
4. THE System SHALL be fully functional in the latest stable versions of Google Chrome, Mozilla Firefox, and Microsoft Edge without requiring any additional software installation or browser plugins.
