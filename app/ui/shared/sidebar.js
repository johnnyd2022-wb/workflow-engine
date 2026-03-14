/**
 * Shared Sidebar Component JavaScript
 * Handles mobile menu toggle and sidebar interactions
 */

// ============================================
// SIDEBAR — Mobile Toggle
// ============================================

function initSidebar() {
  const toggle = document.querySelector('.mobile-menu-toggle');
  const sidebar = document.querySelector('.left-pane');
  const overlay = document.querySelector('.mobile-overlay');
  
  if (toggle && sidebar && overlay) {
    toggle.addEventListener('click', () => {
      sidebar.classList.toggle('active');
      overlay.classList.toggle('active');
    });
    
    overlay.addEventListener('click', () => {
      sidebar.classList.remove('active');
      overlay.classList.remove('active');
    });
  }
}

// ============================================
// NAVIGATION — Active Link Highlighting
// ============================================

function setActiveNav() {
  const currentPath = window.location.pathname;
  const navLinks = document.querySelectorAll('.nav-link');
  
  navLinks.forEach(link => {
    const linkPath = new URL(link.href).pathname;
    if (currentPath === linkPath || currentPath.endsWith(linkPath)) {
      link.classList.add('active');
    }
  });
}

// ============================================
// Initialize on DOM ready
// ============================================

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function() {
    initSidebar();
    setActiveNav();
  });
} else {
  // DOM already ready
  initSidebar();
  setActiveNav();
}

