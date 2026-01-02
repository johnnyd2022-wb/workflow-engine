/**
 * Shared Account Info Component
 * Provides reusable account information display and logout functionality
 */

(function() {
  'use strict';
  
  /**
   * Load account information from /auth/me endpoint
   * @param {string} containerId - ID of the container element to insert the component into
   */
  async function loadAccountInfo(containerId) {
    const container = document.getElementById(containerId);
    if (!container) {
      console.error('Account info container not found:', containerId);
      return;
    }
    
    try {
      const response = await fetch('/auth/me', {
        method: 'GET',
        credentials: 'include'
      });
      
      // Check for 401 before parsing JSON
      if (response.status === 401) {
        // Not authenticated - hide component
        const component = document.getElementById('account-info-component');
        if (component) component.style.display = 'none';
        return;
      }
      
      if (response.ok) {
        const data = await response.json();
        if (data.user && data.organisation) {
          // Update account info
          const emailEl = document.getElementById('account-info-email');
          const orgEl = document.getElementById('account-info-org');
          
          if (emailEl) emailEl.textContent = data.user.email || 'Unknown';
          if (orgEl) orgEl.textContent = data.organisation.name || 'Unknown';
          
          // Show component
          const component = document.getElementById('account-info-component');
          if (component) {
            component.style.display = 'block';
            // Insert into container if not already there
            if (!container.contains(component)) {
              container.appendChild(component);
            }
          }
        } else {
          // Not authenticated - hide component
          const component = document.getElementById('account-info-component');
          if (component) component.style.display = 'none';
        }
      } else {
        // Error - hide component
        const component = document.getElementById('account-info-component');
        if (component) component.style.display = 'none';
      }
    } catch (error) {
      console.error('Error loading account info:', error);
      // Hide component on error
      const component = document.getElementById('account-info-component');
      if (component) component.style.display = 'none';
    }
  }
  
  /**
   * Logout handler for account info component
   */
  async function handleAccountInfoLogout() {
    try {
      const response = await fetch('/auth/logout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include'
      });
      
      if (response.ok) {
        window.location.href = '/';
      } else {
        console.error('Logout failed');
        // Still redirect on failure
        window.location.href = '/';
      }
    } catch (error) {
      console.error('Logout error:', error);
      // Still redirect on error
      window.location.href = '/';
    }
  }
  
  // Export functions to global scope
  window.loadAccountInfo = loadAccountInfo;
  window.handleAccountInfoLogout = handleAccountInfoLogout;
  
})();

