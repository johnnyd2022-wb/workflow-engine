/**
 * Shared password policy checking functionality
 * Provides real-time password strength recommendations
 */

(function() {
  'use strict';
  
  // Store timeouts per input field to avoid conflicts
  const timeouts = new Map();
  
  /**
   * Check password against policy and display warnings
   * @param {string} password - The password to check
   * @param {string} warningsDivId - ID of the div element to display warnings in
   */
  async function checkPasswordPolicy(password, warningsDivId) {
    if (!password || password.length === 0) {
      const warningsDiv = document.getElementById(warningsDivId);
      if (warningsDiv) {
        warningsDiv.style.display = 'none';
      }
      return;
    }
    
    try {
      // /auth/* is CSRF-exempt by design (called before a session exists during
      // signup); see app_factory.py CSRFProtect setup.
      // nosemgrep: raw-fetch-post
      const response = await fetch('/auth/password-policy-check', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ password: password })
      });
      
      const data = await response.json();
      const warningsDiv = document.getElementById(warningsDivId);
      
      if (warningsDiv) {
        if (data.warnings && data.warnings.length > 0) {
          // Escape HTML in warnings to prevent XSS
          const escapeHtml = (text) => {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
          };
          
          const headerText = 'You can still proceed, but we recommend increasing password complexity:';
          const warningsList = data.warnings.map(w => {
            const escapedWarning = escapeHtml(w);
            return '<li style="margin-bottom: 0.25rem;">' + escapedWarning + '</li>';
          }).join('');
          
          warningsDiv.innerHTML = 
            '<div style="margin-bottom: 0.5rem; font-weight: 500; color: inherit;">' + escapeHtml(headerText) + '</div>' +
            '<ul style="margin: 0.5rem 0 0 1.5rem; padding: 0; list-style-type: disc;">' +
            warningsList +
            '</ul>';
          warningsDiv.style.display = 'block';
          warningsDiv.style.visibility = 'visible';
        } else {
          warningsDiv.style.display = 'none';
        }
      } else {
        console.warn('Password policy warnings div not found:', warningsDivId);
      }
    } catch (error) {
      // Silently fail - don't block user from typing
      console.error('Password policy check failed:', error);
    }
  }
  
  /**
   * Attach password policy checking to a password input field
   * @param {string} inputId - ID of the password input field
   * @param {string} warningsDivId - ID of the div element to display warnings in
   * @param {number} debounceMs - Debounce delay in milliseconds (default: 1000)
   */
  function attachPasswordPolicyCheck(inputId, warningsDivId, debounceMs = 1000) {
    const passwordInput = document.getElementById(inputId);
    if (!passwordInput) {
      return;
    }
    
    // Clear any existing timeout for this input
    if (timeouts.has(inputId)) {
      clearTimeout(timeouts.get(inputId));
    }
    
    // Handle input events (debounced)
    passwordInput.addEventListener('input', function(e) {
      const password = e.target.value;
      
      // Clear existing timeout
      if (timeouts.has(inputId)) {
        clearTimeout(timeouts.get(inputId));
      }
      
      // Set new timeout
      const timeoutId = setTimeout(() => {
        checkPasswordPolicy(password, warningsDivId);
        timeouts.delete(inputId);
      }, debounceMs);
      
      timeouts.set(inputId, timeoutId);
    });
    
    // Also check on blur (when user leaves the field)
    passwordInput.addEventListener('blur', function(e) {
      // Clear timeout and check immediately
      if (timeouts.has(inputId)) {
        clearTimeout(timeouts.get(inputId));
        timeouts.delete(inputId);
      }
      checkPasswordPolicy(e.target.value, warningsDivId);
    });
  }
  
  // Export to window for global access
  window.PasswordPolicy = {
    check: checkPasswordPolicy,
    attach: attachPasswordPolicyCheck
  };
})();

