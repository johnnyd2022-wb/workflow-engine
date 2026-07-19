// Flume - Common JavaScript Functions

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Navigation Bar
function renderNavbar(activePage = '') {
  const navLinks = [
    { href: '/workflow-engine/dashboard', icon: 'dashboard', label: 'Dashboard', id: 'dashboard' },
    { href: '/workflow-engine/core', icon: 'flow', label: 'Core Flows', id: 'core' },
    { href: '/workflow-engine/compliance', icon: 'file', label: 'Compliance', id: 'compliance' },
    { href: '/workflow-engine/integrations', icon: 'link', label: 'Integrations', id: 'integrations' },
    { href: '/workflow-engine/settings', icon: 'settings', label: 'Settings', id: 'settings' }
  ];

  const iconPaths = {
    dashboard: '<rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect>',
    flow: '<path d="M3 7l6-3 6 3 6-3v13l-6 3-6-3-6 3V7z"></path><path d="M9 4v13"></path><path d="M15 7v13"></path>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M9 15l2 2 4-4"></path>',
    link: '<path d="M6 9h11"></path><path d="M6 15h11"></path><circle cx="18" cy="9" r="3"></circle><circle cx="18" cy="15" r="3"></circle>',
    settings: '<circle cx="12" cy="12" r="3"></circle><path d="M12 1v6m0 6v6m7.071-1.071l-4.242-4.242M9.171 9.171L4.929 4.929m0 14.142l4.242-4.242m4.242-4.242l4.242-4.242"></path>'
  };

  const navLinksHtml = navLinks.map(link => {
    const isActive = link.id === activePage;
    return `
      <a href="${link.href}">
        <button class="btn ${isActive ? 'active' : 'btn-ghost'}">
          <svg class="icon-md" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            ${iconPaths[link.icon]}
          </svg>
          ${link.label}
        </button>
      </a>
    `;
  }).join('');

  return `
    <nav class="navbar">
      <div class="container">
        <a href="/workflow-engine-lovable" class="navbar-logo">
          <div class="navbar-logo-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
              <path d="M3 7l6-3 6 3 6-3v13l-6 3-6-3-6 3V7z"></path>
              <path d="M9 4v13"></path>
              <path d="M15 7v13"></path>
            </svg>
          </div>
          <span class="navbar-logo-text">Flume</span>
        </a>

        <div class="navbar-nav">
          ${navLinksHtml}
        </div>

        <div class="navbar-menu">
          <button class="btn btn-glass btn-icon">
            <svg class="icon-md" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"></circle>
              <path d="M12 1v6m0 6v6m7.071-1.071l-4.242-4.242M9.171 9.171L4.929 4.929m0 14.142l4.242-4.242m4.242-4.242l4.242-4.242"></path>
            </svg>
          </button>
        </div>
      </div>
    </nav>
  `;
}

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
      box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.2);
    `;
    
    // nosemgrep: innerhtml-template-literal -- audited: all dynamic values here go through escapeHtml()
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
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="hsl(142, 71%, 37%)" stroke-width="2">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </div>
        <div style="flex: 1;">
          <div style="font-weight: 600; margin-bottom: 0.25rem;">${escapeHtml(title)}</div>
          <div style="font-size: 0.875rem; color: var(--muted-foreground);">${escapeHtml(description)}</div>
        </div>
        <button onclick="this.parentElement.parentElement.remove()" style="
          background: none;
          border: none;
          cursor: pointer;
          padding: 0;
          color: var(--muted-foreground);
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
    const currentPage = window.location.pathname.split('/').pop() || 'index.html';
    const navLinks = document.querySelectorAll('.navbar-nav a');
    
    navLinks.forEach(link => {
      const linkPage = link.getAttribute('href');
      const btn = link.querySelector('.btn');
      
      if (btn) {
        btn.classList.remove('active');
        
        if (
          (currentPage === 'dashboard.html' && linkPage === 'dashboard.html') ||
          (currentPage === 'compliance.html' && linkPage === 'compliance.html') ||
          (currentPage === 'integrations.html' && linkPage === 'integrations.html') ||
          (currentPage === 'settings.html' && linkPage === 'settings.html')
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