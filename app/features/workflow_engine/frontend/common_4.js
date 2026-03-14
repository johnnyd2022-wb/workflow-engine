/**
 * Flume UI Version 4 — Warm Liquid Clarity with Microinteractions
 * Enhanced JavaScript for smooth animations and interactive behaviors
 */

// ============================================
// SIDEBAR — Mobile Toggle
// ============================================

function initSidebar() {
  const toggle = document.querySelector('.mobile-menu-toggle');
  const sidebar = document.querySelector('.sidebar');
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
// MODAL — Open/Close Interactions
// ============================================

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

// Close modal on overlay click
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.style.display = 'none';
    document.body.style.overflow = 'auto';
  }
});

// ============================================
// METRIC CARDS — Count-Up Animation
// ============================================

function animateValue(element, start, end, duration, suffix = '') {
  const range = end - start;
  const increment = range / (duration / 16);
  let current = start;
  
  const timer = setInterval(() => {
    current += increment;
    if ((increment > 0 && current >= end) || (increment < 0 && current <= end)) {
      current = end;
      clearInterval(timer);
    }
    
    // Format based on value type
    let displayValue;
    if (end % 1 !== 0) {
      displayValue = current.toFixed(1);
    } else {
      displayValue = Math.floor(current);
    }
    
    element.textContent = displayValue + suffix;
  }, 16);
}

function initMetricCountUp() {
  const metrics = document.querySelectorAll('.metric-value');
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting && !entry.target.dataset.animated) {
        const text = entry.target.textContent;
        const match = text.match(/[\d.]+/);
        
        if (match) {
          const endValue = parseFloat(match[0]);
          const suffix = text.replace(match[0], '');
          
          entry.target.dataset.animated = 'true';
          animateValue(entry.target, 0, endValue, 1000, suffix);
        }
      }
    });
  }, { threshold: 0.5 });
  
  metrics.forEach(metric => observer.observe(metric));
}

// ============================================
// PROGRESS BAR — Animated Fill
// ============================================

function animateProgress(elementId, targetValue, duration = 1000) {
  const element = document.getElementById(elementId);
  if (!element) return;
  
  let current = 0;
  const increment = targetValue / (duration / 16);
  
  const timer = setInterval(() => {
    current += increment;
    if (current >= targetValue) {
      current = targetValue;
      clearInterval(timer);
    }
    element.style.width = current + '%';
  }, 16);
}

// ============================================
// BUTTON — Success Shimmer Effect
// ============================================

function triggerSuccessShimmer(buttonElement) {
  buttonElement.classList.add('btn-success-shimmer');
  
  setTimeout(() => {
    buttonElement.classList.remove('btn-success-shimmer');
  }, 2000);
}

// Handle Generate Report button
function handleGenerateReport() {
  const generateBtn = document.querySelector('[data-action="generate-report"]');
  
  if (generateBtn) {
    generateBtn.addEventListener('click', () => {
      triggerSuccessShimmer(generateBtn);
    });
  }
}

// ============================================
// SMOOTH SCROLL
// ============================================

function smoothScrollTo(elementId) {
  const element = document.getElementById(elementId);
  if (element) {
    element.scrollIntoView({
      behavior: 'smooth',
      block: 'start'
    });
  }
}

// ============================================
// TOOLTIPS
// ============================================

function initTooltips() {
  const tooltipElements = document.querySelectorAll('[data-tooltip]');
  
  tooltipElements.forEach(element => {
    const tooltipText = element.getAttribute('data-tooltip');
    
    element.addEventListener('mouseenter', (e) => {
      const tooltip = document.createElement('div');
      tooltip.className = 'tooltip';
      tooltip.textContent = tooltipText;
      tooltip.style.cssText = `
        position: absolute;
        background: rgba(0, 0, 0, 0.9);
        color: white;
        padding: 0.5rem 0.75rem;
        border-radius: 0.5rem;
        font-size: 0.875rem;
        white-space: nowrap;
        z-index: 1000;
        pointer-events: none;
        animation: fadeIn 0.2s ease-out;
      `;
      
      document.body.appendChild(tooltip);
      
      const rect = element.getBoundingClientRect();
      tooltip.style.top = (rect.top - tooltip.offsetHeight - 8) + 'px';
      tooltip.style.left = (rect.left + rect.width / 2 - tooltip.offsetWidth / 2) + 'px';
      
      element._tooltip = tooltip;
    });
    
    element.addEventListener('mouseleave', () => {
      if (element._tooltip) {
        element._tooltip.remove();
        element._tooltip = null;
      }
    });
  });
}

// ============================================
// TOAST NOTIFICATIONS
// ============================================

function showToast(message, type = 'info', duration = 3000) {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  toast.style.cssText = `
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    background: white;
    padding: 1rem 1.5rem;
    border-radius: 0.75rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1);
    z-index: 1001;
    animation: slideIn 0.3s ease-out;
    border-left: 4px solid;
  `;
  
  const colors = {
    success: '#16A34A',
    warning: '#F59E0B',
    error: '#DC2626',
    info: '#2563EB'
  };
  
  toast.style.borderColor = colors[type] || colors.info;
  
  document.body.appendChild(toast);
  
  setTimeout(() => {
    toast.style.animation = 'fadeOut 0.3s ease-out';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ============================================
// PAGE TRANSITIONS
// ============================================

function initPageTransitions() {
  const navLinks = document.querySelectorAll('.nav-link');
  
  navLinks.forEach(link => {
    link.addEventListener('click', (e) => {
      // Only animate if navigating to a different page
      if (!link.classList.contains('active')) {
        document.body.style.opacity = '0.95';
        document.body.style.transition = 'opacity 200ms ease-out';
        
        setTimeout(() => {
          document.body.style.opacity = '1';
        }, 200);
      }
    });
  });
}

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  setActiveNav();
  initMetricCountUp();
  initTooltips();
  handleGenerateReport();
  initPageTransitions();
  
  // Animate progress bars if present
  const progressBars = document.querySelectorAll('.progress-fill');
  progressBars.forEach((bar, index) => {
    setTimeout(() => {
      const targetWidth = bar.getAttribute('data-progress') || 
                         bar.style.width.replace('%', '');
      bar.style.width = '0%';
      animateProgress(bar.id || `progress-${index}`, parseFloat(targetWidth));
    }, 300 + (index * 100));
  });
});

// ============================================
// GLOBAL EXPORTS
// ============================================

window.FlumeApp = {
  openModal,
  closeModal,
  showToast,
  smoothScrollTo,
  animateProgress,
  triggerSuccessShimmer
};
