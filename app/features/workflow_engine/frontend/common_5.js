// Flume - Common JavaScript Functions - Version 5: Warm Midnight Flow

// Modal Management
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.remove('active');
    document.body.style.overflow = '';
  }
}

// Close modal when clicking overlay
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('modal-overlay')) {
    closeModal(e.target.id);
  }
});

// Close modal on Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    const activeModal = document.querySelector('.modal-overlay.active');
    if (activeModal) {
      closeModal(activeModal.id);
    }
  }
});

// Generate Compliance Report
function generateReport() {
  const button = document.getElementById('generateBtn');
  const form = document.getElementById('reportForm');
  const success = document.getElementById('reportSuccess');
  
  if (button && form && success) {
    button.textContent = 'Generating...';
    button.disabled = true;
    
    // Simulate report generation
    setTimeout(() => {
      form.style.display = 'none';
      success.style.display = 'block';
      
      // Show toast notification
      showToast('Your NP3 Export is Ready 🎉', 'Compliance report generated successfully');
    }, 2000);
  }
}

// Download Report
function downloadReport() {
  showToast('Download started', 'Your compliance report is downloading');
  
  // Reset modal
  setTimeout(() => {
    const form = document.getElementById('reportForm');
    const success = document.getElementById('reportSuccess');
    const button = document.getElementById('generateBtn');
    
    if (form && success && button) {
      form.style.display = 'block';
      success.style.display = 'none';
      button.textContent = 'Generate Audit Report';
      button.disabled = false;
    }
    
    closeModal('complianceModal');
  }, 500);
}

// Toast Notification System
let toastContainer = null;

function initToastContainer() {
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.id = 'toast-container';
    toastContainer.style.cssText = `
      position: fixed;
      top: 1rem;
      right: 1rem;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      max-width: 400px;
    `;
    document.body.appendChild(toastContainer);
  }
}

function showToast(title, description, duration = 3000) {
  initToastContainer();
  
  const toast = document.createElement('div');
  toast.className = 'glass-card animate-scale-in';
  toast.style.cssText = `
    padding: 1rem;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(255, 255, 255, 0.1);
  `;
  
  toast.innerHTML = `
    <div style="display: flex; gap: 0.75rem; align-items: start;">
      <div style="
        width: 2rem;
        height: 2rem;
        border-radius: 50%;
        background: rgba(22, 163, 74, 0.2);
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      ">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#16A34A" stroke-width="2">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      </div>
      <div style="flex: 1;">
        <div style="font-weight: 600; margin-bottom: 0.25rem; color: #F9FAFB;">${title}</div>
        <div style="font-size: 0.875rem; color: #9CA3AF;">${description}</div>
      </div>
      <button onclick="this.parentElement.parentElement.remove()" style="
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
        color: #9CA3AF;
        flex-shrink: 0;
      ">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
    </div>
  `;
  
  toastContainer.appendChild(toast);
  
  // Auto remove after duration
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// Set active navigation link
function setActiveNavLink() {
  const currentPage = window.location.pathname.split('/').pop() || 'index_5.html';
  const navLinks = document.querySelectorAll('.navbar-nav a');
  
  navLinks.forEach(link => {
    const linkPage = link.getAttribute('href');
    const btn = link.querySelector('.btn');
    
    if (btn) {
      btn.classList.remove('active');
      
      if (
        (currentPage === 'dashboard_5.html' && linkPage === 'dashboard_5.html') ||
        (currentPage === 'compliance_5.html' && linkPage === 'compliance_5.html') ||
        (currentPage === 'integrations_5.html' && linkPage === 'integrations_5.html') ||
        (currentPage === 'settings_5.html' && linkPage === 'settings_5.html')
      ) {
        btn.classList.add('active');
      }
    }
  });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
  setActiveNavLink();
  
  // Add animation delays to fade-in elements
  const fadeElements = document.querySelectorAll('.animate-fade-in');
  fadeElements.forEach((el, idx) => {
    el.style.animationDelay = `${idx * 0.1}s`;
  });
});

// Progress bar animation
function animateProgress(elementId, targetValue) {
  const progressBar = document.getElementById(elementId);
  if (progressBar) {
    let current = 0;
    const increment = targetValue / 50;
    const interval = setInterval(() => {
      current += increment;
      if (current >= targetValue) {
        current = targetValue;
        clearInterval(interval);
      }
      progressBar.style.width = current + '%';
    }, 20);
  }
}

// Animate progress bars on scroll
function animateProgressOnScroll() {
  const progressBars = document.querySelectorAll('.progress-bar[data-value]');
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const value = parseInt(entry.target.getAttribute('data-value'));
        entry.target.style.width = value + '%';
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.5 });
  
  progressBars.forEach(bar => observer.observe(bar));
}

// Initialize progress animation on load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', animateProgressOnScroll);
} else {
  animateProgressOnScroll();
}
