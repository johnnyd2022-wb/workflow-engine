(function() {
  'use strict';

  function toggleStepSummary(stepId) {
    const summaryCard = document.getElementById(stepId);
    if (!summaryCard) return;
    
    const expandedDetails = summaryCard.querySelector('.step-summary-expanded');
    const collapsedSummary = summaryCard.querySelector('.step-summary-collapsed');
    const expandIcon = summaryCard.querySelector('.step-summary-expand-icon');
    
    if (!expandedDetails || !expandIcon) return;
    
    const isExpanded = summaryCard.dataset.expanded === 'true';
    if (isExpanded) {
      expandedDetails.style.display = 'none';
      if (collapsedSummary) collapsedSummary.style.display = 'block';
      expandIcon.style.transform = 'rotate(0deg)';
      summaryCard.dataset.expanded = 'false';
    } else {
      expandedDetails.style.display = 'block';
      if (collapsedSummary) collapsedSummary.style.display = 'none';
      expandIcon.style.transform = 'rotate(180deg)';
      summaryCard.dataset.expanded = 'true';
    }
  }

  window.ProcessModalStepSummaryUi = Object.freeze({ toggleStepSummary });
})();
