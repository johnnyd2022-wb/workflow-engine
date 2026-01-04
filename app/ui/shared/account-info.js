/**
 * Shared Account Info Component
 * Provides reusable account information display and logout functionality
 */

(function() {
  'use strict';
  
  // Track initialization state to prevent duplicate calls
  const initializedContainers = new Set();
  
  /**
   * Initialize account info component in a container
   * Safe to call multiple times - will only initialize once per container
   * @param {string} containerId - ID of the container element
   */
  async function initAccountInfo(containerId) {
    // Prevent duplicate initialization
    if (initializedContainers.has(containerId)) {
      return;
    }
    
    const container = document.getElementById(containerId);
    if (!container) {
      console.error('Account info container not found:', containerId);
      return;
    }
    
    // Mark as initialized immediately to prevent race conditions
    initializedContainers.add(containerId);
    
    // Find or create the component in the container
    let component = container.querySelector('#account-info-component');
    if (!component) {
      // Component HTML should already be inlined in the page
      // If not found, this is an error state
      console.error('Account info component not found in container:', containerId);
      initializedContainers.delete(containerId);
      return;
    }
    
    // Load user/org data asynchronously
    try {
      const response = await fetch('/auth/me', {
        method: 'GET',
        credentials: 'include'
      });
      
      // Check for 401 before parsing JSON
      if (response.status === 401) {
        // Not authenticated - hide component
        component.style.display = 'none';
        return;
      }
      
      if (response.ok) {
        const data = await response.json();
        if (data.user && data.organisation) {
          // Update account info
          const emailEl = component.querySelector('#account-info-email');
          const orgEl = component.querySelector('#account-info-org');
          
          if (emailEl) {
            const email = data.user.email || 'Unknown';
            emailEl.textContent = email;
            emailEl.title = email; // Show full email on hover
          }
          if (orgEl) {
            const orgName = data.organisation.name || 'Unknown';
            orgEl.textContent = orgName;
            orgEl.title = orgName; // Show full org name on hover
          }
          
          // Show component (already visible by default, but ensure it's shown)
          component.style.display = 'block';
        } else {
          // Not authenticated - hide component
          component.style.display = 'none';
        }
      } else {
        // Error - hide component
        component.style.display = 'none';
      }
    } catch (error) {
      console.error('Error loading account info:', error);
      // Hide component on error
      component.style.display = 'none';
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
  window.initAccountInfo = initAccountInfo;
  window.handleAccountInfoLogout = handleAccountInfoLogout;
  
  // Auto-initialize on DOM ready if container exists
  // This provides a fallback for pages that don't manually call initAccountInfo
  function autoInit() {
    const containers = document.querySelectorAll('[id^="account-info-container"]');
    containers.forEach(container => {
      if (container.id && !initializedContainers.has(container.id)) {
        initAccountInfo(container.id);
      }
    });
  }
  
  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoInit);
  } else {
    // DOM already ready
    autoInit();
  }
  
})();

