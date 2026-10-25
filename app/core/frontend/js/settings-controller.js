/* Settings account/security controller. Each full or boosted visit owns its effects. */
(function () {
  'use strict';
  window.bize.onPage('.settings-overview', function (root) {
    const controller = new AbortController();
    // A full navigation away (Back reloads from the server) also cuts this page's requests off;
    // abort first so they end quietly instead of being logged as failures.
    window.addEventListener('pagehide', () => controller.abort(), { once: true, signal: controller.signal });
    const timeouts = new Set();
    const intervals = new Set();
    const originalPageFetch = window.fetch;
    const previousGlobals = {
      loadSettings: window.loadSettings,
      saveSettings: window.saveSettings,
      showSessionTimeoutModal: window.showSessionTimeoutModal
    };
    function eventTarget(target) {
      return { addEventListener(type, listener, options) {
        target.addEventListener(type, listener, {...(options || {}), signal: controller.signal});
      }};
    }
    const transients = new Set();
    // Only this controller's requests are canceled on navigation; shell requests remain independent.
    async function settingsRequest(input, options) {
      const headers = new Headers(options?.headers);
      if (!['GET', 'HEAD'].includes((options?.method || 'GET').toUpperCase())) {
        headers.set('X-CSRFToken', document.querySelector('meta[name="csrf-token"]')?.content || '');
      }
      const response = await window.fetch(input, {...(options || {}), headers, signal: controller.signal});
      controller.signal.throwIfAborted();
      return new Proxy(response, {
        get(target, property) {
          if (property === 'json') return async function () {
            const data = await target.json();
            controller.signal.throwIfAborted();
            return data;
          };
          const value = target[property];
          return typeof value === 'function' ? value.bind(target) : value;
        }
      });
    }
    const pageDocument = eventTarget(document);
    const pageWindow = eventTarget(window);
    function setTimeout(callback, delay) {
      const id = window.setTimeout(() => { timeouts.delete(id); callback(); }, delay);
      timeouts.add(id);
      return id;
    }
    function setInterval(callback, delay) {
      const id = window.setInterval(callback, delay);
      intervals.add(id);
      return id;
    }
    if (window.initAccountInfo) window.initAccountInfo('account-info-container');
    // Check if page loaded due to session timeout redirect
    (function() {
      // Check URL for session_expired parameter
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('session_expired') === 'true') {
        // Remove the parameter from URL (clean URL)
        const newUrl = window.location.pathname;
        window.history.replaceState({}, '', newUrl);
        // Show modal after a brief delay to ensure DOM is ready
        setTimeout(() => {
          showSessionTimeoutModal();
        }, 100);
        return;
      }

      // Check on DOM ready if the page content is a JSON error
      if (document.readyState === 'loading') {
        pageDocument.addEventListener('DOMContentLoaded', checkForJsonError);
      } else {
        checkForJsonError();
      }

      function checkForJsonError() {
        // Check if the page body contains only JSON error (session expired)
        const bodyText = document.body ? document.body.textContent.trim() : '';
        if (bodyText.startsWith('{') && bodyText.includes('"error"') && bodyText.includes('Session expired')) {
          // Clear the page content and show modal
          document.body.innerHTML = '';
          showSessionTimeoutModal();
          return;
        }
      }

      // Also check when page becomes visible (user switches back to tab)
      pageDocument.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
          // Page became visible - check session status
          setTimeout(async () => {
            try {
              const response = await settingsRequest('/auth/me', {
                method: 'GET',
                credentials: 'include'
              });
              if (response.status === 401) {
                const path = window.location.pathname;
                if (path !== '/' && !path.includes('login')) {
                  showSessionTimeoutModal();
                }
              }
            } catch (error) {
        if (controller.signal.aborted) return;
              // Silently handle
            }
          }, 100);
        }
      });
    })();

    // Global error handler to catch and suppress 401-related errors
    pageWindow.addEventListener('error', function(event) {
      // Suppress errors related to session timeout
      if (event.message && (
        event.message.includes('Session expired') ||
        event.message.includes('401') ||
        event.message.includes('Unauthorized')
      )) {
        event.preventDefault();
        // Show modal if not already showing
        const modal = document.getElementById('sessionTimeoutModal');
        if (modal && !modal.classList.contains('active')) {
          showSessionTimeoutModal();
        }
        return false;
      }
    });

    // Catch unhandled promise rejections (often from failed fetch calls)
    pageWindow.addEventListener('unhandledrejection', function(event) {
      // Suppress rejections related to 401/session timeout
      const reason = event.reason;
      if (reason && (
        (typeof reason === 'string' && (reason.includes('401') || reason.includes('Session expired'))) ||
        (reason.status === 401) ||
        (reason.message && (reason.message.includes('401') || reason.message.includes('Session expired')))
      )) {
        event.preventDefault();
        // Show modal if not already showing
        const modal = document.getElementById('sessionTimeoutModal');
        if (modal && !modal.classList.contains('active')) {
          showSessionTimeoutModal();
        }
      }
    });

    // 2FA Management
    let current2FAStatus = false;
    let enrollmentSecret = null;
    let enrollmentInProgress = false;  // Prevent multiple enrollment modals
    let twoFactorRequired = false;          // Admin policy: can't be disabled
    let twoFactorEnrollmentRequired = false; // Admin without 2FA: everything else is blocked
    let autoEnrollmentOffered = false;

    // Check for incomplete enrollment on page load
    async function checkIncompleteEnrollment() {
      const incompleteFlag = localStorage.getItem('2fa_enrollment_incomplete');
      const storedStep = sessionStorage.getItem('2fa_enrollment_step');
      const storedCodes = sessionStorage.getItem('2fa_backup_codes');

      if (incompleteFlag === 'true' || (storedStep === '4' && storedCodes)) {
        // Check server state to see if 2FA is actually enabled
        try {
          const response = await settingsRequest('/auth/me', { credentials: 'include' });
          if (response.ok) {
            const data = await response.json();
            if (data.user?.two_factor_enabled) {
              // 2FA is enabled - check if we have backup codes to restore
              if (storedStep === '4' && storedCodes) {
                try {
                  const codes = JSON.parse(storedCodes);
                  // Restore enrollment state
                  backupCodes = codes;
                  enrollmentCompleted = false;
                  closeDynamicModals();
                  document.getElementById('2fa-enrollment-modal').classList.add('active');
                  displayBackupCodes(codes);
                  show2FAStep(4);
                  showErrorNotification('⚠️ IMPORTANT: You were viewing your backup codes. Please confirm you have saved them before closing this window.');
                } catch (e) {
        if (controller.signal.aborted) return;
                  // Failed to restore backup codes - don't log sensitive data
                  showWarningAboutIncompleteEnrollment();
                }
              } else {
                // 2FA enabled but no backup codes in storage
                showWarningAboutIncompleteEnrollment();
              }
            } else {
              // 2FA not enabled - clear flags (enrollment was cancelled)
              localStorage.removeItem('2fa_enrollment_incomplete');
              sessionStorage.removeItem('2fa_enrollment_step');
              sessionStorage.removeItem('2fa_backup_codes');
            }
          }
        } catch (error) {
        if (controller.signal.aborted) return;
          // Don't log error object - may contain sensitive data
          console.error('Error checking enrollment state');
          // On error, show warning but don't clear flags
          if (incompleteFlag === 'true') {
            showWarningAboutIncompleteEnrollment();
          }
        }
      }
    }

    function showWarningAboutIncompleteEnrollment() {
      setTimeout(() => {
        const confirmed = confirm(
          '⚠️ WARNING: A previous 2FA enrollment may not have completed properly.\n\n' +
          'If you did not save your backup codes, you may be locked out of your account.\n\n' +
          'Please check your 2FA status in settings and contact support if needed.\n\n' +
          'Click OK to clear this warning.'
        );
        if (confirmed) {
          localStorage.removeItem('2fa_enrollment_incomplete');
          sessionStorage.removeItem('2fa_enrollment_step');
          sessionStorage.removeItem('2fa_backup_codes');
        }
      }, 1000);
    }

    // Handle 401 responses globally — installed before initial fetch calls so all requests are covered
    (function() {
      const originalFetch = window.fetch;
      window.fetch = async function(...args) {
        try {
          const response = await originalFetch.apply(this, args);

          // Check for 401 responses (session expired) - do this BEFORE any JSON parsing
          if (!controller.signal.aborted && response.status === 401) {
            // Get the URL from args (could be string or Request object)
            const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || args[0]?.href || '');
            const path = window.location.pathname;

            // Only show modal for authenticated endpoints, not login/signup
            const isAuthEndpoint = url.includes('/auth/login') || url.includes('/auth/signup');
            const isLandingPage = path === '/' || path.includes('login');

            if (!isAuthEndpoint && !isLandingPage) {
              // Session expired - show modal IMMEDIATELY

              // Show modal right away
              showSessionTimeoutModal();

              // Wrap response to prevent JSON parsing errors from displaying
              // Use Proxy to intercept .json() calls and return empty object
              const wrappedResponse = new Proxy(response, {
                get: function(target, prop) {
                  if (prop === 'json') {
                    // Return a function that returns empty object instead of parsing
                    return async function() {
                      return {};
                    };
                  }
                  // Return all other properties/methods normally
                  const value = target[prop];
                  return typeof value === 'function' ? value.bind(target) : value;
                }
              });

              // Return the wrapped response - prevents JSON parsing errors
              return wrappedResponse;
            }
          }

          return response;
        } catch (error) {
          // Re-throw the error
          throw error;
        }
      };
    })();

    // Check on page load
    checkIncompleteEnrollment();

    // Load settings on page load
    async function loadSettings() {
      const status = document.getElementById('settings-load-status');
      const retry = document.getElementById('settings-load-retry');
      const controls = ['settings-first-name', 'settings-last-name', 'settings-email', 'settings-phone', 'settings-save-btn']
        .map(id => document.getElementById(id)).filter(Boolean);
      controls.forEach(control => { control.disabled = true; });
      if (status) { status.hidden = false; status.textContent = 'Loading your account…'; }
      if (retry) retry.hidden = true;
      try {
        const response = await settingsRequest('/auth/settings', {
          method: 'GET',
          credentials: 'include'
        });

        // Check for 401 before parsing JSON
        if (response.status === 401) {
          const path = window.location.pathname;
          if (path !== '/' && !path.includes('login')) {
            showSessionTimeoutModal();
            return;
          }
        }

        if (!response.ok) throw new Error('Account unavailable');
        if (response.ok) {
          const data = await response.json();
          const orgNameInput = document.getElementById('settings-org-name');
          const firstNameInput = document.getElementById('settings-first-name');
          const lastNameInput = document.getElementById('settings-last-name');
          const emailInput = document.getElementById('settings-email');
          const phoneInput = document.getElementById('settings-phone');

          if (orgNameInput) orgNameInput.value = data.org_name || '';
          if (firstNameInput) firstNameInput.value = data.first_name || '';
          if (lastNameInput) lastNameInput.value = data.last_name || '';
          if (emailInput) emailInput.value = data.email || '';
          if (phoneInput) phoneInput.value = data.phone_number || '';
          controls.forEach(control => { control.disabled = false; });
          if (status) status.hidden = true;
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        if (status) status.textContent = 'Your account could not load. Retry before editing your details.';
        if (retry) retry.hidden = false;
      }
    }

    // Save settings
    async function saveSettings() {
      const emailInput = document.getElementById('settings-email');
      const firstNameInput = document.getElementById('settings-first-name');
      const lastNameInput = document.getElementById('settings-last-name');
      const phoneInput = document.getElementById('settings-phone');
      const saveBtn = document.getElementById('settings-save-btn');
      const messageDiv = document.getElementById('settings-message');
      const phoneErrorDiv = document.getElementById('settings-phone-error');

      if (!emailInput || !phoneInput || !firstNameInput || !lastNameInput || !saveBtn) return;

      const email = emailInput.value.trim();
      let phoneNumber = phoneInput.value.trim();
      const firstName = firstNameInput.value.trim();
      const lastName = lastNameInput.value.trim();

      // Hide previous messages
      if (messageDiv) messageDiv.style.display = 'none';
      if (phoneErrorDiv) phoneErrorDiv.style.display = 'none';

      // Validate email
      if (!email || !email.includes('@')) {
        if (messageDiv) {
          messageDiv.textContent = 'Please enter a valid email address';
          messageDiv.style.display = 'block';
          messageDiv.style.background = 'rgba(239, 68, 68, 0.1)';
          messageDiv.style.border = '1px solid rgba(239, 68, 68, 0.3)';
          messageDiv.style.color = '#ef4444';
        }
        return;
      }

      // Validate name lengths (server-side also enforces this)
      if (firstName.length > 255) {
        if (messageDiv) {
          messageDiv.textContent = 'First name must be 255 characters or fewer';
          messageDiv.style.display = 'block';
          messageDiv.style.background = 'rgba(239, 68, 68, 0.1)';
          messageDiv.style.border = '1px solid rgba(239, 68, 68, 0.3)';
          messageDiv.style.color = '#ef4444';
        }
        return;
      }
      if (lastName.length > 255) {
        if (messageDiv) {
          messageDiv.textContent = 'Last name must be 255 characters or fewer';
          messageDiv.style.display = 'block';
          messageDiv.style.background = 'rgba(239, 68, 68, 0.1)';
          messageDiv.style.border = '1px solid rgba(239, 68, 68, 0.3)';
          messageDiv.style.color = '#ef4444';
        }
        return;
      }

      // Validate phone number if provided (6-15 digits only)
      if (phoneNumber) {
        const phoneDigits = phoneNumber.replace(/\D/g, ''); // Remove non-digits
        if (phoneDigits.length < 6 || phoneDigits.length > 15) {
          if (phoneErrorDiv) {
            phoneErrorDiv.textContent = 'Phone number must be 6-15 digits';
            phoneErrorDiv.style.display = 'block';
          }
          return;
        }
        phoneNumber = phoneDigits; // Store only digits
      }

      // Disable save button
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';

      try {
        const response = await settingsRequest('/auth/settings', {
          method: 'PUT',
          headers: {
            'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
              'Content-Type': 'application/json',
          },
          credentials: 'include',
          body: JSON.stringify({
            email: email,
            first_name: firstName,
            last_name: lastName,
            phone_number: phoneNumber || ''
          })
        });

        // Check for 401 before parsing JSON
        if (response.status === 401) {
          const path = window.location.pathname;
          if (path !== '/' && !path.includes('login')) {
            showSessionTimeoutModal();
            return;
          }
        }

        const data = await response.json();

        if (response.ok) {
          // Success - update UI and show message
          if (firstNameInput) firstNameInput.value = data.first_name || '';
          if (lastNameInput) lastNameInput.value = data.last_name || '';
          if (phoneInput) phoneInput.value = data.phone_number || '';
          if (messageDiv) {
            messageDiv.textContent = data.message || 'Settings saved successfully';
            messageDiv.style.display = 'block';
            messageDiv.style.background = 'rgba(34, 197, 94, 0.1)';
            messageDiv.style.border = '1px solid rgba(34, 197, 94, 0.3)';
            messageDiv.style.color = '#22c55e';
          }
        } else if (response.status === 409) {
          // Email conflict - show clear, actionable message
          if (messageDiv) {
            messageDiv.textContent = data.error || 'This email address is already in use. Please choose a different email.';
            messageDiv.style.display = 'block';
            messageDiv.style.background = 'rgba(239, 68, 68, 0.1)';
            messageDiv.style.border = '1px solid rgba(239, 68, 68, 0.3)';
            messageDiv.style.color = '#ef4444';
          }
          // Don't update UI state - keep original email value
        } else {
          // Other errors
          if (messageDiv) {
            messageDiv.textContent = data.error || 'Failed to save settings';
            messageDiv.style.display = 'block';
            messageDiv.style.background = 'rgba(239, 68, 68, 0.1)';
            messageDiv.style.border = '1px solid rgba(239, 68, 68, 0.3)';
            messageDiv.style.color = '#ef4444';
          }
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error('Error saving settings:', error);
        if (messageDiv) {
          messageDiv.textContent = 'Network error. Please try again.';
          messageDiv.style.display = 'block';
          messageDiv.style.background = 'rgba(239, 68, 68, 0.1)';
          messageDiv.style.border = '1px solid rgba(239, 68, 68, 0.3)';
          messageDiv.style.color = '#ef4444';
        }
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save changes';
      }
    }

    window.loadSettings = loadSettings;
    window.saveSettings = saveSettings;
    // Load settings on page load
    loadSettings();

    // Load 2FA status on page load
    async function load2FAStatus() {
      try {
        const response = await settingsRequest('/auth/me', {
          method: 'GET',
          credentials: 'include'
        });

        // Check for 401 before parsing JSON
        if (response.status === 401) {
          const path = window.location.pathname;
          if (path !== '/' && !path.includes('login')) {
            showSessionTimeoutModal();
            return;
          }
        }

        if (response.ok) {
          const data = await response.json();
          if (data.user) {
            current2FAStatus = data.user.two_factor_enabled || false;
            twoFactorRequired = !!data.user.two_factor_required;
            twoFactorEnrollmentRequired = !!data.user.two_factor_enrollment_required;
            update2FAUI();
            if (twoFactorEnrollmentRequired && !autoEnrollmentOffered) {
              // Open enrolment straight away: nothing else works until it's done.
              autoEnrollmentOffered = true;
              const enableBtn = document.getElementById('enable-2fa-btn');
              if (enableBtn) enableBtn.click();
            }
          }
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        // Don't log error object - may contain sensitive data
        console.error('Error loading 2FA status');
      }
    }

    function update2FAUI() {
      const statusValue = document.getElementById('2fa-status-value');
      const enableBtn = document.getElementById('enable-2fa-btn');
      const disableBtn = document.getElementById('disable-2fa-btn');

      const requiredBanner = document.getElementById('2fa-required-banner');
      if (requiredBanner) requiredBanner.hidden = !(twoFactorRequired && !current2FAStatus);
      if (current2FAStatus) {
        statusValue.textContent = twoFactorRequired ? 'Enabled (required for administrators)' : 'Enabled';
        statusValue.style.color = 'var(--azure-blue)';
        enableBtn.style.display = 'none';
        disableBtn.style.display = twoFactorRequired ? 'none' : 'block';
      } else {
        statusValue.textContent = 'Disabled';
        statusValue.style.color = 'var(--text-secondary)';
        enableBtn.style.display = 'block';
        disableBtn.style.display = 'none';
      }
      const mins = lastKnownSessionTimeoutMinutes != null
        ? lastKnownSessionTimeoutMinutes
        : (function() {
            const input = document.getElementById('session-timeout-input');
            const unitSelect = document.getElementById('session-timeout-unit');
            return (input && unitSelect) ? sessionTimeoutToMinutes(input.value, unitSelect.value) : null;
          })();
      if (mins != null) updateLongSessionBanner(mins);
    }

    // Display QR code from backend (generated server-side)
    function displayQRCode(container, qrCodeDataUrl) {
      if (!qrCodeDataUrl) {
        container.innerHTML = '<p style="color: #ef4444; padding: 1rem; text-align: center;">No QR code data received. Please use the manual code below.</p>';
        return;
      }

      const img = document.createElement('img');
      img.src = qrCodeDataUrl;
      img.alt = 'QR Code for 2FA Setup';
      img.style.width = '256px';
      img.style.height = '256px';
      img.style.display = 'block';
      img.style.margin = '0 auto';

      // Add error handler for image loading
      img.onerror = function(e) {
        // Don't log error object - may contain sensitive QR code data
        console.error('Error loading QR code image');
        container.innerHTML = '<p style="color: #ef4444; padding: 1rem; text-align: center;">Error displaying QR code image. Please use the manual code below.</p>';
      };

      img.onload = function() {
        // QR code image loaded successfully
      };

      container.innerHTML = '';
      container.appendChild(img);
    }

    // Enable 2FA - Start enrollment
    document.getElementById('enable-2fa-btn').addEventListener('click', async function() {
      // CRITICAL: Prevent multiple enrollment modals
      if (enrollmentInProgress) {
        return;
      }

      enrollmentInProgress = true;
      const enableBtn = this;
      enableBtn.disabled = true;

      try {
        const response = await settingsRequest('/auth/2fa/enroll', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
              'Content-Type': 'application/json'
          }
        });

        // Check for 401 before parsing JSON
        if (response.status === 401) {
          const path = window.location.pathname;
          if (path !== '/' && !path.includes('login')) {
            showSessionTimeoutModal();
            return;
          }
        }

        if (response.ok) {
          const data = await response.json();

          enrollmentSecret = data.secret;

          // Display QR code from backend
          const qrContainer = document.getElementById('qrcode-container');

          if (data.qr_code) {
            displayQRCode(qrContainer, data.qr_code);
          } else {
            console.error('No QR code in response');
            qrContainer.innerHTML = '<p style="color: #ef4444; padding: 1rem;">No QR code data received. Please use the manual code below.</p>';
          }

          // Display secret text
          document.getElementById('2fa-secret-text').textContent = enrollmentSecret;

          // Show modal and reset to step 1 (close any other dynamic modal first)
          closeDynamicModals();
          document.getElementById('2fa-enrollment-modal').classList.add('active');
          show2FAStep(1);
        } else {
          // Check for 401 before parsing JSON
          if (response.status === 401) {
            const path = window.location.pathname;
            if (path !== '/' && !path.includes('login')) {
              showSessionTimeoutModal();
              return;
            }
          }
          const error = await response.json();
          alert('Error: ' + (error.error || 'Failed to start 2FA enrollment'));
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        // Don't log error object - may contain sensitive secret data
        console.error('Error enrolling in 2FA');
        alert('Error: Failed to start 2FA enrollment. Please try again.');
      } finally {
        enrollmentInProgress = false;
        enableBtn.disabled = false;
      }
    });

    // Store backup codes temporarily
    let backupCodes = null;
    let enrollmentCompleted = false;

    // Step navigation functions
    function show2FAStep(step) {
      document.getElementById('2fa-enrollment-step1').style.display = step === 1 ? 'flex' : 'none';
      document.getElementById('2fa-enrollment-step2').style.display = step === 2 ? 'flex' : 'none';
      document.getElementById('2fa-enrollment-step3').style.display = step === 3 ? 'flex' : 'none';
      document.getElementById('2fa-enrollment-step4').style.display = step === 4 ? 'flex' : 'none';

      // Clear all inputs and errors (but preserve firstToken when moving to step 3)
      if (step !== 3) {
        document.getElementById('2fa-verification-code-1').value = '';
      }
      if (step !== 4) {
        document.getElementById('2fa-verification-code-2').value = '';
      }
      document.getElementById('2fa-error').style.display = 'none';
      document.getElementById('2fa-error').textContent = '';
      document.getElementById('2fa-error-step3').style.display = 'none';
      document.getElementById('2fa-error-step3').textContent = '';

      // Focus on the current input
      if (step === 2) {
        setTimeout(() => document.getElementById('2fa-verification-code-1').focus(), 100);
      } else if (step === 3) {
        setTimeout(() => document.getElementById('2fa-verification-code-2').focus(), 100);
      }
    }

    // Start verification button - move to step 2
    document.getElementById('2fa-start-verification-btn').addEventListener('click', function() {
      show2FAStep(2);
    });

    // Back to step 1
    document.getElementById('2fa-back-to-step1-btn').addEventListener('click', function() {
      show2FAStep(1);
    });

    // Back to step 2
    document.getElementById('2fa-back-to-step2-btn').addEventListener('click', function() {
      show2FAStep(2);
    });

    // Store first token for final verification
    let firstToken = null;

    // Verify first token - move to step 3
    document.getElementById('2fa-verify-token1-btn').addEventListener('click', function() {
      const code = document.getElementById('2fa-verification-code-1').value.trim();
      const errorDiv = document.getElementById('2fa-error');

      // Clear previous errors
      errorDiv.style.display = 'none';
      errorDiv.textContent = '';

      // Basic validation
      if (!code || code.length !== 6 || !/^\d{6}$/.test(code)) {
        errorDiv.textContent = 'Please enter a valid 6-digit code';
        errorDiv.style.display = 'block';
        return;
      }

      // Store first token and move to step 3
      firstToken = code;
      show2FAStep(3);
    });

    // Verify second token and enable 2FA
    document.getElementById('2fa-verify-token2-btn').addEventListener('click', async function() {
      const code1 = firstToken;
      const code2 = document.getElementById('2fa-verification-code-2').value.trim();
      const errorDiv = document.getElementById('2fa-error-step3');

      // Clear previous errors
      errorDiv.style.display = 'none';
      errorDiv.textContent = '';

      // Basic validation
      if (!code2 || code2.length !== 6 || !/^\d{6}$/.test(code2)) {
        errorDiv.textContent = 'Please enter a valid 6-digit code';
        errorDiv.style.display = 'block';
        return;
      }

      // Ensure codes are different
      if (code1 === code2) {
        errorDiv.textContent = 'The second code must be different from the first. Please wait for a new code.';
        errorDiv.style.display = 'block';
        return;
      }

      // Disable button during verification
      const verifyBtn = document.getElementById('2fa-verify-token2-btn');
      verifyBtn.disabled = true;
      verifyBtn.textContent = 'Verifying...';

      try {
        const response = await settingsRequest('/auth/2fa/enable', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
              'Content-Type': 'application/json'
          },
          body: JSON.stringify({ token1: code1, token2: code2 })
        });

        // Check for 401 before parsing JSON
        if (response.status === 401) {
          const path = window.location.pathname;
          if (path !== '/' && !path.includes('login')) {
            showSessionTimeoutModal();
            return;
          }
        }

        if (response.ok) {
          let data;
          try {
            data = await response.json();
            // Don't log response data - may contain sensitive backup codes
          } catch (parseError) {
            if (controller.signal.aborted) return;
            // Don't log parse error - may contain sensitive backup codes
            console.error('Error parsing response JSON');
            errorDiv.textContent = 'Error parsing server response. Please try again.';
            errorDiv.style.display = 'block';
            verifyBtn.disabled = false;
            verifyBtn.textContent = 'Verify & Enable 2FA';
            return;
          }

          if (data && data.enabled) {
            if (data.backup_codes && Array.isArray(data.backup_codes) && data.backup_codes.length > 0) {
              // Store backup codes in memory and sessionStorage (survives page refresh)
              backupCodes = data.backup_codes;
              try {
                sessionStorage.setItem('2fa_backup_codes', JSON.stringify(data.backup_codes));
                sessionStorage.setItem('2fa_enrollment_step', '4');
              } catch (e) {
        if (controller.signal.aborted) return;
                // Failed to store backup codes - don't log sensitive data
                console.warn('Failed to store backup codes in sessionStorage');
              }
              displayBackupCodes(data.backup_codes);
              show2FAStep(4);
              // Don't close modal yet - wait for user confirmation
              enrollmentCompleted = false;
              // Re-enable button in case user goes back
              verifyBtn.disabled = false;
              verifyBtn.textContent = 'Verify & Enable 2FA';
            } else {
              // Backup codes not in response - this shouldn't happen, but handle gracefully
              // Don't log backup codes - they may be present in data.backup_codes
              console.error('Backup codes not received in response or invalid format');
              close2FAModal();
              current2FAStatus = true;
              update2FAUI();
              showSuccessNotification('Two-factor authentication has been enabled successfully!');
            }
          } else {
            // Response says not enabled - show error
            // Don't log data object - may contain sensitive backup codes
            console.error('Response indicates 2FA was not enabled');
            errorDiv.textContent = 'Failed to enable 2FA. Please try again.';
            errorDiv.style.display = 'block';
            verifyBtn.disabled = false;
            verifyBtn.textContent = 'Verify & Enable 2FA';
          }
        } else {
          // Check for 401 before parsing JSON
          if (response.status === 401) {
            const path = window.location.pathname;
            if (path !== '/' && !path.includes('login')) {
              showSessionTimeoutModal();
              return;
            }
          }
          const error = await response.json();
          errorDiv.textContent = error.error || 'Invalid verification code';
          errorDiv.style.display = 'block';
          verifyBtn.disabled = false;
          verifyBtn.textContent = 'Verify & Enable 2FA';
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        // Don't log error object - may contain sensitive backup codes
        console.error('Error enabling 2FA');
        errorDiv.textContent = 'Network error. Please try again.';
        errorDiv.style.display = 'block';
        verifyBtn.disabled = false;
        verifyBtn.textContent = 'Verify & Enable 2FA';
      }
    });

    // Display backup codes
    function displayBackupCodes(codes) {
      // Don't log backup codes - they are sensitive
      const container = document.getElementById('backup-codes-container');
      if (!container) {
        console.error('Backup codes container not found!');
        return;
      }
      container.innerHTML = '';
      if (!codes || !Array.isArray(codes)) {
        // Don't log codes - they are sensitive
        console.error('Invalid backup codes format');
        return;
      }
      codes.forEach((code, index) => {
        const codeDiv = document.createElement('div');
        codeDiv.style.cssText = 'padding: 0.75rem; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); border-radius: 0.5rem; text-align: center; font-weight: 600; color: var(--text);';
        codeDiv.textContent = code;
        container.appendChild(codeDiv);
      });
    }

    // Enable/disable confirm button based on checkbox
    document.getElementById('backup-codes-confirmed').addEventListener('change', function() {
      document.getElementById('2fa-confirm-backup-codes-btn').disabled = !this.checked;
    });

    // Confirm backup codes and complete enrollment
    document.getElementById('2fa-confirm-backup-codes-btn').addEventListener('click', function() {
      if (!document.getElementById('backup-codes-confirmed').checked) {
        return;
      }

      enrollmentCompleted = true;

      // CRITICAL: Clear all enrollment-related storage on successful completion
      try {
        sessionStorage.removeItem('2fa_backup_codes');
        sessionStorage.removeItem('2fa_enrollment_step');
        localStorage.removeItem('2fa_enrollment_incomplete');
      } catch (e) {
        if (controller.signal.aborted) return;
        // Don't log error object - may contain sensitive backup codes
        console.warn('Failed to clear enrollment storage');
      }

      close2FAModal();
      // Update status
      current2FAStatus = true;
      update2FAUI();
      showSuccessNotification('Two-factor authentication has been enabled successfully!');
      if (twoFactorEnrollmentRequired) {
        // Enrolment was the only thing this session could do; carry on into the app.
        twoFactorEnrollmentRequired = false;
        setTimeout(() => { window.location.href = '/dashboard'; }, 800);
      }
    });

    // Retry helper for critical operations
    async function retryOperation(operation, maxRetries = 3, baseDelay = 1000) {
      for (let i = 0; i < maxRetries; i++) {
        try {
          const result = await operation();
          return { success: true, result };
        } catch (error) {
        if (controller.signal.aborted) return;
          if (i === maxRetries - 1) {
            // Final attempt failed
            return { success: false, error };
          }
          // Exponential backoff: 1s, 2s, 4s
          const delay = baseDelay * Math.pow(2, i);
          await new Promise(resolve => setTimeout(resolve, delay));
        }
      }
      return { success: false, error: new Error('Max retries exceeded') };
    }

    // Cancel enrollment on step 4 - disable 2FA if it was enabled
    document.getElementById('2fa-cancel-step4-btn').addEventListener('click', async function() {
      // If enrollment was completed (2FA enabled) but user cancels, disable it
      if (!enrollmentCompleted) {
        const disableResult = await retryOperation(async () => {
          const response = await settingsRequest('/auth/2fa/disable', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
              'Content-Type': 'application/json'
            }
          });

          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }

          return response;
        }, 3, 1000);

        if (controller.signal.aborted) return;
        if (disableResult.success) {
          current2FAStatus = false;
          update2FAUI();
        } else {
          // Critical: Show warning if disable failed
          console.error('Failed to disable 2FA after cancellation:', disableResult.error);
          alert('⚠️ WARNING: Failed to cancel 2FA enrollment. Your account may be locked if you did not save your backup codes. Please contact support immediately or try disabling 2FA from settings.');
          // Store flag to detect incomplete enrollment on next page load
          localStorage.setItem('2fa_enrollment_incomplete', 'true');
        }
      }

      close2FAModal();
    });

    // Close modal function
    function close2FAModal() {
      // If closing modal before confirming backup codes, disable 2FA
      if (!enrollmentCompleted && backupCodes !== null) {
        // 2FA was enabled but user didn't confirm - disable it with retry
        retryOperation(async () => {
          const response = await settingsRequest('/auth/2fa/disable', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
              'Content-Type': 'application/json'
            }
          });

          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }

          return response;
        }, 3, 1000).then(result => {
          if (controller.signal.aborted) return;
          if (result.success) {
            current2FAStatus = false;
            update2FAUI();
          } else {
            // Critical: Show warning if disable failed
            console.error('Error disabling 2FA after modal close:', result.error);
            // Don't show alert here as it might interrupt user flow, but log and store flag
            localStorage.setItem('2fa_enrollment_incomplete', 'true');
          }
        });
      }

      document.getElementById('2fa-enrollment-modal').classList.remove('active');
      enrollmentSecret = null;
      firstToken = null;
      backupCodes = null;
      enrollmentCompleted = false;
      enrollmentInProgress = false;  // Reset enrollment flag

      // CRITICAL: Clear sessionStorage when modal is closed (unless enrollment completed)
      if (!enrollmentCompleted) {
        try {
          sessionStorage.removeItem('2fa_backup_codes');
          sessionStorage.removeItem('2fa_enrollment_step');
        } catch (e) {
        if (controller.signal.aborted) return;
          // Don't log error object - may contain sensitive backup codes
          console.warn('Failed to clear sessionStorage');
        }
      }

      document.getElementById('backup-codes-confirmed').checked = false;
      document.getElementById('2fa-confirm-backup-codes-btn').disabled = true;
      document.getElementById('enable-2fa-btn').disabled = false;  // Re-enable button
      show2FAStep(1); // Reset to first step
    }

    // Cancel enrollment (step 1-3)
    document.getElementById('2fa-cancel-btn').addEventListener('click', close2FAModal);

    // Close button - same behavior as cancel
    document.getElementById('2fa-close-btn').addEventListener('click', close2FAModal);

    // Prevent closing modal by clicking outside during step 4 (backup codes confirmation)
    // If user clicks outside, treat it as cancellation
    document.getElementById('2fa-enrollment-modal').addEventListener('click', function(e) {
      // Only handle clicks on the overlay (not the modal content)
      if (e.target === this) {
        const step4 = document.getElementById('2fa-enrollment-step4');
        if (step4 && step4.style.display === 'flex') {
          // User clicked outside during step 4 - treat as cancellation
          e.preventDefault();
          e.stopPropagation();
          // Trigger the cancel button behavior
          document.getElementById('2fa-cancel-step4-btn').click();
        }
      }
    });

    // Prevent event propagation from modal card to overlay (core2-style)
    const modal = document.getElementById('2fa-enrollment-modal');
    if (modal) {
      const modalCard = modal.querySelector('.card');
      if (modalCard) {
        modalCard.addEventListener('click', function(e) {
          e.stopPropagation();
        });
      }
    }

    // Remove any dynamically created modal overlays (e.g. disable-2fa confirm). Keeps #sessionTimeoutModal and #2fa-enrollment-modal.
    function closeDynamicModals() {
      document.querySelectorAll('.modal-overlay').forEach(function(el) {
        if (el.id === 'sessionTimeoutModal' || el.id === '2fa-enrollment-modal') return;
        el.remove();
      });
    }

    // Disable 2FA
    document.getElementById('disable-2fa-btn').addEventListener('click', async function() {
      closeDynamicModals(); // remove any existing dynamic modal (e.g. previous confirm) so only one is open
      const disableBtn = document.getElementById('disable-2fa-btn');
      disableBtn.disabled = true;
      let confirmed = false;
      const confirmDiv = document.createElement('div');
      confirmDiv.className = 'modal-overlay active';
      confirmDiv.setAttribute('role', 'dialog');
      confirmDiv.setAttribute('aria-modal', 'true');
      confirmDiv.setAttribute('aria-labelledby', 'settings-disable-2fa-title');
      confirmDiv.setAttribute('data-modal', 'disable-2fa-confirm');
      confirmDiv.appendChild(document.getElementById('settings-disable-2fa-template').content.cloneNode(true));
      transients.add(confirmDiv);
      document.body.appendChild(confirmDiv);

      function closeConfirm() {
        confirmDiv.remove();
        disableBtn.disabled = false;
      }

      confirmDiv.addEventListener('click', function(e) {
        if (e.target === confirmDiv) closeConfirm();
      });
      confirmDiv.querySelector('.card').addEventListener('click', function(e) {
        e.stopPropagation();
      });
      document.getElementById('confirm-close-x').addEventListener('click', closeConfirm);

      document.getElementById('confirm-cancel').addEventListener('click', function() {
        closeConfirm();
      });

      document.getElementById('confirm-disable').addEventListener('click', function() {
        confirmed = true;
        closeConfirm();
        proceedDisable();
      });

      async function proceedDisable() {
        try {
          const response = await settingsRequest('/auth/2fa/disable', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
              'Content-Type': 'application/json'
            }
          });

          if (response.ok) {
            const data = await response.json();
            if (data.disabled) {
              current2FAStatus = false;
              update2FAUI();
              showSuccessNotification('Two-factor authentication has been disabled.');
            }
          } else {
            // Check for 401 before parsing JSON
            if (response.status === 401) {
              const path = window.location.pathname;
              if (path !== '/' && !path.includes('login')) {
                showSessionTimeoutModal();
                return;
              }
            }
            const error = await response.json();
            showSuccessNotification('Error: ' + (error.error || 'Failed to disable 2FA'));
          }
        } catch (error) {
        if (controller.signal.aborted) return;
          console.error('Error disabling 2FA:', error);
          showSuccessNotification('Error: Failed to disable 2FA. Please try again.');
        }
      }
    });

    // Allow Enter key to submit verification codes
    const code1Input = document.getElementById('2fa-verification-code-1');
    const code2Input = document.getElementById('2fa-verification-code-2');

    if (code1Input) {
      code1Input.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
          document.getElementById('2fa-verify-token1-btn').click();
        }
      });
    }

    if (code2Input) {
      code2Input.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
          document.getElementById('2fa-verify-token2-btn').click();
        }
      });
    }

    // Note: Click outside handler is already set up above (lines 980-992) with special handling for step 4

    // Close modal on Escape key
    pageDocument.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') {
        const modal = document.getElementById('2fa-enrollment-modal');
        if (modal.classList.contains('active')) {
          close2FAModal();
        }
      }
    });

    // Load 2FA status on page load
    load2FAStatus();

    const longSessionDismiss = document.getElementById('long-session-banner-dismiss');
    if (longSessionDismiss) {
      longSessionDismiss.addEventListener('click', function() {
        sessionStorage.setItem('long_session_banner_dismissed', '1');
        const b = document.getElementById('long-session-banner');
        if (b) b.style.display = 'none';
      });
    }

    // Show success notification (styled like the app)
    function showSuccessNotification(message) {
      const notification = document.createElement('div');
      notification.className = 'glass-card';
      notification.style.cssText = 'position: fixed; top: 2rem; right: 2rem; padding: 1rem 1.5rem; z-index: 2000; background: rgba(16, 185, 129, 0.2); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 0.5rem; color: #10b981; backdrop-filter: blur(8px); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);';
      notification.textContent = message;
      transients.add(notification);
      document.body.appendChild(notification);

      setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transition = 'opacity 0.3s';
        setTimeout(() => notification.remove(), 300);
      }, 3000);
    }

    // Session Timeout Management (API uses minutes; UI supports minutes / hours / days)
    let MIN_SESSION_TIMEOUT = 5;       // minutes (from API; min 5)
    let MAX_SESSION_TIMEOUT = 30 * 24 * 60;
    let lastSessionTimeoutUnit = 'minutes';
    let lastKnownSessionTimeoutMinutes = null;

    function sessionTimeoutToDisplay(totalMinutes) {
      const m = totalMinutes;
      if (m >= 24 * 60 && m % (24 * 60) === 0) {
        return { value: m / (24 * 60), unit: 'days' };
      }
      if (m >= 60 && m % 60 === 0) {
        return { value: m / 60, unit: 'hours' };
      }
      return { value: m, unit: 'minutes' };
    }

    function sessionTimeoutToMinutes(value, unit) {
      const n = Number(value);
      if (isNaN(n) || n < 0) return 0;
      if (unit === 'days') return Math.round(n * 24 * 60);
      if (unit === 'hours') return Math.round(n * 60);
      return Math.round(n);
    }

    function getSessionTimeoutInputBounds() {
      const unit = (document.getElementById('session-timeout-unit') || {}).value || 'minutes';
      if (unit === 'days') {
        return { min: Math.max(1, Math.ceil(MIN_SESSION_TIMEOUT / (24 * 60))), max: Math.floor(MAX_SESSION_TIMEOUT / (24 * 60)) };
      }
      if (unit === 'hours') {
        return { min: Math.max(1, Math.ceil(MIN_SESSION_TIMEOUT / 60)), max: Math.floor(MAX_SESSION_TIMEOUT / 60) };
      }
      return { min: MIN_SESSION_TIMEOUT, max: MAX_SESSION_TIMEOUT };
    }

    function formatSessionTimeoutLabel(value, unit) {
      const v = Number(value);
      const u = unit === 'days' ? (v === 1 ? 'day' : 'days') : unit === 'hours' ? (v === 1 ? 'hour' : 'hours') : (v === 1 ? 'minute' : 'minutes');
      return (isNaN(v) ? '—' : v) + ' ' + u;
    }

    function updateSessionTimeoutUI() {
      const input = document.getElementById('session-timeout-input');
      const unitSelect = document.getElementById('session-timeout-unit');
      const display = document.getElementById('session-timeout-display');
      if (!input || !unitSelect) return;
      const bounds = getSessionTimeoutInputBounds();
      input.min = bounds.min;
      input.max = bounds.max;
      const unit = unitSelect.value;
      if (display) display.textContent = formatSessionTimeoutLabel(input.value, unit);
    }

    async function loadSessionTimeout() {
      try {
        const response = await settingsRequest('/auth/session-timeout', {
          method: 'GET',
          credentials: 'include'
        });

        if (response.status === 401) {
          const path = window.location.pathname;
          if (path !== '/' && !path.includes('login')) {
            showSessionTimeoutModal();
            return;
          }
        }

        if (response.ok) {
          const data = await response.json();
          const timeoutMinutes = data.session_timeout_minutes ?? (24 * 60);
          if (data.min_session_timeout_minutes !== undefined) MIN_SESSION_TIMEOUT = data.min_session_timeout_minutes;
          if (data.max_session_timeout_minutes !== undefined) MAX_SESSION_TIMEOUT = data.max_session_timeout_minutes;

          const { value, unit } = sessionTimeoutToDisplay(timeoutMinutes);
          const input = document.getElementById('session-timeout-input');
          const unitSelect = document.getElementById('session-timeout-unit');
          const display = document.getElementById('session-timeout-display');
          if (input) {
            input.value = value;
            const bounds = getSessionTimeoutInputBounds();
            input.min = bounds.min;
            input.max = bounds.max;
          }
          if (unitSelect) {
            unitSelect.value = unit;
            lastSessionTimeoutUnit = unit;
          }
          if (display) display.textContent = formatSessionTimeoutLabel(value, unit);
          lastKnownSessionTimeoutMinutes = timeoutMinutes;
          updateLongSessionBanner(timeoutMinutes);
        } else if (response.status === 401) {
          window.location.href = '/';
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error('Failed to load session timeout:', error);
      }
    }

    function updateLongSessionBanner(sessionTimeoutMinutes) {
      const banner = document.getElementById('long-session-banner');
      if (!banner) return;
      if (sessionStorage.getItem('long_session_banner_dismissed') === '1') {
        banner.style.display = 'none';
        return;
      }
      const longSessionMinutes = 24 * 60;
      const show = (sessionTimeoutMinutes != null && sessionTimeoutMinutes > longSessionMinutes) && !current2FAStatus;
      banner.style.display = show ? 'block' : 'none';
    }

    async function saveSessionTimeout() {
      const input = document.getElementById('session-timeout-input');
      const unitSelect = document.getElementById('session-timeout-unit');
      const messageDiv = document.getElementById('session-timeout-message');
      const saveBtn = document.getElementById('save-session-timeout-btn');

      if (!input || !unitSelect) return;

      const unit = unitSelect.value;
      const timeoutMinutes = sessionTimeoutToMinutes(input.value, unit);
      if (timeoutMinutes < MIN_SESSION_TIMEOUT || timeoutMinutes > MAX_SESSION_TIMEOUT) {
        if (messageDiv) {
          const bounds = getSessionTimeoutInputBounds();
          messageDiv.textContent = `Session timeout must be between ${bounds.min} and ${bounds.max} ${unit}`;
          messageDiv.style.color = '#ef4444';
          messageDiv.style.display = 'block';
        }
        return;
      }

      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';

      try {
        const response = await settingsRequest('/auth/session-timeout', {
          method: 'PUT',
          headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
              'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ session_timeout_minutes: timeoutMinutes })
        });

        if (response.status === 401) {
          const path = window.location.pathname;
          if (path !== '/' && !path.includes('login')) {
            showSessionTimeoutModal();
            return;
          }
        }

        if (response.ok) {
          const data = await response.json();
          const { value: v, unit: u } = sessionTimeoutToDisplay(data.session_timeout_minutes);
          const display = document.getElementById('session-timeout-display');
          if (display) display.textContent = formatSessionTimeoutLabel(v, u);
          if (messageDiv) {
            messageDiv.textContent = 'Session timeout updated successfully';
            messageDiv.style.color = '#10b981';
            messageDiv.style.display = 'block';
            setTimeout(() => { messageDiv.style.display = 'none'; }, 3000);
          }
          showSuccessNotification('Session timeout updated');
          lastKnownSessionTimeoutMinutes = data.session_timeout_minutes;
          updateLongSessionBanner(data.session_timeout_minutes);
        } else if (response.status === 401) {
          window.location.href = '/';
        } else {
          const errorData = await response.json().catch(() => ({}));
          if (messageDiv) {
            messageDiv.textContent = errorData.error || 'Failed to update session timeout';
            messageDiv.style.color = '#ef4444';
            messageDiv.style.display = 'block';
          }
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error('Failed to save session timeout:', error);
        if (messageDiv) {
          messageDiv.textContent = 'Network error. Please try again.';
          messageDiv.style.color = '#ef4444';
          messageDiv.style.display = 'block';
        }
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save session timeout';
      }
    }

    // Initialize session timeout UI
    const saveTimeoutBtn = document.getElementById('save-session-timeout-btn');
    if (saveTimeoutBtn) saveTimeoutBtn.addEventListener('click', saveSessionTimeout);

    const timeoutInput = document.getElementById('session-timeout-input');
    const timeoutUnitSelect = document.getElementById('session-timeout-unit');
    if (timeoutInput) {
      timeoutInput.addEventListener('keypress', function(e) { if (e.key === 'Enter') saveSessionTimeout(); });
      timeoutInput.addEventListener('input', updateSessionTimeoutUI);
    }
    if (timeoutUnitSelect) {
      timeoutUnitSelect.addEventListener('change', function() {
        const input = document.getElementById('session-timeout-input');
        if (input) {
          const minutes = sessionTimeoutToMinutes(input.value, lastSessionTimeoutUnit);
          lastSessionTimeoutUnit = this.value;
          const bounds = getSessionTimeoutInputBounds();
          let displayValue = lastSessionTimeoutUnit === 'days' ? minutes / (24 * 60) : lastSessionTimeoutUnit === 'hours' ? minutes / 60 : minutes;
          displayValue = Math.max(bounds.min, Math.min(bounds.max, Math.round(displayValue * 100) / 100));
          input.value = displayValue % 1 === 0 ? Math.round(displayValue) : displayValue;
        }
        updateSessionTimeoutUI();
      });
    }

    loadSessionTimeout();

    // Add password policy checking to new password field
    if (window.PasswordPolicy) {
      window.PasswordPolicy.attach('new-password', 'new-password-warnings', 1000);
    }

    // Password Reset Handler
    const passwordResetForm = document.getElementById('password-reset-form');
    if (passwordResetForm) {
      passwordResetForm.addEventListener('submit', async function(e) {
        e.preventDefault();

        const currentPassword = document.getElementById('current-password').value;
        const newPassword = document.getElementById('new-password').value;
        const newPasswordConfirm = document.getElementById('new-password-confirm').value;
        const errorDiv = document.getElementById('password-reset-error');
        const submitButton = document.getElementById('password-reset-btn');

        // Clear previous errors
        errorDiv.style.display = 'none';
        errorDiv.textContent = '';

        // Client-side validation
        if (!currentPassword || !newPassword || !newPasswordConfirm) {
          errorDiv.textContent = 'All fields are required';
          errorDiv.style.display = 'block';
          return;
        }

        if (newPassword !== newPasswordConfirm) {
          errorDiv.textContent = 'New passwords do not match';
          errorDiv.style.display = 'block';
          return;
        }

        if (currentPassword === newPassword) {
          errorDiv.textContent = 'New password must be different from current password';
          errorDiv.style.display = 'block';
          return;
        }

        // Disable button during submission
        submitButton.disabled = true;
        submitButton.textContent = 'Updating...';

        try {
          const response = await settingsRequest('/auth/change-password', {
            method: 'POST',
            credentials: 'include',
            redirect: 'manual',
            headers: {
              'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '',
              'Content-Type': 'application/json',
              'Accept': 'application/json'
            },
            body: JSON.stringify({
              current_password: currentPassword,
              new_password: newPassword,
              new_password_confirm: newPasswordConfirm
            })
          });

          let data = {};
          try {
            const text = await response.text();
            if (text && text.trim().length > 0) {
              data = JSON.parse(text);
            }
          } catch (_) {
            data = {};
          }

          if (response.type === 'opaqueredirect' || response.status === 302 || response.status === 301) {
            errorDiv.textContent = 'Your session may have expired. Please sign in again.';
            errorDiv.style.display = 'block';
            return;
          }

          if (response.ok) {
            passwordResetForm.reset();
            if (document.getElementById('new-password-warnings')) document.getElementById('new-password-warnings').style.display = 'none';
            showSuccessNotification('Password updated successfully.');
            return;
          }

          if (response.status === 400) {
            errorDiv.textContent = data.error || 'Current password is incorrect. Please try again.';
            errorDiv.style.display = 'block';
            return;
          }

          if (response.status === 401) {
            const msg = (data.error || data.message || '').toLowerCase();
            if (msg.includes('current password') || msg.includes('incorrect')) {
              errorDiv.textContent = data.error || data.message || 'Current password is incorrect. Please try again.';
              errorDiv.style.display = 'block';
              return;
            }
            const path = window.location.pathname;
            if (path !== '/' && !path.includes('login')) {
              showSessionTimeoutModal();
            }
            return;
          }

          errorDiv.textContent = data.error || 'Failed to update password. Please try again.';
          errorDiv.style.display = 'block';
        } catch (error) {
        if (controller.signal.aborted) return;
          console.error('Error updating password:', error);
          errorDiv.textContent = 'Network error. Please try again.';
          errorDiv.style.display = 'block';
        } finally {
          submitButton.disabled = false;
          submitButton.textContent = 'Update password';
        }
      });
    }

    // Frontend Activity Tracking
    // Track user activity to keep session alive
    let lastActivityTime = Date.now();
    let lastPingTime = 0;
    let pingInProgress = false; // Prevent concurrent pings
    const MIN_PING_INTERVAL = 20000; // Ping at most every 20 seconds (throttle)
    const ACTIVITY_CHECK_INTERVAL = 45000; // Check every 45 seconds (less frequent to avoid rate limits)

    // Throttled function to ping backend on activity
    async function pingBackendOnActivity() {
      const now = Date.now();
      // Throttle: only ping if at least MIN_PING_INTERVAL has passed since last ping
      if (now - lastPingTime < MIN_PING_INTERVAL) {
        return;
      }

      // Prevent concurrent pings
      if (pingInProgress) {
        return;
      }

      pingInProgress = true;
      lastPingTime = now;

      try {
        // Make a lightweight request to keep session alive
        const response = await settingsRequest('/auth/me', {
          method: 'GET',
          credentials: 'include'
        });

        // If session expired, show modal
        if (response.status === 401) {
          const path = window.location.pathname;
          if (path !== '/' && !path.includes('login')) {
            showSessionTimeoutModal();
            return;
          }
        }
        } catch (error) {
        if (controller.signal.aborted) return;
          // Silently handle errors - session might have expired
          if (error.message && (error.message.includes('401') || error.message.includes('Unauthorized'))) {
            const path = window.location.pathname;
            if (path !== '/' && !path.includes('login')) {
              showSessionTimeoutModal();
            }
          }
        } finally {
          pingInProgress = false;
        }
      }

    function trackActivity() {
      lastActivityTime = Date.now();
      // Ping backend immediately when activity is detected (throttled)
      pingBackendOnActivity();
    }

    // Track various user activities
    ['mousedown', 'mousemove', 'keypress', 'keydown', 'scroll', 'touchstart', 'click', 'input'].forEach(event => {
      pageDocument.addEventListener(event, trackActivity, { passive: true });
    });

    // Periodically check activity and notify backend (backup in case activity tracking misses something)
    const activityInterval = setInterval(async () => {
      const timeSinceActivity = Date.now() - lastActivityTime;
      // Ping if there was recent activity (within last 2 minutes) or if we haven't pinged recently
      if (timeSinceActivity < 120000 || (Date.now() - lastPingTime) > ACTIVITY_CHECK_INTERVAL) {
        await pingBackendOnActivity();
      }
    }, ACTIVITY_CHECK_INTERVAL);



    // Session timeout notification modal
    let sessionTimeoutTimer = null;
    function showSessionTimeoutModal() {
      // Allow showing on login page if session_expired parameter is present
      const urlParams = new URLSearchParams(window.location.search);
      const isSessionExpiredRedirect = urlParams.get('session_expired') === 'true';

      // Don't show if already showing, unless it's a session expired redirect
      if (!isSessionExpiredRedirect && (window.location.pathname.includes('login') || window.location.pathname === '/')) {
        return;
      }

      const modal = document.getElementById('sessionTimeoutModal');
      const countdownEl = document.getElementById('sessionTimeoutCountdown');
      if (!modal) return;
      if (modal.classList.contains('active')) return;

      // Clear any existing timer
      if (sessionTimeoutTimer) {
        clearInterval(sessionTimeoutTimer);
      }

      // Show modal
      modal.classList.add('active');
      document.body.style.overflow = 'hidden';

      // Countdown and redirect
      let seconds = 3;
      countdownEl.textContent = `Redirecting in ${seconds} seconds...`;

      sessionTimeoutTimer = setInterval(() => {
        seconds--;
        if (seconds > 0) {
          countdownEl.textContent = `Redirecting in ${seconds} second${seconds !== 1 ? 's' : ''}...`;
        } else {
          clearInterval(sessionTimeoutTimer);
          countdownEl.textContent = 'Redirecting now...';
          setTimeout(() => {
            window.location.href = '/';
          }, 300);
        }
      }, 1000);
    }

    window.showSessionTimeoutModal = showSessionTimeoutModal;
    // Clear sensitive sessionStorage if user navigates away mid-enrollment (only step 4 needs persistence)
    pageDocument.addEventListener('htmx:beforeSwap', function() {
      if (window.location.pathname === '/core/settings') {
        if (sessionStorage.getItem('2fa_enrollment_step') !== '4') {
          sessionStorage.removeItem('2fa_backup_codes');
          sessionStorage.removeItem('2fa_enrollment_step');
        }
      }
    });

    const installedFetch = window.fetch;
    return function () {
      controller.abort();
      window.clearInterval(activityInterval);
      timeouts.forEach(id => window.clearTimeout(id));
      intervals.forEach(id => window.clearInterval(id));
      transients.forEach(element => element.remove());
      document.body.style.overflow = '';
      if (window.fetch === installedFetch) window.fetch = originalPageFetch;
      Object.entries(previousGlobals).forEach(([name, value]) => {
        if (value === undefined) delete window[name];
        else window[name] = value;
      });
      if (sessionStorage.getItem('2fa_enrollment_step') !== '4') {
        sessionStorage.removeItem('2fa_backup_codes');
        sessionStorage.removeItem('2fa_enrollment_step');
      }
    };
  });
})();
