/**
 * UTCL Bus Management System - Core Client-Side Logic
 * Simulates a PostgreSQL + Redis backend using localStorage.
 */

function setSelectDisabled(nativeSelect, isDisabled) {
    if (!nativeSelect) return;
    nativeSelect.disabled = isDisabled;
    const container = document.getElementById('custom-select-' + nativeSelect.id);
    if (container) {
        container.classList.toggle('disabled', isDisabled);
        const trigger = container.querySelector('.custom-select-trigger');
        if (trigger) {
            trigger.classList.toggle('disabled', isDisabled);
        }
    }
}

function addMobileTableLabels(tableSelectorOrElement) {
    if (!tableSelectorOrElement) return;
    let el = typeof tableSelectorOrElement === 'string'
        ? document.querySelector(tableSelectorOrElement)
        : tableSelectorOrElement;
    if (!el) return;

    const table = el.tagName !== 'TABLE' ? el.closest('table') : el;
    if (!table) return;

    const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
    if (headers.length === 0) return;

    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
        const cells = row.querySelectorAll('td');
        cells.forEach((cell, idx) => {
            const content = cell.textContent.trim();
            const hasVisualElements = cell.querySelector('img, input, select, canvas, button, svg, a');
            if (!content && !hasVisualElements) {
                cell.innerHTML = '—';
            }
            if (headers[idx]) {
                cell.setAttribute('data-label', headers[idx]);
            }
        });
    });
}

class UTCLBusSystem {
    constructor() {
        this.initDatabase();
        this.initSession();
        this.setupEventListeners();
        this.startInactivityTimer();

        // Active states for booking flow
        this.bookingData = {
            date: '',
            shiftId: '',
            boardingIndex: -1,
            dropIndex: -1,
            empName: '',
            psNumber: '',
            verified: false,
            seatNumber: -1,
            seatNumbers: []
        };

        // Active admin navigation state
        this.currentAdminTab = 'dashboard';
        this.currentEmployeeTab = 'booking';

        // Edit Shift State
        this.activeEditShiftId = null;

        // WebSocket state
        this.socket = null;
        this.currentSeatRoom = null;  // room name currently joined, e.g. 'S1F_2026-06-06'
        this._seatPollInterval = null;  // fallback polling interval
        this.attendancePollInterval = null; // fallback polling interval for attendance
        this.isSocketReconnecting = false;
        this._syncTimeout = null;
        this._syncResolveQueue = [];

        // Check and render initial view
        this.renderView();

        // If user is already logged in, sync latest database state immediately
        if (this.currentUser) {
            this.syncStateSilent();
        }

        // Initialize WebSocket after DOM is ready
        this.initSocket();

        // Initialize custom dropdown refactoring
        this.initCustomSelects();
    }

    loadScript(src) {
        return new Promise((resolve, reject) => {
            if (document.querySelector(`script[src="${src}"]`)) {
                resolve();
                return;
            }
            const script = document.createElement('script');
            script.src = src;
            script.onload = () => resolve();
            script.onerror = () => reject(new Error(`Failed to load script ${src}`));
            document.head.appendChild(script);
        });
    }

    getShiftLabel(shiftId) {
        const mapping = {
            'S1F': 'Bus 1 - Forward',
            'S1R': 'Bus 1 - Return',
            'S2F': 'Bus 2 - Forward',
            'S2R': 'Bus 2 - Return',
            'S3F': 'Bus 3 - Forward',
            'S3R': 'Bus 3 - Return',
            'S4F': 'Bus 4 - Forward',
            'S4R': 'Bus 4 - Return'
        };
        return mapping[shiftId] || shiftId;
    }

    // ==========================================================================
    // 1. DATABASE & STATE SIMULATION (PERSISTED IN LOCALSTORAGE)
    // ==========================================================================

    initDatabase() {
        // Core tables
        const defaultUsers = [
            { id: 'u1', name: 'System Administrator', psNumber: 'PS00001', password: 'password123', role: 'ADMIN', isActive: true, email: 'admin@adityabirla.com' },
            { id: 'u2', name: 'Rohan Sharma', psNumber: 'PS10001', password: 'password123', role: 'EMPLOYEE', isActive: true, email: 'employee@adityabirla.com' },
            { id: 'u3', name: 'Amit Verma', psNumber: 'PS10002', password: 'password123', role: 'EMPLOYEE', isActive: true, email: 'amit.verma@adityabirla.com' },
            { id: 'u4', name: 'Priya Patel', psNumber: 'PS10003', password: 'password123', role: 'EMPLOYEE', isActive: true, email: 'priya.patel@adityabirla.com' },
            { id: 'u5', name: 'Sanjay Gupta', psNumber: 'PS10004', password: 'password123', role: 'EMPLOYEE', isActive: true, email: 'sanjay.gupta@adityabirla.com' },
            { id: 'u6', name: 'Rajesh Kumar', psNumber: 'PS20001', password: 'password123', role: 'DRIVER', isActive: true, email: 'rajesh@gmail.com' },
            { id: 'u7', name: 'Suresh Singh', psNumber: 'PS20002', password: 'password123', role: 'DRIVER', isActive: true, email: 'suresh@gmail.com' },
            { id: 'u8', name: 'Vikram Rathore', psNumber: 'PS20003', password: 'password123', role: 'DRIVER', isActive: true, email: 'vikram@gmail.com' }
        ];

        const defaultBuses = [
            { id: 'b1', identifier: 'Bus 1', isActive: true },
            { id: 'b2', identifier: 'Bus 2', isActive: true }
        ];

        const defaultShifts = [
            {
                id: 'S1F', busId: 'b1', direction: 'FORWARD', departureTime: '05:30 AM', isActive: true, stops: [
                    { index: 0, name: 'Awalpur', arrival: '05:30 AM' },
                    { index: 1, name: 'Bibee', arrival: '05:40 AM' },
                    { index: 2, name: 'Gadchandur', arrival: '05:55 AM' },
                    { index: 3, name: 'Manikgarh', arrival: '06:00 AM' },
                    { index: 4, name: 'Rajura', arrival: '06:25 AM' },
                    { index: 5, name: 'Ballarsha', arrival: '06:40 AM' },
                    { index: 6, name: 'Chandrapur', arrival: '07:10 AM' }
                ]
            },
            {
                id: 'S1R', busId: 'b1', direction: 'RETURN', departureTime: '08:00 AM', isActive: true, stops: [
                    { index: 0, name: 'Chandrapur', arrival: '08:00 AM' },
                    { index: 1, name: 'Ballarsha', arrival: '08:30 AM' },
                    { index: 2, name: 'Rajura', arrival: '08:45 AM' },
                    { index: 3, name: 'Manikgarh', arrival: '09:10 AM' },
                    { index: 4, name: 'Gadchandur', arrival: '09:15 AM' },
                    { index: 5, name: 'Bibee', arrival: '09:30 AM' },
                    { index: 6, name: 'Awalpur', arrival: '09:40 AM' }
                ]
            },
            {
                id: 'S2F', busId: 'b2', direction: 'FORWARD', departureTime: '08:30 AM', isActive: true, stops: [
                    { index: 0, name: 'Awalpur', arrival: '08:30 AM' },
                    { index: 1, name: 'Bibee', arrival: '08:40 AM' },
                    { index: 2, name: 'Gadchandur', arrival: '08:55 AM' },
                    { index: 3, name: 'Manikgarh', arrival: '09:00 AM' },
                    { index: 4, name: 'Rajura', arrival: '09:25 AM' },
                    { index: 5, name: 'Ballarsha', arrival: '09:40 AM' },
                    { index: 6, name: 'Chandrapur', arrival: '10:10 AM' }
                ]
            },
            {
                id: 'S2R', busId: 'b2', direction: 'RETURN', departureTime: '12:30 PM', isActive: true, stops: [
                    { index: 0, name: 'Chandrapur', arrival: '12:30 PM' },
                    { index: 1, name: 'Ballarsha', arrival: '01:00 PM' },
                    { index: 2, name: 'Rajura', arrival: '01:15 PM' },
                    { index: 3, name: 'Manikgarh', arrival: '01:40 PM' },
                    { index: 4, name: 'Gadchandur', arrival: '01:45 PM' },
                    { index: 5, name: 'Bibee', arrival: '02:00 PM' },
                    { index: 6, name: 'Awalpur', arrival: '02:10 PM' }
                ]
            },
            {
                id: 'S3F', busId: 'b1', direction: 'FORWARD', departureTime: '10:30 AM', isActive: true, stops: [
                    { index: 0, name: 'Awalpur', arrival: '10:30 AM' },
                    { index: 1, name: 'Bibee', arrival: '10:40 AM' },
                    { index: 2, name: 'Gadchandur', arrival: '10:55 AM' },
                    { index: 3, name: 'Manikgarh', arrival: '11:00 AM' },
                    { index: 4, name: 'Rajura', arrival: '11:25 AM' },
                    { index: 5, name: 'Ballarsha', arrival: '11:40 AM' },
                    { index: 6, name: 'Chandrapur', arrival: '12:10 PM' }
                ]
            },
            {
                id: 'S3R', busId: 'b1', direction: 'RETURN', departureTime: '03:30 PM', isActive: true, stops: [
                    { index: 0, name: 'Chandrapur', arrival: '03:30 PM' },
                    { index: 1, name: 'Ballarsha', fill: '#58595B', arrival: '04:00 PM' },
                    { index: 2, name: 'Rajura', arrival: '04:15 PM' },
                    { index: 3, name: 'Manikgarh', arrival: '04:40 PM' },
                    { index: 4, name: 'Gadchandur', arrival: '04:45 PM' },
                    { index: 5, name: 'Bibee', arrival: '05:00 PM' },
                    { index: 6, name: 'Awalpur', arrival: '05:10 PM' }
                ]
            },
            {
                id: 'S4F', busId: 'b2', direction: 'FORWARD', departureTime: '03:00 PM', isActive: true, stops: [
                    { index: 0, name: 'Awalpur', arrival: '03:00 PM' },
                    { index: 1, name: 'Bibee', arrival: '03:10 PM' },
                    { index: 2, name: 'Gadchandur', arrival: '03:25 PM' },
                    { index: 3, name: 'Manikgarh', arrival: '03:30 PM' },
                    { index: 4, name: 'Rajura', arrival: '03:55 PM' },
                    { index: 5, name: 'Ballarsha', arrival: '04:10 PM' },
                    { index: 6, name: 'Chandrapur', arrival: '04:40 PM' }
                ]
            },
            {
                id: 'S4R', busId: 'b2', direction: 'RETURN', departureTime: '07:00 PM', isActive: true, stops: [
                    { index: 0, name: 'Chandrapur', arrival: '07:00 PM' },
                    { index: 1, name: 'Ballarsha', arrival: '07:30 PM' },
                    { index: 2, name: 'Rajura', arrival: '07:45 PM' },
                    { index: 3, name: 'Manikgarh', arrival: '08:10 PM' },
                    { index: 4, name: 'Gadchandur', arrival: '08:15 PM' },
                    { index: 5, name: 'Bibee', arrival: '08:30 PM' },
                    { index: 6, name: 'Awalpur', arrival: '08:40 PM' }
                ]
            }
        ];

        // Seed if missing
        if (!localStorage.getItem('utcl_users')) {
            localStorage.setItem('utcl_users', JSON.stringify(defaultUsers));
        }
        if (!localStorage.getItem('utcl_buses')) {
            localStorage.setItem('utcl_buses', JSON.stringify(defaultBuses));
        }
        if (!localStorage.getItem('utcl_shifts')) {
            localStorage.setItem('utcl_shifts', JSON.stringify(defaultShifts));
        }
        if (!localStorage.getItem('utcl_driver_shifts')) {
            // Assign drivers initially
            const defaultAssignments = [
                { id: 'da1', driverId: 'u6', shiftId: 'S1F', date: this.getTodayString() },
                { id: 'da2', driverId: 'u6', shiftId: 'S1R', date: this.getTodayString() },
                { id: 'da3', driverId: 'u7', shiftId: 'S2F', date: this.getTodayString() },
                { id: 'da4', driverId: 'u7', shiftId: 'S2R', date: this.getTodayString() }
            ];
            localStorage.setItem('utcl_driver_shifts', JSON.stringify(defaultAssignments));
        }
        if (!localStorage.getItem('utcl_maintenance')) {
            const defaultMaintenance = [
                { id: 'm1', busId: 'b1', scheduledDate: this.getRelativeDateString(-2), description: 'Periodic engine tuning & filter replacement', status: 'COMPLETED', actualCompletionDate: this.getRelativeDateString(-2) },
                { id: 'm2', busId: 'b2', scheduledDate: this.getRelativeDateString(-5), description: 'Brake pad renewal and fluid top-up', status: 'COMPLETED', actualCompletionDate: this.getRelativeDateString(-5) },
                { id: 'm3', busId: 'b1', scheduledDate: this.getRelativeDateString(3), description: 'A/C service & refrigerant recharge', status: 'SCHEDULED', actualCompletionDate: null }
            ];
            localStorage.setItem('utcl_maintenance', JSON.stringify(defaultMaintenance));
        }
        if (!localStorage.getItem('utcl_tracking')) {
            const defaultTracking = [
                { busId: 'b1', operationalStatus: 'ACTIVE', currentShiftId: 'S1F', currentStopIndex: 3, lastUpdated: new Date().toISOString() },
                { busId: 'b2', operationalStatus: 'IDLE', currentShiftId: null, currentStopIndex: null, lastUpdated: new Date().toISOString() }
            ];
            localStorage.setItem('utcl_tracking', JSON.stringify(defaultTracking));
        }
        if (!localStorage.getItem('utcl_notifications')) {
            localStorage.setItem('utcl_notifications', JSON.stringify([]));
        }
        if (!localStorage.getItem('utcl_cancelled_shifts')) {
            localStorage.setItem('utcl_cancelled_shifts', JSON.stringify([]));
        }

        // Initialize empty arrays if none exist
        if (!localStorage.getItem('utcl_bookings')) {
            localStorage.setItem('utcl_bookings', JSON.stringify([]));
        }
        if (!localStorage.getItem('utcl_tickets')) {
            localStorage.setItem('utcl_tickets', JSON.stringify([]));
        }

        // Seed bookings with beautiful analytics data if none exist (local development only)
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            const currentBookings = JSON.parse(localStorage.getItem('utcl_bookings') || '[]');
            if (currentBookings.length === 0) {
                this.seedMockBookings();
            } else {
                // Clean up any pre-seeded mock bookings for today's date to allow active testing
                const bookings = JSON.parse(localStorage.getItem('utcl_bookings'));
                const todayStr = this.getTodayString();
                const hasMockToday = bookings.some(b => b.travelDate === todayStr && b.id.startsWith('bk_') && b.id.includes(todayStr));
                if (hasMockToday) {
                    const filteredBookings = bookings.filter(b => !(b.travelDate === todayStr && b.id.startsWith('bk_') && b.id.includes(todayStr)));
                    localStorage.setItem('utcl_bookings', JSON.stringify(filteredBookings));
                    
                    if (localStorage.getItem('utcl_tickets')) {
                        const tickets = JSON.parse(localStorage.getItem('utcl_tickets'));
                        const filteredTickets = tickets.filter(t => !(t.travelDate === todayStr && t.id.startsWith('tk_') && t.id.includes(todayStr)));
                        localStorage.setItem('utcl_tickets', JSON.stringify(filteredTickets));
                    }
                }
            }
        }
    }

    seedMockBookings() {
        const bookings = [];
        const tickets = [];
        const shifts = JSON.parse(localStorage.getItem('utcl_shifts'));
        const users = JSON.parse(localStorage.getItem('utcl_users'));
        const employees = users.filter(u => u.role === 'EMPLOYEE');

        // Loop over the past 15 days, excluding today (i = 0) to allow live active booking tests
        for (let i = 15; i >= 1; i--) {
            const dateStr = this.getRelativeDateString(-i);

            shifts.forEach(shift => {
                // Generate a random booking load (higher load on weekdays, lower on weekends)
                const dateObj = new Date(dateStr);
                const day = dateObj.getDay();
                const isWeekend = (day === 0 || day === 6);

                // Average bookings: 2-3 on weekdays, 1 on weekends
                const numBookings = isWeekend ? 1 : Math.floor(Math.random() * 2) + 2;

                const selectedSeats = new Set();
                for (let j = 0; j < numBookings; j++) {
                    const emp = employees[Math.floor(Math.random() * employees.length)];
                    let seatNumber;
                    do {
                        seatNumber = Math.floor(Math.random() * 49) + 2;
                    } while (selectedSeats.has(seatNumber));
                    selectedSeats.add(seatNumber);

                    // Pick random valid boarding and drop off stops
                    const boardingIdx = Math.floor(Math.random() * 5); // 0 to 4
                    const dropIdx = boardingIdx + Math.floor(Math.random() * (6 - boardingIdx)) + 1; // boardingIdx + 1 to 6

                    const bookingId = `bk_${dateStr}_${shift.id}_${seatNumber}`;
                    const ticketId = `tk_${dateStr}_${shift.id}_${seatNumber}`;

                    bookings.push({
                        id: bookingId,
                        shiftId: shift.id,
                        psNumber: emp.psNumber,
                        employeeName: emp.name,
                        seatNumber: seatNumber,
                        boardingStopIndex: boardingIdx,
                        dropStopIndex: dropIdx,
                        fareAmount: 20,
                        status: 'CONFIRMED',
                        travelDate: dateStr,
                        bookedAt: new Date(dateStr + 'T08:00:00').toISOString()
                    });

                    tickets.push({
                        id: ticketId,
                        bookingId: bookingId,
                        ticketNumber: `UTCL-${Math.floor(Math.random() * 90000) + 10000}`,
                        employeeName: emp.name,
                        psNumber: emp.psNumber,
                        shiftCode: shift.id,
                        seatNumber: seatNumber,
                        boardingStop: shift.stops[boardingIdx].name,
                        dropStop: shift.stops[dropIdx].name,
                        fare: 20,
                        departureTime: shift.departureTime,
                        travelDate: dateStr,
                        generatedAt: new Date(dateStr + 'T08:05:00').toISOString()
                    });
                }
            });
        }

        localStorage.setItem('utcl_bookings', JSON.stringify(bookings));
        localStorage.setItem('utcl_tickets', JSON.stringify(tickets));
    }

    // Helper functions for dates
    getTodayString() {
        const t = new Date();
        return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
    }

    getRelativeDateString(offsetDays) {
        const t = new Date();
        t.setDate(t.getDate() + offsetDays);
        return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
    }

    // Generic DB Accessors
    getItems(key) {
        return JSON.parse(localStorage.getItem(key)) || [];
    }

    setItem(key, data) {
        localStorage.setItem(key, JSON.stringify(data));
        const syncKeys = [
            'utcl_users',
            'utcl_buses',
            'utcl_shifts',
            'utcl_driver_shifts',
            'utcl_maintenance',
            'utcl_tracking',
            'utcl_notifications',
            'utcl_bookings',
            'utcl_tickets'
        ];
        // Async background sync to MySQL backend
        if (syncKeys.includes(key)) {
            let syncData = data;
            if (key === 'utcl_bookings') {
                syncData = data.filter(b => b.id && !b.id.startsWith('ws_'));
            } else if (key === 'utcl_tickets') {
                syncData = data.filter(t => t.bookingId && !t.bookingId.startsWith('ws_'));
            }
            return fetch('/api/sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key, data: syncData })
            }).then(response => {
                if (response.status === 401) {
                    console.warn('Session expired or unauthorized (401). Logging out.');
                    this.logout(true);
                } else if (!response.ok) {
                    console.error('Failed to sync changes to database for key:', key);
                }
                return response;
            }).catch(err => {
                console.error('Network error syncing changes to database for key:', key, err);
                throw err;
            });
        }
        return Promise.resolve(null);
    }

    // ==========================================================================
    // 2. SESSION & SECURITY CONTROLS
    // ==========================================================================

    initSession() {
        this.currentUser = JSON.parse(localStorage.getItem('utcl_session')) || null;
        this.resetInactivityTimer();
    }

    resetInactivityTimer() {
        this.lastActivityTime = Date.now();
        if (this.currentUser) {
            localStorage.setItem('utcl_session_last_activity', String(this.lastActivityTime));
        }
    }

    startInactivityTimer() {
        setInterval(() => {
            if (!this.currentUser) return;

            const elapsedMs = Date.now() - this.lastActivityTime;
            const elapsedMinutes = elapsedMs / 60000;

            // 25 minutes warning
            if (elapsedMinutes >= 25 && elapsedMinutes < 30) {
                const modal = document.getElementById('inactivity-modal');
                if (modal && modal.classList.contains('hidden')) {
                    modal.classList.remove('hidden');
                }
            }

            // 30 minutes logout
            if (elapsedMinutes >= 30) {
                this.logout(true); // Forced logout due to timeout
            }
        }, 10000); // Check every 10 seconds
    }

    refreshActivity() {
        this.resetInactivityTimer();
        const modal = document.getElementById('inactivity-modal');
        if (modal) modal.classList.add('hidden');
    }

    // Forgot Password & Reset Methods
    showForgotPasswordStep1(e) {
        if (e) e.preventDefault();
        // Hide login form
        document.getElementById('login-form').classList.add('hidden');
        // Reset errors and inputs
        document.getElementById('fp-ps-number').value = '';
        document.getElementById('fp-step1-error').classList.add('hidden');
        document.getElementById('fp-step-1').classList.remove('hidden');
        document.getElementById('fp-step-2').classList.add('hidden');
        document.getElementById('fp-step-3').classList.add('hidden');
        
        // Show forgot password panel
        document.getElementById('forgot-password-panel').classList.remove('hidden');
        document.getElementById('forgot-password-desc').textContent = "Please enter your PS Number to receive a reset OTP.";
    }

    showLoginForm(e) {
        if (e) e.preventDefault();
        // Hide forgot password panel
        document.getElementById('forgot-password-panel').classList.add('hidden');
        // Show login form
        document.getElementById('login-form').classList.remove('hidden');
        document.getElementById('login-error-message').classList.add('hidden');
        
        // Clear timer if running
        if (this._otpInterval) {
            clearInterval(this._otpInterval);
            this._otpInterval = null;
        }
    }

    async submitForgotPasswordStep1() {
        const psInput = document.getElementById('fp-ps-number').value.trim().toUpperCase();
        const errAlert = document.getElementById('fp-step1-error');
        if (errAlert) errAlert.classList.add('hidden');
        
        if (!psInput) {
            errAlert.textContent = "Please enter your PS Number.";
            errAlert.classList.remove('hidden');
            return;
        }
        
        try {
            const res = await fetch('/api/auth/forgot-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ psNumber: psInput })
            });
            
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || "Server error, failed to send OTP.");
            
            if (data.status === 'user_not_found') {
                errAlert.textContent = "PS Number not found in system.";
                errAlert.classList.remove('hidden');
            } else if (data.status === 'no_email') {
                errAlert.innerHTML = `You don't have a registered email.<br>Please contact your administrator to reset your password.`;
                errAlert.classList.remove('hidden');
            } else if (data.status === 'success') {
                // Save state
                this._resetPsNumber = psInput;
                this._maskedEmail = data.maskedEmail;
                
                // Advance to step 2
                document.getElementById('fp-step-1').classList.add('hidden');
                document.getElementById('fp-step-2').classList.remove('hidden');
                document.getElementById('forgot-password-desc').innerHTML = `OTP has been sent to your registered email: <strong>${data.maskedEmail}</strong>. Please check your inbox.`;
                
                // Clear OTP digit inputs
                const digitInputs = document.querySelectorAll('.otp-digit');
                digitInputs.forEach(input => input.value = '');
                if (digitInputs[0]) digitInputs[0].focus();
                
                // Start cooldown timer
                this.startOtpTimer();
            }
        } catch (err) {
            errAlert.textContent = err.message;
            errAlert.classList.remove('hidden');
        }
    }

    handleOtpInput(element, event) {
        // Move to next input on entering a character
        if (element.value.length === element.maxLength) {
            const next = element.nextElementSibling;
            if (next && next.classList.contains('otp-digit')) {
                next.focus();
            }
        }
        // Move to previous on backspace
        if (event.key === 'Backspace' || event.key === 'Delete') {
            const prev = element.previousElementSibling;
            if (prev && prev.classList.contains('otp-digit')) {
                prev.focus();
            }
        }
    }

    getOtpValue() {
        const digitInputs = document.querySelectorAll('.otp-digit');
        let otp = '';
        digitInputs.forEach(input => {
            otp += input.value.trim();
        });
        return otp;
    }

    async submitForgotPasswordStep2() {
        const otp = this.getOtpValue();
        const errAlert = document.getElementById('fp-step2-error');
        if (errAlert) errAlert.classList.add('hidden');
        
        if (otp.length < 6) {
            errAlert.textContent = "Please enter the complete 6-digit OTP code.";
            errAlert.classList.remove('hidden');
            return;
        }
        
        try {
            const res = await fetch('/api/auth/verify-otp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    psNumber: this._resetPsNumber,
                    token: otp
                })
            });
            
            if (!res.ok) throw new Error("Server error, failed to verify OTP.");
            const data = await res.json();
            
            if (data.status === 'invalid') {
                errAlert.textContent = "Invalid OTP code. Please try again.";
                errAlert.classList.remove('hidden');
            } else if (data.status === 'expired') {
                errAlert.textContent = "OTP code has expired. Please request a new one.";
                errAlert.classList.remove('hidden');
            } else if (data.status === 'success') {
                // Save temporary resetToken
                this._resetToken = data.resetToken;
                
                // Clear timer
                if (this._otpInterval) {
                    clearInterval(this._otpInterval);
                    this._otpInterval = null;
                }
                
                // Advance to step 3
                document.getElementById('fp-step-2').classList.add('hidden');
                document.getElementById('fp-step-3').classList.remove('hidden');
                document.getElementById('forgot-password-desc').textContent = "Please set a secure new password for your account.";
                
                document.getElementById('fp-new-password').value = '';
                document.getElementById('fp-confirm-password').value = '';
            }
        } catch (err) {
            errAlert.textContent = err.message;
            errAlert.classList.remove('hidden');
        }
    }

    async submitForgotPasswordStep3() {
        const newPassword = document.getElementById('fp-new-password').value;
        const confirmPassword = document.getElementById('fp-confirm-password').value;
        const errAlert = document.getElementById('fp-step3-error');
        if (errAlert) errAlert.classList.add('hidden');
        
        if (!newPassword || !confirmPassword) {
            errAlert.textContent = "All fields are required.";
            errAlert.classList.remove('hidden');
            return;
        }
        
        if (newPassword !== confirmPassword) {
            errAlert.textContent = "Passwords do not match.";
            errAlert.classList.remove('hidden');
            return;
        }
        
        try {
            const res = await fetch('/api/auth/reset-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    psNumber: this._resetPsNumber,
                    resetToken: this._resetToken,
                    newPassword: newPassword
                })
            });
            
            if (!res.ok) throw new Error("Server error, failed to reset password.");
            const data = await res.json();
            
            if (data.status === 'invalid_token') {
                errAlert.textContent = "Session expired or invalid token. Please start over.";
                errAlert.classList.remove('hidden');
            } else if (data.status === 'success') {
                // Update local storage user password representation
                const users = this.getItems('utcl_users');
                const user = users.find(u => u.psNumber.toUpperCase() === this._resetPsNumber.toUpperCase());
                if (user) {
                    user.password = newPassword;
                    this.setItem('utcl_users', users);
                }
                
                this.showLiveToast("Password reset successfully! You can now log in.", "Success");
                this.showLoginForm();
            }
        } catch (err) {
            errAlert.textContent = err.message;
            errAlert.classList.remove('hidden');
        }
    }

    startOtpTimer() {
        const btn = document.getElementById('otp-resend-btn');
        const timerSpan = document.getElementById('otp-timer');
        if (!btn || !timerSpan) return;
        
        btn.disabled = true;
        btn.style.textDecoration = 'none';
        btn.style.cursor = 'default';
        
        let seconds = 60;
        timerSpan.textContent = seconds;
        
        if (this._otpInterval) clearInterval(this._otpInterval);
        
        this._otpInterval = setInterval(() => {
            seconds--;
            timerSpan.textContent = seconds;
            if (seconds <= 0) {
                clearInterval(this._otpInterval);
                this._otpInterval = null;
                btn.disabled = false;
                btn.style.textDecoration = 'underline';
                btn.style.cursor = 'pointer';
                btn.innerHTML = 'Resend OTP';
            }
        }, 1000);
    }

    async resendOtp() {
        const errAlert = document.getElementById('fp-step2-error');
        if (errAlert) errAlert.classList.add('hidden');
        
        try {
            const res = await fetch('/api/auth/forgot-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ psNumber: this._resetPsNumber })
            });
            
            if (!res.ok) throw new Error("Failed to resend OTP.");
            const data = await res.json();
            
            if (data.status === 'success') {
                this.showLiveToast("A new OTP code has been sent to your email.", "Info");
                this.startOtpTimer();
            } else {
                throw new Error("Unable to send OTP code.");
            }
        } catch (err) {
            errAlert.textContent = err.message;
            errAlert.classList.remove('hidden');
        }
    }

    // Change Password Self Service
    async submitChangePassword() {
        const currentPassword = document.getElementById('cp-current-password').value;
        const newPassword = document.getElementById('cp-new-password').value;
        const confirmPassword = document.getElementById('cp-confirm-password').value;
        const errAlert = document.getElementById('cp-error');
        if (errAlert) errAlert.classList.add('hidden');
        
        if (!currentPassword || !newPassword || !confirmPassword) {
            errAlert.textContent = "All fields are required.";
            errAlert.classList.remove('hidden');
            return;
        }
        
        if (newPassword !== confirmPassword) {
            errAlert.textContent = "New password and confirmation do not match.";
            errAlert.classList.remove('hidden');
            return;
        }
        
        if (currentPassword === newPassword) {
            errAlert.textContent = "New password cannot be the same as your current password.";
            errAlert.classList.remove('hidden');
            return;
        }
        
        try {
            const res = await fetch('/api/auth/change-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    psNumber: this.currentUser.psNumber,
                    currentPassword: currentPassword,
                    newPassword: newPassword
                })
            });
            
            if (!res.ok) throw new Error("Server error, failed to update password.");
            const data = await res.json();
            
            if (data.status === 'wrong_current_password') {
                errAlert.textContent = "Incorrect current password.";
                errAlert.classList.remove('hidden');
            } else if (data.status === 'same_password') {
                errAlert.textContent = "New password cannot be the same as your current password.";
                errAlert.classList.remove('hidden');
            } else if (data.status === 'success') {
                // Update local storage representation
                const users = this.getItems('utcl_users');
                const user = users.find(u => u.psNumber.toUpperCase() === this.currentUser.psNumber.toUpperCase());
                if (user) {
                    user.password = newPassword;
                    this.setItem('utcl_users', users);
                }
                
                this.closeModal('change-password-modal');
                this.showLiveToast("Password updated successfully!", "Success");
            }
        } catch (err) {
            errAlert.textContent = err.message;
            errAlert.classList.remove('hidden');
        }
    }

    // Authentication Actions
    async handleLogin(e) {
        e.preventDefault();
        const psInput = document.getElementById('login-ps-number').value.trim().toUpperCase();
        const passwordInput = document.getElementById('login-password').value;
        const err = document.getElementById('login-error-message');
        if (err) err.classList.add('hidden');

        if (!psInput || !passwordInput) {
            if (err) {
                err.textContent = "Please enter both PS Number and password.";
                err.classList.remove('hidden');
            }
            return;
        }

        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ psNumber: psInput, password: passwordInput })
            });
            const data = await res.json();

            // 401 = invalid credentials (not a session-expired auto-logout — user is not logged in yet)
            if (res.status === 401 || data.status === 'invalid') {
                if (err) {
                    err.textContent = "Invalid PS Number or password. Please try again.";
                    err.classList.remove('hidden');
                }
                return;
            }

            if (!res.ok) throw new Error(data.message || "Server error. Please try again.");

            if (data.status === 'success') {
                this.currentUser = {
                    id: data.user.id,
                    name: data.user.name,
                    psNumber: data.user.psNumber,
                    role: data.user.role,
                    plant: data.user.plant
                };

                localStorage.setItem('utcl_session', JSON.stringify(this.currentUser));
                this.resetInactivityTimer();

                // Emit dynamic socket user registration on login
                if (this.socket && this.socket.connected) {
                    this.socket.emit('register_user', {
                        psNumber: this.currentUser.psNumber,
                        userId: this.currentUser.id,
                        role: this.currentUser.role
                    });
                }

                // Sync all database state from server upon successful login
                await this.syncStateSilent();

                // Clear inputs
                document.getElementById('login-ps-number').value = '';
                document.getElementById('login-password').value = '';
                if (err) err.classList.add('hidden');

                this.renderView();
            } else {
                if (err) {
                    err.textContent = "Invalid credentials. Please try again.";
                    err.classList.remove('hidden');
                }
            }
        } catch (errVal) {
            if (err) {
                err.textContent = errVal.message;
                err.classList.remove('hidden');
            }
        }
    }

    logout(isTimeout = false) {
        this.stopAttendancePolling();
        if (this.currentUser && this.socket && this.socket.connected) {
            this.socket.emit('unregister_user', {
                psNumber: this.currentUser.psNumber,
                userId: this.currentUser.id,
                role: this.currentUser.role
            });
        }
        this.currentUser = null;
        localStorage.removeItem('utcl_session');
        localStorage.removeItem('utcl_session_last_activity');

        // Close modals
        const timeoutModal = document.getElementById('inactivity-modal');
        if (timeoutModal) timeoutModal.classList.add('hidden');

        this.renderView();

        if (isTimeout) {
            alert("Your session has expired due to 30 minutes of inactivity. You have been logged out.");
        }
    }

    // ==========================================================================
    // 3. EMPLOYEE BOOKING FLOW & UTILITIES
    // ==========================================================================

    switchEmployeeTab(tab) {
        if (this.currentEmployeeTab === 'booking' && ['seats', 'stops', 'confirm'].includes(this.currentStep)) {
            return;
        }
        this.currentEmployeeTab = tab;
        const navBtns = document.querySelectorAll('.emp-nav-btn');
        navBtns.forEach(btn => {
            if (btn.getAttribute('onclick').includes(tab)) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Hide all employee tab contents
        const panels = document.querySelectorAll('.emp-tab-panel');
        panels.forEach(p => p.classList.remove('active'));

        // Show active panel
        const activePanel = document.getElementById(`emp-tab-${tab}`);
        if (activePanel) activePanel.classList.add('active');

        // Reload views
        if (tab === 'booking') {
            this.resetBookingFlow();
        } else if (tab === 'history') {
            this.loadBookingHistory();
        } else if (tab === 'schedules') {
            this.loadSchedulesTimings();
        } else if (tab === 'mytickets') {
            this.loadMyTickets();
        } else if (tab === 'myfares') {
            this.loadMyFares();
        }
    }

    resetBookingFlow() {
        this.bookingData = {
            date: this.getTodayString(),
            shiftId: '',
            boardingIndex: -1,
            dropIndex: -1,
            empName: this.currentUser ? this.currentUser.name : '',
            psNumber: this.currentUser ? this.currentUser.psNumber : '',
            verified: true, // Auto-verified
            seatNumber: '',
            seatNumbers: [],
            passengers: this.currentUser ? [{ name: this.currentUser.name, isEmployee: true, psNumber: this.currentUser.psNumber }] : [],
            remainingLimit: 4
        };

        // Reset inputs
        const dateInput = document.getElementById('booking-date');
        if (dateInput) {
            dateInput.value = this.bookingData.date;
            dateInput.min = this.getTodayString();
        }

        const psNumberInput = document.getElementById('booking-ps-number');
        if (psNumberInput && this.currentUser) {
            psNumberInput.value = this.currentUser.psNumber;
            psNumberInput.disabled = true;
        }

        const empNameInput = document.getElementById('booking-emp-name');
        if (empNameInput && this.currentUser) {
            empNameInput.value = this.currentUser.name;
            empNameInput.disabled = true;
        }

        const selfCheck = document.getElementById('booking-self-check');
        if (selfCheck) {
            selfCheck.checked = true;
            selfCheck.disabled = false;
        }

        const passengerListContainer = document.getElementById('passenger-list-container');
        if (passengerListContainer) {
            passengerListContainer.innerHTML = '';
        }

        const toConfirmBtn = document.getElementById('btn-to-confirm');
        if (toConfirmBtn) {
            toConfirmBtn.disabled = true;
        }

        // Reset panels
        this.changeStep('schedule');
        this.renderAvailableShifts();

        // Clear ticket/seat display
        const ticketEmptyState = document.getElementById('ticket-empty-state');
        if (ticketEmptyState) ticketEmptyState.classList.remove('hidden');

        const seatContainer = document.getElementById('seat-selection-container');
        if (seatContainer) seatContainer.classList.add('hidden');

        const ticketCard = document.getElementById('virtual-ticket-card');
        if (ticketCard) ticketCard.classList.add('hidden');
    }

    onBookingDateChange() {
        this.bookingData.date = document.getElementById('booking-date').value;
        this.bookingData.shiftId = '';
        this.renderAvailableShifts();
    }

    renderAvailableShifts() {
        const container = document.getElementById('booking-shifts-list');
        if (!container) return;
        container.innerHTML = '';

        if (!this.bookingData.date) {
            return;
        }

        const monthPrefix = this.bookingData.date.substring(0, 7);
        const periods = this.getItems('utcl_payroll_periods') || [];
        const isPeriodLocked = periods.some(p => p.periodMonth === monthPrefix && p.status === 'PROCESSED');

        if (isPeriodLocked) {
            container.innerHTML = `
                <div class="alert alert-danger font-semibold" style="margin: 15px 0; border-radius: 8px; border-left: 4px solid var(--accent-danger, #ef4444); background: rgba(239, 68, 68, 0.1); color: var(--accent-danger, #ef4444); padding: 12px 16px;">
                    ⚠️ Bookings and cancellations are frozen for ${monthPrefix} because the payroll period has already been processed and locked.
                </div>
            `;
            // Also hide seat selection container in case it was showing
            const seatContainer = document.getElementById('seat-selection-container');
            if (seatContainer) seatContainer.classList.add('hidden');
            return;
        }

        const shifts = this.getItems('utcl_shifts').filter(s => s.isActive);
        const bookings = this.getItems('utcl_bookings').filter(b => b.travelDate === this.bookingData.date && b.status === 'CONFIRMED');

        const now = new Date();
        const isToday = (this.bookingData.date === this.getTodayString());

        shifts.forEach(shift => {
            const cancelledShifts = this.getItems('utcl_cancelled_shifts') || [];
            const isCancelled = cancelledShifts.some(cs => cs.shiftId === shift.id && cs.date === this.bookingData.date);

            // Check if shift departure time has passed today or is within the 5-minute lock window
            let isPassed = false;
            let isLocked = false;
            if (isToday) {
                const [time, period] = shift.departureTime.split(' ');
                let [hours, minutes] = time.split(':').map(Number);
                if (period === 'PM' && hours !== 12) hours += 12;
                if (period === 'AM' && hours === 12) hours = 0;

                const departureDate = new Date();
                departureDate.setHours(hours, minutes, 0, 0);

                if (now > departureDate) {
                    isPassed = true;
                } else {
                    const timeDiff = departureDate - now;
                    if (timeDiff <= 5 * 60 * 1000) {
                        isLocked = true;
                    }
                }
            }

            const shiftBookings = bookings.filter(b => b.shiftId === shift.id);
            const occupiedCount = shiftBookings.reduce((sum, b) => sum + (b.seatNumber ? String(b.seatNumber).split(',').length : 1), 0);
            const availableSeats = Math.max(0, 49 - occupiedCount);

            const isSelected = (this.bookingData.shiftId === shift.id);

            const card = document.createElement('div');
            card.id = `shift-card-${shift.id}`;
            
            if (isPassed || isLocked || isCancelled) {
                card.className = `shift-card disabled locked`;
                card.onclick = null;
            } else {
                card.className = `shift-card ${isSelected ? 'active' : ''}`;
                card.onclick = () => this.selectBookingShift(shift.id);
            }

            let badgeHtml = '';
            if (isCancelled) {
                badgeHtml = `<span class="shift-seats-badge badge badge-danger">Cancelled</span>`;
            } else if (isPassed) {
                badgeHtml = `<span class="shift-seats-badge badge badge-danger">Expired</span>`;
            } else if (isLocked) {
                badgeHtml = `<span class="shift-seats-badge badge bg-slate-50 border border-slate-200 text-slate-400 cursor-not-allowed">🔒 Booking Closed & Locked</span>`;
            } else {
                badgeHtml = `<span class="shift-seats-badge badge ${availableSeats === 0 ? 'badge-danger' : 'badge-success'}">${availableSeats === 0 ? 'Fully Booked' : `${availableSeats} Seats Left`}</span>`;
            }

            card.innerHTML = `
                <div class="shift-card-info">
                    <span class="shift-code-tag">${this.getShiftLabel(shift.id)}</span>
                    <span class="shift-route-text">${shift.stops[0].name} → ${shift.stops[shift.stops.length - 1].name}</span>
                </div>
                <div class="text-right">
                    <span class="shift-card-timing">${shift.departureTime}</span>
                    ${badgeHtml}
                </div>
            `;
            container.appendChild(card);
        });
    }

    getSeatsBookedTodayInDirection(shiftId, travelDate, psNumber) {
        const bookings = this.getItems('utcl_bookings').filter(b =>
            b.psNumber === psNumber &&
            b.travelDate === travelDate &&
            b.status === 'CONFIRMED'
        );
        const shifts = this.getItems('utcl_shifts');
        const selectedShift = shifts.find(s => s.id === shiftId);
        if (!selectedShift) return 0;
        
        const currentDirection = selectedShift.direction;
        let count = 0;
        bookings.forEach(b => {
            const bShift = shifts.find(s => s.id === b.shiftId);
            if (bShift && bShift.direction === currentDirection) {
                if (b.seatNumber) {
                    const seats = String(b.seatNumber).split(',').map(s => s.trim()).filter(Boolean);
                    count += seats.length;
                }
            }
        });
        return count;
    }

    selectBookingShift(shiftId) {
        this.bookingData.shiftId = shiftId;
        this.renderAvailableShifts();

        // Calculate remaining limit
        const seatsBookedTodayInDirection = this.getSeatsBookedTodayInDirection(shiftId, this.bookingData.date, this.currentUser.psNumber);
        const limit = 4 - seatsBookedTodayInDirection;

        if (limit <= 0) {
            alert("You have already reached your daily limit of 4 seats in this direction today.");
            this.bookingData.shiftId = '';
            this.renderAvailableShifts();
            return;
        }

        this.bookingData.remainingLimit = limit;

        // Start with empty passengers and seat numbers
        this.bookingData.passengers = [];
        this.bookingData.seatNumbers = [];
        this.bookingData.seatNumber = '';

        // Reset stops dropdowns
        this.setupStopsDropdowns();

        // Set max seats label for Step 2
        const maxLabel = document.getElementById('max-seats-label');
        if (maxLabel) {
            maxLabel.textContent = this.bookingData.remainingLimit.toString();
        }

        // Reset inputs and limit checkbox if checked
        const selfCheck = document.getElementById('booking-self-check');
        if (selfCheck) {
            selfCheck.checked = (this.bookingData.remainingLimit > 0);
        }

        // Go to next step (Choose Seats)
        this.changeStep('seats');
        
        // Show seat selection container in the right panel, hide empty state, and render the map
        document.getElementById('ticket-empty-state').classList.add('hidden');
        document.getElementById('virtual-ticket-card').classList.add('hidden');
        
        const seatContainer = document.getElementById('seat-selection-container');
        if (seatContainer) {
            seatContainer.classList.remove('hidden');
        }

        this.renderSeatMap();
    }

    setupStopsDropdowns() {
        const shift = this.getItems('utcl_shifts').find(s => s.id === this.bookingData.shiftId);

        const boardingSelect = document.getElementById('booking-boarding');
        const dropSelect = document.getElementById('booking-drop');

        boardingSelect.innerHTML = '';
        dropSelect.innerHTML = '';

        shift.stops.forEach(stop => {
            const opt1 = document.createElement('option');
            opt1.value = stop.index;
            opt1.textContent = `${stop.name} (${stop.arrival})`;
            boardingSelect.appendChild(opt1);

            const opt2 = document.createElement('option');
            opt2.value = stop.index;
            opt2.textContent = `${stop.name} (${stop.arrival})`;
            dropSelect.appendChild(opt2);
        });

        // Set default values (e.g. boarding at 0, drop off at last)
        boardingSelect.value = 0;
        dropSelect.value = shift.stops.length - 1;

        this.bookingData.boardingIndex = 0;
        this.bookingData.dropIndex = shift.stops.length - 1;
        this.onStopsChange();
    }

    onStopsChange() {
        const boardingVal = parseInt(document.getElementById('booking-boarding').value);
        const dropVal = parseInt(document.getElementById('booking-drop').value);
        const errorAlert = document.getElementById('stops-validation-error');
        const nextBtn = document.getElementById('btn-to-confirm');

        this.bookingData.boardingIndex = boardingVal;
        this.bookingData.dropIndex = dropVal;

        // Boarding Stop must precede Drop Stop
        if (boardingVal >= dropVal) {
            errorAlert.classList.remove('hidden');
            if (nextBtn) nextBtn.disabled = true;
        } else {
            errorAlert.classList.add('hidden');
            this.checkStep2Validity();
        }
    }

    // Dynamic Passenger Management functions (simplified for seats-first flow)
    onPassengerNameInput(input, idx) {
        // Sanitize name: keep only letters and spaces (no numbers, special characters, or symbols)
        const sanitizedValue = input.value.replace(/[^a-zA-Z\s]/g, '');
        input.value = sanitizedValue;

        if (this.bookingData.passengers && this.bookingData.passengers[idx]) {
            this.bookingData.passengers[idx].name = sanitizedValue;
        }
        this.checkStep2Validity();
    }

    toggleBookingForSelf() {
        const selfCheck = document.getElementById('booking-self-check');
        const includeSelf = selfCheck ? selfCheck.checked : false;

        if (this.bookingData.passengers && this.bookingData.passengers.length > 0) {
            if (includeSelf) {
                this.bookingData.passengers[0] = {
                    name: this.currentUser.name,
                    isEmployee: true,
                    psNumber: this.currentUser.psNumber,
                    seat: this.bookingData.seatNumbers[0]
                };
            } else {
                this.bookingData.passengers[0] = {
                    name: '',
                    isEmployee: false,
                    seat: this.bookingData.seatNumbers[0]
                };
            }
        }

        this.renderPassengerRows();
        this.checkStep2Validity();
    }

    renderPassengerRows() {
        const container = document.getElementById('passenger-list-container');
        if (!container) return;
        container.innerHTML = '';

        if (!this.bookingData.passengers) {
            this.bookingData.passengers = [];
        }

        this.bookingData.passengers.forEach((p, idx) => {
            const div = document.createElement('div');
            div.className = 'passenger-row';
            
            if (p.isEmployee) {
                div.innerHTML = `
                    <span class="seat-badge" style="background: rgba(0, 85, 165, 0.1); color: var(--primary, #0055a5); border: 1px solid rgba(0, 85, 165, 0.2); padding: 10px 12px; border-radius: 8px; font-weight: 700; font-size: 0.85rem; min-width: 80px; text-align: center; display: inline-flex; align-items: center; justify-content: center;">Seat ${p.seat}</span>
                    <input type="text" class="passenger-name-input locked-field" value="${p.name}" readonly disabled placeholder="Employee Name">
                `;
            } else {
                div.innerHTML = `
                    <span class="seat-badge" style="background: #f8fafc; color: #475569; border: 1px solid #e2e8f0; padding: 10px 12px; border-radius: 8px; font-weight: 700; font-size: 0.85rem; min-width: 80px; text-align: center; display: inline-flex; align-items: center; justify-content: center;">Seat ${p.seat}</span>
                    <input type="text" placeholder="Enter Passenger Name" class="passenger-name-input" value="${p.name}" oninput="app.onPassengerNameInput(this, ${idx})" required>
                `;
            }
            container.appendChild(div);
        });
    }

    updateSeatSelectionCounter() {
        const counter = document.getElementById('seat-selection-counter');
        const limit = (this.bookingData.remainingLimit !== undefined) ? this.bookingData.remainingLimit : 4;
        const S = this.bookingData.seatNumbers ? this.bookingData.seatNumbers.length : 0;
        if (counter) {
            counter.textContent = `Seats Selected: ${S} / ${limit}`;
        }

        const grid = document.getElementById('seat-map-grid');
        if (grid) {
            if (limit <= 0) {
                grid.classList.add('disabled');
                grid.style.pointerEvents = 'none';
            } else {
                grid.classList.remove('disabled');
                grid.style.pointerEvents = 'auto';
            }
        }

        // Enable or disable the Proceed to Details button
        const btnToStops = document.getElementById('btn-to-stops');
        if (btnToStops) {
            btnToStops.disabled = !(S > 0 && S <= limit);
        }
    }

    checkStep2Validity() {
        const nextBtn = document.getElementById('btn-to-confirm');
        if (!nextBtn) return;

        const boardingVal = this.bookingData.boardingIndex;
        const dropVal = this.bookingData.dropIndex;
        
        const N = this.bookingData.passengers ? this.bookingData.passengers.length : 0;
        const S = this.bookingData.seatNumbers ? this.bookingData.seatNumbers.length : 0;

        const routeValid = boardingVal < dropVal;
        const passengersCountValid = N > 0;
        const namesFilled = this.bookingData.passengers.every(p => p.name.trim().length > 0);
        const seatsValid = S === N;

        if (routeValid && passengersCountValid && namesFilled && seatsValid) {
            nextBtn.disabled = false;
        } else {
            nextBtn.disabled = true;
        }
    }

    changeStep(stepName) {
        const prevStep = this.currentStep;
        this.currentStep = stepName;

        // Enable/Disable employee navigation tabs based on step
        const navBtns = document.querySelectorAll('.emp-nav-btn');
        const lockSteps = ['seats', 'stops', 'confirm'];
        if (lockSteps.includes(stepName)) {
            navBtns.forEach(btn => btn.disabled = true);
        } else {
            navBtns.forEach(btn => btn.disabled = false);
        }


        // Reset warnings/alerts
        const stopsError = document.getElementById('stops-validation-error');
        if (stopsError) stopsError.classList.add('hidden');
        
        const submitError = document.getElementById('booking-submit-error');
        if (submitError) submitError.classList.add('hidden');

        // Hide all steps
        document.querySelectorAll('.booking-step').forEach(s => s.classList.add('hidden'));

        // Show targets
        const targetStep = document.getElementById(`step-${stepName}`);
        if (targetStep) targetStep.classList.remove('hidden');

        // Toggle right panel containers
        const seatContainer = document.getElementById('seat-selection-container');
        const emptyState = document.getElementById('ticket-empty-state');
        const ticketCard = document.getElementById('virtual-ticket-card');
        const seatGrid = document.getElementById('seat-map-grid');

        if (stepName === 'schedule') {
            // Release any currently selected seats via WebSockets instantly
            if (this.bookingData && this.bookingData.seatNumbers && this.bookingData.seatNumbers.length > 0) {
                if (this.socket && this.socket.connected) {
                    this.bookingData.seatNumbers.forEach(num => {
                        this.socket.emit('deselect_seat', {
                            shiftId: this.bookingData.shiftId,
                            date: this.bookingData.date,
                            seatNumber: num,
                            psNumber: this.bookingData.psNumber
                        });
                    });
                }
                this.bookingData.seatNumbers = [];
                this.bookingData.seatNumber = '';
            }

            if (seatContainer) seatContainer.classList.add('hidden');
            if (emptyState) emptyState.classList.remove('hidden');
            if (ticketCard) ticketCard.classList.add('hidden');
            this.leaveSeatRoom();  // unsubscribe from live seat updates when not viewing seats

            // Reload the page only when returning to Step 1 from a subsequent step
            if (prevStep === 'seats' || prevStep === 'stops' || prevStep === 'confirm' || prevStep === 'success') {
                window.location.reload();
                return;
            }
        } else if (stepName === 'stops' || stepName === 'confirm') {
            if (seatContainer) seatContainer.classList.add('hidden');
            if (emptyState) emptyState.classList.remove('hidden');
            if (ticketCard) ticketCard.classList.add('hidden');
            this.leaveSeatRoom();  // unsubscribe from live seat updates when not viewing seats
        } else if (stepName === 'seats') {
            if (seatContainer) seatContainer.classList.remove('hidden');
            if (emptyState) emptyState.classList.add('hidden');
            if (ticketCard) ticketCard.classList.add('hidden');
            
            if (seatGrid) {
                seatGrid.style.pointerEvents = 'auto';
            }

            // Subscribe to real-time seat updates for this shift+date
            if (this.bookingData.shiftId && this.bookingData.date) {
                this.joinSeatRoom(this.bookingData.shiftId, this.bookingData.date);
            }
        } else if (stepName === 'success') {
            if (seatContainer) seatContainer.classList.add('hidden');
            if (emptyState) emptyState.classList.add('hidden');
            if (ticketCard) ticketCard.classList.remove('hidden');
            this.leaveSeatRoom();  // booking complete, leave the room
        }

        // If step is confirm, setup summary details
        if (stepName === 'confirm') {
            this.setupBookingSummary();
        }

        // If step is stops, prepare and validate passenger name inputs
        if (stepName === 'stops') {
            const seatCount = this.bookingData.seatNumbers.length;
            const selfCheck = document.getElementById('booking-self-check');
            const includeSelf = selfCheck ? selfCheck.checked : true; // default to true

            const newPassengers = [];
            for (let i = 0; i < seatCount; i++) {
                const seatNum = this.bookingData.seatNumbers[i];
                if (i === 0 && includeSelf) {
                    newPassengers.push({
                        name: this.currentUser.name,
                        isEmployee: true,
                        psNumber: this.currentUser.psNumber,
                        seat: seatNum
                    });
                } else {
                    const existing = this.bookingData.passengers && this.bookingData.passengers[i];
                    newPassengers.push({
                        name: (existing && !existing.isEmployee) ? existing.name : '',
                        isEmployee: false,
                        seat: seatNum
                    });
                }
            }
            this.bookingData.passengers = newPassengers;

            this.renderPassengerRows();
            this.checkStep2Validity();
        }
    }

    renderSeatMap() {
        const grid = document.getElementById('seat-map-grid');
        if (!grid) return;
        grid.innerHTML = '';

        // Fetch existing bookings for this shift + date from client storage
        const bookings = this.getItems('utcl_bookings').filter(b =>
            b.shiftId === this.bookingData.shiftId &&
            b.travelDate === this.bookingData.date &&
            b.status === 'CONFIRMED'
        );

        const occupiedSeats = [];
        bookings.forEach(b => {
            if (b.seatNumber) {
                const seats = String(b.seatNumber).split(',').map(s => parseInt(s.trim(), 10));
                seats.forEach(s => {
                    if (!isNaN(s)) {
                        occupiedSeats.push(s);
                    }
                });
            }
        });

        let row10Wrapper = null;
        for (let i = 1; i <= 50; i++) {
            const seat = document.createElement('div');
            const isOccupied = occupiedSeats.includes(i);

            // Check if there is an active holding lock on the seat
            const hold = this.activeHolds ? this.activeHolds.find(h => h.seatNumber === i) : null;
            const isHeldByOthers = hold && hold.heldBy !== this.bookingData.psNumber;
            const isHeldByMe = hold && hold.heldBy === this.bookingData.psNumber;

            seat.textContent = i;

            if (i === 1) {
                // Conductor seat: labeled "C", non-bookable
                seat.textContent = 'C';
                seat.className = 'seat conductor';
                seat.onclick = null;
            } else {
                if (isOccupied) {
                    // Permanently occupied/booked
                    seat.className = 'seat occupied';
                } else if (isHeldByOthers) {
                    // Temporarily locked by another user -> turns red & completely unclickable
                    seat.className = 'seat held';
                    seat.title = `Temporarily locked by user ${hold.heldBy}`;
                } else if (isHeldByMe) {
                    // Selected by current user -> turns blue & clickable to toggle
                    seat.className = 'seat selected';
                    seat.onclick = () => this.handleSeatToggle(i);
                } else {
                    // Available for selection -> standard grey & clickable
                    seat.className = 'seat';
                    seat.onclick = () => this.handleSeatToggle(i);
                }
            }

            // Assign position and append to layout
            if (i === 1) {
                seat.style.gridRow = "1";
                seat.style.gridColumn = "1";
                grid.appendChild(seat);

                // Add spacer at Row 1 Col 2
                const spacer = document.createElement('div');
                spacer.className = 'seat-spacer';
                spacer.style.gridRow = "1";
                spacer.style.gridColumn = "2";
                grid.appendChild(spacer);
            } else if (i >= 2 && i <= 4) {
                seat.style.gridRow = "1";
                seat.style.gridColumn = (i + 2).toString();
                grid.appendChild(seat);
            } else if (i >= 5 && i <= 44) {
                const r = Math.floor((i - 5) / 5) + 2;
                const colIdx = (i - 5) % 5;
                const colMapping = [1, 2, 4, 5, 6];
                seat.style.gridRow = r.toString();
                seat.style.gridColumn = colMapping[colIdx].toString();
                grid.appendChild(seat);
            } else {
                // Row 10 (seats 45-50) wrapped in a flex container spanning all 6 columns
                if (!row10Wrapper) {
                    row10Wrapper = document.createElement('div');
                    row10Wrapper.className = 'row-10-wrapper';
                    row10Wrapper.style.gridRow = "10";
                }
                row10Wrapper.appendChild(seat);
            }
        }
        if (row10Wrapper) {
            grid.appendChild(row10Wrapper);
        }

        // Update the counter display
        this.updateSeatSelectionCounter();
    }

    async handleSeatToggle(num) {
        if (!this.bookingData.seatNumbers) {
            this.bookingData.seatNumbers = [];
        }

        const isSelected = this.bookingData.seatNumbers.includes(num);

        if (isSelected) {
            // Deselect: send deselect event to server
            if (this.socket && this.socket.connected) {
                this.socket.emit('deselect_seat', {
                    shiftId: this.bookingData.shiftId,
                    date: this.bookingData.date,
                    seatNumber: num,
                    psNumber: this.bookingData.psNumber
                });
            }
            // Optimistic deselect locally
            this.bookingData.seatNumbers = this.bookingData.seatNumbers.filter(s => s !== num);
            this.bookingData.seatNumber = this.bookingData.seatNumbers.join(', ');
            this.renderSeatMap();
        } else {
            // Select: verify seat limit first (based on remaining limit)
            const limit = (this.bookingData.remainingLimit !== undefined) ? this.bookingData.remainingLimit : 4;
            if (limit <= 0) {
                alert("You have already reached your daily limit of 4 seats in this direction today.");
                return;
            }
            if (this.bookingData.seatNumbers.length >= limit) {
                alert(`You can select up to ${limit} seat(s) based on your remaining daily limit.`);
                return;
            }

            // Optimistic selection locally to block subsequent fast clicks
            this.bookingData.seatNumbers.push(num);
            this.bookingData.seatNumber = this.bookingData.seatNumbers.join(', ');
            this.renderSeatMap();
            this.updateSeatSelectionCounter();

            // Select: emit select_seat with callback for race-condition prevention
            if (this.socket && this.socket.connected) {
                this.socket.emit('select_seat', {
                    shiftId: this.bookingData.shiftId,
                    date: this.bookingData.date,
                    seatNumber: num,
                    psNumber: this.bookingData.psNumber
                }, (response) => {
                    if (response && response.status === 'error') {
                        // Reject with error message
                        this.showLiveUpdateBar(`⚠️ ${response.message}`, 5000);
                        // Remove the optimistically added seat
                        this.bookingData.seatNumbers = this.bookingData.seatNumbers.filter(s => s !== num);
                        this.bookingData.seatNumber = this.bookingData.seatNumbers.join(', ');
                        this.renderSeatMap();
                        this.updateSeatSelectionCounter();
                    } else {
                        // Successfully selected on server. (Already added locally, just refresh UI/counter)
                        this.updateSeatSelectionCounter();
                    }
                });
            } else {
                // If socket is disconnected, allow direct local selection (graceful degradation)
                // (Already added locally)
                this.updateSeatSelectionCounter();
            }
        }
    }

    // Retained for backward compatibility / structural consistency
    selectSeat(num) {
        this.handleSeatToggle(num);
    }

    setupBookingSummary() {
        const shift = this.getItems('utcl_shifts').find(s => s.id === this.bookingData.shiftId);
        if (!shift) return;

        const passengerNames = this.bookingData.passengers.map(p => p.name).join(', ');

        document.getElementById('sum-name').textContent = passengerNames;
        document.getElementById('sum-ps').textContent = this.bookingData.psNumber;
        document.getElementById('sum-date').textContent = this.bookingData.date;
        document.getElementById('sum-shift').textContent = `${this.getShiftLabel(this.bookingData.shiftId)} (${shift.departureTime})`;
        document.getElementById('sum-route').textContent = `${shift.stops[this.bookingData.boardingIndex].name} → ${shift.stops[this.bookingData.dropIndex].name}`;
        document.getElementById('sum-seat').textContent = this.bookingData.seatNumbers.join(', ');
        
        const totalFare = this.bookingData.seatNumbers.length * 20;
        document.getElementById('sum-fare').textContent = `₹${totalFare}`;
    }

    async submitBooking() {
        const errorAlert = document.getElementById('booking-submit-error');
        if (errorAlert) errorAlert.classList.add('hidden');

        // Prevent double click/submission by disabling the confirm button
        const btnSubmit = document.querySelector('button[onclick="app.submitBooking()"]');
        let originalText = "";
        if (btnSubmit) {
            originalText = btnSubmit.innerHTML;
            btnSubmit.disabled = true;
            btnSubmit.innerHTML = "Booking...";
        }

        try {
            const bookings = this.getItems('utcl_bookings');
            const shifts = this.getItems('utcl_shifts');
            const shift = shifts.find(s => s.id === this.bookingData.shiftId);

            if (!this.bookingData.seatNumbers || this.bookingData.seatNumbers.length === 0) {
                throw new Error("NO_SEATS: Please select at least one seat.");
            }

            const newlySelectedSeatsCount = this.bookingData.seatNumbers.length;
            const N = this.bookingData.passengers.length;

            if (newlySelectedSeatsCount !== N) {
                throw new Error(`SEATS_MISMATCH: You must select exactly ${N} seat(s) for your passengers.`);
            }

            // 1. Check daily seat limit in this direction
            const seatsBookedTodayInDirection = this.getSeatsBookedTodayInDirection(this.bookingData.shiftId, this.bookingData.date, this.bookingData.psNumber);
            if (seatsBookedTodayInDirection + newlySelectedSeatsCount > 4) {
                throw new Error(`LIMIT_EXCEEDED: You can book up to 4 seats per day for this journey direction. You have already booked ${seatsBookedTodayInDirection} seat(s).`);
            }

            // 2. Seat collision check inside transaction
            const occupiedSeats = [];
            bookings.forEach(b => {
                if (b.shiftId === this.bookingData.shiftId && b.travelDate === this.bookingData.date && b.status === 'CONFIRMED') {
                    if (b.seatNumber) {
                        const seats = String(b.seatNumber).split(',').map(s => parseInt(s.trim(), 10)).filter(Boolean);
                        occupiedSeats.push(...seats);
                    }
                }
            });

            const conflictSeat = this.bookingData.seatNumbers.find(s => occupiedSeats.includes(s));
            if (conflictSeat) {
                throw new Error(`SEAT_CONFLICT: Seat ${conflictSeat} was just occupied by another passenger. Please choose other seats.`);
            }

            // Directly complete the booking since payment is now direct salary deduction
            await this.submitBookingReal();

        } catch (err) {
            if (errorAlert) {
                errorAlert.textContent = err.message;
                errorAlert.classList.remove('hidden');
            }
        } finally {
            if (btnSubmit) {
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = originalText;
            }
        }
    }

    async submitBookingReal() {
        const errorAlert = document.getElementById('booking-submit-error');
        if (errorAlert) errorAlert.classList.add('hidden');

        try {
            const bookings = this.getItems('utcl_bookings');
            const tickets  = this.getItems('utcl_tickets');
            const shifts   = this.getItems('utcl_shifts');

            const shift          = shifts.find(s => s.id === this.bookingData.shiftId);
            const totalFare      = this.bookingData.seatNumbers.length * 20;
            const seatNumberStr  = this.bookingData.seatNumbers.join(', ');
            const passengerNames = this.bookingData.passengers.map(p => p.name).join(', ');

            // Build booking + ticket objects (same structure as before)
            const bookingId    = `bk_${Date.now()}`;
            const ticketId     = `tk_${Date.now()}`;
            const ticketNumber = `UTCL-${Math.floor(Math.random() * 90000) + 10000}`;

            const newBooking = {
                id: bookingId,
                shiftId: this.bookingData.shiftId,
                psNumber: this.bookingData.psNumber,
                employeeName: passengerNames,
                seatNumber: seatNumberStr,
                boardingStopIndex: this.bookingData.boardingIndex,
                dropStopIndex: this.bookingData.dropIndex,
                fareAmount: totalFare,
                status: 'CONFIRMED',
                travelDate: this.bookingData.date,
                bookedAt: new Date().toISOString()
            };

            const newTicket = {
                id: ticketId,
                bookingId: bookingId,
                ticketNumber: ticketNumber,
                employeeName: passengerNames,
                psNumber: this.bookingData.psNumber,
                shiftCode: this.bookingData.shiftId,
                seatNumber: seatNumberStr,
                boardingStop: shift.stops[this.bookingData.boardingIndex].name,
                dropStop:     shift.stops[this.bookingData.dropIndex].name,
                fare: totalFare,
                departureTime: shift.departureTime,
                travelDate: this.bookingData.date,
                generatedAt: new Date().toISOString()
            };

            // ── POST to server: atomic DB insert + WebSocket broadcast ─────────
            try {
                const res = await fetch('/api/booking/create', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ booking: newBooking, ticket: newTicket })
                });

                if (res.status === 409) {
                    // Seat conflict — another user just grabbed one of our seats
                    const errData = await res.json();
                    // Immediately mark conflicted seats occupied in the UI
                    if (errData.conflictSeats) {
                        const seatEls = document.querySelectorAll('#seat-map-grid .seat');
                        seatEls.forEach(el => {
                            const seatNum = parseInt(el.textContent, 10);
                            if (errData.conflictSeats.includes(seatNum)) {
                                el.classList.add('just-booked', 'occupied');
                                el.onclick = null;
                            }
                        });
                        // Remove from selection
                        this.bookingData.seatNumbers = this.bookingData.seatNumbers
                            .filter(s => !errData.conflictSeats.includes(s));
                        this.bookingData.seatNumber = this.bookingData.seatNumbers.join(', ');
                        this.updateSeatSelectionCounter();
                        this.checkStep2Validity();
                    }
                    throw new Error(errData.message || 'Seat conflict — please select again.');
                }

                if (!res.ok) {
                    const errData = await res.json().catch(() => ({}));
                    const serverErr = new Error(errData.message || 'Server error, booking failed.');
                    serverErr.isServerError = true;
                    throw serverErr;
                }
            } catch (fetchErr) {
                if (fetchErr.isServerError || fetchErr.message.includes('seat') || fetchErr.message.includes('Seat')) throw fetchErr;
                // Network unreachable — continue with localStorage-only (graceful degradation)
                console.warn('[Booking] Server unreachable, saving locally only:', fetchErr.message);
            }

            // ── Always update localStorage for immediate UI consistency ────────
            bookings.push(newBooking);
            tickets.push(newTicket);
            this.setItem('utcl_bookings', bookings);
            this.setItem('utcl_tickets', tickets);

            // Display virtual ticket
            setTimeout(() => {
                this.displayVirtualTicket(newTicket);
            }, 800);

        } catch (err) {
            if (errorAlert) {
                errorAlert.textContent = err.message;
                errorAlert.classList.remove('hidden');
            }
        }
    }

    cancelPayment() {
        this.closeModal('payment-gateway-modal');
    }

    processPayment(method) {
        // Show Processing Overlay
        document.getElementById('pay-processing-overlay').classList.remove('hidden');

        // Delay 1.8 seconds
        setTimeout(() => {
            document.getElementById('pay-processing-overlay').classList.add('hidden');
            document.getElementById('pay-success-overlay').classList.remove('hidden');

            // Success display 1.2 seconds before finishing
            setTimeout(() => {
                this.closeModal('payment-gateway-modal');
                this.submitBookingReal();
            }, 1200);

        }, 1800);
    }

    displayVirtualTicket(ticket) {
        document.getElementById('ticket-empty-state').classList.add('hidden');
        const ticketCard = document.getElementById('virtual-ticket-card');

        document.getElementById('ticket-number').textContent = ticket.ticketNumber;
        document.getElementById('t-name').textContent = ticket.employeeName;
        document.getElementById('t-ps').textContent = ticket.psNumber;
        document.getElementById('t-shift').textContent = this.getShiftLabel(ticket.shiftCode);
        document.getElementById('t-seat').textContent = ticket.seatNumber;
        document.getElementById('t-boarding').textContent = ticket.boardingStop;
        document.getElementById('t-drop').textContent = ticket.dropStop;
        document.getElementById('t-time').textContent = ticket.departureTime;
        document.getElementById('t-date').textContent = ticket.travelDate;

        // Render passenger count and fare paid
        const seatCount = ticket.seatNumber ? String(ticket.seatNumber).split(',').map(s => s.trim()).filter(Boolean).length : 1;
        const passEl = document.getElementById('t-passengers');
        if (passEl) passEl.textContent = seatCount;
        document.getElementById('t-fare').textContent = `₹${ticket.fare || (seatCount * 20)}`;

        ticketCard.classList.remove('hidden');

        // Generate QR code after a brief delay so the canvas has nonzero dimensions
        setTimeout(() => this.generateTicketQR(ticket, 'ticket-qr-canvas'), 80);

        // Switch flow panel to step-success
        this.changeStep('success');
    }

    isShiftLocked(departureTimeStr, dateStr) {
        const now = new Date();
        const [time, period] = departureTimeStr.split(' ');
        let [hours, minutes] = time.split(':').map(Number);
        if (period === 'PM' && hours !== 12) hours += 12;
        if (period === 'AM' && hours === 12) hours = 0;

        const departureDate = new Date(dateStr + 'T00:00:00');
        departureDate.setHours(hours, minutes, 0, 0);

        const timeDiff = departureDate - now;
        return timeDiff <= 5 * 60 * 1000;
    }

    renderUpcomingManifests() {
        const tbody = document.getElementById('admin-upcoming-manifests-body');
        if (!tbody) return;
        tbody.innerHTML = '';

        const shifts = this.getItems('utcl_shifts').filter(s => s.isActive);
        const todayStr = this.getTodayString();

        shifts.forEach(shift => {
            const isLocked = this.isShiftLocked(shift.departureTime, todayStr);
            const row = document.createElement('tr');
            
            let statusHtml = '';
            let actionHtml = '';
            
            if (isLocked) {
                statusHtml = `<span class="badge bg-slate-50 border border-slate-200 text-slate-400 cursor-not-allowed">🔒 Locked</span>`;
                actionHtml = `
                    <button onclick="app.downloadManifest('${shift.id}', '${todayStr}')" class="btn btn-success btn-sm flex items-center gap-1.5 cursor-pointer">
                        &darr; EXPORT TO EXCEL
                    </button>
                `;
            } else {
                statusHtml = `<span class="badge badge-success">Open</span>`;
                actionHtml = `
                    <button disabled class="btn btn-success btn-sm cursor-not-allowed" style="opacity: 0.5;">
                        &darr; EXPORT TO EXCEL
                    </button>
                `;
            }
            
            row.innerHTML = `
                <td><strong>${this.getShiftLabel(shift.id)}</strong></td>
                <td>${shift.departureTime}</td>
                <td>${statusHtml}</td>
                <td>${actionHtml}</td>
            `;
            tbody.appendChild(row);
        });
        addMobileTableLabels('#admin-upcoming-manifests-body');
    }

    downloadManifest(shiftId, date) {
        fetch(`/api/admin/shifts/${shiftId}/export-manifest?date=${encodeURIComponent(date)}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Server returned an error during Excel generation');
                }
                return response.blob();
            })
            .then(blob => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = `UTCL_Passenger_Manifest_Shift_${shiftId}_2026.xlsx`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();
            })
            .catch(err => {
                console.error('Export manifest Excel failed:', err);
                alert('Export failed: ' + err.message);
            });
    }

    loadBookingHistory() {
        const psInput = document.getElementById('history-ps-number').value.trim().toUpperCase();
        const tbody = document.getElementById('history-table-body');
        const exportBtn = document.getElementById('export-excel-btn');
        const clearBtn = document.getElementById('history-clear-btn');
        const manifestSection = document.getElementById('history-manifest-section');
        const employeeSection = document.getElementById('history-employee-section');
        const employeeTitle = document.getElementById('history-employee-title');

        if (!psInput) {
            // No PS entered — show manifest, hide employee section
            if (manifestSection) manifestSection.classList.remove('hidden');
            if (employeeSection) employeeSection.classList.add('hidden');
            if (exportBtn) exportBtn.classList.add('hidden');
            if (clearBtn) clearBtn.classList.add('hidden');
            return;
        }

        // Show Clear button
        if (clearBtn) clearBtn.classList.remove('hidden');

        const bookings = this.getItems('utcl_bookings').filter(b => b.psNumber === psInput && b.status === 'CONFIRMED');
        const shifts = this.getItems('utcl_shifts');

        // Resolve employee name for title
        const users = this.getItems('utcl_users');
        const emp = users.find(u => u.psNumber === psInput);
        const empLabel = emp ? `${emp.name} (${psInput})` : psInput;
        if (employeeTitle) employeeTitle.textContent = `Booking History — ${empLabel}`;

        // Switch views: hide manifest, show employee history
        if (manifestSection) manifestSection.classList.add('hidden');
        if (employeeSection) employeeSection.classList.remove('hidden');

        if (bookings.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">No confirmed bookings found for PS Number ${psInput}.</td></tr>`;
            if (exportBtn) exportBtn.classList.add('hidden');
            return;
        }

        // Sort by scheduled travel date/departure time (descending)
        bookings.sort((a, b) => {
            const dateA = new Date(a.travelDate + ' ' + (shifts.find(s => s.id === a.shiftId)?.departureTime || ''));
            const dateB = new Date(b.travelDate + ' ' + (shifts.find(s => s.id === b.shiftId)?.departureTime || ''));
            return dateB - dateA;
        });

        tbody.innerHTML = '';
        const todayStr = this.getTodayString();

        bookings.forEach(b => {
            const shift = shifts.find(s => s.id === b.shiftId);
            const isActive = (b.travelDate >= todayStr);
            const statusLabel = isActive
                ? `<span class="badge badge-success">Active</span>`
                : `<span class="badge badge-warning">Past</span>`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${b.travelDate}</td>
                <td>${this.getShiftLabel(b.shiftId)} (${shift ? shift.departureTime : ''})</td>
                <td>Seat ${b.seatNumber}</td>
                <td>${shift ? shift.stops[b.boardingStopIndex].name : ''}</td>
                <td>${shift ? shift.stops[b.dropStopIndex].name : ''}</td>
                <td>\u20B9${b.fareAmount}</td>
                <td>${statusLabel}</td>
                <td>
                    <button class="btn btn-outline btn-xs" onclick="app.viewPastTicket('${b.id}')">View Ticket</button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        // Show Export button now that data is loaded
        if (exportBtn) exportBtn.classList.remove('hidden');
    }

    clearBookingHistorySearch() {
        const input = document.getElementById('history-ps-number');
        if (input) input.value = '';
        this.closeHistoryAutocomplete();

        const clearBtn = document.getElementById('history-clear-btn');
        if (clearBtn) clearBtn.classList.add('hidden');

        const exportBtn = document.getElementById('export-excel-btn');
        if (exportBtn) exportBtn.classList.add('hidden');

        // Restore manifest, hide employee section
        const manifestSection = document.getElementById('history-manifest-section');
        const employeeSection = document.getElementById('history-employee-section');
        if (manifestSection) manifestSection.classList.remove('hidden');
        if (employeeSection) employeeSection.classList.add('hidden');

        // Re-render manifests
        this.renderUpcomingManifests();
    }

    // ==========================================================================
    // MY TICKETS TAB — Employee self-service cancellation
    // ==========================================================================

    loadMyTickets() {
        const tbody    = document.getElementById('my-tickets-table-body');
        const wrapper  = document.getElementById('my-tickets-table-wrapper');
        const empty    = document.getElementById('my-tickets-empty-state');
        if (!tbody || !wrapper || !empty) return;

        if (!this.currentUser) return;

        const todayStr = this.getTodayString();
        const bookings = this.getItems('utcl_bookings').filter(b =>
            b.psNumber   === this.currentUser.psNumber &&
            b.status     === 'CONFIRMED' &&
            b.travelDate >= todayStr &&
            !b.id.startsWith('ws_')   // exclude phantom WebSocket sync entries
        );
        const tickets = this.getItems('utcl_tickets');
        const shifts  = this.getItems('utcl_shifts');

        if (bookings.length === 0) {
            wrapper.classList.add('hidden');
            empty.classList.remove('hidden');
            return;
        }

        empty.classList.add('hidden');
        wrapper.classList.remove('hidden');

        // Sort upcoming first
        bookings.sort((a, b) => new Date(a.travelDate) - new Date(b.travelDate));

        tbody.innerHTML = '';
        bookings.forEach(b => {
            const shift   = shifts.find(s => s.id === b.shiftId);
            const today   = b.travelDate === todayStr;

            // Check if shift has already departed (for today's bookings)
            let hasDeparted = false;
            if (today && shift) {
                const [timePart, period] = shift.departureTime.split(' ');
                let [h, m] = timePart.split(':').map(Number);
                if (period === 'PM' && h !== 12) h += 12;
                if (period === 'AM' && h === 12) h = 0;
                const depDate = new Date();
                depDate.setHours(h, m, 0, 0);
                hasDeparted = new Date() >= depDate;
            }

            const statusBadge = `<span class="badge badge-success">Active</span>`;
            const route = shift
                ? `${shift.stops[b.boardingStopIndex]?.name || '?'} → ${shift.stops[b.dropStopIndex]?.name || '?'}`
                : '—';

            const monthPrefix = b.travelDate.substring(0, 7);
            const periods = this.getItems('utcl_payroll_periods') || [];
            const isPeriodLocked = periods.some(p => p.periodMonth === monthPrefix && p.status === 'PROCESSED');

            let cancelBtn;
            if (isPeriodLocked) {
                cancelBtn = `<button class="btn btn-xs" style="opacity:0.4;cursor:not-allowed;" disabled title="Payroll is processed and locked">Cancel</button>`;
            } else if (hasDeparted) {
                cancelBtn = `<button class="btn btn-xs" style="opacity:0.4;cursor:not-allowed;" disabled title="Shift has departed">Cancel</button>`;
            } else {
                cancelBtn = `<button class="btn btn-cancel btn-xs" onclick="app.initiateCancel('${b.id}')">Cancel Ticket</button>`;
            }

            const tr = document.createElement('tr');
            tr.id = `ticket-row-${b.id}`;
            tr.innerHTML = `
                <td>${b.travelDate}</td>
                <td>${this.getShiftLabel(b.shiftId)} ${shift ? '(' + shift.departureTime + ')' : ''}</td>
                <td>Seat ${b.seatNumber}</td>
                <td>${route}</td>
                <td>₹${b.fareAmount}</td>
                <td>${statusBadge}</td>
                <td style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                    <button class="btn btn-outline btn-xs" onclick="app.viewPastTicket('${b.id}')">View Ticket</button>
                    ${cancelBtn}
                </td>
            `;
            tbody.appendChild(tr);
        });
        addMobileTableLabels('#my-tickets-table');
    }

    // Called when employee clicks "Cancel Ticket" on a row
    initiateCancel(bookingId) {
        this._pendingCancelBookingId = bookingId;
        this._pendingCancelIsAdmin   = false;
        this.openModal('cancel-confirm-modal');
    }

    // Called when admin clicks "Cancel Booking" in admin ticket modal
    adminCancelBooking() {
        if (!this._adminViewBookingId) return;
        this._pendingCancelBookingId = this._adminViewBookingId;
        this._pendingCancelIsAdmin   = true;
        this.closeModal('admin-ticket-modal');
        this.openModal('cancel-confirm-modal');
    }

    async confirmCancelBooking() {
        const bookingId = this._pendingCancelBookingId;
        if (!bookingId) return;

        const confirmBtn = document.getElementById('confirm-cancel-btn');
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Cancelling...';
        }

        try {
            const res = await fetch(`/api/booking/cancel/${bookingId}`, { method: 'POST' });
            const data = await res.json();

            if (res.ok && data.status === 'ok') {
                // Update localStorage immediately for instant UI feedback (without syncing back to DB since the server did it)
                const bookings = this.getItems('utcl_bookings');
                const booking  = bookings.find(b => b.id === bookingId);
                if (booking) booking.status = 'CANCELLED';
                localStorage.setItem('utcl_bookings', JSON.stringify(bookings));

                const tickets = this.getItems('utcl_tickets');
                const ticket  = tickets.find(t => t.bookingId === bookingId);
                if (ticket) ticket.status = 'CANCELLED';
                localStorage.setItem('utcl_tickets', JSON.stringify(tickets));

                // Animate row removal from My Tickets table
                const row = document.getElementById(`ticket-row-${bookingId}`);
                if (row) {
                    row.classList.add('ticket-row-fade-out');
                    setTimeout(() => {
                        row.remove();
                        // Reload table to update empty state if no more rows
                        if (this.currentEmployeeTab === 'mytickets') this.loadMyTickets();
                    }, 350);
                }

                // Also remove from seat map if the same shift+date is currently viewed
                if (data.shiftId && data.travelDate && this.currentSeatRoom === `${data.shiftId}_${data.travelDate}`) {
                    if (typeof this.renderSeatMap === 'function') this.renderSeatMap();
                }

                this.showLiveToast('Booking cancelled successfully. Your seat has been released.', 'Booking Cancelled');

                // If admin triggered, refresh booking history
                if (this._pendingCancelIsAdmin) {
                    setTimeout(() => this.loadBookingHistory(), 200);
                }
            } else {
                this.showLiveToast(data.message || 'Failed to cancel booking.', 'Error');
            }
        } catch (err) {
            console.error('[Cancel] Network error:', err);
            this.showLiveToast('Network error. Please try again.', 'Error');
        } finally {
            this.closeModal('cancel-confirm-modal');
            this._pendingCancelBookingId = null;
            this._pendingCancelIsAdmin   = false;
            if (confirmBtn) {
                confirmBtn.disabled = false;
                confirmBtn.textContent = 'Yes, Cancel It';
            }
        }
    }

    viewPastTicket(bookingId) {
        const tickets = this.getItems('utcl_tickets');
        const ticket = tickets.find(t => t.bookingId === bookingId);

        if (ticket) {
            if (this.currentUser && this.currentUser.role === 'ADMIN') {
                this.displayAdminTicket(ticket, bookingId);
            } else {
                // Switch back to booking tab structure to display ticket
                this.switchEmployeeTab('booking');
                this.displayVirtualTicket(ticket);
            }
        }
    }

    displayAdminTicket(ticket, bookingId) {
        const content = document.getElementById('admin-ticket-card-content');
        if (!content) return;

        const seatCount = ticket.seatNumber ? String(ticket.seatNumber).split(',').map(s => s.trim()).filter(Boolean).length : 1;

        content.innerHTML = `
            <div class="ticket-card" style="margin: 0; box-shadow: none; width: 100%;">
                <div class="ticket-header-band">
                    <div class="ticket-logo">
                        <span>UltraTech</span>
                        <span class="text-xs block">E-Ticket</span>
                    </div>
                    <div class="ticket-number-label">
                        Ticket No: <span>${ticket.ticketNumber}</span>
                    </div>
                </div>
                <div class="ticket-body">
                    <div class="ticket-row">
                        <div style="flex: 2;">
                            <span class="ticket-label">PASSENGER NAME</span>
                            <span class="ticket-val">${ticket.employeeName}</span>
                        </div>
                        <div style="flex: 1;">
                            <span class="ticket-label">PS NUMBER</span>
                            <span class="ticket-val">${ticket.psNumber}</span>
                        </div>
                    </div>
                    <div class="ticket-row">
                        <div style="flex: 2;">
                            <span class="ticket-label">SHIFT / BUS</span>
                            <span class="ticket-val">${this.getShiftLabel(ticket.shiftCode)}</span>
                        </div>
                        <div style="flex: 1;">
                            <span class="ticket-label">SEAT NUMBER</span>
                            <span class="ticket-val highlight-val">${ticket.seatNumber}</span>
                        </div>
                    </div>
                    <div class="ticket-route-display">
                        <div class="stop-point">
                            <span class="ticket-label">BOARDING STOP</span>
                            <span class="ticket-val">${ticket.boardingStop}</span>
                        </div>
                        <div class="route-line-dots">→</div>
                        <div class="stop-point align-right">
                            <span class="ticket-label">DROP STOP</span>
                            <span class="ticket-val">${ticket.dropStop}</span>
                        </div>
                    </div>
                    <div class="ticket-row">
                        <div style="flex: 1;">
                            <span class="ticket-label">DEPARTURE TIME</span>
                            <span class="ticket-val">${ticket.departureTime}</span>
                        </div>
                        <div style="flex: 1;">
                            <span class="ticket-label">DATE</span>
                            <span class="ticket-val">${ticket.travelDate}</span>
                        </div>
                    </div>
                </div>
                <div class="ticket-footer-fare">
                    <span>FARE PAID</span>
                    <span class="fare-amount">₹${ticket.fare}</span>
                </div>
                <div class="ticket-qr-block">
                    <canvas id="admin-ticket-qr-canvas"></canvas>
                    <span class="qr-label">Scan to Verify</span>
                </div>
            </div>
        `;
        this.openModal('admin-ticket-modal');
        // Store the bookingId for admin-cancel action
        this._adminViewBookingId = ticket.bookingId || null;

        // Show/hide Cancel Booking button based on whether travel date is still upcoming and payroll is not locked
        const cancelBtn = document.getElementById('admin-cancel-booking-btn');
        if (cancelBtn) {
            const todayStr = this.getTodayString();
            const monthPrefix = ticket.travelDate ? ticket.travelDate.substring(0, 7) : '';
            const periods = this.getItems('utcl_payroll_periods') || [];
            const isPeriodLocked = periods.some(p => p.periodMonth === monthPrefix && p.status === 'PROCESSED');

            if (ticket.travelDate && ticket.travelDate >= todayStr && ticket.status !== 'CANCELLED' && !isPeriodLocked) {
                cancelBtn.classList.remove('hidden');
            } else {
                cancelBtn.classList.add('hidden');
            }
        }

        // Delay to allow modal content to render before drawing on canvas
        setTimeout(() => this.generateTicketQR(ticket, 'admin-ticket-qr-canvas'), 80);
    }

    loadSchedulesTimings() {
        const grid = document.getElementById('schedules-timings-grid');
        grid.innerHTML = '';
        const shifts = this.getItems('utcl_shifts').filter(s => s.isActive);

        shifts.forEach(shift => {
            const card = document.createElement('div');
            card.className = "glass-panel p-5 schedule-card-interactive";
            
            card.onclick = () => {
                // Switch tab to booking
                this.switchEmployeeTab('booking');
                // Default date to today if none selected
                const dateInput = document.getElementById('booking-date');
                if (dateInput && !dateInput.value) {
                    this.bookingData.date = this.getTodayString();
                    dateInput.value = this.bookingData.date;
                    this.onBookingDateChange();
                }
                // Select specific shift and go to stops selection
                this.selectBookingShift(shift.id);
            };

            let stopsHtml = '<div class="driver-stop-timeline mt-2">';
            shift.stops.forEach((stop, i) => {
                stopsHtml += `
                    <div class="timeline-stop-node">
                        <strong>${stop.name}</strong> - ${stop.arrival}
                    </div>
                `;
            });
            stopsHtml += '</div>';

            card.innerHTML = `
                <h3 class="font-outfit text-primary border-bottom pb-2 mb-4">${this.getShiftLabel(shift.id)}</h3>
                <div class="flex-between mb-4 pb-3 border-bottom-dashed">
                    <div>
                        <span class="text-xs text-muted block uppercase tracking-wider">VEHICLE ASSIGNED</span>
                        <strong class="text-sm font-bold">${shift.busId === 'b1' ? 'Bus 1' : 'Bus 2'}</strong>
                    </div>
                    <div class="text-right">
                        <span class="text-xs text-muted block uppercase tracking-wider">FLAT FARE</span>
                        <strong class="text-success text-sm font-bold">₹20</strong>
                    </div>
                </div>
                <div>
                    <span class="text-xs text-muted block uppercase tracking-wider mb-2">TIMELINE STOPS</span>
                    ${stopsHtml}
                </div>
            `;
            grid.appendChild(card);
        });
    }

    // ==========================================================================
    // 4. DRIVER PORTAL SERVICES & STATUSES
    // ==========================================================================

    renderDriverDashboard() {
        // Load assigned driver details (Driver: Rajesh Kumar - u6 - Bus 1)
        const driverId = this.currentUser.id;
        const users = this.getItems('utcl_users');
        const driver = users.find(u => u.id === driverId);

        // Find assigned bus dynamically from today's driver_shift assignments
        // This supports any driver, not just the default u6/u7 pair.
        const todayStr = this.getTodayString();
        const allDriverShifts = this.getItems('utcl_driver_shifts');
        const allShifts = this.getItems('utcl_shifts');
        const todayAssignments = allDriverShifts.filter(a =>
            a.driverId === driverId && a.date === todayStr
        );
        const assignedBusIds = new Set();
        todayAssignments.forEach(a => {
            const shift = allShifts.find(s => s.id === a.shiftId);
            if (shift) assignedBusIds.add(shift.busId);
        });

        // Map bus IDs to display labels using the buses table
        let assignedBus = null;
        if (assignedBusIds.size > 0) {
            const allBuses = this.getItems('utcl_buses');
            const labels = [...assignedBusIds].map(bid => {
                const bus = allBuses.find(b => b.id === bid);
                return bus ? bus.identifier : bid;
            }).sort();
            assignedBus = labels.join(' & ');
        }

        const busVal = document.getElementById('driver-assigned-bus');
        const nameVal = document.getElementById('driver-name-display');
        const psVal = document.getElementById('driver-ps-display');

        nameVal.textContent = driver.name;
        psVal.textContent = driver.psNumber;

        const shiftsContainer = document.getElementById('driver-shifts-list');
        const maintenanceContainer = document.getElementById('driver-maintenance-list');

        if (!assignedBus) {
            busVal.textContent = "No bus assigned";
            busVal.className = "info-val text-danger";

            // Hide schedule and maintenance sections (Requirement 6.2)
            shiftsContainer.closest('.glass-panel').classList.add('hidden');
            maintenanceContainer.closest('.glass-panel').classList.add('hidden');
            
            // Hide attendance card for unassigned drivers
            const attendanceCard = document.getElementById('driver-attendance-card');
            if (attendanceCard) attendanceCard.style.display = 'none';
            return;
        }

        busVal.textContent = assignedBus;
        busVal.className = "info-val text-success";
        shiftsContainer.closest('.glass-panel').classList.remove('hidden');
        maintenanceContainer.closest('.glass-panel').classList.remove('hidden');

        // Load Driver's assigned shifts (Requirement 6.3)
        // Shifts are assigned in `utcl_driver_shifts`
        const assignments = this.getItems('utcl_driver_shifts').filter(a =>
            a.driverId === driverId &&
            a.date === todayStr
        );

        shiftsContainer.innerHTML = '';
        if (assignments.length === 0) {
            shiftsContainer.innerHTML = `<div class="empty-state">No shifts assigned to you today.</div>`;
        } else {
            const shifts = this.getItems('utcl_shifts');
            assignments.forEach(assign => {
                const shift = shifts.find(s => s.id === assign.shiftId);
                if (shift) {
                    const item = document.createElement('div');
                    item.className = "driver-shift-item";

                    let stopsHtml = '';
                    shift.stops.forEach(stop => {
                        stopsHtml += `
                            <div class="timeline-stop-node">
                                <strong>${stop.name}</strong> - ${stop.arrival}
                            </div>
                        `;
                    });

                    item.innerHTML = `
                        <div class="driver-shift-header">
                            <strong>${this.getShiftLabel(shift.id)}</strong>
                            <span class="badge badge-success">Active</span>
                        </div>
                        <div class="driver-stop-timeline">
                            ${stopsHtml}
                        </div>
                    `;
                    shiftsContainer.appendChild(item);
                }
            });
        }

        // Load Upcoming Maintenance Schedules (Requirement 6.5)
        // Show maintenance for all buses assigned to this driver today.
        const maintenance = this.getItems('utcl_maintenance');

        const upcomingMaint = maintenance.filter(m =>
            assignedBusIds.has(m.busId) &&
            m.status !== 'COMPLETED'
        );

        maintenanceContainer.innerHTML = '';
        if (upcomingMaint.length === 0) {
            maintenanceContainer.innerHTML = `<div class="empty-state">No upcoming maintenance scheduled for your bus.</div>`;
        } else {
            upcomingMaint.forEach(m => {
                const item = document.createElement('div');
                item.className = "maintenance-notice-item";

                // Show status tag
                const isOverdue = (m.scheduledDate < todayStr);
                let statusTag = '';
                if (m.status === 'PENDING_CONFIRMATION') {
                    statusTag = `<span class="badge badge-info">Awaiting Admin</span>`;
                } else if (isOverdue) {
                    statusTag = `<span class="badge badge-danger">Overdue</span>`;
                } else {
                    statusTag = `<span class="badge badge-warning">Scheduled</span>`;
                }

                // Show "Service Done" button only for SCHEDULED/OVERDUE (not pending/completed)
                const canRequest = (m.status === 'SCHEDULED' || m.status === 'OVERDUE');
                const actionBtn = canRequest
                    ? `<button class="btn btn-success btn-xs" onclick="app.requestServiceDone('${m.id}')">✔ Service Done</button>`
                    : '';

                item.innerHTML = `
                    <div>
                        <span class="text-xs text-muted block">SCHEDULED FOR: ${m.scheduledDate}</span>
                        <strong>${m.description}</strong>
                    </div>
                    <div class="text-right flex items-center gap-2">
                        ${actionBtn}
                        ${statusTag}
                    </div>
                `;
                maintenanceContainer.appendChild(item);
            });
        }

        // Setup Driver attendance logging card
        const attendanceCard = document.getElementById('driver-attendance-card');
        const selectShift = document.getElementById('driver-select-shift');
        if (attendanceCard && selectShift) {
            attendanceCard.style.display = 'block';
            selectShift.innerHTML = '';
            
            if (assignments.length === 0) {
                selectShift.innerHTML = '<option value="">-- No Shifts Today --</option>';
            } else {
                assignments.forEach(assign => {
                    const opt = document.createElement('option');
                    opt.value = assign.shiftId;
                    opt.textContent = `${this.getShiftLabel(assign.shiftId)} (Today)`;
                    selectShift.appendChild(opt);
                });
            }
            this.onDriverShiftChange();
        }
    }

    async onDriverShiftChange() {
        const selectShift = document.getElementById('driver-select-shift');
        if (!selectShift) return;
        const shiftId = selectShift.value;
        const driverId = this.currentUser.psNumber;
        const date = this.getTodayString();

        // Hide all steps initially
        document.querySelectorAll('.attendance-step').forEach(el => el.classList.add('hidden'));

        // Reset file inputs and previews
        const depInput = document.getElementById('driver-upload-dep-file');
        const arrInput = document.getElementById('driver-upload-arr-file');
        if (depInput) depInput.value = '';
        if (arrInput) arrInput.value = '';
        
        const depPreviewCont = document.getElementById('driver-dep-preview-container');
        const arrPreviewCont = document.getElementById('driver-arr-preview-container');
        if (depPreviewCont) depPreviewCont.classList.add('hidden');
        if (arrPreviewCont) arrPreviewCont.classList.add('hidden');

        if (!shiftId) return;

        try {
            const res = await fetch(`/api/driver/attendance/status?driverId=${encodeURIComponent(driverId)}&shiftId=${encodeURIComponent(shiftId)}&date=${encodeURIComponent(date)}`);
            const data = await res.json();
            
            if (data.status === 'success') {
                const att = data.attendance;
                if (!att) {
                    // State 1: Mark Departure
                    document.getElementById('driver-att-step-departure').classList.remove('hidden');
                } else if (att.status === 'InTransit') {
                    // State 2: In Transit
                    document.getElementById('driver-att-step-intransit').classList.remove('hidden');
                    const timeEl = document.getElementById('driver-dep-marked-time');
                    if (timeEl) timeEl.textContent = `Departure logged at: ${att.departureTime || '--'}`;
                } else {
                    // State 4: Final status display (Pending, Approved, Rejected)
                    document.getElementById('driver-att-step-status').classList.remove('hidden');
                    
                    const box = document.getElementById('driver-attendance-status-box');
                    const icon = document.getElementById('driver-status-icon');
                    const title = document.getElementById('driver-status-title');
                    const desc = document.getElementById('driver-status-desc');
                    const depTime = document.getElementById('driver-status-dep-time');
                    const arrTime = document.getElementById('driver-status-arr-time');

                    if (depTime) depTime.textContent = att.departureTime || '--';
                    if (arrTime) arrTime.textContent = att.arrivalTime || '--';

                    if (att.status === 'Pending') {
                        if (box) {
                            box.style.background = '#FFFBEB';
                            box.style.borderColor = '#FDE68A';
                            box.style.color = '#B45309';
                        }
                        if (icon) icon.textContent = '⏳';
                        if (title) title.textContent = 'Completed & Pending Review';
                        if (desc) desc.textContent = 'Waiting for admin review';
                    } else if (att.status === 'Approved') {
                        if (box) {
                            box.style.background = '#ECFDF5';
                            box.style.borderColor = '#A7F3D0';
                            box.style.color = '#047857';
                        }
                        if (icon) icon.textContent = '✅';
                        if (title) title.textContent = 'Approved';
                        if (desc) desc.textContent = 'Trip verified and approved';
                    } else if (att.status === 'Rejected') {
                        if (box) {
                            box.style.background = '#FEF2F2';
                            box.style.borderColor = '#FCA5A5';
                            box.style.color = '#B91C1C';
                        }
                        if (icon) icon.textContent = '❌';
                        if (title) title.textContent = 'Rejected';
                        if (desc) desc.textContent = 'Trip rejected by admin';
                    }
                }
            }
        } catch (err) {
            console.error('Error fetching driver attendance status:', err);
        }
    }

    previewAttendancePhoto(step, event) {
        const file = event.target.files[0];
        if (!file) return;

        const maxSize = 15 * 1024 * 1024; // 15 MB
        if (file.size > maxSize) {
            alert('Error: Photo file size exceeds the 15 MB limit. Please take or choose a smaller photo.');
            event.target.value = ''; // clear input
            const previewCont = document.getElementById(`driver-${step}-preview-container`);
            if (previewCont) previewCont.classList.add('hidden');
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const previewImg = document.getElementById(`driver-${step}-preview`);
            const previewCont = document.getElementById(`driver-${step}-preview-container`);
            if (previewImg && previewCont) {
                previewImg.src = e.target.result;
                previewCont.classList.remove('hidden');
            }
        };
        reader.readAsDataURL(file);
    }

    // -----------------------------------------------------------------------
    // Client-side image compressor (runs in-browser before upload)
    // Resizes to max 1280×960 and re-encodes as JPEG at 75% quality.
    // Reduces a 15 MB raw photo to ~250-400 KB before it leaves the device.
    // Note: Canvas strips EXIF — server-side PIL compressor preserves GPS.
    // -----------------------------------------------------------------------
    compressImageForUpload(file, maxW = 1280, maxH = 960, quality = 0.75) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(new Error('Failed to read image file'));
            reader.onload = (e) => {
                const img = new Image();
                img.onerror = () => reject(new Error('Failed to decode image'));
                img.onload = () => {
                    // Calculate scaled dimensions keeping aspect ratio
                    let { width, height } = img;
                    if (width > maxW || height > maxH) {
                        const ratio = Math.min(maxW / width, maxH / height);
                        width  = Math.round(width  * ratio);
                        height = Math.round(height * ratio);
                    }
                    const canvas = document.createElement('canvas');
                    canvas.width  = width;
                    canvas.height = height;
                    canvas.getContext('2d').drawImage(img, 0, 0, width, height);
                    canvas.toBlob(
                        (blob) => blob ? resolve(blob) : reject(new Error('Canvas compression failed')),
                        'image/jpeg',
                        quality
                    );
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        });
    }


    async submitDepartureAttendance() {
        const selectShift = document.getElementById('driver-select-shift');
        if (!selectShift) return;
        const shiftId = selectShift.value;
        const driverId = this.currentUser.psNumber;
        const date = this.getTodayString();

        // Get bus ID dynamically from shift information
        const shifts = this.getItems('utcl_shifts');
        const shift = shifts.find(s => s.id === shiftId);
        const busId = shift ? shift.busId : '';

        const fileInput = document.getElementById('driver-upload-dep-file');
        if (!fileInput || fileInput.files.length === 0) {
            alert('Please select or capture a departure photo.');
            return;
        }

        const file = fileInput.files[0];
        const maxSize = 15 * 1024 * 1024;
        if (file.size > maxSize) {
            alert('Error: Photo file size exceeds the 15 MB limit. Please take or choose a smaller photo.');
            return;
        }

        const submitBtn = document.getElementById('driver-submit-dep-btn');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Compressing...';
        }

        try {
            // Compress in-browser before sending (~15 MB → ~300 KB)
            const compressedBlob = await this.compressImageForUpload(file);
            console.log(`[Photo] Departure: ${(file.size/1024).toFixed(0)} KB → ${(compressedBlob.size/1024).toFixed(0)} KB`);

            if (submitBtn) submitBtn.textContent = 'Submitting...';

            const formData = new FormData();
            formData.append('driverId', driverId);
            formData.append('busId', busId);
            formData.append('shiftId', shiftId);
            formData.append('date', date);
            formData.append('departure_photo', compressedBlob, 'departure.jpg');

            const res = await fetch('/api/driver/attendance/submit-departure', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (data.status === 'success') {
                alert('Departure attendance submitted successfully!');
                await this.onDriverShiftChange();
            } else {
                alert('Error submitting departure attendance: ' + data.message);
            }
        } catch (err) {
            console.error('Error submitting departure attendance:', err);
            alert('Error: ' + (err.message || 'Network error submitting departure attendance.'));
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Submit Departure';
            }
        }
    }

    showArrivalAttendanceStep() {
        document.getElementById('driver-att-step-intransit').classList.add('hidden');
        document.getElementById('driver-att-step-arrival').classList.remove('hidden');
    }

    async submitArrivalAttendance() {
        const selectShift = document.getElementById('driver-select-shift');
        if (!selectShift) return;
        const shiftId = selectShift.value;
        const driverId = this.currentUser.psNumber;
        const date = this.getTodayString();

        const fileInput = document.getElementById('driver-upload-arr-file');
        if (!fileInput || fileInput.files.length === 0) {
            alert('Please select or capture an arrival photo.');
            return;
        }

        const file = fileInput.files[0];
        const maxSize = 15 * 1024 * 1024;
        if (file.size > maxSize) {
            alert('Error: Photo file size exceeds the 15 MB limit. Please take or choose a smaller photo.');
            return;
        }

        const submitBtn = document.getElementById('driver-submit-arr-btn');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Compressing...';
        }

        try {
            // Compress in-browser before sending (~15 MB → ~300 KB)
            const compressedBlob = await this.compressImageForUpload(file);
            console.log(`[Photo] Arrival: ${(file.size/1024).toFixed(0)} KB → ${(compressedBlob.size/1024).toFixed(0)} KB`);

            if (submitBtn) submitBtn.textContent = 'Submitting...';

            const formData = new FormData();
            formData.append('driverId', driverId);
            formData.append('shiftId', shiftId);
            formData.append('date', date);
            formData.append('arrival_photo', compressedBlob, 'arrival.jpg');

            const res = await fetch('/api/driver/attendance/submit-arrival', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (data.status === 'success') {
                alert('Arrival attendance submitted successfully! Status is now pending admin review.');
                await this.onDriverShiftChange();
            } else {
                alert('Error submitting arrival attendance: ' + data.message);
            }
        } catch (err) {
            console.error('Error submitting arrival attendance:', err);
            alert('Error: ' + (err.message || 'Network error submitting arrival attendance.'));
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Submit Arrival & End Trip';
            }
        }
    }

    async loadPendingAttendances() {
        const tbody = document.getElementById('driver-management-table-body');
        if (!tbody) return;

        // Hide Clear button, Hide Export to Excel, set title/headers for Pending Review
        const clearBtn = document.getElementById('driver-history-clear-btn');
        if (clearBtn) clearBtn.classList.add('hidden');
        
        const exportBtn = document.getElementById('driver-export-excel-btn');
        if (exportBtn) exportBtn.classList.add('hidden');
        
        const paginationContainer = document.getElementById('driver-history-pagination');
        if (paginationContainer) paginationContainer.classList.add('hidden');

        // Set pending headers
        const thead = document.getElementById('driver-management-table-head');
        if (thead) {
            thead.innerHTML = `
                <tr>
                    <th>Date</th>
                    <th>Driver Name</th>
                    <th>Bus ID</th>
                    <th>Shift ID</th>
                    <th>Departure Info</th>
                    <th>Arrival Info</th>
                    <th>Actions</th>
                </tr>
            `;
        }

        try {
            const res = await fetch('/api/admin/attendance/pending');
            const data = await res.json();

            if (data.status === 'success') {
                const list = data.attendance;
                if (!list || list.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No pending driver attendances for review.</td></tr>`;
                    return;
                }

                tbody.innerHTML = '';
                list.forEach(att => {
                    const tr = document.createElement('tr');
                    
                    let depPhotoHtml = '';
                    if (!att.departurePhotoUrl) {
                        depPhotoHtml = '<span class="badge badge-warning">No Image Uploaded</span>';
                    } else {
                        const depUrl = `${window.location.origin}${att.departurePhotoUrl}`;
                        depPhotoHtml = `
                            <a href="${depUrl}" target="_blank" rel="noopener noreferrer" class="flex items-center gap-1" style="display:inline-flex; align-items:center; gap:4px;">
                                <img src="${depUrl}" style="width: 30px; height: 30px; object-fit: cover; border-radius: 4px;"> View
                            </a>
                        `;
                    }

                    let arrPhotoHtml = '';
                    if (!att.arrivalPhotoUrl) {
                        arrPhotoHtml = '<span class="badge badge-warning">No Image Uploaded</span>';
                    } else {
                        const arrUrl = `${window.location.origin}${att.arrivalPhotoUrl}`;
                        arrPhotoHtml = `
                            <a href="${arrUrl}" target="_blank" rel="noopener noreferrer" class="flex items-center gap-1" style="display:inline-flex; align-items:center; gap:4px;">
                                <img src="${arrUrl}" style="width: 30px; height: 30px; object-fit: cover; border-radius: 4px;"> View
                            </a>
                        `;
                    }

                    tr.innerHTML = `
                        <td>${att.date}</td>
                        <td><strong>${att.driverName || 'Driver ' + att.driverId} (${att.driverId})</strong></td>
                        <td>${att.busId === 'b1' ? 'Bus 1' : (att.busId === 'b2' ? 'Bus 2' : att.busId)}</td>
                        <td>${this.getShiftLabel(att.shiftId)}</td>
                        <td>
                            <div class="mb-1">${att.departureTime || '--'}</div>
                            <div>${depPhotoHtml}</div>
                        </td>
                        <td>
                            <div class="mb-1">${att.arrivalTime || '--'}</div>
                            <div>${arrPhotoHtml}</div>
                        </td>
                        <td>
                            <button class="btn btn-primary btn-xs" onclick="app.openAttendanceReview('${att.id}')">Review</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
                addMobileTableLabels('#driver-management-table-body');
            } else {
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Error loading data: ${data.message}</td></tr>`;
            }
        } catch (err) {
            console.error('Error loading pending attendances:', err);
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Network error loading pending reviews.</td></tr>`;
        }
    }

    async openAttendanceReview(id) {
        this.activeReviewId = id;
        const errorAlert = document.getElementById('attendance-action-error');
        if (errorAlert) errorAlert.classList.add('hidden');

        try {
            // Find the record from the list of pending attendances or fetch again
            const res = await fetch('/api/admin/attendance/pending');
            const data = await res.json();
            if (data.status === 'success') {
                const att = data.attendance.find(a => a.id === id);
                if (att) {
                    const depImg = document.getElementById('admin-review-dep-img');
                    const arrImg = document.getElementById('admin-review-arr-img');
                    const depTime = document.getElementById('admin-review-dep-time');
                    const arrTime = document.getElementById('admin-review-arr-time');

                    if (depImg) depImg.src = att.departurePhotoUrl || '';
                    if (arrImg) arrImg.src = att.arrivalPhotoUrl || '';
                    if (depTime) depTime.textContent = `Logged at: ${att.departureTime || '--'}`;
                    if (arrTime) arrTime.textContent = `Logged at: ${att.arrivalTime || '--'}`;

                    // Reset modal title and button visibility for review mode
                    const modalTitle = document.getElementById('admin-attendance-modal-title');
                    if (modalTitle) modalTitle.textContent = 'Review Trip Attendance Photos';

                    const rejectBtn = document.getElementById('admin-attendance-reject-btn');
                    const approveBtn = document.getElementById('admin-attendance-approve-btn');
                    if (rejectBtn) rejectBtn.classList.remove('hidden');
                    if (approveBtn) approveBtn.classList.remove('hidden');

                    this.openModal('admin-attendance-modal');
                } else {
                    alert('Attendance record not found.');
                }
            }
        } catch (err) {
            console.error('Error opening attendance review modal:', err);
            alert('Failed to load attendance review details.');
        }
    }

    async submitAttendanceApproval(isApproved) {
        const id = this.activeReviewId;
        if (!id) return;

        const errorAlert = document.getElementById('attendance-action-error');
        if (errorAlert) errorAlert.classList.add('hidden');

        const status = isApproved ? 'Approved' : 'Rejected';

        try {
            const res = await fetch(`/api/admin/attendance/${id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status })
            });
            const data = await res.json();
            if (data.status === 'success') {
                alert(`Trip attendance successfully ${status.toLowerCase()}!`);
                this.closeModal('admin-attendance-modal');
                await this.loadPendingAttendances();
            } else {
                if (errorAlert) {
                    errorAlert.textContent = data.message;
                    errorAlert.classList.remove('hidden');
                } else {
                    alert('Error updating attendance: ' + data.message);
                }
            }
        } catch (err) {
            console.error('Error submitting attendance approval:', err);
            if (errorAlert) {
                errorAlert.textContent = 'Network error updating attendance status.';
                errorAlert.classList.remove('hidden');
            } else {
                alert('Network error updating attendance.');
            }
        }
    }

    // ==========================================================================
    // 5. ADMIN PORTAL SERVICES
    // ==========================================================================

    switchAdminTab(tab) {
        this.stopAttendancePolling();
        this.currentAdminTab = tab;
        const navBtns = document.querySelectorAll('.admin-nav-btn');
        navBtns.forEach(btn => {
            if (btn.getAttribute('onclick').includes(tab)) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Hide all panels
        const panels = document.querySelectorAll('.admin-tab-panel');
        panels.forEach(p => p.classList.remove('active'));

        // Show active panel
        const activePanel = document.getElementById(`admin-tab-${tab}`);
        if (activePanel) activePanel.classList.add('active');

        // Trigger updates depending on tab
        if (tab === 'dashboard') {
            this.loadAdminKPIs();
            this.initDashboardCharts();
        } else if (tab === 'users') {
            const searchInput = document.getElementById('admin-users-search');
            if (searchInput) searchInput.value = '';
            this.loadAdminUsers();
        } else if (tab === 'buses') {
            this.loadAdminBuses();
        } else if (tab === 'shifts') {
            this.loadAdminShiftsList();
        } else if (tab === 'maintenance') {
            this.loadAdminMaintenance();
        } else if (tab === 'revenue') {
            this.initRevenueAnalytics();
        } else if (tab === 'occupancy') {
            this.initOccupancyAnalysis();
        } else if (tab === 'notifications') {
            this.initAdminNotificationsTab();
        } else if (tab === 'history') {
            // Reset to default manifest view
            const input = document.getElementById('history-ps-number');
            if (input) input.value = '';
            this.closeHistoryAutocomplete();
            const clearBtn = document.getElementById('history-clear-btn');
            if (clearBtn) clearBtn.classList.add('hidden');
            const exportBtn = document.getElementById('export-excel-btn');
            if (exportBtn) exportBtn.classList.add('hidden');
            // Show manifest section, hide employee history section
            const manifestSection = document.getElementById('history-manifest-section');
            const employeeSection = document.getElementById('history-employee-section');
            if (manifestSection) manifestSection.classList.remove('hidden');
            if (employeeSection) employeeSection.classList.add('hidden');
            this.renderUpcomingManifests();
        } else if (tab === 'attendance') {
            this.loadPendingAttendances();
            this.startAttendancePolling();
        } else if (tab === 'payroll') {
            this.initPayrollTab();
        }
    }

    loadAdminKPIs() {
        const todayStr = this.getTodayString();
        const bookings = this.getItems('utcl_bookings').filter(b => b.travelDate === todayStr && b.status === 'CONFIRMED');
        const buses = this.getItems('utcl_buses').filter(b => b.isActive);

        // Active Fleet
        document.getElementById('admin-kpi-fleet').textContent = `${buses.length} / 2`;

        // Today Bookings
        document.getElementById('admin-kpi-bookings').textContent = bookings.length;

        // Today Revenue
        document.getElementById('admin-kpi-revenue').textContent = `₹${bookings.length * 20}`;

        // Average Occupancy
        const capacityTotal = buses.length * 4 * 49; // 2 buses * 4 shifts * 49 seats = 392 max seats
        const occPct = capacityTotal > 0 ? Math.round((bookings.length / capacityTotal) * 100) : 0;
        document.getElementById('admin-kpi-occupancy').textContent = `${occPct}%`;

        // All-time KPIs
        const allBookings = this.getItems('utcl_bookings').filter(b => b.status === 'CONFIRMED');
        const allRevenue = allBookings.reduce((sum, b) => sum + (b.fareAmount || 20), 0);
        document.getElementById('admin-kpi-total-bookings').textContent = allBookings.length;
        document.getElementById('admin-kpi-total-revenue').textContent = `₹${allRevenue.toLocaleString('en-IN')}`;

        // Load alerts and warnings
        const alertsContainer = document.getElementById('admin-dashboard-alerts');
        alertsContainer.innerHTML = '';

        // Alert 1: Overdue Maintenance (Requirement 9.4)
        const maintenance = this.getItems('utcl_maintenance');
        const overdueMaint = maintenance.filter(m => m.scheduledDate < todayStr && m.status !== 'COMPLETED');

        overdueMaint.forEach(m => {
            const bus = buses.find(b => b.id === m.busId);
            const alertItem = document.createElement('div');
            alertItem.className = "alert alert-danger";
            alertItem.innerHTML = `<strong>Overdue Maintenance Alert:</strong> ${bus ? bus.identifier : 'Unknown Bus'} was scheduled for "${m.description}" on ${m.scheduledDate}. Status is OVERDUE.`;
            alertsContainer.appendChild(alertItem);
        });

        if (overdueMaint.length === 0) {
            alertsContainer.innerHTML = `<div class="empty-state">No critical operation alerts. Systems operating normally.</div>`;
        }
    }

    // ── FEATURE 1: Enhanced Analytics Dashboard Charts ────────────────────────
    destroyDashboardCharts() {
        ['_dashDailyChart', '_dashShiftChart', '_dashStopsChart', '_dashWeekdayChart'].forEach(key => {
            if (this[key]) { this[key].destroy(); this[key] = null; }
        });
    }

    initDashboardCharts() {
        this.destroyDashboardCharts();
        const allBookings = this.getItems('utcl_bookings').filter(b => b.status === 'CONFIRMED');

        // Shared chart defaults
        const gridColor = 'rgba(0,0,0,0.06)';
        const tickColor = '#64748B';
        const baseOpts = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: gridColor }, ticks: { color: tickColor, font: { size: 11 } } },
                y: { grid: { color: gridColor }, ticks: { color: tickColor, font: { size: 11 } }, beginAtZero: true }
            }
        };

        // 1. Daily Bookings — Last 14 days
        const days14 = [];
        const counts14 = [];
        for (let i = 13; i >= 0; i--) {
            const d = new Date();
            d.setDate(d.getDate() - i);
            const ds = d.toISOString().slice(0, 10);
            const label = `${d.getDate()}/${d.getMonth() + 1}`;
            days14.push(label);
            counts14.push(allBookings.filter(b => b.travelDate === ds).length);
        }
        this._dashDailyChart = new Chart(
            document.getElementById('dash-daily-chart').getContext('2d'),
            {
                type: 'line',
                data: {
                    labels: days14,
                    datasets: [{
                        label: 'Bookings',
                        data: counts14,
                        borderColor: '#0057A8',
                        backgroundColor: 'rgba(0,87,168,0.10)',
                        fill: true,
                        tension: 0.4,
                        pointBackgroundColor: '#0057A8',
                        pointRadius: 4
                    }]
                },
                options: { ...baseOpts }
            }
        );

        // 2. Bookings by Shift (horizontal bar)
        const shiftCounts = {};
        allBookings.forEach(b => { shiftCounts[b.shiftId] = (shiftCounts[b.shiftId] || 0) + 1; });
        const shiftLabels = Object.keys(shiftCounts).sort();
        const shiftData = shiftLabels.map(k => shiftCounts[k]);
        const shiftColors = ['#0057A8','#E86614','#1a7a3c','#8B2FC9','#CC0000','#009688','#FF6F00','#5C6BC0'];
        this._dashShiftChart = new Chart(
            document.getElementById('dash-shift-chart').getContext('2d'),
            {
                type: 'bar',
                data: {
                    labels: shiftLabels,
                    datasets: [{
                        data: shiftData,
                        backgroundColor: shiftLabels.map((_, i) => shiftColors[i % shiftColors.length]),
                        borderRadius: 6
                    }]
                },
                options: { ...baseOpts }
            }
        );

        // 3. Top Boarding Stops (doughnut)
        const stopCounts = {};
        allBookings.forEach(b => {
            const stop = b.boardingStopIndex !== undefined ? `Stop ${b.boardingStopIndex}` : 'Unknown';
            // Try to get real stop name from shifts
            const shift = this.getItems('utcl_shifts').find(s => s.id === b.shiftId);
            const stopName = shift && shift.stops && shift.stops[b.boardingStopIndex]
                ? shift.stops[b.boardingStopIndex].name
                : `Stop ${b.boardingStopIndex}`;
            stopCounts[stopName] = (stopCounts[stopName] || 0) + 1;
        });
        const stopLabels = Object.keys(stopCounts).sort((a, b) => stopCounts[b] - stopCounts[a]).slice(0, 6);
        const stopData = stopLabels.map(k => stopCounts[k]);
        const doughnutColors = ['#0057A8','#E86614','#1a7a3c','#8B2FC9','#CC0000','#009688'];
        this._dashStopsChart = new Chart(
            document.getElementById('dash-stops-chart').getContext('2d'),
            {
                type: 'doughnut',
                data: {
                    labels: stopLabels,
                    datasets: [{
                        data: stopData,
                        backgroundColor: doughnutColors,
                        borderWidth: 2,
                        borderColor: '#fff'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'right',
                            labels: { color: '#334155', font: { size: 11 }, boxWidth: 14, padding: 12 }
                        }
                    }
                }
            }
        );

        // 4. Bookings by Day of Week
        const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const dayCounts = [0,0,0,0,0,0,0];
        allBookings.forEach(b => {
            if (b.travelDate) {
                const dow = new Date(b.travelDate + 'T12:00:00').getDay();
                dayCounts[dow]++;
            }
        });
        this._dashWeekdayChart = new Chart(
            document.getElementById('dash-weekday-chart').getContext('2d'),
            {
                type: 'bar',
                data: {
                    labels: dayNames,
                    datasets: [{
                        data: dayCounts,
                        backgroundColor: dayCounts.map((_, i) =>
                            (i === 0 || i === 6) ? 'rgba(204,0,0,0.7)' : 'rgba(0,87,168,0.75)'
                        ),
                        borderRadius: 6
                    }]
                },
                options: { ...baseOpts }
            }
        );
    }

    // ── FEATURE 1: Real-Time Seat Availability via WebSockets ────────────────

    /** Connect to Socket.IO (served by Flask-SocketIO on same host:port). */
    /** Connect to Socket.IO (served by Flask-SocketIO on same host:port). */
    initSocket() {
        // Gracefully skip if Socket.IO client JS didn't load (e.g. file:// protocol)
        if (typeof io === 'undefined') {
            console.warn('[WS] Socket.IO client not available — real-time updates disabled.');
            return;
        }
        try {
            // Dynamic LAN/Origin binding configuration
            this.socket = io(window.location.origin, {
                transports: ['polling'],
                reconnection: true,
                reconnectionDelay: 1000,
                reconnectionDelayMax: 5000,
                reconnectionAttempts: Infinity
            });

            this.socket.on('connect', () => {
                console.log('[WS] Connected:', this.socket.id);
                this._updateLiveBadge(true);
                this.stopSeatPolling();  // WS is up — no need for polling fallback
                
                // Re-register user dynamic room mappings on connection and recovery
                if (this.currentUser) {
                    this.socket.emit('register_user', {
                        psNumber: this.currentUser.psNumber,
                        userId: this.currentUser.id,
                        role: this.currentUser.role
                    });
                }

                // Re-join room if we were in one before reconnect
                if (this.currentSeatRoom) {
                    this.socket.emit('join_seat_room', { room: this.currentSeatRoom });
                }

                // State Sync Fallback: pull down updates if we just recovered from connection drop
                if (this.isSocketReconnecting) {
                    console.log('[WS] Connection recovered. Triggering fallback state sync.');
                    this.isSocketReconnecting = false;
                    this.syncStateSilent();
                }
            });

            this.socket.on('disconnect', (reason) => {
                console.warn('[WS] Disconnected:', reason);
                this._updateLiveBadge(false);
                this.isSocketReconnecting = true;
                // Start polling fallback so seat map stays fresh
                if (this.currentSeatRoom) this.startSeatPolling();
            });

            this.socket.on('reconnect', (attemptNumber) => {
                console.log('[WS] Reconnected successfully on attempt:', attemptNumber);
            });

            // Clean up existing listeners to prevent duplicate socket event handling
            this.socket.off('seat_booked');
            this.socket.off('seat_held');
            this.socket.off('seat_released');
            this.socket.off('current_holds');
            this.socket.off('NEW_NOTIFICATION');
            this.socket.off('SCHEDULE_UPDATED');
            this.socket.off('SHIFT_SCHEDULE_UPDATED');
            this.socket.off('ATTENDANCE_STATUS_CHANGED');
            this.socket.off('ATTENDANCE_UPDATED');
            this.socket.off('MAINTENANCE_UPDATED');
            this.socket.off('USER_UPDATED');
            this.socket.off('BOOKING_UPDATED');
            this.socket.off('BOOKING_CANCELLED');
            this.socket.off('TRACKING_UPDATED');
            this.socket.off('SHIFT_LOCKED');
            this.socket.off('SEAT_COUNT_UPDATED');
            this.socket.off('SHIFT_CANCELLED_FOR_DAY');

            this.socket.on('seat_booked', (data) => {
                this.onSeatBooked(data);
            });

            this.socket.on('seat_held', (data) => {
                this.onSeatHeld(data);
            });

            this.socket.on('seat_released', (data) => {
                this.onSeatReleased(data);
            });

            this.socket.on('current_holds', (data) => {
                this.onCurrentHolds(data);
            });

            // ── EXTENDED REAL-TIME UPDATE LISTENERS ───────────────────────

            this.socket.on('NEW_NOTIFICATION', (data) => {
                if (!this.currentUser) return;
                
                const isTarget = data.recipientUserId === this.currentUser.id ||
                                 (this.currentUser.role === 'EMPLOYEE' && data.recipientUserId === 'all_employees') ||
                                 (this.currentUser.role === 'DRIVER' && data.recipientUserId === 'all_drivers');

                if (isTarget) {
                    console.log('[WS] New Notification received:', data);
                    
                    // Deduplicate multi-tab displays by checking/updating a displayed IDs list in localStorage.
                    let displayedIds = JSON.parse(localStorage.getItem('utcl_displayed_notifications') || '[]');
                    if (displayedIds.includes(data.id)) {
                        // Already shown on another tab, sync local cache but skip displaying the toast
                        const list = this.getItems('utcl_notifications') || [];
                        if (!list.some(n => n.id === data.id)) {
                            list.push(data);
                            localStorage.setItem('utcl_notifications', JSON.stringify(list));
                            this.updateNotificationsUI();
                        }
                        return;
                    }
                    
                    // Add to displayed cache (limit to last 50 IDs)
                    displayedIds.push(data.id);
                    if (displayedIds.length > 50) displayedIds.shift();
                    localStorage.setItem('utcl_displayed_notifications', JSON.stringify(displayedIds));

                    // Show a premium live banner/toast with Amber yellow title
                    this.showLiveToast(data.message, "NEW NOTIFICATION");
                    
                    // Sync local cache
                    const list = this.getItems('utcl_notifications') || [];
                    if (!list.some(n => n.id === data.id)) {
                        list.push(data);
                        localStorage.setItem('utcl_notifications', JSON.stringify(list));
                        this.updateNotificationsUI();
                    }
                }
            });

            this.socket.on('SCHEDULE_UPDATED', async (data) => {
                console.log('[WS] Schedule updated globally. Synchronizing layout state...', data);
                await this.syncStateSilent();
            });

            this.socket.on('SHIFT_SCHEDULE_UPDATED', async (data) => {
                console.log('[WS] Shift schedule updated. Synchronizing layout state...', data);
                await this.syncStateSilent();
            });

            this.socket.on('ATTENDANCE_STATUS_CHANGED', async (data) => {
                if (this.currentUser && this.currentUser.psNumber === data.driverId) {
                    console.log('[WS] Attendance reviewed:', data);
                    
                    // Display status change toast
                    this.showLiveToast(
                        `Your attendance for shift ${this.getShiftLabel(data.shiftId)} on ${data.date} has been ${data.status.toLowerCase()}.`,
                        "Attendance Reviewed"
                    );

                    // Pull updated records and redraw dashboard views
                    await this.syncStateSilent();
                    if (typeof this.onDriverShiftChange === 'function') {
                        this.onDriverShiftChange();
                    }
                }
            });

            this.socket.on('MAINTENANCE_UPDATED', async (data) => {
                console.log('[WS] Maintenance schedule updated. Synchronizing state...', data);
                // syncStateSilent → refreshUI() handles driver dashboard re-render.
                await this.syncStateSilent();
            });

            this.socket.on('USER_UPDATED', async (data) => {
                console.log('[WS] User list updated. Synchronizing state...', data);
                await this.syncStateSilent();
            });

            this.socket.on('BOOKING_UPDATED', async (data) => {
                console.log('[WS] Bookings/tickets updated. Synchronizing state...', data);
                // syncStateSilent → refreshUI() handles all tab-specific re-renders.
                // No need to call tab functions manually here — that caused double renders.
                await this.syncStateSilent();
            });

            this.socket.on('BOOKING_CANCELLED', async (data) => {
                console.log('[WS] BOOKING_CANCELLED received:', data);
                const { bookingId, shiftId, travelDate, seats, psNumber } = data;

                // Clean up any active holds for these seats
                if (this.activeHolds) {
                    this.activeHolds = this.activeHolds.filter(h => !seats.includes(h.seatNumber));
                }

                // 1. Update localStorage immediately (WITHOUT syncing back to the database since the server is the source of truth)
                let isAlreadyCancelled = false;
                const bookings = this.getItems('utcl_bookings');
                const booking  = bookings.find(b => b.id === bookingId);
                if (booking) {
                    if (booking.status === 'CANCELLED') {
                        isAlreadyCancelled = true;
                    } else {
                        booking.status = 'CANCELLED';
                    }
                }
                localStorage.setItem('utcl_bookings', JSON.stringify(bookings));

                const tickets = this.getItems('utcl_tickets');
                const ticket  = tickets.find(t => t.bookingId === bookingId);
                if (ticket) ticket.status = 'CANCELLED';
                localStorage.setItem('utcl_tickets', JSON.stringify(tickets));

                // 2. If seat map for this shift+date is open, re-render it to show freed seats
                if (this.currentSeatRoom === `${shiftId}_${travelDate}`) {
                    if (typeof this.renderSeatMap === 'function') this.renderSeatMap();
                    // Show live update bar only if not initiated by self to avoid double notifications
                    if (this.currentUser && this.currentUser.psNumber !== psNumber) {
                        this.showLiveUpdateBar(`✅ Seat(s) ${seats.join(', ')} just released — now available!`, 5000);
                    }
                }

                // 3. If employee's My Tickets tab is open, refresh it
                if (this.currentUser && this.currentUser.role === 'EMPLOYEE' && this.currentEmployeeTab === 'mytickets') {
                    const row = document.getElementById(`ticket-row-${bookingId}`);
                    if (row && !row.classList.contains('ticket-row-fade-out')) {
                        row.classList.add('ticket-row-fade-out');
                        setTimeout(() => {
                            row.remove();
                            this.loadMyTickets();
                        }, 350);
                    } else if (!row && !isAlreadyCancelled) {
                        this.loadMyTickets();
                    }
                }

                // 4. If admin's booking history is open, refresh the appropriate section
                if (this.currentUser && this.currentUser.role === 'ADMIN' && this.currentAdminTab === 'history') {
                    if (!isAlreadyCancelled) {
                        setTimeout(() => {
                            const employeeSection = document.getElementById('history-employee-section');
                            const psInput = document.getElementById('history-ps-number');
                            if (employeeSection && !employeeSection.classList.contains('hidden') && psInput && psInput.value.trim()) {
                                this.loadBookingHistory();
                            } else {
                                this.renderUpcomingManifests();
                            }
                        }, 300);
                    }
                }

                // 4.5. If admin's payroll tab is open, refresh it
                if (this.currentUser && this.currentUser.role === 'ADMIN' && this.currentAdminTab === 'payroll') {
                    if (!isAlreadyCancelled) {
                        this.generatePayrollPreview();
                        this.loadPayrollHistory();
                    }
                }

                // 4.6. If employee's myfares tab is open, refresh it
                if (this.currentUser && this.currentUser.role === 'EMPLOYEE' && this.currentEmployeeTab === 'myfares') {
                    if (!isAlreadyCancelled) {
                        this.loadMyFares();
                    }
                }

                // 5. Show a toast only if the cancelled booking is NOT by the current user
                // (current user already sees their own confirmCancelBooking toast)
                if (this.currentUser && this.currentUser.psNumber !== psNumber) {
                    this.showLiveToast(`Seat(s) ${seats.join(', ')} on shift ${shiftId} (${travelDate}) have been released.`, 'Seat Released');
                }
            });

            this.socket.on('PAYROLL_UPDATED', async (data) => {
                console.log('[WS] Payroll updated:', data);
                await this.syncStateSilent();
                if (this.currentUser && this.currentUser.role === 'ADMIN') {
                    if (this.currentAdminTab === 'payroll') {
                        this.generatePayrollPreview();
                        this.loadPayrollHistory();
                    }
                } else if (this.currentUser && this.currentUser.role === 'EMPLOYEE') {
                    if (this.currentEmployeeTab === 'myfares') {
                        this.loadMyFares();
                    }
                }
            });

            this.socket.on('TRACKING_UPDATED', async (data) => {
                console.log('[WS] Bus tracking updated. Synchronizing state...', data);
                await this.syncStateSilent();
            });

            this.socket.on('ATTENDANCE_UPDATED', async (data) => {
                console.log('[WS] Attendance updated. Refetching...', data);
                if (this.currentUser && this.currentUser.role === 'ADMIN') {
                    if (this.currentAdminTab === 'attendance') {
                        const searchInput = document.getElementById('driver-history-ps-number');
                        if (searchInput && searchInput.value.trim()) {
                            this.loadDriverAttendanceHistory(1);
                        } else {
                            this.loadPendingAttendances();
                        }
                    }
                }
            });

            this.socket.on('SHIFT_LOCKED', (data) => {
                console.log('[WS] Shift locked:', data);
                const { shiftId } = data;
                const card = document.getElementById(`shift-card-${shiftId}`);
                if (card) {
                    card.onclick = null;
                    card.classList.add('disabled', 'locked');
                    const badge = card.querySelector('.shift-seats-badge');
                    if (badge) {
                        badge.className = 'shift-seats-badge badge bg-slate-50 border border-slate-200 text-slate-400 cursor-not-allowed';
                        badge.innerHTML = '🔒 Booking Closed & Locked';
                    }
                }
                
                if (this.bookingData && this.bookingData.shiftId === shiftId) {
                    this.bookingData.shiftId = '';
                    const seatContainer = document.getElementById('seat-selection-container');
                    if (seatContainer) seatContainer.classList.add('hidden');
                    const virtualTicketCard = document.getElementById('virtual-ticket-card');
                    if (virtualTicketCard) virtualTicketCard.classList.add('hidden');
                    const ticketEmptyState = document.getElementById('ticket-empty-state');
                    if (ticketEmptyState) ticketEmptyState.classList.remove('hidden');
                    alert(`⚠️ The shift ${this.getShiftLabel ? this.getShiftLabel(shiftId) : shiftId} is now locked for departure. Booking is closed.`);
                    this.renderAvailableShifts();
                }

                if (this.currentUser && this.currentUser.role === 'ADMIN') {
                    if (typeof this.renderUpcomingManifests === 'function') {
                        this.renderUpcomingManifests();
                    }
                }
            });

            this.socket.on('SHIFT_CANCELLED_FOR_DAY', async (data) => {
                const { shiftId, travelDate, reason, cancelledCount } = data;
                console.log('[WS] SHIFT_CANCELLED_FOR_DAY received:', data);

                // Sync all local state from server
                await this.syncStateSilent();

                if (this.currentUser && this.currentUser.role === 'EMPLOYEE') {
                    // Refresh My Tickets if open
                    if (this.currentEmployeeTab === 'mytickets') {
                        if (typeof this.loadMyTickets === 'function') this.loadMyTickets();
                    }
                    // Refresh My Fares if open
                    if (this.currentEmployeeTab === 'myfares') {
                        if (typeof this.loadMyFares === 'function') this.loadMyFares();
                    }
                    // If on Book a Trip and seat map for this shift+date is open, close it
                    if (this.currentEmployeeTab === 'book' &&
                        this.bookingData && this.bookingData.shiftId === shiftId) {
                        if (typeof this.renderAvailableShifts === 'function') this.renderAvailableShifts();
                    }
                    // Show a prominent alert toast
                    this.showLiveToast(
                        `🚫 Shift ${this.getShiftLabel ? this.getShiftLabel(shiftId) : shiftId} on ${travelDate} has been cancelled. Reason: ${reason || 'Not specified'}.`,
                        'Shift Cancelled'
                    );
                }

                if (this.currentUser && this.currentUser.role === 'ADMIN') {
                    // Refresh whichever admin tab is active
                    if (this.currentAdminTab === 'shifts') {
                        if (typeof this.loadAdminShiftsList === 'function') this.loadAdminShiftsList();
                    } else if (this.currentAdminTab === 'history') {
                        if (typeof this.renderUpcomingManifests === 'function') this.renderUpcomingManifests();
                    } else if (this.currentAdminTab === 'payroll') {
                        if (typeof this.generatePayrollPreview === 'function') this.generatePayrollPreview();
                    }
                    this.showLiveToast(
                        `✅ Shift ${this.getShiftLabel ? this.getShiftLabel(shiftId) : shiftId} on ${travelDate} cancelled — ${cancelledCount} booking(s) removed.`,
                        'Admin: Shift Cancelled'
                    );
                }

                if (this.currentUser && this.currentUser.role === 'DRIVER') {
                    if (typeof this.renderDriverDashboard === 'function') this.renderDriverDashboard();
                    this.showLiveToast(
                        `🚫 Shift ${this.getShiftLabel ? this.getShiftLabel(shiftId) : shiftId} on ${travelDate} has been cancelled.`,
                        'Shift Cancelled'
                    );
                }
            });

            this.socket.on('SEAT_COUNT_UPDATED', async (data) => {
                console.log('[WS] Seat count updated:', data);
                // syncStateSilent already calls refreshUI() which re-renders the active tab.
                // Don't call renderAvailableShifts() manually — it's handled inside refreshUI().
                await this.syncStateSilent();
            });

        } catch (err) {
            console.error('[WS] initSocket error:', err);
        }
    }

    /** Silent background API re-fetch function to instantly pull down updates, debounced and coalesced to prevent multi-refresh bugs */
    syncStateSilent() {
        return new Promise((resolve) => {
            this._syncResolveQueue.push(resolve);

            if (this._syncTimeout) {
                clearTimeout(this._syncTimeout);
            }

            this._syncTimeout = setTimeout(async () => {
                const resolves = [...this._syncResolveQueue];
                this._syncResolveQueue = [];
                this._syncTimeout = null;

                try {
                    console.log('[WS] Syncing database state silently...');
                    const response = await fetch('/api/data');
                    if (response.ok) {
                        const data = await response.json();
                        Object.keys(data).forEach(key => {
                            localStorage.setItem(key, JSON.stringify(data[key]));
                        });
                        console.log('[WS] Local state database synchronization complete.');
                        this.refreshUI();
                    }
                } catch (err) {
                    console.error('[WS] Silent state sync error:', err);
                } finally {
                    resolves.forEach(res => res());
                }
            }, 80); // 80ms debounce window to group burst socket events
        });
    }

    /** Refresh UI layout models dynamically without page reload */
    refreshUI() {
        if (!this.currentUser) return;
        console.log('[WS] Refreshing UI dashboard layout views...');

        // Update notifications badge
        this.updateNotificationsUI();

        // Refresh current active view
        if (this.currentUser.role === 'EMPLOYEE') {
            if (this.currentEmployeeTab === 'booking') {
                if (typeof this.renderAvailableShifts === 'function') this.renderAvailableShifts();
            } else if (this.currentEmployeeTab === 'schedules') {
                if (typeof this.loadSchedulesTimings === 'function') this.loadSchedulesTimings();
            } else if (this.currentEmployeeTab === 'mytickets') {
                if (typeof this.loadMyTickets === 'function') this.loadMyTickets();
            }
        } else if (this.currentUser.role === 'DRIVER') {
            if (typeof this.renderDriverDashboard === 'function') this.renderDriverDashboard();
        } else if (this.currentUser.role === 'ADMIN') {
            if (this.currentAdminTab === 'dashboard') {
                if (typeof this.loadAdminKPIs === 'function') this.loadAdminKPIs();
                if (typeof this.initDashboardCharts === 'function') this.initDashboardCharts();
            } else if (this.currentAdminTab === 'users') {
                if (typeof this.loadAdminUsers === 'function') this.loadAdminUsers();
            } else if (this.currentAdminTab === 'buses') {
                if (typeof this.loadAdminBuses === 'function') this.loadAdminBuses();
            } else if (this.currentAdminTab === 'shifts') {
                if (typeof this.loadAdminShiftsList === 'function') this.loadAdminShiftsList();
            } else if (this.currentAdminTab === 'driver-assignment') {
                if (typeof this.loadAdminBuses === 'function') this.loadAdminBuses();
            } else if (this.currentAdminTab === 'attendance') {
                if (typeof this.loadPendingAttendances === 'function') this.loadPendingAttendances();
            } else if (this.currentAdminTab === 'maintenance') {
                if (typeof this.loadAdminMaintenance === 'function') this.loadAdminMaintenance();
            } else if (this.currentAdminTab === 'revenue') {
                if (typeof this.initRevenueAnalytics === 'function') this.initRevenueAnalytics();
            } else if (this.currentAdminTab === 'occupancy') {
                if (typeof this.initOccupancyAnalysis === 'function') this.initOccupancyAnalysis();
            } else if (this.currentAdminTab === 'notifications') {
                if (typeof this.initAdminNotificationsTab === 'function') this.initAdminNotificationsTab();
            } else if (this.currentAdminTab === 'history') {
                // Refresh whichever section is visible
                const employeeSection = document.getElementById('history-employee-section');
                const psInput = document.getElementById('history-ps-number');
                if (employeeSection && !employeeSection.classList.contains('hidden') && psInput && psInput.value.trim()) {
                    if (typeof this.loadBookingHistory === 'function') this.loadBookingHistory();
                } else {
                    if (typeof this.renderUpcomingManifests === 'function') this.renderUpcomingManifests();
                }
            }
        }

        // If a virtual ticket is currently displayed, refresh its timings and other details dynamically
        const ticketCard = document.getElementById('virtual-ticket-card');
        if (ticketCard && !ticketCard.classList.contains('hidden')) {
            const ticketNumElem = document.getElementById('ticket-number');
            if (ticketNumElem && ticketNumElem.textContent) {
                const ticketNum = ticketNumElem.textContent.trim();
                const tickets = this.getItems('utcl_tickets');
                const currentTicket = tickets.find(t => t.ticketNumber === ticketNum);
                if (currentTicket) {
                    this.displayVirtualTicket(currentTicket);
                }
            }
        }

        // MutationObserver naturally handles option list updates, but let's re-run initialization
        // on custom select boxes to ensure new dynamically added selectors are captured
        if (typeof this.initCustomSelects === 'function') {
            this.initCustomSelects();
        }
    }

    /** Trigger a premium live banner/toast notification on the screen */
    showLiveToast(message, title = "NEW NOTIFICATION") {
        let container = document.getElementById('live-toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'live-toast-container';
            container.className = 'live-toast-container';
            document.body.appendChild(container);
        }

        if (!this.activeToasts) {
            this.activeToasts = [];
        }

        const toast = document.createElement('div');
        toast.className = 'live-toast';
        toast.innerHTML = `
            <div class="live-toast-header">
                <span class="live-toast-title">${title}</span>
                <button class="live-toast-close">&times;</button>
            </div>
            <div class="live-toast-body">${message}</div>
        `;

        const dismissToast = (t) => {
            if (!t.classList.contains('show')) return;
            t.classList.remove('show');
            // Remove from the state-driven tracking array
            this.activeToasts = this.activeToasts.filter(x => x !== t);
            setTimeout(() => {
                if (t.parentNode) {
                    t.remove();
                }
            }, 400);
        };

        // Close button click listener
        toast.querySelector('.live-toast-close').addEventListener('click', () => {
            dismissToast(toast);
        });

        // Limit the maximum number of simultaneous on-screen toasts to 3
        if (this.activeToasts.length >= 3) {
            const oldest = this.activeToasts.shift();
            if (oldest) {
                dismissToast(oldest);
            }
        }

        container.appendChild(toast);
        this.activeToasts.push(toast);

        // Slide in animation
        setTimeout(() => toast.classList.add('show'), 50);

        // Auto remove after a clean 4-second timeout
        setTimeout(() => {
            dismissToast(toast);
        }, 4000);
    }

    /** Update the pulsing live badge in the seat map heading. */
    _updateLiveBadge(connected) {
        const badge = document.getElementById('ws-live-badge');
        if (!badge) return;
        if (connected) {
            badge.classList.add('connected');
            badge.classList.remove('offline');
            badge.title = '🟢 Live — real-time seat updates active';
        } else {
            badge.classList.remove('connected');
            badge.classList.add('offline');
            badge.title = '🔴 Offline — refreshing on a 15s timer';
        }
    }

    /**
     * Join the seat-availability room for a given shift + date.
     * Called when the seat selection step becomes visible.
     */
    joinSeatRoom(shiftId, date) {
        if (!shiftId || !date) return;
        const room = `${shiftId}_${date}`;
        if (this.currentSeatRoom === room) return;  // already in this room
        // Leave old room first
        this.leaveSeatRoom();
        this.currentSeatRoom = room;
        if (this.socket && this.socket.connected) {
            this.socket.emit('join_seat_room', { room });
        } else {
            // WS not ready — start polling fallback
            this.startSeatPolling();
        }
    }

    /** Leave the current seat room (when navigating away from seat step). */
    leaveSeatRoom() {
        if (this.currentSeatRoom && this.socket && this.socket.connected) {
            this.socket.emit('leave_seat_room', { room: this.currentSeatRoom });
        }
        this.currentSeatRoom = null;
        this.stopSeatPolling();
    }

    /**
     * Handles a live 'seat_booked' event broadcast by the server.
     * Marks seats as occupied with a flash animation and warns the user
     * if any of their currently selected seats were just taken.
     */
    onSeatBooked(data) {
        const { shiftId, date, seats, bookedBy } = data;

        // Clean up any active holds for these seats
        if (this.activeHolds) {
            this.activeHolds = this.activeHolds.filter(h => !seats.includes(h.seatNumber));
        }

        // Keep localStorage in sync so the next renderSeatMap() reflects reality
        const bookings = this.getItems('utcl_bookings');
        const alreadySynced = bookings.some(b =>
            b.shiftId === shiftId && b.travelDate === date &&
            String(b.seatNumber).split(',').map(s => parseInt(s.trim(), 10)).some(s => seats.includes(s))
        );
        if (!alreadySynced) {
            // Use 'PHANTOM' as psNumber so this ghost entry NEVER matches any real user's PS number
            // and never appears in "My Tickets" or any user-facing booking list
            const phantom = {
                id: `ws_${Date.now()}`,
                shiftId, psNumber: 'PHANTOM',
                employeeName: 'Other User', seatNumber: seats.join(', '),
                boardingStopIndex: 0, dropStopIndex: 1,
                fareAmount: seats.length * 20, status: 'CONFIRMED',
                travelDate: date, bookedAt: new Date().toISOString()
            };
            bookings.push(phantom);
            this.setItem('utcl_bookings', bookings);
        }

        // Only act if the user is viewing this shift+date seat map
        if (!this.currentSeatRoom || this.currentSeatRoom !== `${shiftId}_${date}`) return;
        if (!seats || seats.length === 0) return;

        // Re-render the seat map so that previously held (red solid) seats instantly transition to occupied
        this.renderSeatMap();

        // Deselect any of our chosen seats that were just taken
        if (this.bookingData.seatNumbers) {
            const conflicts = this.bookingData.seatNumbers.filter(s => seats.includes(s));
            if (conflicts.length > 0) {
                this.bookingData.seatNumbers = this.bookingData.seatNumbers.filter(s => !seats.includes(s));
                this.bookingData.seatNumber = this.bookingData.seatNumbers.join(', ');
                this.updateSeatSelectionCounter();
                this.checkStep2Validity();
                this.showLiveUpdateBar(`⚠️ Seat(s) ${conflicts.join(', ')} just booked by someone else — please reselect.`, 6000);
            } else {
                const isSelf = bookedBy === this.bookingData.psNumber;
                if (!isSelf) {
                    this.showLiveUpdateBar(`🔴 Seat(s) ${seats.join(', ')} just taken by another user`, 4000);
                }
            }
        }
    }

    onSeatHeld(data) {
        const { shiftId, date, seatNumber, heldBy, expiresAt } = data;
        if (this.currentSeatRoom !== `${shiftId}_${date}`) return;

        if (!this.activeHolds) this.activeHolds = [];
        this.activeHolds = this.activeHolds.filter(h => h.seatNumber !== seatNumber);
        this.activeHolds.push({
            seatNumber,
            heldBy,
            expiresAt
        });

        // If held by me, verify it is in local selected seatNumbers
        if (heldBy === this.bookingData.psNumber) {
            if (!this.bookingData.seatNumbers) this.bookingData.seatNumbers = [];
            if (!this.bookingData.seatNumbers.includes(seatNumber)) {
                this.bookingData.seatNumbers.push(seatNumber);
                this.bookingData.seatNumber = this.bookingData.seatNumbers.join(', ');
                this.updateSeatSelectionCounter();
                this.checkStep2Validity();
            }
        } else {
            // Held by another user: remove from our selection if we had selected it locally (due to network delays)
            if (this.bookingData.seatNumbers && this.bookingData.seatNumbers.includes(seatNumber)) {
                this.bookingData.seatNumbers = this.bookingData.seatNumbers.filter(s => s !== seatNumber);
                this.bookingData.seatNumber = this.bookingData.seatNumbers.join(', ');
                this.updateSeatSelectionCounter();
                this.checkStep2Validity();
                this.showLiveUpdateBar(`⚠️ Seat ${seatNumber} is now held by another user.`, 5000);
            }
        }

        this.renderSeatMap();
    }

    onSeatReleased(data) {
        const { shiftId, date, seatNumber, expired } = data;
        if (this.currentSeatRoom !== `${shiftId}_${date}`) return;

        if (this.activeHolds) {
            this.activeHolds = this.activeHolds.filter(h => h.seatNumber !== seatNumber);
        }

        // If the hold was ours and expired, deselect and warn
        if (this.bookingData.seatNumbers && this.bookingData.seatNumbers.includes(seatNumber)) {
            if (expired) {
                this.bookingData.seatNumbers = this.bookingData.seatNumbers.filter(s => s !== seatNumber);
                this.bookingData.seatNumber = this.bookingData.seatNumbers.join(', ');
                this.updateSeatSelectionCounter();
                this.checkStep2Validity();
                this.showLiveUpdateBar(`⚠️ Your 3-minute hold on Seat ${seatNumber} has expired.`, 6000);
            }
        }

        this.renderSeatMap();
    }

    onCurrentHolds(data) {
        const { room, holds } = data;
        if (this.currentSeatRoom !== room) return;

        this.activeHolds = holds || [];

        // Prune any of our selections if they are now held by other users on server sync
        if (this.bookingData.seatNumbers) {
            let pruned = false;
            this.bookingData.seatNumbers = this.bookingData.seatNumbers.filter(s => {
                const hold = this.activeHolds.find(h => h.seatNumber === s);
                if (hold && hold.heldBy !== this.bookingData.psNumber) {
                    pruned = true;
                    return false;
                }
                return true;
            });
            if (pruned) {
                this.bookingData.seatNumber = this.bookingData.seatNumbers.join(', ');
                this.updateSeatSelectionCounter();
                this.checkStep2Validity();
                this.showLiveUpdateBar('⚠️ Some of your selected seats are now held by another user.', 5000);
            }
        }

        this.renderSeatMap();
    }

    /** Show a transient notification bar below the seat legend. */
    showLiveUpdateBar(message, durationMs = 4000) {
        const bar = document.getElementById('live-update-bar');
        const msg = document.getElementById('live-update-msg');
        if (!bar || !msg) return;
        msg.textContent = message;
        bar.classList.remove('hidden');
        clearTimeout(this._liveBarTimeout);
        this._liveBarTimeout = setTimeout(() => bar.classList.add('hidden'), durationMs);
    }

    /**
     * Fallback: poll /api/data every 15 s to refresh seat availability
     * if the WebSocket connection drops.
     */
    startSeatPolling() {
        this.stopSeatPolling();
        this._seatPollInterval = setInterval(async () => {
            if (!this.currentSeatRoom) return;
            try {
                const res = await fetch('/api/data');
                if (!res.ok) return;
                const serverData = await res.json();
                if (serverData.utcl_bookings) {
                    this.setItem('utcl_bookings', serverData.utcl_bookings);
                    this.renderSeatMap();  // re-draw with fresh server data
                }
            } catch (_) {}
        }, 15000);
    }

    stopSeatPolling() {
        if (this._seatPollInterval) {
            clearInterval(this._seatPollInterval);
            this._seatPollInterval = null;
        }
    }

    startAttendancePolling() {
        this.stopAttendancePolling();
        this.attendancePollInterval = setInterval(async () => {
            if (this.currentUser && this.currentUser.role === 'ADMIN' && this.currentAdminTab === 'attendance') {
                const searchInput = document.getElementById('driver-history-ps-number');
                if (searchInput && searchInput.value.trim()) {
                    this.loadDriverAttendanceHistory(1);
                } else {
                    this.loadPendingAttendances();
                }
            } else {
                this.stopAttendancePolling();
            }
        }, 5000);
    }

    stopAttendancePolling() {
        if (this.attendancePollInterval) {
            clearInterval(this.attendancePollInterval);
            this.attendancePollInterval = null;
        }
    }

    // ── FEATURE 2: QR Code on Ticket (Compact Offline Text) ──────────────────
    async generateTicketQR(ticket, canvasId) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        if (typeof QRCode === 'undefined') {
            try {
                await this.loadScript('js/qrcode.min.js');
            } catch(e) {
                console.error("Failed to load QRCode script:", e);
                return;
            }
        }

        // Format shift label
        const sc = ticket.shiftCode || '';
        const busNum = sc.replace(/[^0-9]/g, '');
        const dir = sc.toUpperCase().endsWith('R') ? 'Return' : 'Forward';
        const shiftLabel = busNum ? `Bus ${busNum} - ${dir}` : sc;

        // Format date nicely
        let dateLabel = ticket.travelDate || '';
        try {
            const d = new Date(ticket.travelDate);
            dateLabel = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
        } catch(e) {}

        // ── Clean, human-readable text — looks good in any phone camera popup ──
        // Works 100% offline, no server/WiFi/URL needed.
        const qrData = [
            '=== UTCL EMPLOYEE TICKET ===',
            `Ticket No : ${ticket.ticketNumber || ''}`,
            `Passenger : ${ticket.employeeName || ''}`,
            `PS Number : ${ticket.psNumber || ''}`,
            `Shift/Bus : ${shiftLabel}`,
            `Seat No   : ${ticket.seatNumber || ''}`,
            `Departure : ${ticket.departureTime || ''}`,
            `Date      : ${dateLabel}`,
            `Boarding  : ${ticket.boardingStop || ''}`,
            `Drop-off  : ${ticket.dropStop || ''}`,
            `Fare Paid : Rs.${ticket.fare || 0}`,
            '============================'
        ].join('\n');

        QRCode.toCanvas(canvas, qrData, {
            width: 140,
            margin: 1,
            errorCorrectionLevel: 'M',
            color: { dark: '#1E293B', light: '#FFFFFF' }
        }, err => { if (err) console.error('QR generation failed:', err); });
    }

    // HTML-escape helper
    _esc(str) {
        return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    // ── FEATURE 3: Export Booking History to Excel ───────────────────────────

    exportHistoryToExcel() {
        const tbody = document.getElementById('history-table-body');
        if (!tbody || tbody.querySelectorAll('tr').length === 0 || tbody.innerHTML.includes('Please enter') || tbody.innerHTML.includes('No confirmed bookings found')) {
            alert('No booking data to export. Please search a valid PS number first.');
            return;
        }
        const psNumber = (document.getElementById('history-ps-number').value || 'ALL').trim();
        
        fetch(`/api/bookings/export?psNumber=${encodeURIComponent(psNumber)}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Server returned an error during Excel generation');
                }
                return response.blob(); // Safely read the data stream purely as a 'blob' object
            })
            .then(blob => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = 'booking_history.xlsx'; // Set clean filename trigger
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();
            })
            .catch(err => {
                console.error('Export Excel failed:', err);
                alert('Export failed: ' + err.message);
            });
    }

    // User Management
    loadAdminUsers() {
        const tbody = document.getElementById('admin-users-table-body');
        tbody.innerHTML = '';
        const users = this.getItems('utcl_users');

        const searchInput = document.getElementById('admin-users-search');
        const query = searchInput ? searchInput.value.trim().toLowerCase() : '';

        const filteredUsers = users.filter(u => {
            if (!query) return true;
            return u.psNumber && u.psNumber.toLowerCase().includes(query);
        });

        if (filteredUsers.length === 0) {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td colspan="7" class="text-center text-muted py-4">No users found matching "${query}"</td>`;
            tbody.appendChild(tr);
            return;
        }

        filteredUsers.forEach(u => {
            const tr = document.createElement('tr');
            
            // Build action buttons
            let actionsHtml = '';
            const isSuperAdminUser = (u.role === 'ADMIN' && (!u.plant || u.plant === ''));
            if (u.isActive && u.id !== this.currentUser.id && !isSuperAdminUser) {
                actionsHtml += `<button class="btn btn-danger btn-xs mr-2" onclick="app.deactivateUser('${u.id}')">Deactivate</button>`;
                actionsHtml += `<button class="btn btn-warning btn-xs" onclick="app.showAdminResetPasswordModal('${u.name}', '${u.psNumber}')">Reset Password</button>`;
            } else {
                actionsHtml = `<span class="text-muted text-xs">-</span>`;
            }

            tr.innerHTML = `
                <td><strong>${u.name}</strong></td>
                <td>${u.psNumber}</td>
                <td class="email-column">${u.email || '<span class="text-muted text-xs">No email</span>'}</td>
                <td><span class="badge ${u.role === 'ADMIN' ? 'badge-danger' : (u.role === 'DRIVER' ? 'badge-warning' : 'badge-info')}">${u.role}</span></td>
                <td><span class="badge badge-secondary">${u.plant || 'Awalpur'}</span></td>
                <td><span class="badge ${u.isActive ? 'badge-success' : 'badge-danger'}">${u.isActive ? 'Active' : 'Inactive'}</span></td>
                <td>${actionsHtml}</td>
            `;
            tbody.appendChild(tr);
        });
        addMobileTableLabels('#admin-users-table-body');
    }

    showAdminResetPasswordModal(name, psNumber) {
        document.getElementById('admin-reset-user-name').textContent = name;
        document.getElementById('admin-reset-user-ps').textContent = psNumber;
        document.getElementById('admin-reset-user-target-ps').value = psNumber;
        
        document.getElementById('admin-reset-new-password').value = '';
        document.getElementById('admin-reset-confirm-password').value = '';
        
        const errAlert = document.getElementById('admin-reset-error');
        if (errAlert) errAlert.classList.add('hidden');
        
        this.openModal('admin-reset-password-modal');
    }

    async submitAdminResetPassword() {
        const targetPs = document.getElementById('admin-reset-user-target-ps').value;
        const newPassword = document.getElementById('admin-reset-new-password').value;
        const confirmPassword = document.getElementById('admin-reset-confirm-password').value;
        const errAlert = document.getElementById('admin-reset-error');
        if (errAlert) errAlert.classList.add('hidden');
        
        if (!newPassword || !confirmPassword) {
            errAlert.textContent = "All fields are required.";
            errAlert.classList.remove('hidden');
            return;
        }
        
        if (newPassword !== confirmPassword) {
            errAlert.textContent = "New password and confirmation do not match.";
            errAlert.classList.remove('hidden');
            return;
        }
        
        try {
            const res = await fetch('/api/admin/reset-user-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    adminPsNumber: this.currentUser.psNumber,
                    targetPsNumber: targetPs,
                    newPassword: newPassword
                })
            });
            
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || "Failed to reset password.");
            
            if (data.status === 'success') {
                // Update local storage representation
                const users = this.getItems('utcl_users');
                const user = users.find(u => u.psNumber.toUpperCase() === targetPs.toUpperCase());
                if (user) {
                    user.password = newPassword;
                    this.setItem('utcl_users', users);
                }
                
                this.closeModal('admin-reset-password-modal');
                this.showLiveToast("User password has been successfully reset.", "Success");
            } else {
                errAlert.textContent = data.message || "Failed to reset password.";
                errAlert.classList.remove('hidden');
            }
        } catch (err) {
            errAlert.textContent = err.message;
            errAlert.classList.remove('hidden');
        }
    }

    showCreateUserModal() {
        document.getElementById('new-user-name').value = '';
        document.getElementById('new-user-ps').value = '';
        document.getElementById('new-user-email').value = '';
        const errorAlert = document.getElementById('create-user-error');
        if (errorAlert) errorAlert.classList.add('hidden');

        const plantSelect = document.getElementById('new-user-plant');
        const roleSelect = document.getElementById('new-user-role');

        const adminPlant = this.currentUser.plant;
        if (adminPlant) {
            plantSelect.innerHTML = `<option value="${adminPlant}" selected>${adminPlant}</option>`;
            plantSelect.value = adminPlant;
            setSelectDisabled(plantSelect, true);

            roleSelect.innerHTML = `
                <option value="EMPLOYEE" selected>Employee</option>
                <option value="DRIVER">Driver</option>
            `;
            if (roleSelect.rebuildCustomOptions) {
                roleSelect.rebuildCustomOptions();
            }
        } else {
            plantSelect.innerHTML = `
                <option value="Awalpur" selected>Awalpur</option>
                <option value="Manikgarh">Manikgarh</option>
            `;
            setSelectDisabled(plantSelect, false);

            roleSelect.innerHTML = `
                <option value="EMPLOYEE" selected>Employee</option>
                <option value="DRIVER">Driver</option>
                <option value="ADMIN">Administrator</option>
            `;
            if (roleSelect.rebuildCustomOptions) {
                roleSelect.rebuildCustomOptions();
            }
        }

        if (plantSelect.rebuildCustomOptions) {
            plantSelect.rebuildCustomOptions();
        }

        this.openModal('create-user-modal');
    }

    handleCreateUser(e) {
        e.preventDefault();
        const name = document.getElementById('new-user-name').value.trim();
        const psNumber = document.getElementById('new-user-ps').value.trim().toUpperCase();
        const role = document.getElementById('new-user-role').value;
        const plant = document.getElementById('new-user-plant').value;
        const email = document.getElementById('new-user-email').value.trim() || null;
        const errorAlert = document.getElementById('create-user-error');
        errorAlert.classList.add('hidden');

        const users = this.getItems('utcl_users');

        // Check PS Number length limit (Max 10 characters/digits)
        if (psNumber.length > 10) {
            errorAlert.textContent = "Error: PS Number must be up to 10 characters!";
            errorAlert.classList.remove('hidden');
            return;
        }

        // Check duplicate PS Number (Requirement 7.3)
        if (users.some(u => u.psNumber === psNumber)) {
            errorAlert.textContent = "Error: PS Number is already registered!";
            errorAlert.classList.remove('hidden');
            return;
        }

        const newUser = {
            id: `u_${Date.now()}`,
            name: name,
            psNumber: psNumber,
            role: role,
            plant: plant,
            isActive: true,
            email: email
        };

        if (role === 'EMPLOYEE' || role === 'ADMIN') {
            newUser.password = document.getElementById('new-user-password').value;
        }

        users.push(newUser);

        const submitBtn = e.target.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Creating...';
        }

        this.setItem('utcl_users', users).then(async response => {
            if (response && response.ok) {
                const data = await response.json();
                if (data.tempPasswords && data.tempPasswords[psNumber]) {
                    const tempPwd = data.tempPasswords[psNumber];
                    alert(`User Created Successfully!\n\nDriver PS Number: ${psNumber}\nTemporary Password: ${tempPwd}\n\nPlease copy this password and share it with the driver.`);
                } else {
                    this.showLiveToast("User created successfully.", "Success");
                }
            } else {
                this.showLiveToast("User created locally, but database sync failed.", "Warning");
            }
            this.loadAdminUsers();
        }).catch(err => {
            console.error("Error creating user:", err);
            this.showLiveToast("Error synchronizing new user.", "Danger");
            this.loadAdminUsers();
        }).finally(() => {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Create User';
            }
            // Reset inputs and close
            document.getElementById('create-user-form').reset();
            this.closeModal('create-user-modal');
        });
    }

    toggleUserFormFields() {
        const role = document.getElementById('new-user-role').value;
        const fields = document.getElementById('user-credentials-fields');
        const passwordInput = document.getElementById('new-user-password');
        const emailField = document.getElementById('user-email-field');

        if (role === 'DRIVER') {
            fields.classList.add('hidden');
            passwordInput.removeAttribute('required');
        } else {
            fields.classList.remove('hidden');
            passwordInput.setAttribute('required', 'required');
        }
        
        // Email address field is visible for all designations so drivers can register Gmail addresses for self-service resets
        if (emailField) {
            emailField.classList.remove('hidden');
        }
    }

    deactivateUser(userId) {
        if (!confirm("Are you sure you want to deactivate this user account? Any active bookings will be cancelled.")) return;

        const users = this.getItems('utcl_users');
        const user = users.find(u => u.id === userId);

        if (user) {
            user.isActive = false;
            this.setItem('utcl_users', users);

            // If deactivated user is an Employee, cancel active bookings (Requirement 7.4)
            if (user.role === 'EMPLOYEE') {
                const bookings = this.getItems('utcl_bookings');
                const todayStr = this.getTodayString();
                const notifications = this.getItems('utcl_notifications');
                let hasNotification = false;

                bookings.forEach(b => {
                    if (b.psNumber === user.psNumber && b.travelDate >= todayStr && b.status === 'CONFIRMED') {
                        b.status = 'CANCELLED';
                        notifications.push({
                            id: `nt_${Date.now()}_${Math.floor(Math.random() * 1000)}_${Math.floor(Math.random() * 1000)}`,
                            recipientUserId: user.id,
                            message: `Your active booking for ${b.travelDate} was cancelled because your user account was deactivated.`,
                            isRead: false,
                            createdAt: new Date().toISOString()
                        });
                        hasNotification = true;
                    }
                });
                if (hasNotification) {
                    this.setItem('utcl_notifications', notifications);
                    this.updateNotificationsUI();
                }
                this.setItem('utcl_bookings', bookings);
            }

            // If Driver, unassign from active shifts (Requirement 7.5)
            if (user.role === 'DRIVER') {
                const driverShifts = this.getItems('utcl_driver_shifts');
                const todayStr = this.getTodayString();
                const updated = driverShifts.filter(ds => !(ds.driverId === userId && ds.date >= todayStr));
                this.setItem('utcl_driver_shifts', updated);
            }

            this.loadAdminUsers();
        }
    }

    // Bus Management
    loadAdminBuses() {
        const tbody = document.getElementById('admin-buses-table-body');
        tbody.innerHTML = '';
        const buses = this.getItems('utcl_buses');

        buses.forEach(b => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${b.identifier}</strong></td>
                <td><span class="badge ${b.isActive ? 'badge-success' : 'badge-danger'}">${b.isActive ? 'Active' : 'Inactive'}</span></td>
                <td>
                    ${b.isActive ?
                    `<button class="btn btn-danger btn-xs" onclick="app.deactivateBus('${b.id}')">Deactivate</button>` :
                    `<button class="btn btn-success btn-xs" onclick="app.activateBus('${b.id}')">Activate</button>`
                }
                </td>
            `;
            tbody.appendChild(tr);
        });
        addMobileTableLabels('#admin-buses-table-body');

        // Load Driver Assignment Select dropdowns
        const driverSelect = document.getElementById('assign-driver-select');
        const shiftSelect = document.getElementById('assign-shift-select');

        driverSelect.innerHTML = '<option value="">-- Choose Driver --</option>';
        this.getItems('utcl_users').filter(u => u.role === 'DRIVER' && u.isActive).forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = `${d.name} (${d.psNumber})`;
            driverSelect.appendChild(opt);
        });

        shiftSelect.innerHTML = '<option value="">-- Choose Shift --</option>';
        this.getItems('utcl_shifts').filter(s => s.isActive).forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = `${this.getShiftLabel(s.id)} (${s.departureTime})`;
            shiftSelect.appendChild(opt);
        });

        const assignDateInput = document.getElementById('assign-date');
        assignDateInput.value = this.getTodayString();
        assignDateInput.min = this.getTodayString();
        
        // Remove existing listener if any, then add fresh listener to update shift dropdown disabled states dynamically
        assignDateInput.removeEventListener('change', this._onAssignDateChange);
        this._onAssignDateChange = () => this.updateShiftSelectDisabledStates();
        assignDateInput.addEventListener('change', this._onAssignDateChange);
        
        this.updateShiftSelectDisabledStates();
    }

    updateShiftSelectDisabledStates() {
        const dateInput = document.getElementById('assign-date');
        if (!dateInput) return;
        const date = dateInput.value;
        const shiftSelect = document.getElementById('assign-shift-select');
        if (!shiftSelect) return;
        
        const shifts = this.getItems('utcl_shifts');
        const now = new Date();
        
        Array.from(shiftSelect.options).forEach(opt => {
            if (!opt.value) return; // skip -- Choose Shift --
            const s = shifts.find(x => x.id === opt.value);
            if (!s) return;
            
            let isDisabled = false;
            const timeParts = s.departureTime.split(' ');
            if (timeParts.length === 2) {
                const [time, modifier] = timeParts;
                const [hoursStr, minutesStr] = time.split(':');
                let hours = parseInt(hoursStr, 10);
                const minutes = parseInt(minutesStr, 10);
                if (modifier === 'PM' && hours < 12) {
                    hours += 12;
                }
                if (modifier === 'AM' && hours === 12) {
                    hours = 0;
                }
                if (date) {
                    const [year, month, day] = date.split('-').map(x => parseInt(x, 10));
                    if (!isNaN(year) && !isNaN(month) && !isNaN(day)) {
                        const departureDateTime = new Date(year, month - 1, day, hours, minutes);
                        if (departureDateTime < now) {
                            isDisabled = true;
                        }
                    }
                }
            }
            
            opt.textContent = `${this.getShiftLabel(s.id)} (${s.departureTime})`;
            if (isDisabled) {
                opt.disabled = true;
                // If the currently selected option is now disabled, reset select value
                if (shiftSelect.value === opt.value) {
                    shiftSelect.value = "";
                }
            } else {
                opt.disabled = false;
            }
        });

        // Sync with custom select if initialized
        if (typeof shiftSelect.rebuildCustomOptions === 'function') {
            shiftSelect.rebuildCustomOptions();
        }
    }

    handleAddBus(e) {
        e.preventDefault();
        const identifier = document.getElementById('new-bus-id').value.trim();
        const errorAlert = document.getElementById('add-bus-error');
        errorAlert.classList.add('hidden');

        const buses = this.getItems('utcl_buses');

        // Check duplicate Identifier (Requirement 8.2)
        if (buses.some(b => b.identifier.toLowerCase() === identifier.toLowerCase())) {
            errorAlert.textContent = "Error: Bus identifier already exists!";
            errorAlert.classList.remove('hidden');
            return;
        }

        const newBus = {
            id: `b_${Date.now()}`,
            identifier: identifier,
            isActive: true
        };

        buses.push(newBus);
        this.setItem('utcl_buses', buses);

        // Initialize tracking entry
        const tracking = this.getItems('utcl_tracking');
        tracking.push({
            busId: newBus.id,
            operationalStatus: 'IDLE',
            currentShiftId: null,
            currentStopIndex: null,
            lastUpdated: new Date().toISOString()
        });
        this.setItem('utcl_tracking', tracking);

        document.getElementById('add-bus-form').reset();
        this.closeModal('add-bus-modal');
        this.loadAdminBuses();
    }

    activateBus(busId) {
        const buses = this.getItems('utcl_buses');
        const bus = buses.find(b => b.id === busId);
        if (bus) {
            bus.isActive = true;
            this.setItem('utcl_buses', buses);
            this.loadAdminBuses();
        }
    }

    deactivateBus(busId) {
        if (!confirm("Are you sure you want to deactivate this bus? All future bookings for shifts running on this bus will be cancelled and passengers will be notified.")) return;

        const buses = this.getItems('utcl_buses');
        const bus = buses.find(b => b.id === busId);

        if (bus) {
            bus.isActive = false;
            this.setItem('utcl_buses', buses);

            // Cancel future bookings running on shifts associated with this bus (Requirement 8.3/8.4)
            const shifts = this.getItems('utcl_shifts').filter(s => s.busId === busId);
            const shiftIds = shifts.map(s => s.id);
            const bookings = this.getItems('utcl_bookings');
            const todayStr = this.getTodayString();
            const notifications = this.getItems('utcl_notifications');
            const users = this.getItems('utcl_users');
            let hasNotification = false;

            bookings.forEach(b => {
                if (shiftIds.includes(b.shiftId) && b.travelDate >= todayStr && b.status === 'CONFIRMED') {
                    b.status = 'CANCELLED';

                    // In-system notification to each affected Employee (Requirement 8.4)
                    const recipient = users.find(u => u.psNumber === b.psNumber);
                    if (recipient) {
                        notifications.push({
                            id: `nt_${Date.now()}_${Math.floor(Math.random() * 1000)}_${Math.floor(Math.random() * 1000)}`,
                            recipientUserId: recipient.id,
                            message: `Cancellation Notification: Your booking on shift ${b.shiftId} for ${b.travelDate} has been cancelled because Bus ${bus.identifier} was deactivated.`,
                            isRead: false,
                            createdAt: new Date().toISOString()
                        });
                        hasNotification = true;
                    }
                }
            });
            if (hasNotification) {
                this.setItem('utcl_notifications', notifications);
                this.updateNotificationsUI();
            }
            this.setItem('utcl_bookings', bookings);
            this.loadAdminBuses();
        }
    }

    handleDriverAssignment(e) {
        e.preventDefault();
        const driverId = document.getElementById('assign-driver-select').value;
        const shiftId = document.getElementById('assign-shift-select').value;
        const date = document.getElementById('assign-date').value;

        if (!driverId || !shiftId || !date) {
            alert("Please select a driver, a shift, and a date.");
            return;
        }

        // Validate past shift assignment
        const shifts = this.getItems('utcl_shifts');
        const shift = shifts.find(s => s.id === shiftId);
        if (shift) {
            const timeParts = shift.departureTime.split(' ');
            if (timeParts.length === 2) {
                const [time, modifier] = timeParts;
                const [hoursStr, minutesStr] = time.split(':');
                let hours = parseInt(hoursStr, 10);
                const minutes = parseInt(minutesStr, 10);
                if (modifier === 'PM' && hours < 12) {
                    hours += 12;
                }
                if (modifier === 'AM' && hours === 12) {
                    hours = 0;
                }
                if (date) {
                    const [year, month, day] = date.split('-').map(x => parseInt(x, 10));
                    if (!isNaN(year) && !isNaN(month) && !isNaN(day)) {
                        const departureDateTime = new Date(year, month - 1, day, hours, minutes);
                        const now = new Date();
                        if (departureDateTime < now) {
                            alert("Error: Cannot assign a driver to a past shift that has already departed.");
                            return;
                        }
                    }
                }
            }
        }

        // Check driver conflict warning (Requirement 8.6)
        // If driver is already assigned to a shift that shares any time within the same calendar day
        const assignments = this.getItems('utcl_driver_shifts');
        const conflict = assignments.find(a => a.driverId === driverId && a.date === date);

        if (conflict) {
            // Save state in object temporary storage so we can override
            this.pendingAssignment = { driverId, shiftId, date };
            this.openModal('driver-conflict-modal');
        } else {
            this.saveDriverAssignment(driverId, shiftId, date);
        }
    }

    confirmDriverAssignment() {
        if (this.pendingAssignment) {
            const { driverId, shiftId, date } = this.pendingAssignment;
            this.saveDriverAssignment(driverId, shiftId, date);
            this.pendingAssignment = null;
            this.closeModal('driver-conflict-modal');
        }
    }

    saveDriverAssignment(driverId, shiftId, date) {
        const assignments = this.getItems('utcl_driver_shifts');
        const newAssign = {
            id: `da_${Date.now()}`,
            driverId,
            shiftId,
            date
        };
        assignments.push(newAssign);
        this.setItem('utcl_driver_shifts', assignments);

        alert("Driver assigned successfully.");
        document.getElementById('driver-assign-form').reset();
        document.getElementById('assign-date').value = this.getTodayString();
    }

    loadAdminShiftsList() {
        const select = document.getElementById('edit-shift-select');
        select.innerHTML = '<option value="">-- Choose Shift --</option>';

        const cancelSelect = document.getElementById('cancel-shift-select');
        if (cancelSelect) {
            cancelSelect.innerHTML = '<option value="">-- Choose Shift --</option>';
        }

        const shifts = this.getItems('utcl_shifts');
        shifts.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = `${this.getShiftLabel(s.id)} (${s.departureTime})`;
            select.appendChild(opt);

            if (cancelSelect) {
                const cancelOpt = opt.cloneNode(true);
                cancelSelect.appendChild(cancelOpt);
            }
        });

        document.getElementById('shift-edit-form').classList.add('hidden');

        const cancelDateInput = document.getElementById('cancel-shift-date');
        if (cancelDateInput && !cancelDateInput.value) {
            cancelDateInput.value = this.getTodayString();
        }

        this.updateCancelShiftBookingCount();
    }


    loadShiftEditForm() {
        const shiftId = document.getElementById('edit-shift-select').value;
        const form = document.getElementById('shift-edit-form');
        const container = document.getElementById('shift-stops-edit-list');

        if (!shiftId) {
            form.classList.add('hidden');
            return;
        }

        this.activeEditShiftId = shiftId;
        const shift = this.getItems('utcl_shifts').find(s => s.id === shiftId);

        container.innerHTML = '';
        shift.stops.forEach((stop, i) => {
            const div = document.createElement('div');
            div.className = "form-group";
            div.innerHTML = `
                <label>${i + 1}. Stop: ${stop.name}</label>
                <input type="text" class="stop-time-input" data-index="${stop.index}" value="${stop.arrival}" placeholder="e.g. 05:40 AM" required>
            `;
            container.appendChild(div);
        });

        form.classList.remove('hidden');
    }

    saveShiftModification(e) {
        e.preventDefault();
        const shifts = this.getItems('utcl_shifts');
        const shift = shifts.find(s => s.id === this.activeEditShiftId);

        const inputs = document.querySelectorAll('.stop-time-input');

        // Update arrival times
        inputs.forEach(input => {
            const idx = parseInt(input.dataset.index);
            shift.stops[idx].arrival = input.value.trim();
        });

        // Set departure time equal to arrival time of first stop
        shift.departureTime = shift.stops[0].arrival;

        this.setItem('utcl_shifts', shifts);

        // Notify passengers with existing bookings for this shift (Requirement 8.8)
        const bookings = this.getItems('utcl_bookings');
        const todayStr = this.getTodayString();
        const users = this.getItems('utcl_users');
        const notifications = this.getItems('utcl_notifications');
        let hasNotification = false;
        const notifiedUserIds = new Set();

        bookings.forEach(b => {
            if (b.shiftId === shift.id && b.travelDate >= todayStr && b.status === 'CONFIRMED') {
                const recipient = users.find(u => u.psNumber === b.psNumber);
                if (recipient && !notifiedUserIds.has(recipient.id)) {
                    notifications.push({
                        id: `nt_${Date.now()}_${Math.floor(Math.random() * 1000)}_${Math.floor(Math.random() * 1000)}`,
                        recipientUserId: recipient.id,
                        message: `Schedule Update: The schedule for your booked trip on shift ${this.getShiftLabel(shift.id)} has been updated. Departure is now ${shift.departureTime}.`,
                        isRead: false,
                        createdAt: new Date().toISOString()
                    });
                    notifiedUserIds.add(recipient.id);
                    hasNotification = true;
                }
            }
        });

        if (hasNotification) {
            this.setItem('utcl_notifications', notifications);
            this.updateNotificationsUI();
        }

        // Also update any future tickets for this shift with the new departure time!
        const tickets = this.getItems('utcl_tickets');
        let hasTicketUpdate = false;
        tickets.forEach(tk => {
            if (tk.shiftCode === shift.id && tk.travelDate >= todayStr) {
                tk.departureTime = shift.departureTime;
                hasTicketUpdate = true;
            }
        });
        if (hasTicketUpdate) {
            this.setItem('utcl_tickets', tickets);
        }

        alert("Shift schedule modified successfully. Affected passengers have been notified.");
        this.loadAdminShiftsList();
    }

    async updateCancelShiftBookingCount() {
        const select = document.getElementById('cancel-shift-select');
        const dateInput = document.getElementById('cancel-shift-date');
        const container = document.getElementById('cancel-shift-count-container');
        const badge = document.getElementById('cancel-shift-affected-badge');

        if (!select || !dateInput) return;

        const shiftId = select.value;
        const travelDate = dateInput.value;

        if (!shiftId || !travelDate) {
            if (container) container.classList.add('hidden');
            return;
        }

        try {
            const res = await fetch(`/api/admin/shifts/booking-count?shiftId=${encodeURIComponent(shiftId)}&date=${encodeURIComponent(travelDate)}`);
            const data = await res.json();
            if (res.ok && data.status === 'ok') {
                if (badge) {
                    badge.textContent = data.count;
                    badge.className = data.count === 0 ? "text-xl font-bold text-slate-500" : "text-xl font-bold text-blue-600";
                }
                const textSpan = document.getElementById('cancel-shift-affected-text');
                if (textSpan) {
                    textSpan.textContent = data.count === 0 
                        ? "affected passengers." 
                        : "passengers with affected bookings will be unassigned and notified.";
                }
                if (container) {
                    container.classList.remove('hidden');
                }
            } else {
                console.error("Error fetching booking count:", data.message);
            }
        } catch (err) {
            console.error("Error fetching booking count:", err);
        }
    }

    async handleCancelShiftForDay(e) {
        e.preventDefault();
        const select = document.getElementById('cancel-shift-select');
        const dateInput = document.getElementById('cancel-shift-date');
        const reasonInput = document.getElementById('cancel-shift-reason');

        if (!select || !dateInput || !reasonInput) return;

        const shiftId = select.value;
        const travelDate = dateInput.value;
        const reason = reasonInput.value.trim();

        if (!shiftId || !travelDate) {
            alert("Please select a shift and date.");
            return;
        }

        let count = 0;
        try {
            const res = await fetch(`/api/admin/shifts/booking-count?shiftId=${encodeURIComponent(shiftId)}&date=${encodeURIComponent(travelDate)}`);
            const data = await res.json();
            if (res.ok && data.status === 'ok') {
                count = data.count;
            }
        } catch (err) {
            console.error("Failed to precheck booking count:", err);
        }

        const confirmMsg = `Are you sure you want to cancel shift ${shiftId} on ${travelDate}?\nThis will cancel ${count} bookings.`;
        if (!confirm(confirmMsg)) {
            return;
        }

        try {
            const res = await fetch('/api/admin/shifts/cancel-for-day', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    shiftId,
                    date: travelDate,
                    reason
                })
            });
            const data = await res.json();
            if (res.ok && (data.status === 'ok' || data.status === 'success')) {
                alert("Shift cancelled successfully. Affected passengers have been notified.");
                document.getElementById('admin-cancel-shift-form').reset();
                const container = document.getElementById('cancel-shift-count-container');
                if (container) container.classList.add('hidden');
                
                await this.syncStateSilent();
                this.loadAdminShiftsList();
            } else {
                alert("Error cancelling shift: " + (data.message || "Unknown error"));
            }
        } catch (err) {
            console.error("Error cancelling shift:", err);
            alert("Network error: failed to cancel shift.");
        }
    }


    // Maintenance logs
    loadAdminMaintenance() {
        const tbody = document.getElementById('admin-maintenance-table-body');
        tbody.innerHTML = '';

        const maintenance = this.getItems('utcl_maintenance');
        const buses = this.getItems('utcl_buses');
        const todayStr = this.getTodayString();

        maintenance.forEach(m => {
            const bus = buses.find(b => b.id === m.busId);
            const tr = document.createElement('tr');

            // Auto update overdue status if scheduled_date passes (Requirement 9.4)
            let status = m.status;
            if (m.scheduledDate < todayStr && m.status === 'SCHEDULED') {
                status = 'OVERDUE';
                // Mutate local storage
                m.status = 'OVERDUE';
            }

            const statusClass = status === 'COMPLETED'           ? 'badge-success'
                              : status === 'PENDING_CONFIRMATION' ? 'badge-warning'
                              : status === 'OVERDUE'              ? 'badge-danger'
                              : 'badge-info';

            const statusLabel = status === 'PENDING_CONFIRMATION' ? 'Pending Confirm' : status;

            let actionCell = '';
            if (status === 'COMPLETED') {
                actionCell = `<span class="badge-service-done">SERVICE DONE</span>`;
            } else if (status === 'PENDING_CONFIRMATION') {
                actionCell = `
                    <button class="btn btn-warning btn-xs" onclick="app.completeMaintenance('${m.id}')">✔ Confirm Service</button>
                `;
            } else {
                actionCell = `<button class="btn btn-success btn-xs" onclick="app.completeMaintenance('${m.id}')">Mark Complete</button>`;
            }

            tr.innerHTML = `
                <td><strong>${bus ? bus.identifier : 'Unknown'}</strong></td>
                <td>${m.scheduledDate}</td>
                <td>${m.description}</td>
                <td><span class="badge ${statusClass}">${statusLabel}</span></td>
                <td>${m.actualCompletionDate || '-'}</td>
                <td>${actionCell}</td>
            `;
            tbody.appendChild(tr);
        });
        addMobileTableLabels('#admin-maintenance-table-body');

        // Set up create modal dropdown
        const busSelect = document.getElementById('maint-bus-id');
        busSelect.innerHTML = '';
        buses.filter(b => b.isActive).forEach(b => {
            const opt = document.createElement('option');
            opt.value = b.id;
            opt.textContent = b.identifier;
            busSelect.appendChild(opt);
        });

        document.getElementById('maint-date').value = this.getTodayString();
        document.getElementById('maint-date').min = this.getTodayString();
    }

    handleCreateMaintenance(e) {
        e.preventDefault();
        const busId = document.getElementById('maint-bus-id').value;
        const date = document.getElementById('maint-date').value;
        const desc = document.getElementById('maint-desc').value.trim();
        const conflictAlert = document.getElementById('maintenance-conflict-alert');

        // Check if conflict date falls on the same date as an Active Shift for the same bus (Requirement 9.3)
        // Active shift means there exists a shift associated with this bus.
        const shifts = this.getItems('utcl_shifts').filter(s => s.busId === busId && s.isActive);

        // Check if shift matches this bus (since S1F, S2F etc have fixed bus assignments)
        const hasShiftOnDate = (shifts.length > 0);

        // If we haven't overridden yet and there's a shift, show warning
        if (hasShiftOnDate && conflictAlert.classList.contains('hidden')) {
            conflictAlert.classList.remove('hidden');
            return;
        }

        const maintenanceList = this.getItems('utcl_maintenance');
        const newMaint = {
            id: `m_${Date.now()}`,
            busId,
            scheduledDate: date,
            description: desc,
            status: 'SCHEDULED',
            actualCompletionDate: null
        };

        maintenanceList.push(newMaint);
        this.setItem('utcl_maintenance', maintenanceList);

        // Reset
        document.getElementById('create-maintenance-form').reset();
        conflictAlert.classList.add('hidden');
        this.closeModal('create-maintenance-modal');
        this.loadAdminMaintenance();
    }

    completeMaintenance(id) {
        const list = this.getItems('utcl_maintenance');
        const item = list.find(m => m.id === id);

        if (item) {
            item.status = 'COMPLETED';
            item.actualCompletionDate = this.getTodayString(); // Requirement 9.5
            this.setItem('utcl_maintenance', list);
            this.loadAdminMaintenance();
        }
    }

    /** Driver calls this to flag service as done — sets status to PENDING_CONFIRMATION for admin approval */
    async requestServiceDone(id) {
        if (!confirm('Mark this service as completed and send a confirmation request to the admin?')) return;

        const list = this.getItems('utcl_maintenance');
        const item = list.find(m => m.id === id);

        if (!item) return;

        const originalStatus = item.status;
        item.status = 'PENDING_CONFIRMATION';

        // Update local cache immediately so the UI is responsive
        localStorage.setItem('utcl_maintenance', JSON.stringify(list));
        if (typeof this.renderDriverDashboard === 'function') this.renderDriverDashboard();

        try {
            const response = await this.setItem('utcl_maintenance', list);

            if (!response || !response.ok) {
                // Server rejected the request — revert local state
                item.status = originalStatus;
                localStorage.setItem('utcl_maintenance', JSON.stringify(list));
                if (typeof this.renderDriverDashboard === 'function') this.renderDriverDashboard();
                this.showLiveToast('Request failed. Please try again or contact the admin.', 'Request Failed');
                return;
            }

            // Re-fetch from DB to ensure local state exactly matches server
            await this.syncStateSilent();
            this.showLiveToast('Your service completion request has been sent to the admin for confirmation.', 'Request Sent');
        } catch (err) {
            // Network error — revert
            item.status = originalStatus;
            localStorage.setItem('utcl_maintenance', JSON.stringify(list));
            if (typeof this.renderDriverDashboard === 'function') this.renderDriverDashboard();
            this.showLiveToast('Network error. Check your connection and try again.', 'Connection Error');
        }
    }

    // Revenue Analytics Dashboard
    initRevenueAnalytics() {
        // Set default filter to current calendar month (Requirement 10.1)
        const now = new Date();
        const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        const formatDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

        document.getElementById('rev-date-from').value = formatDate(firstDay);
        document.getElementById('rev-date-to').value = formatDate(lastDay);

        this.renderRevenueData(formatDate(firstDay), formatDate(lastDay));
    }

    filterRevenue(e) {
        e.preventDefault();
        const from = document.getElementById('rev-date-from').value;
        const to = document.getElementById('rev-date-to').value;
        const errorAlert = document.getElementById('revenue-date-error');
        errorAlert.classList.add('hidden');

        // Requirement 10.3: Start date is after end date
        if (from > to) {
            errorAlert.classList.remove('hidden');
            return;
        }

        this.renderRevenueData(from, to);
    }

    renderRevenueData(from, to) {
        const bookings = this.getItems('utcl_bookings').filter(b =>
            b.travelDate >= from &&
            b.travelDate <= to &&
            b.status === 'CONFIRMED'
        );

        const totalBookings = bookings.length;
        // Sum actual fareAmount from bookings
        const totalRevenue = bookings.reduce((sum, b) => sum + (b.fareAmount || 20), 0);

        document.getElementById('rev-total-bookings').textContent = totalBookings;
        document.getElementById('rev-total-revenue').textContent = `₹${totalRevenue}`;

        const tbody = document.getElementById('revenue-table-body');
        tbody.innerHTML = '';

        if (totalBookings === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">No revenue data is available for that period.</td></tr>`;
            // Clear chart
            if (this.revenueChart) this.revenueChart.destroy();
            return;
        }

        // Calculate per-shift breakdown
        const shifts = this.getItems('utcl_shifts');
        const breakdown = {};

        shifts.forEach(s => {
            breakdown[s.id] = { busId: s.busId, count: 0, revenue: 0 };
        });

        bookings.forEach(b => {
            if (breakdown[b.shiftId]) {
                const count = b.seatNumber ? String(b.seatNumber).split(',').length : 1;
                breakdown[b.shiftId].count += count;
                breakdown[b.shiftId].revenue += (b.fareAmount || (count * 20));
            }
        });

        // Populate table
        const chartLabels = [];
        const chartData = [];

        Object.keys(breakdown).forEach(shiftId => {
            const item = breakdown[shiftId];
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${shiftId}</strong></td>
                <td>${item.busId === 'b1' ? 'Bus 1' : 'Bus 2'}</td>
                <td>${item.count}</td>
                <td><strong>₹${item.revenue}</strong></td>
            `;
            tbody.appendChild(tr);

            chartLabels.push(shiftId);
            chartData.push(item.revenue);
        });
        addMobileTableLabels('#revenue-table-body');

        // Render Chart.js Bar Chart
        const ctx = document.getElementById('revenue-shift-chart').getContext('2d');
        if (this.revenueChart) {
            this.revenueChart.destroy();
        }

        this.revenueChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: chartLabels,
                datasets: [{
                    label: 'Revenue (₹)',
                    data: chartData,
                    backgroundColor: 'rgba(0, 87, 168, 0.65)',
                    borderColor: '#0057A8',
                    borderWidth: 1.5,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#9CA3AF' }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#9CA3AF' }
                    }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }

    // Occupancy Analysis Dashboard
    initOccupancyAnalysis() {
        const now = new Date();
        const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
        const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0);

        const formatDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

        document.getElementById('occ-date-from').value = formatDate(firstDay);
        document.getElementById('occ-date-to').value = formatDate(lastDay);

        // Load shift history selector
        const historySelect = document.getElementById('occupancy-history-shift-select');
        historySelect.innerHTML = '';
        this.getItems('utcl_shifts').forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = `${s.id} History (30d)`;
            historySelect.appendChild(opt);
        });

        this.renderOccupancyData(formatDate(firstDay), formatDate(lastDay));
        this.loadHistoricalOccupancyChart();
    }

    filterOccupancy(e) {
        e.preventDefault();
        const from = document.getElementById('occ-date-from').value;
        const to = document.getElementById('occ-date-to').value;
        this.renderOccupancyData(from, to);
    }

    renderOccupancyData(from, to) {
        const bookings = this.getItems('utcl_bookings').filter(b =>
            b.travelDate >= from &&
            b.travelDate <= to &&
            b.status === 'CONFIRMED'
        );

        const shifts = this.getItems('utcl_shifts');
        const tbody = document.getElementById('occupancy-table-body');
        tbody.innerHTML = '';

        // Calculate shift averages
        // First count how many unique travel dates are in range
        const uniqueDates = Array.from(new Set(bookings.map(b => b.travelDate)));
        const totalDaysCount = uniqueDates.length || 1;

        const weekdayDates = uniqueDates.filter(d => {
            const day = new Date(d).getDay();
            return day >= 1 && day <= 5;
        });
        const weekendDates = uniqueDates.filter(d => {
            const day = new Date(d).getDay();
            return day === 0 || day === 6;
        });

        const weekdayDaysCount = weekdayDates.length || 1;
        const weekendDaysCount = weekendDates.length || 1;

        const shiftData = {};
        shifts.forEach(s => {
            shiftData[s.id] = { weekdayCount: 0, weekendCount: 0, totalCount: 0 };
        });

        bookings.forEach(b => {
            const day = new Date(b.travelDate).getDay();
            const isWeekend = (day === 0 || day === 6);
            const count = b.seatNumber ? String(b.seatNumber).split(',').length : 1;
            if (shiftData[b.shiftId]) {
                shiftData[b.shiftId].totalCount += count;
                if (isWeekend) {
                    shiftData[b.shiftId].weekendCount += count;
                } else {
                    shiftData[b.shiftId].weekdayCount += count;
                }
            }
        });

        // Render shifts table
        const chartLabels = [];
        const weekdayAverages = [];
        const weekendAverages = [];

        shifts.forEach(s => {
            const item = shiftData[s.id];

            // Occupancy average calculations
            const avgBookings = item.totalCount / totalDaysCount;
            // Requirement 11.1: Occupancy = bookings / seats * 100%
            const occupancyPct = Math.round((avgBookings / 49) * 100);

            const avgWeekdayBookings = item.weekdayCount / weekdayDaysCount;
            const weekdayOccPct = Math.round((avgWeekdayBookings / 49) * 100);

            const avgWeekendBookings = item.weekendCount / weekendDaysCount;
            const weekendOccPct = Math.round((avgWeekendBookings / 49) * 100);

            chartLabels.push(s.id);
            weekdayAverages.push(weekdayOccPct);
            weekendAverages.push(weekendOccPct);

            // High (>=80%) vs Low (<=40%) load classifications (Requirement 11.3)
            let badgeClass = 'badge-success';
            let badgeText = 'Normal';
            if (occupancyPct >= 80) {
                badgeClass = 'badge-danger';
                badgeText = 'High Load';
            } else if (occupancyPct <= 40) {
                badgeClass = 'badge-warning';
                badgeText = 'Low Load';
            }

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${s.id}</strong></td>
                <td>${s.stops[0].name} → ${s.stops[s.stops.length - 1].name}</td>
                <td>${avgBookings.toFixed(1)}</td>
                <td><strong>${occupancyPct}%</strong></td>
                <td><span class="badge ${badgeClass}">${badgeText}</span></td>
            `;
            tbody.appendChild(tr);
        });
        addMobileTableLabels('#occupancy-table-body');

        // Double Bar Chart for Weekday vs Weekend Average
        const ctx = document.getElementById('occupancy-type-chart').getContext('2d');
        if (this.occupancyChart) this.occupancyChart.destroy();

        this.occupancyChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: chartLabels,
                datasets: [
                    {
                        label: 'Weekday Avg (%)',
                        data: weekdayAverages,
                        backgroundColor: '#0057A8'
                    },
                    {
                        label: 'Weekend Avg (%)',
                        data: weekendAverages,
                        backgroundColor: '#58595B'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#9CA3AF' }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#9CA3AF' }
                    }
                },
                plugins: {
                    legend: { labels: { color: '#F3F4F6' } }
                }
            }
        });
    }

    loadHistoricalOccupancyChart() {
        const shiftId = document.getElementById('occupancy-history-shift-select').value;
        if (!shiftId) return;

        // Fetch bookings for this shift
        const bookings = this.getItems('utcl_bookings').filter(b =>
            b.shiftId === shiftId &&
            b.status === 'CONFIRMED'
        );

        // Group by travel date, sorted ascending
        const dateLoads = {};
        bookings.forEach(b => {
            const count = b.seatNumber ? String(b.seatNumber).split(',').length : 1;
            dateLoads[b.travelDate] = (dateLoads[b.travelDate] || 0) + count;
        });

        const sortedDates = Object.keys(dateLoads).sort();
        // Limit to last 30 dates (1 month)
        const lastDates = sortedDates.slice(-30);

        const chartLabels = [];
        const chartData = [];
        const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

        lastDates.forEach(date => {
            // Format YYYY-MM-DD to DD MMM (e.g. 2026-05-08 to 08 May)
            const parts = date.split('-');
            const formattedDate = `${parts[2]} ${monthNames[parseInt(parts[1], 10) - 1]}`;
            chartLabels.push(formattedDate);
            const occPct = Math.round((dateLoads[date] / 49) * 100);
            chartData.push(occPct);
        });

        const ctx = document.getElementById('occupancy-history-chart').getContext('2d');
        if (this.historyChart) this.historyChart.destroy();

        this.historyChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: chartLabels,
                datasets: [{
                    label: 'Occupancy Trend (%)',
                    data: chartData,
                    borderColor: '#0057A8',
                    backgroundColor: 'rgba(0, 87, 168, 0.1)',
                    fill: true,
                    tension: 0.1,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#9CA3AF' }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#9CA3AF' }
                    }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }

    // Admin Notifications Tab Logic
    initAdminNotificationsTab() {
        this.populateNotificationUsers();
        this.renderSentNotificationsHistory();
    }

    onRecipientTypeChange() {
        const type = document.getElementById('notification-recipient-type').value;
        const group = document.getElementById('specific-user-recipient-group');
        if (type === 'SPECIFIC_USER') {
            group.classList.remove('hidden');
        } else {
            group.classList.add('hidden');
        }
    }

    populateNotificationUsers() {
        const input = document.getElementById('notification-recipient-search');
        const hidden = document.getElementById('notification-recipient-ps');
        if (input) input.value = '';
        if (hidden) hidden.value = '';
        this.closeRecipientAutocomplete();
    }

    handleSendBroadcastNotification(e) {
        e.preventDefault();
        const type = document.getElementById('notification-recipient-type').value;
        const message = document.getElementById('notification-message-content').value.trim();
        if (!message) return;

        const users = this.getItems('utcl_users');

        if (type === 'ALL_EMPLOYEES') {
            const employees = users.filter(u => u.isActive && u.role === 'EMPLOYEE');
            if (employees.length === 0) {
                alert("No active employees found to notify.");
                return;
            }
            this.sendNotification('all_employees', message);
        } else if (type === 'ALL_DRIVERS') {
            const drivers = users.filter(u => u.isActive && u.role === 'DRIVER');
            if (drivers.length === 0) {
                alert("No active drivers found to notify.");
                return;
            }
            this.sendNotification('all_drivers', message);
        } else if (type === 'SPECIFIC_USER') {
            const userId = document.getElementById('notification-recipient-ps').value;
            if (!userId) {
                alert("Please select a recipient.");
                return;
            }
            this.sendNotification(userId, message);
        }

        // Clear message input
        document.getElementById('notification-message-content').value = '';
        
        // Refresh history table
        this.renderSentNotificationsHistory();
        
        alert("Notification sent successfully!");
    }

    renderSentNotificationsHistory() {
        const tbody = document.getElementById('admin-sent-notifications-tbody');
        if (!tbody) return;
        tbody.innerHTML = '';

        const notifications = this.getItems('utcl_notifications');
        const users = this.getItems('utcl_users');

        if (notifications.length === 0) {
            tbody.innerHTML = `<tr><td colspan="3" class="text-center text-xs text-muted">No notifications sent yet.</td></tr>`;
            return;
        }

        // Sort by createdAt descending
        const sorted = [...notifications].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

        sorted.forEach(n => {
            const recipient = users.find(u => u.id === n.recipientUserId);
            let recipientLabel = '';
            if (n.recipientUserId === 'all_employees') {
                recipientLabel = 'All Employees';
            } else if (n.recipientUserId === 'all_drivers') {
                recipientLabel = 'All Drivers';
            } else {
                recipientLabel = recipient 
                    ? `${recipient.name} (${recipient.role === 'DRIVER' ? 'Driver' : 'Employee'})` 
                    : (n.recipientUserId || 'Unknown');
            }

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="col-recipient"><strong>${recipientLabel}</strong></td>
                <td class="col-message">${n.message}</td>
                <td class="col-sent-at"><span class="text-xxs text-muted">${new Date(n.createdAt).toLocaleString()}</span></td>
            `;
            tbody.appendChild(tr);
        });
        addMobileTableLabels('#admin-sent-notifications-tbody');
    }

    // Notifications API
    sendNotification(recipientUserId, message) {
        const list = this.getItems('utcl_notifications');
        list.push({
            id: `nt_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
            recipientUserId,
            message,
            isRead: false,
            createdAt: new Date().toISOString()
        });
        this.setItem('utcl_notifications', list);
        this.updateNotificationsUI();
    }

    toggleNotifications(e) {
        e.stopPropagation();
        const drop = document.getElementById('notification-dropdown');
        drop.classList.toggle('hidden');
    }

    toggleProfileDropdown(e) {
        if (e) e.stopPropagation();
        
        // Close notification dropdown if open
        const notifDrop = document.getElementById('notification-dropdown');
        if (notifDrop) notifDrop.classList.add('hidden');
        
        const drop = document.getElementById('profile-dropdown');
        if (drop) {
            drop.classList.toggle('hidden');
        }
    }

    closeProfileDropdown() {
        const drop = document.getElementById('profile-dropdown');
        if (drop) {
            drop.classList.add('hidden');
        }
    }

    getCurrentUserNotifications() {
        if (!this.currentUser) return [];
        const all = this.getItems('utcl_notifications');
        return all.filter(n => {
            if (n.recipientUserId === this.currentUser.id) return true;
            if (this.currentUser.role === 'EMPLOYEE' && n.recipientUserId === 'all_employees') return true;
            if (this.currentUser.role === 'DRIVER' && n.recipientUserId === 'all_drivers') return true;
            return false;
        });
    }

    updateNotificationsUI() {
        if (!this.currentUser) return;

        const list = this.getCurrentUserNotifications();
        const unreadCount = list.filter(n => !n.isRead).length;

        const badge = document.getElementById('notification-count');
        const container = document.getElementById('notification-list');

        if (unreadCount > 0) {
            badge.textContent = unreadCount;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }

        container.innerHTML = '';
        if (list.length === 0) {
            container.innerHTML = `<div class="empty-state text-xs">No notifications</div>`;
        } else {
            list.slice(-5).reverse().forEach(n => { // Last 5
                // Normalize UTC timestamp from Python backend (e.g. "2026-06-22 10:16:44" -> "2026-06-22T10:16:44Z")
                let dtStr = n.createdAt;
                if (dtStr && typeof dtStr === 'string' && !dtStr.includes('T') && !dtStr.endsWith('Z')) {
                    dtStr = dtStr.replace(' ', 'T') + 'Z';
                }

                const item = document.createElement('div');
                item.className = `notification-item ${n.isRead ? '' : 'unread'}`;
                item.onclick = () => this.markNotificationRead(n.id);
                item.innerHTML = `
                    <p class="text-xs">${n.message}</p>
                    <span class="text-xxs text-muted mt-1 block">${new Date(dtStr).toLocaleTimeString()}</span>
                `;
                container.appendChild(item);
            });
        }
    }

    markNotificationRead(id) {
        const list = this.getItems('utcl_notifications');
        const item = list.find(n => n.id === id);
        if (item) {
            item.isRead = true;
            this.setItem('utcl_notifications', list);
            this.updateNotificationsUI();
        }
    }

    markAllNotificationsRead() {
        if (!this.currentUser) return;
        const list = this.getItems('utcl_notifications');
        list.forEach(n => {
            if (n.recipientUserId === this.currentUser.id ||
                (this.currentUser.role === 'EMPLOYEE' && n.recipientUserId === 'all_employees') ||
                (this.currentUser.role === 'DRIVER' && n.recipientUserId === 'all_drivers')) {
                n.isRead = true;
            }
        });
        this.setItem('utcl_notifications', list);
        this.updateNotificationsUI();
    }

    // ==========================================================================
    // 6. RENDER LOGIC & CONTROLLERS
    // ==========================================================================

    initCustomSelects() {
        const selectElements = document.querySelectorAll(
            '#view-admin select, #create-user-modal select, #create-maintenance-modal select'
        );

        selectElements.forEach(select => {
            if (select.dataset.customized === 'true') return;
            select.dataset.customized = 'true';

            // Hide the native select
            select.style.display = 'none';

            // Create container
            const container = document.createElement('div');
            container.className = 'custom-select-container';
            container.id = 'custom-select-' + select.id;

            // Create trigger
            const trigger = document.createElement('div');
            trigger.className = 'custom-select-trigger';

            if (select.disabled) {
                container.classList.add('disabled');
                trigger.classList.add('disabled');
            }

            const triggerText = document.createElement('span');
            triggerText.className = 'custom-select-trigger-text';
            trigger.appendChild(triggerText);

            // Add SVG chevron icon
            const chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            chevron.setAttribute('class', 'custom-select-chevron');
            chevron.setAttribute('viewBox', '0 0 24 24');
            chevron.setAttribute('width', '16');
            chevron.setAttribute('height', '16');
            chevron.setAttribute('stroke', 'currentColor');
            chevron.setAttribute('stroke-width', '2');
            chevron.setAttribute('fill', 'none');
            
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', 'M6 9l6 6 6-6');
            chevron.appendChild(path);
            trigger.appendChild(chevron);

            container.appendChild(trigger);

            // Create options panel
            const optionsPanel = document.createElement('div');
            optionsPanel.className = 'custom-select-options hidden';
            container.appendChild(optionsPanel);

            // Insert container after native select
            select.parentNode.insertBefore(container, select.nextSibling);

            // Document listener once
            if (!window.customSelectGlobalListenerAdded) {
                window.customSelectGlobalListenerAdded = true;
                document.addEventListener('click', (e) => {
                    document.querySelectorAll('.custom-select-options').forEach(el => {
                        if (!el.parentNode.contains(e.target)) {
                            el.classList.add('hidden');
                            el.previousSibling.classList.remove('open');
                        }
                    });
                });
            }

            // Click listener for trigger
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                if (trigger.classList.contains('disabled') || container.classList.contains('disabled')) {
                    return;
                }
                // Close other custom selects
                document.querySelectorAll('.custom-select-options').forEach(el => {
                    if (el !== optionsPanel) {
                        el.classList.add('hidden');
                        el.previousSibling.classList.remove('open');
                    }
                });
                
                const isOpen = !optionsPanel.classList.contains('hidden');
                if (isOpen) {
                    optionsPanel.classList.add('hidden');
                    trigger.classList.remove('open');
                } else {
                    // Update disabled states first if this is the shift select dropdown!
                    if (select.id === 'assign-shift-select') {
                        this.updateShiftSelectDisabledStates();
                    }
                    rebuildOptions();
                    optionsPanel.classList.remove('hidden');
                    trigger.classList.add('open');
                }
            });

            // Rebuild function
            const rebuildOptions = () => {
                optionsPanel.innerHTML = '';
                Array.from(select.options).forEach(opt => {
                    const optDiv = document.createElement('div');
                    optDiv.className = 'custom-select-option';
                    if (opt.disabled) {
                        optDiv.classList.add('disabled');
                    }
                    optDiv.dataset.value = opt.value;
                    optDiv.textContent = opt.textContent;

                    if (opt.selected) {
                        optDiv.classList.add('selected');
                        triggerText.textContent = opt.textContent;
                    }

                    optDiv.addEventListener('click', (e) => {
                        e.stopPropagation();
                        if (opt.disabled || optDiv.classList.contains('disabled')) return;
                        if (optDiv.classList.contains('selecting')) return;
                        optDiv.classList.add('selecting');

                        // Update value programmatically on native select
                        select.value = opt.value;

                        setTimeout(() => {
                            optionsPanel.classList.add('hidden');
                            trigger.classList.remove('open');

                            optionsPanel.querySelectorAll('.custom-select-option').forEach(el => {
                                el.classList.remove('selected');
                            });
                            optDiv.classList.add('selected');
                            optDiv.classList.remove('selecting');
                            triggerText.textContent = opt.textContent;

                            // Dispatch change event to notify any native listeners
                            select.dispatchEvent(new Event('change'));
                        }, 150);
                    });

                    optionsPanel.appendChild(optDiv);
                });

                // Set default trigger text if none is selected
                if (select.selectedIndex === -1 || select.options.length === 0) {
                    triggerText.textContent = select.placeholder || '';
                } else if (select.options[select.selectedIndex]) {
                    triggerText.textContent = select.options[select.selectedIndex].textContent;
                }
            };

            // Expose rebuild function on native select so we can call it when options properties change programmatically
            select.rebuildCustomOptions = rebuildOptions;

            // MutationObserver to rebuild custom options when native options change
            const observer = new MutationObserver(() => {
                rebuildOptions();
            });
            observer.observe(select, { childList: true, subtree: true });

            // Initial build
            rebuildOptions();

            // Intercept select.value property descriptors to sync custom UI if changed via JS code
            const originalValueDescriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
            if (originalValueDescriptor) {
                Object.defineProperty(select, 'value', {
                    get() {
                        return originalValueDescriptor.get.call(this);
                    },
                    set(val) {
                        originalValueDescriptor.set.call(this, val);
                        // Sync selected class on custom options
                        optionsPanel.querySelectorAll('.custom-select-option').forEach(el => {
                            if (el.dataset.value === String(val)) {
                                el.classList.add('selected');
                                triggerText.textContent = el.textContent;
                            } else {
                                el.classList.remove('selected');
                            }
                        });
                    },
                    configurable: true
                });
            }

            // Intercept select.selectedIndex property descriptors to sync custom UI if changed via JS code
            const originalSelectedIndexDescriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'selectedIndex');
            if (originalSelectedIndexDescriptor) {
                Object.defineProperty(select, 'selectedIndex', {
                    get() {
                        return originalSelectedIndexDescriptor.get.call(this);
                    },
                    set(val) {
                        originalSelectedIndexDescriptor.set.call(this, val);
                        const opt = select.options[val];
                        if (opt) {
                            optionsPanel.querySelectorAll('.custom-select-option').forEach(el => {
                                if (el.dataset.value === opt.value) {
                                    el.classList.add('selected');
                                    triggerText.textContent = el.textContent;
                                } else {
                                    el.classList.remove('selected');
                                }
                            });
                        }
                    },
                    configurable: true
                });
            }
        });
    }

    renderView() {
        // Toggle Global Header
        const header = document.getElementById('global-header');

        // Hide all views
        document.querySelectorAll('.view-panel').forEach(p => p.classList.add('hidden'));

        if (this.currentUser) {
            header.classList.remove('hidden');

            // Set header info
            document.getElementById('header-user-name').textContent = this.currentUser.name;
            document.getElementById('header-user-role').textContent = this.currentUser.role;
            document.getElementById('header-avatar').textContent = this.currentUser.name.charAt(0);

            this.updateNotificationsUI();

            // Load role-specific panel
            if (this.currentUser.role === 'EMPLOYEE') {
                document.getElementById('view-employee').classList.remove('active'); // Reset triggers
                document.getElementById('view-employee').classList.remove('hidden');
                document.getElementById('view-employee').classList.add('active');
                
                // Render view immediately for fastest possible LCP
                this.switchEmployeeTab('booking');
                
                // Load QRCode script in background for later step
                this.loadScript('js/qrcode.min.js').catch(err => {
                    console.error("Failed to load QRCode in background:", err);
                });
            } else if (this.currentUser.role === 'DRIVER') {
                document.getElementById('view-driver').classList.remove('hidden');
                document.getElementById('view-driver').classList.add('active');
                this.renderDriverDashboard();
            } else if (this.currentUser.role === 'ADMIN') {
                document.getElementById('view-admin').classList.remove('hidden');
                document.getElementById('view-admin').classList.add('active');
                this.loadScript('js/chart.js').then(() => {
                    this.switchAdminTab('dashboard');
                }).catch(err => {
                    console.error("Failed to load Chart.js:", err);
                    this.switchAdminTab('dashboard');
                });
            }
        } else {
            header.classList.add('hidden');
            document.getElementById('view-login').classList.remove('hidden');
            document.getElementById('view-login').classList.add('active');
        }
    }

    // Modal Helpers
    openModal(id) {
        document.getElementById(id).classList.remove('hidden');
    }

    closeModal(id) {
        document.getElementById(id).classList.add('hidden');

        // Clear warning overlays
        if (id === 'create-maintenance-modal') {
            document.getElementById('maintenance-conflict-alert').classList.add('hidden');
        }
    }

    handleHistorySearchInput(input) {
        const query = input.value.trim();
        const dropdown = document.getElementById('history-autocomplete-dropdown');
        if (!dropdown) return;

        if (this.historySearchTimeout) {
            clearTimeout(this.historySearchTimeout);
        }

        if (!query) {
            this.closeHistoryAutocomplete();
            return;
        }

        // Debounce search by 300ms
        this.historySearchTimeout = setTimeout(() => {
            fetch(`/api/employees/search?query=${encodeURIComponent(query)}`)
                .then(res => {
                    if (!res.ok) throw new Error("API failed");
                    return res.json();
                })
                .then(data => {
                    this.renderHistoryAutocomplete(data);
                })
                .catch(err => {
                    console.warn("Backend search failed or offline. Falling back to local storage.", err);
                    // Fallback to local storage
                    const users = this.getItems('utcl_users');
                    const filtered = users
                        .filter(u => u.role === 'EMPLOYEE' && u.psNumber.toLowerCase().startsWith(query.toLowerCase()))
                        .slice(0, 10)
                        .map(u => ({ psNumber: u.psNumber, name: u.name }));
                    this.renderHistoryAutocomplete(filtered);
                });
        }, 300);
    }

    renderHistoryAutocomplete(employees) {
        const dropdown = document.getElementById('history-autocomplete-dropdown');
        if (!dropdown) return;
        dropdown.innerHTML = '';
        this.historyAutocompleteHighlightedIndex = -1;

        if (!employees || employees.length === 0) {
            const div = document.createElement('div');
            div.className = 'autocomplete-item no-results';
            div.textContent = 'No employees found';
            dropdown.appendChild(div);
            dropdown.classList.remove('hidden');
            return;
        }

        employees.forEach((emp, index) => {
            const div = document.createElement('div');
            div.className = 'autocomplete-item';
            div.dataset.index = index;
            div.dataset.ps = emp.psNumber;
            div.innerHTML = `<strong>${emp.psNumber}</strong> <span class="autocomplete-emp-name">- ${emp.name}</span>`;
            div.onclick = () => {
                if (div.classList.contains('selecting')) return;
                div.classList.add('selecting');
                const input = document.getElementById('history-ps-number');
                if (input) {
                    input.value = emp.psNumber;
                }
                setTimeout(() => {
                    this.closeHistoryAutocomplete();
                    this.loadBookingHistory();
                }, 150);
            };
            dropdown.appendChild(div);
        });

        dropdown.classList.remove('hidden');
    }

    handleHistorySearchKeydown(input, event) {
        const dropdown = document.getElementById('history-autocomplete-dropdown');
        if (!dropdown || dropdown.classList.contains('hidden')) return;

        const items = dropdown.querySelectorAll('.autocomplete-item:not(.no-results)');
        if (items.length === 0) return;

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            this.historyAutocompleteHighlightedIndex++;
            if (this.historyAutocompleteHighlightedIndex >= items.length) {
                this.historyAutocompleteHighlightedIndex = 0;
            }
            this.highlightAutocompleteItem(items);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            this.historyAutocompleteHighlightedIndex--;
            if (this.historyAutocompleteHighlightedIndex < 0) {
                this.historyAutocompleteHighlightedIndex = items.length - 1;
            }
            this.highlightAutocompleteItem(items);
        } else if (event.key === 'Enter') {
            event.preventDefault();
            if (this.historyAutocompleteHighlightedIndex > -1 && items[this.historyAutocompleteHighlightedIndex]) {
                items[this.historyAutocompleteHighlightedIndex].click();
            } else {
                this.closeHistoryAutocomplete();
                this.loadBookingHistory();
            }
        } else if (event.key === 'Escape') {
            event.preventDefault();
            this.closeHistoryAutocomplete();
        }
    }

    highlightAutocompleteItem(items) {
        items.forEach((item, index) => {
            if (index === this.historyAutocompleteHighlightedIndex) {
                item.classList.add('highlighted');
                item.scrollIntoView({ block: 'nearest' });
            } else {
                item.classList.remove('highlighted');
            }
        });
    }

    closeHistoryAutocomplete() {
        const dropdown = document.getElementById('history-autocomplete-dropdown');
        if (dropdown) {
            dropdown.classList.add('hidden');
            dropdown.innerHTML = '';
        }
        this.historyAutocompleteHighlightedIndex = -1;
    }

    handleDriverHistorySearchInput(input) {
        const query = input.value.trim();
        const dropdown = document.getElementById('driver-history-autocomplete-dropdown');
        if (!dropdown) return;

        if (this.driverHistorySearchTimeout) {
            clearTimeout(this.driverHistorySearchTimeout);
        }

        if (!query) {
            this.closeDriverHistoryAutocomplete();
            return;
        }

        // Debounce search by 300ms
        this.driverHistorySearchTimeout = setTimeout(() => {
            fetch(`/api/drivers/search?query=${encodeURIComponent(query)}`)
                .then(res => {
                    if (!res.ok) throw new Error("API failed");
                    return res.json();
                })
                .then(data => {
                    this.renderDriverHistoryAutocomplete(data);
                })
                .catch(err => {
                    console.warn("Backend driver search failed or offline. Falling back to local storage.", err);
                    // Fallback to local storage
                    const users = this.getItems('utcl_users');
                    const filtered = users
                        .filter(u => u.role === 'DRIVER' && u.psNumber.toLowerCase().startsWith(query.toLowerCase()))
                        .slice(0, 10)
                        .map(u => ({ psNumber: u.psNumber, name: u.name }));
                    this.renderDriverHistoryAutocomplete(filtered);
                });
        }, 300);
    }

    renderDriverHistoryAutocomplete(drivers) {
        const dropdown = document.getElementById('driver-history-autocomplete-dropdown');
        if (!dropdown) return;
        dropdown.innerHTML = '';
        this.driverHistoryAutocompleteHighlightedIndex = -1;

        if (!drivers || drivers.length === 0) {
            const div = document.createElement('div');
            div.className = 'autocomplete-item no-results';
            div.textContent = 'No drivers found';
            dropdown.appendChild(div);
            dropdown.classList.remove('hidden');
            return;
        }

        drivers.forEach((drv, index) => {
            const div = document.createElement('div');
            div.className = 'autocomplete-item';
            div.dataset.index = index;
            div.dataset.ps = drv.psNumber;
            div.innerHTML = `<strong>${drv.psNumber}</strong> <span class="autocomplete-emp-name">- ${drv.name}</span>`;
            div.onclick = () => {
                if (div.classList.contains('selecting')) return;
                div.classList.add('selecting');
                const input = document.getElementById('driver-history-ps-number');
                if (input) {
                    input.value = drv.psNumber;
                }
                setTimeout(() => {
                    this.closeDriverHistoryAutocomplete();
                    this.loadDriverAttendanceHistory(1);
                }, 150);
            };
            dropdown.appendChild(div);
        });

        dropdown.classList.remove('hidden');
    }

    handleDriverHistorySearchKeydown(input, event) {
        const dropdown = document.getElementById('driver-history-autocomplete-dropdown');
        if (!dropdown || dropdown.classList.contains('hidden')) return;

        const items = dropdown.querySelectorAll('.autocomplete-item:not(.no-results)');
        if (items.length === 0) return;

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            this.driverHistoryAutocompleteHighlightedIndex++;
            if (this.driverHistoryAutocompleteHighlightedIndex >= items.length) {
                this.driverHistoryAutocompleteHighlightedIndex = 0;
            }
            this.highlightDriverAutocompleteItem(items);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            this.driverHistoryAutocompleteHighlightedIndex--;
            if (this.driverHistoryAutocompleteHighlightedIndex < 0) {
                this.driverHistoryAutocompleteHighlightedIndex = items.length - 1;
            }
            this.highlightDriverAutocompleteItem(items);
        } else if (event.key === 'Enter') {
            event.preventDefault();
            if (this.driverHistoryAutocompleteHighlightedIndex > -1 && items[this.driverHistoryAutocompleteHighlightedIndex]) {
                items[this.driverHistoryAutocompleteHighlightedIndex].click();
            } else {
                this.closeDriverHistoryAutocomplete();
                this.loadDriverAttendanceHistory(1);
            }
        } else if (event.key === 'Escape') {
            event.preventDefault();
            this.closeDriverHistoryAutocomplete();
        }
    }

    highlightDriverAutocompleteItem(items) {
        items.forEach((item, index) => {
            if (index === this.driverHistoryAutocompleteHighlightedIndex) {
                item.classList.add('highlighted');
                item.scrollIntoView({ block: 'nearest' });
            } else {
                item.classList.remove('highlighted');
            }
        });
    }

    closeDriverHistoryAutocomplete() {
        const dropdown = document.getElementById('driver-history-autocomplete-dropdown');
        if (dropdown) {
            dropdown.classList.add('hidden');
            dropdown.innerHTML = '';
        }
        this.driverHistoryAutocompleteHighlightedIndex = -1;
    }

    async loadDriverAttendanceHistory(page = 1) {
        const psInput = document.getElementById('driver-history-ps-number').value.trim().toUpperCase();
        const tbody = document.getElementById('driver-management-table-body');
        const paginationContainer = document.getElementById('driver-history-pagination');
        const exportBtn = document.getElementById('driver-export-excel-btn');
        const clearBtn = document.getElementById('driver-history-clear-btn');

        if (!psInput) {
            this.clearDriverAttendanceSearch();
            return;
        }

        // Show Clear Search button, Show Export Button
        if (clearBtn) clearBtn.classList.remove('hidden');
        if (exportBtn) exportBtn.classList.remove('hidden');

        // Set History headers
        const thead = document.getElementById('driver-management-table-head');
        if (thead) {
            thead.innerHTML = `
                <tr>
                    <th>Date</th>
                    <th>Driver Name</th>
                    <th>Bus ID</th>
                    <th>Shift ID</th>
                    <th>Departure Info</th>
                    <th>Arrival Info</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
            `;
        }

        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">Loading history...</td></tr>`;

        try {
            const res = await fetch(`/api/admin/attendance/history?driverId=${encodeURIComponent(psInput)}&page=${page}&limit=10`);
            const data = await res.json();

            if (data.status === 'success') {
                const list = data.attendance;
                if (!list || list.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">No attendance history found for PS Number ${psInput}.</td></tr>`;
                    if (paginationContainer) paginationContainer.classList.add('hidden');
                    if (exportBtn) exportBtn.disabled = true;
                    return;
                }

                tbody.innerHTML = '';
                list.forEach(att => {
                    const tr = document.createElement('tr');
                    
                    let depPhotoHtml = '';
                    if (!att.departurePhotoUrl) {
                        depPhotoHtml = '<span class="badge badge-warning">No Image Uploaded</span>';
                    } else {
                        const depUrl = `${window.location.origin}${att.departurePhotoUrl}`;
                        depPhotoHtml = `
                            <a href="${depUrl}" target="_blank" rel="noopener noreferrer" class="flex items-center gap-1" style="display:inline-flex; align-items:center; gap:4px;">
                                <img src="${depUrl}" style="width: 30px; height: 30px; object-fit: cover; border-radius: 4px;"> View
                            </a>
                        `;
                    }

                    let arrPhotoHtml = '';
                    if (!att.arrivalPhotoUrl) {
                        arrPhotoHtml = '<span class="badge badge-warning">No Image Uploaded</span>';
                    } else {
                        const arrUrl = `${window.location.origin}${att.arrivalPhotoUrl}`;
                        arrPhotoHtml = `
                            <a href="${arrUrl}" target="_blank" rel="noopener noreferrer" class="flex items-center gap-1" style="display:inline-flex; align-items:center; gap:4px;">
                                <img src="${arrUrl}" style="width: 30px; height: 30px; object-fit: cover; border-radius: 4px;"> View
                            </a>
                        `;
                    }

                    const statusClass = att.status === 'Approved' ? 'badge-success' : 'badge-danger';
                    const statusHtml = `<span class="badge ${statusClass}">${att.status}</span>`;

                    tr.innerHTML = `
                        <td>${att.date}</td>
                        <td><strong>${att.driverName || 'Driver ' + att.driverId} (${att.driverId})</strong></td>
                        <td>${att.busId === 'b1' ? 'Bus 1' : (att.busId === 'b2' ? 'Bus 2' : att.busId)}</td>
                        <td>${this.getShiftLabel(att.shiftId)}</td>
                        <td>
                            <div class="mb-1">${att.departureTime || '--'}</div>
                            <div>${depPhotoHtml}</div>
                        </td>
                        <td>
                            <div class="mb-1">${att.arrivalTime || '--'}</div>
                            <div>${arrPhotoHtml}</div>
                        </td>
                        <td>${statusHtml}</td>
                        <td>
                            <button class="btn btn-outline btn-xs" onclick="app.viewDetailedDriverLog('${att.id}')">View Detailed Log</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });

                if (exportBtn) exportBtn.disabled = false;
                this.renderDriverHistoryPagination(data.pagination);
                addMobileTableLabels('#driver-management-table-body');
            } else {
                tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">Error loading data: ${data.message}</td></tr>`;
                if (paginationContainer) paginationContainer.classList.add('hidden');
                if (exportBtn) exportBtn.disabled = true;
            }
        } catch (err) {
            console.error('Error loading driver attendance history:', err);
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">Network error loading attendance history.</td></tr>`;
            if (paginationContainer) paginationContainer.classList.add('hidden');
            if (exportBtn) exportBtn.disabled = true;
        }
    }

    renderDriverHistoryPagination(pagination) {
        const container = document.getElementById('driver-history-pagination');
        if (!container) return;

        if (!pagination || pagination.totalPages <= 1) {
            container.classList.add('hidden');
            return;
        }

        container.classList.remove('hidden');
        container.innerHTML = '';

        // Info text
        const infoDiv = document.createElement('div');
        infoDiv.className = 'pagination-info';
        const startRecord = (pagination.page - 1) * pagination.limit + 1;
        const endRecord = Math.min(pagination.page * pagination.limit, pagination.totalRecords);
        infoDiv.textContent = `Showing ${startRecord}-${endRecord} of ${pagination.totalRecords} records`;
        container.appendChild(infoDiv);

        // Buttons
        const buttonsDiv = document.createElement('div');
        buttonsDiv.className = 'pagination-buttons';

        // Prev button
        const prevBtn = document.createElement('button');
        prevBtn.className = 'pagination-btn';
        prevBtn.textContent = 'Previous';
        prevBtn.disabled = pagination.page === 1;
        prevBtn.onclick = () => this.loadDriverAttendanceHistory(pagination.page - 1);
        buttonsDiv.appendChild(prevBtn);

        // Page numbers
        for (let i = 1; i <= pagination.totalPages; i++) {
            const pageBtn = document.createElement('button');
            pageBtn.className = `pagination-btn ${pagination.page === i ? 'active' : ''}`;
            pageBtn.textContent = i;
            pageBtn.onclick = () => this.loadDriverAttendanceHistory(i);
            buttonsDiv.appendChild(pageBtn);
        }

        // Next button
        const nextBtn = document.createElement('button');
        nextBtn.className = 'pagination-btn';
        nextBtn.textContent = 'Next';
        nextBtn.disabled = pagination.page === pagination.totalPages;
        nextBtn.onclick = () => this.loadDriverAttendanceHistory(pagination.page + 1);
        buttonsDiv.appendChild(nextBtn);

        container.appendChild(buttonsDiv);
    }

    exportDriverHistoryToExcel() {
        const psInput = document.getElementById('driver-history-ps-number').value.trim().toUpperCase();
        if (!psInput) {
            alert('Please enter a valid driver PS number first.');
            return;
        }

        fetch(`/api/admin/attendance/history/export?driverId=${encodeURIComponent(psInput)}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Server returned an error during Excel generation');
                }
                return response.blob();
            })
            .then(originalBlob => {
                const blob = new Blob([originalBlob], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.setAttribute('download', 'Driver_Attendance_History.xlsx');
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            })
            .catch(err => {
                console.error('Error exporting driver attendance history:', err);
                alert('Failed to export driver attendance history: ' + err.message);
            });
    }

    clearDriverAttendanceSearch() {
        const input = document.getElementById('driver-history-ps-number');
        if (input) input.value = '';
        this.closeDriverHistoryAutocomplete();
        this.loadPendingAttendances();
    }

    async viewDetailedDriverLog(id) {
        const errorAlert = document.getElementById('attendance-action-error');
        if (errorAlert) errorAlert.classList.add('hidden');

        try {
            const res = await fetch(`/api/admin/attendance/record/${id}`);
            const data = await res.json();
            if (data.status === 'success') {
                const att = data.attendance;
                if (att) {
                    const depImg = document.getElementById('admin-review-dep-img');
                    const arrImg = document.getElementById('admin-review-arr-img');
                    const depTime = document.getElementById('admin-review-dep-time');
                    const arrTime = document.getElementById('admin-review-arr-time');

                    if (depImg) depImg.src = att.departurePhotoUrl || '';
                    if (arrImg) arrImg.src = att.arrivalPhotoUrl || '';
                    if (depTime) depTime.textContent = `Logged at: ${att.departureTime || '--'}`;
                    if (arrTime) arrTime.textContent = `Logged at: ${att.arrivalTime || '--'}`;

                    // Update modal title to read-only state
                    const modalTitle = document.getElementById('admin-attendance-modal-title');
                    if (modalTitle) modalTitle.textContent = 'Trip Attendance Details';

                    // Hide Approve/Reject buttons
                    const rejectBtn = document.getElementById('admin-attendance-reject-btn');
                    const approveBtn = document.getElementById('admin-attendance-approve-btn');
                    if (rejectBtn) rejectBtn.classList.add('hidden');
                    if (approveBtn) approveBtn.classList.add('hidden');

                    this.openModal('admin-attendance-modal');
                } else {
                    alert('Attendance details not found.');
                }
            } else {
                alert('Error loading attendance details: ' + data.message);
            }
        } catch (err) {
            console.error('Error opening attendance detailed log modal:', err);
            alert('Failed to load attendance details.');
        }
    }

    handleRecipientSearchInput(input) {
        const query = input.value.trim();
        const dropdown = document.getElementById('recipient-autocomplete-dropdown');
        if (!dropdown) return;

        // Clear hidden input value when search input is emptied or edited
        const hidden = document.getElementById('notification-recipient-ps');
        if (hidden) hidden.value = '';

        if (this.recipientSearchTimeout) {
            clearTimeout(this.recipientSearchTimeout);
        }

        if (!query) {
            this.closeRecipientAutocomplete();
            return;
        }

        // Debounce search by 300ms
        this.recipientSearchTimeout = setTimeout(() => {
            fetch(`/api/recipients/search?query=${encodeURIComponent(query)}`)
                .then(res => {
                    if (!res.ok) throw new Error("API failed");
                    return res.json();
                })
                .then(data => {
                    this.renderRecipientAutocomplete(data);
                })
                .catch(err => {
                    console.warn("Backend recipient search failed or offline. Falling back to local storage.", err);
                    // Fallback to local storage
                    const users = this.getItems('utcl_users');
                    const filtered = users
                        .filter(u => u.isActive && (u.role === 'EMPLOYEE' || u.role === 'DRIVER') && 
                               u.psNumber.toLowerCase().startsWith(query.toLowerCase()))
                        .slice(0, 10)
                        .map(u => ({ id: u.id, psNumber: u.psNumber, name: u.name, role: u.role }));
                    this.renderRecipientAutocomplete(filtered);
                });
        }, 300);
    }

    renderRecipientAutocomplete(recipients) {
        const dropdown = document.getElementById('recipient-autocomplete-dropdown');
        if (!dropdown) return;
        dropdown.innerHTML = '';
        this.recipientAutocompleteHighlightedIndex = -1;

        if (!recipients || recipients.length === 0) {
            const div = document.createElement('div');
            div.className = 'autocomplete-item no-results';
            div.textContent = 'No recipients found';
            dropdown.appendChild(div);
            dropdown.classList.remove('hidden');
            return;
        }

        recipients.forEach((rec, index) => {
            const div = document.createElement('div');
            div.className = 'autocomplete-item';
            div.dataset.index = index;
            div.dataset.id = rec.id;
            div.dataset.ps = rec.psNumber;
            const roleLabel = rec.role === 'DRIVER' ? 'Driver' : 'Employee';
            div.innerHTML = `<strong>${rec.psNumber}</strong> <span class="autocomplete-emp-name">- ${rec.name} (${roleLabel})</span>`;
            
            div.onclick = () => {
                if (div.classList.contains('selecting')) return;
                div.classList.add('selecting');
                
                const searchInput = document.getElementById('notification-recipient-search');
                const hiddenInput = document.getElementById('notification-recipient-ps');
                if (searchInput) {
                    searchInput.value = `${rec.psNumber} - ${rec.name} (${roleLabel})`;
                }
                if (hiddenInput) {
                    hiddenInput.value = rec.id;
                }
                
                setTimeout(() => {
                    this.closeRecipientAutocomplete();
                }, 150);
            };
            dropdown.appendChild(div);
        });

        dropdown.classList.remove('hidden');
    }

    handleRecipientSearchKeydown(input, event) {
        const dropdown = document.getElementById('recipient-autocomplete-dropdown');
        if (!dropdown || dropdown.classList.contains('hidden')) return;

        const items = dropdown.querySelectorAll('.autocomplete-item:not(.no-results)');
        if (items.length === 0) return;

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            this.recipientAutocompleteHighlightedIndex++;
            if (this.recipientAutocompleteHighlightedIndex >= items.length) {
                this.recipientAutocompleteHighlightedIndex = 0;
            }
            this.highlightRecipientAutocompleteItem(items);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            this.recipientAutocompleteHighlightedIndex--;
            if (this.recipientAutocompleteHighlightedIndex < 0) {
                this.recipientAutocompleteHighlightedIndex = items.length - 1;
            }
            this.highlightRecipientAutocompleteItem(items);
        } else if (event.key === 'Enter') {
            event.preventDefault();
            if (this.recipientAutocompleteHighlightedIndex > -1 && items[this.recipientAutocompleteHighlightedIndex]) {
                items[this.recipientAutocompleteHighlightedIndex].click();
            } else {
                this.closeRecipientAutocomplete();
            }
        } else if (event.key === 'Escape') {
            event.preventDefault();
            this.closeRecipientAutocomplete();
        }
    }

    highlightRecipientAutocompleteItem(items) {
        items.forEach((item, index) => {
            if (index === this.recipientAutocompleteHighlightedIndex) {
                item.classList.add('highlighted');
                item.scrollIntoView({ block: 'nearest' });
            } else {
                item.classList.remove('highlighted');
            }
        });
    }

    closeRecipientAutocomplete() {
        const dropdown = document.getElementById('recipient-autocomplete-dropdown');
        if (dropdown) {
            dropdown.classList.add('hidden');
            dropdown.innerHTML = '';
        }
        this.recipientAutocompleteHighlightedIndex = -1;
    }

    // ==========================================================================
    // PAYROLL & DEDUCTIONS SYSTEM (OPTION 3)
    // ==========================================================================

    initPayrollTab() {
        const select = document.getElementById('payroll-month-select');
        if (select && !select.value) {
            const now = new Date();
            const year = now.getFullYear();
            const month = String(now.getMonth() + 1).padStart(2, '0');
            select.value = `${year}-${month}`;
        }

        const plantSelect = document.getElementById('payroll-plant-select');
        if (plantSelect) {
            if (this.currentUser && this.currentUser.plant) {
                plantSelect.value = this.currentUser.plant;
            } else {
                plantSelect.value = 'All';
            }
            plantSelect.style.display = 'none';
            const customContainer = document.getElementById('custom-select-payroll-plant-select');
            if (customContainer) {
                customContainer.style.display = 'none';
            }
            const label = document.querySelector('label[for="payroll-plant-select"]');
            if (label) {
                label.style.display = 'none';
            }
        }

        this.generatePayrollPreview();
        this.loadPayrollHistory();
    }

    async generatePayrollPreview() {
        const select = document.getElementById('payroll-month-select');
        if (!select) return;
        const month = select.value;
        if (!month) return;

        try {
            const plantSelect = document.getElementById('payroll-plant-select');
            const plant = (this.currentUser && this.currentUser.plant) ? this.currentUser.plant : (plantSelect ? plantSelect.value : 'All');
            const res = await fetch(`/api/payroll/summary?month=${month}&plant=${plant}`);
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();

            // Render summary table
            const tbody = document.getElementById('payroll-summary-table-body');
            if (tbody) {
                tbody.innerHTML = '';
                if (!data.employees || data.employees.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted">No bookings found for this month.</td></tr>`;
                } else {
                    data.employees.forEach(emp => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td>${emp.employeeName}</td>
                            <td>${emp.psNumber}</td>
                            <td><span class="badge ${emp.role === 'ADMIN' ? 'badge-primary' : 'badge-secondary'}">${emp.role}</span></td>
                            <td>${emp.totalRides}</td>
                            <td class="font-semibold text-warning">₹${emp.totalAmount}</td>
                        `;
                        tbody.appendChild(tr);
                    });
                    // Append total row
                    const totalTr = document.createElement('tr');
                    totalTr.style.fontWeight = 'bold';
                    totalTr.style.background = 'rgba(255,255,255,0.05)';
                    totalTr.innerHTML = `
                        <td colspan="3">Total Summary</td>
                        <td>${data.totals.totalRides}</td>
                        <td class="text-warning">₹${data.totals.totalAmount}</td>
                    `;
                    tbody.appendChild(totalTr);
                }
                addMobileTableLabels('#payroll-summary-table-body');
            }

            // Manage buttons and banners based on status
            const btnGenerate = document.getElementById('payroll-btn-generate');
            const btnExport = document.getElementById('payroll-btn-export');
            const btnProcess = document.getElementById('payroll-btn-process');
            const btnUnlock = document.getElementById('payroll-btn-unlock');
            const banner = document.getElementById('payroll-status-banner');

            if (data.status === 'PENDING') {
                if (btnGenerate) btnGenerate.classList.remove('hidden');
                if (btnExport) btnExport.classList.add('hidden');
                if (btnProcess) btnProcess.classList.add('hidden');
                if (btnUnlock) btnUnlock.classList.add('hidden');
                if (banner) {
                    banner.className = 'alert alert-info mb-3';
                    banner.innerHTML = `No payroll cycle generated for this month yet. Previewing live booking totals.`;
                }
            } else if (data.status === 'GENERATED_PENDING') {
                if (btnGenerate) btnGenerate.classList.add('hidden');
                if (btnExport) btnExport.classList.remove('hidden');
                if (btnProcess) btnProcess.classList.remove('hidden');
                if (btnUnlock) btnUnlock.classList.add('hidden');
                if (banner) {
                    banner.className = 'alert alert-warning mb-3';
                    banner.innerHTML = `Draft report locked in database, dynamic calculations are active, and cancellations will automatically deduct entries live.`;
                }
            } else if (data.status === 'PROCESSED') {
                if (btnGenerate) btnGenerate.classList.add('hidden');
                if (btnExport) btnExport.classList.remove('hidden');
                if (btnProcess) btnProcess.classList.add('hidden');
                if (btnUnlock) btnUnlock.classList.remove('hidden');
                if (banner) {
                    banner.className = 'alert alert-success mb-3';
                    banner.innerHTML = `This payroll period has been processed and locked. Bookings are frozen. Export the Excel report to send to HR.`;
                }
            }
        } catch (err) {
            console.error('Error generating payroll preview:', err);
            this.showLiveToast('Failed to generate payroll preview.', 'Error');
        }
    }

    async generatePayrollReport() {
        const select = document.getElementById('payroll-month-select');
        if (!select) return;
        const month = select.value;
        if (!month) return;

        if (!confirm(`Are you sure you want to generate and lock the draft payroll cycle for ${month}?`)) {
            return;
        }

        try {
            const res = await fetch('/api/payroll/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    month: month,
                    adminPsNumber: this.currentUser ? this.currentUser.psNumber : 'ADMIN'
                })
            });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();

            this.showLiveToast('Payroll report generated successfully.', 'Success');
            this.generatePayrollPreview();
            this.loadPayrollHistory();
        } catch (err) {
            console.error('Error generating payroll report:', err);
            this.showLiveToast('Failed to generate payroll report.', 'Error');
        }
    }

    async loadPayrollHistory() {
        try {
            const res = await fetch('/api/payroll/periods');
            if (!res.ok) throw new Error(await res.text());
            const periods = await res.json();

            const tbody = document.getElementById('payroll-history-table-body');
            if (tbody) {
                tbody.innerHTML = '';
                if (periods.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">No history found.</td></tr>`;
                } else {
                    periods.forEach(p => {
                        const tr = document.createElement('tr');
                        const statusBadge = p.status === 'PROCESSED' 
                            ? '<span class="badge badge-success">PROCESSED</span>' 
                            : '<span class="badge badge-warning">PENDING</span>';
                        
                        tr.innerHTML = `
                            <td>${p.periodMonth}</td>
                            <td class="font-semibold">₹${parseFloat(p.totalAmount).toLocaleString('en-IN')}</td>
                            <td>${statusBadge}</td>
                            <td>
                                <button class="btn btn-primary btn-sm" onclick="app.viewPayrollHistoryMonth('${p.periodMonth}')">View</button>
                            </td>
                        `;
                        tbody.appendChild(tr);
                    });
                }
                addMobileTableLabels('#payroll-history-table-body');
            }
        } catch (err) {
            console.error('Error loading payroll history:', err);
        }
    }

    viewPayrollHistoryMonth(month) {
        const select = document.getElementById('payroll-month-select');
        if (select) {
            select.value = month;
            select.dispatchEvent(new Event('change'));
        }
    }

    async markPayrollProcessed() {
        const select = document.getElementById('payroll-month-select');
        if (!select) return;
        const month = select.value;
        if (!month) return;

        const notes = prompt("Enter any remarks/notes for this payroll processing cycle (optional):");
        if (notes === null) return; // cancelled

        const periodId = `payroll_${month.replace('-', '_')}`;
        const plantSelect = document.getElementById('payroll-plant-select');
        const plant = (this.currentUser && this.currentUser.plant) ? this.currentUser.plant : (plantSelect ? plantSelect.value : 'All');

        try {
            const res = await fetch(`/api/payroll/period/${periodId}/mark-processed`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    adminPsNumber: this.currentUser ? this.currentUser.psNumber : 'ADMIN',
                    notes: notes,
                    plant: plant
                })
            });
            if (!res.ok) throw new Error(await res.text());

            this.showLiveToast(`Payroll period ${month} marked as processed and locked.`, 'Locked');
            this.generatePayrollPreview();
            this.loadPayrollHistory();
        } catch (err) {
            console.error('Error marking payroll processed:', err);
            this.showLiveToast('Failed to process payroll period.', 'Error');
        }
    }

    async unlockPayrollPeriod() {
        const select = document.getElementById('payroll-month-select');
        if (!select) return;
        const month = select.value;
        if (!month) return;

        if (!confirm(`⚠️ WARNING: Unlocking this payroll period will allow employees to book and cancel seats for ${month} again. \n\nAre you sure you want to unlock this period?`)) {
            return;
        }

        const periodId = `payroll_${month.replace('-', '_')}`;
        const plantSelect = document.getElementById('payroll-plant-select');
        const plant = (this.currentUser && this.currentUser.plant) ? this.currentUser.plant : (plantSelect ? plantSelect.value : 'All');

        try {
            const res = await fetch(`/api/payroll/period/${periodId}/unlock`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    adminPsNumber: this.currentUser ? this.currentUser.psNumber : 'ADMIN',
                    plant: plant
                })
            });
            if (!res.ok) throw new Error(await res.text());

            this.showLiveToast(`Payroll period ${month} unlocked successfully. Bookings are unfrozen.`, 'Unlocked');
            this.generatePayrollPreview();
            this.loadPayrollHistory();
        } catch (err) {
            console.error('Error unlocking payroll period:', err);
            this.showLiveToast('Failed to unlock payroll period.', 'Error');
        }
    }

    exportPayrollExcel() {
        const select = document.getElementById('payroll-month-select');
        if (!select) return;
        const month = select.value;
        if (!month) return;

        const plantSelect = document.getElementById('payroll-plant-select');
        const plant = (this.currentUser && this.currentUser.plant) ? this.currentUser.plant : (plantSelect ? plantSelect.value : 'All');

        const periodId = `payroll_${month.replace('-', '_')}`;
        window.location.href = `/api/payroll/period/${periodId}/export?plant=${plant}`;
    }

    async loadMyFares() {
        const select = document.getElementById('myfares-month-select');
        if (select && !select.value) {
            const now = new Date();
            const year = now.getFullYear();
            const month = String(now.getMonth() + 1).padStart(2, '0');
            select.value = `${year}-${month}`;
        }
        const month = select ? select.value : '';
        if (!month || !this.currentUser) return;

        try {
            const res = await fetch(`/api/payroll/my-fares?psNumber=${this.currentUser.psNumber}&month=${month}`);
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();

            // Update KPIs
            document.getElementById('myfares-kpi-rides').textContent = data.totalRides;
            document.getElementById('myfares-kpi-amount').textContent = `₹${data.totalAmount}`;
            
            const statusCard = document.getElementById('myfares-kpi-status-card');
            if (statusCard) {
                let pillStyle = '';
                let pillText = '';
                let headerText = 'Deduction Status';
                
                switch (data.deductionStatus) {
                    case 'NO_TRIPS':
                        pillStyle = 'bg-slate-50 border border-slate-200 text-slate-500';
                        pillText = 'No Rides Recorded';
                        headerText = 'DEDUCTION STATUS';
                        break;
                    case 'NOT_GENERATED':
                        pillStyle = 'bg-slate-100 text-slate-600';
                        pillText = 'Not Generated';
                        break;
                    case 'PENDING':
                        pillStyle = 'bg-amber-50 border border-amber-200 text-amber-700';
                        pillText = 'Pending Deduction';
                        break;
                    case 'DEDUCTED':
                        pillStyle = 'bg-emerald-50 border border-emerald-200 text-emerald-700';
                        pillText = 'Deducted from Salary';
                        break;
                    default:
                        pillStyle = 'bg-slate-100 text-slate-600';
                        pillText = data.deductionStatus || 'Not Generated';
                        break;
                }
                
                statusCard.innerHTML = `
                    <span class="kpi-label block mb-2">${headerText}</span>
                    <span class="font-semibold text-xs tracking-wide rounded-full px-3 py-1 inline-block ${pillStyle}">${pillText}</span>
                `;
            }

            // Render rides list
            const tbody = document.getElementById('myfares-table-body');
            if (tbody) {
                tbody.innerHTML = '';
                if (!data.bookings || data.bookings.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No bookings found for this month.</td></tr>`;
                } else {
                    data.bookings.forEach(b => {
                        const tr = document.createElement('tr');
                        const boardingStop = this.resolveStopName(b.shiftId, b.boardingStopIndex);
                        const dropStop = this.resolveStopName(b.shiftId, b.dropStopIndex);
                        tr.innerHTML = `
                            <td>${b.travelDate}</td>
                            <td>${b.shiftId}</td>
                            <td>Seat ${b.seatNumber}</td>
                            <td>${boardingStop}</td>
                            <td>${dropStop}</td>
                            <td class="font-semibold text-warning">₹${b.fareAmount}</td>
                        `;
                        tbody.appendChild(tr);
                    });
                }
                addMobileTableLabels('#myfares-table-body');
            }
        } catch (err) {
            console.error('Error loading my fares:', err);
        }
    }

    resolveStopName(shiftId, stopIndex) {
        const shifts = this.getItems('utcl_shifts');
        const shift = shifts.find(s => s.id === shiftId);
        if (shift && shift.stops) {
            let stopsList = [];
            try {
                stopsList = typeof shift.stops === 'string' ? JSON.parse(shift.stops) : shift.stops;
            } catch(e) {}
            if (stopsList && stopsList[stopIndex]) {
                return stopsList[stopIndex].name || stopsList[stopIndex];
            }
        }
        return `Stop #${stopIndex}`;
    }

    setupEventListeners() {
        // Reset activity timers on interactions
        const resetActivity = () => this.resetInactivityTimer();
        window.addEventListener('mousemove', resetActivity);
        window.addEventListener('keypress', resetActivity);
        window.addEventListener('click', resetActivity);
        window.addEventListener('scroll', resetActivity);

        // Click outside dropdowns closes them
        window.addEventListener('click', (e) => {
            const drop = document.getElementById('notification-dropdown');
            if (drop) drop.classList.add('hidden');

            const profileDrop = document.getElementById('profile-dropdown');
            const profileTrigger = document.getElementById('profile-dropdown-trigger');
            if (profileDrop && !profileDrop.contains(e.target) && (!profileTrigger || !profileTrigger.contains(e.target))) {
                profileDrop.classList.add('hidden');
            }

            const historyInput = document.getElementById('history-ps-number');
            const historyDropdown = document.getElementById('history-autocomplete-dropdown');
            if (historyDropdown && !historyDropdown.contains(e.target) && e.target !== historyInput) {
                this.closeHistoryAutocomplete();
            }

            const driverHistoryInput = document.getElementById('driver-history-ps-number');
            const driverHistoryDropdown = document.getElementById('driver-history-autocomplete-dropdown');
            if (driverHistoryDropdown && !driverHistoryDropdown.contains(e.target) && e.target !== driverHistoryInput) {
                this.closeDriverHistoryAutocomplete();
            }

            const recipientInput = document.getElementById('notification-recipient-search');
            const recipientDropdown = document.getElementById('recipient-autocomplete-dropdown');
            if (recipientDropdown && !recipientDropdown.contains(e.target) && e.target !== recipientInput) {
                this.closeRecipientAutocomplete();
            }
        });

        // Proactively release held seats on page refresh/unload
        window.addEventListener('beforeunload', () => {
            if (this.bookingData && this.bookingData.seatNumbers && this.bookingData.seatNumbers.length > 0) {
                const payload = JSON.stringify({
                    shiftId: this.bookingData.shiftId,
                    date: this.bookingData.date,
                    seatNumbers: this.bookingData.seatNumbers
                });
                const blob = new Blob([payload], { type: 'application/json' });
                navigator.sendBeacon('/api/booking/release-holds', blob);
            }
        });
    }
}

// Instantiate and bind to global context
window.addEventListener('DOMContentLoaded', async () => {
    try {
        const response = await fetch('/api/data');
        if (response.ok) {
            const data = await response.json();
            // Store each table from the API into localStorage
            Object.keys(data).forEach(key => {
                localStorage.setItem(key, JSON.stringify(data[key]));
            });
            console.log('Database synced from MySQL backend successfully.');
        } else {
            console.error('Failed to load database from API. Using local cache.');
        }
    } catch (err) {
        console.error('Error fetching database from API. Using local cache:', err);
    }
    window.app = new UTCLBusSystem();
});
