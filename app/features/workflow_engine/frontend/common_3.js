/**
 * FLUME COMMON JAVASCRIPT V3
 * Shared functionality for Flume application
 * Version 3: Updated for Warm Clarity theme with sidebar navigation
 */

// Mobile sidebar toggle
function initSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const overlay = document.getElementById('sidebar-overlay');
  
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      if (overlay) {
        overlay.classList.toggle('active');
      }
    });
  }
  
  if (overlay) {
    overlay.addEventListener('click', () => {
      sidebar.classList.remove('open');
      overlay.classList.remove('active');
    });
  }
}

// Set active navigation item
function setActiveNav() {
  const currentPath = window.location.pathname;
  const navLinks = document.querySelectorAll('.sidebar-nav a');
  
  navLinks.forEach(link => {
    const href = link.getAttribute('href');
    if (currentPath.includes(href) && href !== '#') {
      link.classList.add('active');
    } else {
      link.classList.remove('active');
    }
  });
}

// Modal functionality
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
  }
}

// Close modal when clicking outside
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-overlay')) {
    const modalId = e.target.id;
    closeModal(modalId);
  }
});

// Progress bar animation
function animateProgress(elementId, targetValue, duration = 1000) {
  const progressFill = document.getElementById(elementId);
  if (!progressFill) return;
  
  let startValue = 0;
  const increment = targetValue / (duration / 16);
  
  const animate = () => {
    startValue += increment;
    if (startValue >= targetValue) {
      progressFill.style.width = targetValue + '%';
      return;
    }
    progressFill.style.width = startValue + '%';
    requestAnimationFrame(animate);
  };
  
  animate();
}

// Smooth scroll to element
function smoothScrollTo(elementId) {
  const element = document.getElementById(elementId);
  if (element) {
    element.scrollIntoView({
      behavior: 'smooth',
      block: 'start'
    });
  }
}

// Initialize tooltips
function initTooltips() {
  const tooltips = document.querySelectorAll('[data-tooltip]');
  
  tooltips.forEach(element => {
    element.addEventListener('mouseenter', (e) => {
      const tooltipText = element.getAttribute('data-tooltip');
      const tooltip = document.createElement('div');
      tooltip.className = 'tooltip';
      tooltip.textContent = tooltipText;
      tooltip.style.cssText = `
        position: absolute;
        background: var(--text-primary);
        color: white;
        padding: 0.5rem 0.75rem;
        border-radius: var(--radius-sm);
        font-size: 0.875rem;
        white-space: nowrap;
        z-index: 1000;
        pointer-events: none;
      `;
      
      document.body.appendChild(tooltip);
      
      const rect = element.getBoundingClientRect();
      tooltip.style.top = (rect.top - tooltip.offsetHeight - 8) + 'px';
      tooltip.style.left = (rect.left + (rect.width - tooltip.offsetWidth) / 2) + 'px';
      
      element.addEventListener('mouseleave', () => {
        tooltip.remove();
      }, { once: true });
    });
  });
}

// Notification toast
function showToast(message, type = 'info', duration = 3000) {
  const toast = document.createElement('div');
  toast.className = `alert alert-${type}`;
  toast.style.cssText = `
    position: fixed;
    top: 2rem;
    right: 2rem;
    z-index: 1000;
    animation: slideIn 0.3s ease-out;
    min-width: 300px;
  `;
  
  toast.innerHTML = `
    <span>${message}</span>
  `;
  
  document.body.appendChild(toast);
  
  setTimeout(() => {
    toast.style.animation = 'fadeOut 0.3s ease-out';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  setActiveNav();
  initTooltips();
  
  // Animate progress bars on page load
  const progressBars = document.querySelectorAll('.progress-fill');
  progressBars.forEach(bar => {
    const targetWidth = bar.getAttribute('data-progress') || bar.style.width;
    if (targetWidth) {
      animateProgress(bar.id, parseInt(targetWidth));
    }
  });
});

// Export functions for global use
window.FlumeApp = {
  openModal,
  closeModal,
  showToast,
  smoothScrollTo,
  animateProgress
};
