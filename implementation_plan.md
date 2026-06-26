# Password Reset & Change — Implementation Plan

## Overview

Two separate flows covering all user types:

1. **Forgot Password (Self-Service via Email OTP)** — for employees/admins who have a `@adityabirla.com` corporate email registered in the system
2. **Admin Resets Password on Behalf of User** — for drivers and any user who doesn't have a registered email; admin sets a new password from User Management

A third minor flow:
3. **Change Password (Logged-In Users)** — any logged-in user (employee, driver, admin) can change their own password from their dashboard

---

## Proposed Changes

---

### A. Database Layer — `server.py` (schema)

#### [MODIFY] `users` table

Add two new columns:
- `email VARCHAR(100)` — stores the corporate email (e.g. `rajesh@adityabirla.com`); nullable, not all users will have one
- `phone VARCHAR(20)` — optional, for future use

#### [NEW] `password_reset_tokens` table

Stores time-limited OTP tokens for the forgot-password flow:

```sql
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id VARCHAR(50) PRIMARY KEY,
    psNumber VARCHAR(50),
    token VARCHAR(6),          -- 6-digit OTP
    expiresAt DATETIME,        -- valid for 10 minutes
    used BOOLEAN DEFAULT FALSE
)
```

---

### B. Backend API — `server.py` (new endpoints)

#### [NEW] `POST /api/auth/forgot-password`
- Request body: `{ psNumber }`
- Looks up user by PS number
- If user has a registered `email` → generates 6-digit OTP, stores in `password_reset_tokens`, sends OTP email via SMTP
- If user has **no email** → returns `{ status: "no_email" }` so frontend can show the *"Contact your admin"* message
- Returns: `{ status: "success" | "no_email" | "user_not_found" }`

#### [NEW] `POST /api/auth/verify-otp`
- Request body: `{ psNumber, token }`
- Validates OTP against DB (checks expiry + `used` flag)
- If valid → marks token as used, returns a short-lived `resetToken` (random UUID) that the frontend uses for the next step
- Returns: `{ status: "success" | "invalid" | "expired", resetToken? }`

#### [NEW] `POST /api/auth/reset-password`
- Request body: `{ psNumber, resetToken, newPassword }`
- Validates `resetToken` (must be from a recent successful OTP verify, stored in memory/DB temporarily)
- Updates `users.password` in DB
- Returns: `{ status: "success" | "invalid_token" }`

#### [NEW] `POST /api/admin/reset-user-password`
- **Admin only** (enforce on backend by checking a passed `adminPsNumber` against DB role)
- Request body: `{ adminPsNumber, targetUserId, newPassword }`
- Directly updates `users.password` for `targetUserId`
- Optionally creates an in-app notification for the target user: *"Your password has been reset by the administrator."*
- Returns: `{ status: "success" | "unauthorized" }`

#### [NEW] `POST /api/auth/change-password`
- For **logged-in users** changing their own password
- Request body: `{ psNumber, currentPassword, newPassword }`
- Verifies `currentPassword` matches DB before updating
- Returns: `{ status: "success" | "wrong_current_password" }`

#### [MODIFY] `POST /api/sync` (users table)
- Already syncs the `users` table; will now also carry the `email` and `phone` fields through

#### [MODIFY] `GET /api/data`
- Will include `email` field in the user objects returned (needed for admin to see/manage emails in User Management)

---

### C. SMTP Configuration — `server.py`

#### [NEW] `smtp_config.json` or added to `db_config.json`
Stores SMTP credentials (not hardcoded):
```json
{
  "smtp_host": "smtp.adityabirla.com",
  "smtp_port": 587,
  "smtp_user": "utcl-bus-system@adityabirla.com",
  "smtp_password": "...",
  "sender_name": "UTCL Bus Management System"
}
```

#### [NEW] `send_otp_email(to_email, otp)` helper function in `server.py`
- Uses Python `smtplib` + `email.mime`
- Sends a nicely formatted OTP email

---

### D. Frontend — `index.html`

#### [MODIFY] Login screen
- Add a **"Forgot Password?"** link below the sign-in button
- Clicking it shows a new panel/step on the same login screen

#### [NEW] Forgot Password flow (3-step panel, no page reload)
- **Step 1:** Enter PS Number → hit "Send OTP"
  - If user has email → show masked email (`r****@adityabirla.com`) and "OTP sent" message
  - If no email → show: *"You don't have a registered email. Please contact your administrator to reset your password."*
- **Step 2:** Enter 6-digit OTP + optional resend button (60s cooldown)
- **Step 3:** Enter new password + confirm password → "Reset Password"

#### [MODIFY] Admin User Management table
- Add **"Reset Password"** button next to each non-admin user row (alongside existing Deactivate button)
- Clicking opens a small modal: *"Set new password for [Name]"* with a password input field + confirm

#### [MODIFY] User Management — Create/Edit User form
- Add optional `Email` field to the user creation form (for employees who have corporate email)

#### [NEW] Change Password modal (all logged-in users)
- A **"Change Password"** option accessible from the header (e.g. next to user profile or in a small dropdown)
- Modal with: Current Password, New Password, Confirm Password fields

---

### E. Frontend — `app.js`

#### [NEW] `handleForgotPassword(step, data)` — multi-step forgot password controller
#### [NEW] `submitOtpVerification()` — calls `/api/auth/verify-otp`
#### [NEW] `submitPasswordReset()` — calls `/api/auth/reset-password`
#### [NEW] `handleChangePassword()` — calls `/api/auth/change-password`
#### [NEW] `adminResetUserPassword(userId)` — admin modal + calls `/api/admin/reset-user-password`
#### [MODIFY] `handleCreateUser()` — include `email` field when creating users
#### [MODIFY] `loadAdminUsers()` — show email column + Reset Password button

---

### F. Frontend — `style.css`

#### [NEW] Styles for:
- Forgot password multi-step panel on login screen
- OTP input boxes (large digit inputs, premium look)
- "Reset Password" button variant in admin table
- Change Password modal

---

## Verification Plan

### Manual Testing

1. **Email OTP flow:**
   - Create a test user with a real `@adityabirla.com` email
   - Click "Forgot Password?" → enter PS number → receive OTP email → enter OTP → set new password → log in with new password ✅

2. **No-email user:**
   - Use a Driver account (no email)
   - Click "Forgot Password?" → should show "Contact admin" message, not send OTP ✅

3. **Admin resets user password:**
   - Admin opens User Management → clicks "Reset Password" on any user → sets new password → that user logs in with new password ✅

4. **Change Password (self-service):**
   - Log in as any user → click "Change Password" → enter wrong current password → should reject ✅
   - Enter correct current password + new password → should update → log out → log in with new password ✅

5. **OTP expiry:**
   - Request OTP → wait 10+ minutes → try to use it → should show "OTP expired" ✅

6. **OTP reuse:**
   - Use OTP once successfully → try to use same OTP again → should reject ✅

---

## Open Questions / Decisions Needed Before Build

> [!IMPORTANT]
> **SMTP credentials:** You will need to provide the actual SMTP host, port, sender email, and password before the email sending feature can be tested. These go in a config file and are NOT committed to any repo.

> [!NOTE]
> **Email field for existing users:** Currently no user has an email stored in the DB. After implementation, admin will need to go into User Management and add email addresses for each employee who has one. We can add a bulk-edit or per-user edit screen for this.

> [!NOTE]
> **Password policy:** Should we enforce minimum password length (e.g. 8 characters)? Complexity rules (uppercase, number)? Currently no rules exist.
