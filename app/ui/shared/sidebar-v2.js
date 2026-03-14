// Shared sidebar toggle function for V2 Modern design
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const mainContent = document.querySelector('.main-content');
  sidebar.classList.toggle('collapsed');
  
  // Adjust main content margin based on sidebar state
  if (sidebar.classList.contains('collapsed')) {
    mainContent.style.marginLeft = '72px';
  } else {
    mainContent.style.marginLeft = '260px';
  }
}

