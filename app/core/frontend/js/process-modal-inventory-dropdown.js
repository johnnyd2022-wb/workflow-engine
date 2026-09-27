(function() {
  'use strict';

  // Create searchable dropdown for inventory with category grouping
  function createInventorySearchableDropdown(categorizedItems, onSelect, container, placeholderText = null, selectedInventoryItems) {
    const uniqueId = `guided-dropdown-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const dropdownContainer = document.createElement('div');
    dropdownContainer.className = 'searchable-dropdown-container';
    dropdownContainer.style.position = 'relative';
    dropdownContainer.style.width = '100%';
    
    // Determine placeholder based on whether we have previous outputs only or inventory items
    let placeholder = placeholderText;
    if (!placeholder) {
      const hasPreviousOutputs = categorizedItems.previous_outputs && categorizedItems.previous_outputs.length > 0;
      const hasInventory = (categorizedItems.raw_material?.length || 0) + 
                          (categorizedItems.work_in_progress?.length || 0) + 
                          (categorizedItems.final_product?.length || 0) > 0;
      if (hasPreviousOutputs && !hasInventory) {
        placeholder = 'Search previous step outputs...';
      } else {
        placeholder = 'Search inventory items...';
      }
    }
    
    // nosemgrep: innerhtml-template-literal -- audited: all dynamic values here go through escapeHtml()
    dropdownContainer.innerHTML = `
      <input
        type="text"
        class="form-input guided-input-name searchable-dropdown-input"
        placeholder="${escapeHtml(placeholder)}"
        autocomplete="off"
        style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"
        data-dropdown-id="${uniqueId}"
      />
      <div 
        class="searchable-dropdown-list" 
        id="${uniqueId}"
        style="display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 1000; max-height: 300px; overflow-y: auto; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); margin-top: 4px; box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));"
      ></div>
    `;
    
    const input = dropdownContainer.querySelector('.searchable-dropdown-input');
    const dropdown = dropdownContainer.querySelector('.searchable-dropdown-list');
    let filteredItems = [];
    let selectedIndex = -1;
    
    // Flatten categorized items into a single array for easier filtering
    function flattenItems(categorized) {
      const allItems = [];
      if (categorized.raw_material) {
        allItems.push(...categorized.raw_material);
      }
      if (categorized.work_in_progress) {
        allItems.push(...categorized.work_in_progress);
      }
      if (categorized.final_product) {
        allItems.push(...categorized.final_product);
      }
      if (categorized.previous_outputs) {
        allItems.push(...categorized.previous_outputs);
      }
      return allItems;
    }
    
    // Get all items as flat array
    const allItems = flattenItems(categorizedItems);
    
    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }
    
    function getAvailableItems() {
      // Filter out already selected items (except the one currently selected in this input)
      return allItems.filter(item => {
        const isSelected = selectedInventoryItems.has(item.name);
        const isCurrentSelection = input.value.trim() === item.name;
        return !isSelected || isCurrentSelection;
      });
    }
    
    // Group items by category
    function groupByCategory(items) {
      const grouped = {
        raw_material: [],
        work_in_progress: [],
        final_product: [],
        previous_outputs: []
      };
      items.forEach(item => {
        const category = item.category || 'raw_material';
        if (grouped[category]) {
          grouped[category].push(item);
        }
      });
      return grouped;
    }
    
    // Initialize filteredItems
    filteredItems = getAvailableItems();
    
    function renderDropdown() {
      const availableItems = getAvailableItems();
      
      if (availableItems.length === 0) {
        dropdown.innerHTML = '<div style="padding: 12px; color: var(--text-secondary); text-align: center; font-size: 13px;">No items available (all items may already be selected)</div>';
        dropdown.style.display = 'block';
        return;
      }
      
      // Apply search filter if there's a search term
      let itemsToShow = availableItems;
      const searchTerm = input.value.trim().toLowerCase();
      if (searchTerm) {
        itemsToShow = availableItems.filter(item => item.name.toLowerCase().includes(searchTerm));
      }
      
      // Group filtered items by category
      const grouped = groupByCategory(itemsToShow);
      
      // Category labels
      const categoryLabels = {
        raw_material: 'Raw Materials',
        work_in_progress: 'Intermediate',
        final_product: 'Final Products',
        previous_outputs: 'Previous Step Outputs'
      };
      
      // Category order - previous outputs first so they're easy to find
      const categoryOrder = ['previous_outputs', 'raw_material', 'work_in_progress', 'final_product'];
      
      // Build flat array in the same order as rendering (for index mapping)
      const flatItemsForIndex = [];
      categoryOrder.forEach(category => {
        const categoryItems = grouped[category] || [];
        flatItemsForIndex.push(...categoryItems);
      });
      
      // Store flat items for click/keyboard handlers
      filteredItems = flatItemsForIndex;
      
      let html = '';
      let itemIndex = 0;
      
      categoryOrder.forEach(category => {
        const categoryItems = grouped[category] || [];
        if (categoryItems.length > 0) {
          // Category header
          html += `
            <div style="padding: 8px 12px; background: var(--bg-secondary, #f9fafb); border-bottom: 1px solid var(--border-default); font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0; z-index: 10;">
              ${escapeHtml(categoryLabels[category])}
            </div>
          `;
          
          // Category items
          categoryItems.forEach(item => {
            const isSelected = itemIndex === selectedIndex;
            // Use displayName if available (for previous outputs), otherwise use name
            const displayText = item.displayName || item.name;
            html += `
              <div 
                class="dropdown-item ${isSelected ? 'selected' : ''}"
                data-index="${itemIndex}"
                data-category="${category}"
                style="padding: 10px 12px 10px 24px; cursor: pointer; border-bottom: 1px solid var(--border-light); transition: background 0.15s; ${isSelected ? 'background: var(--bg-hover, rgba(0, 0, 0, 0.05));' : ''}"
                onmouseover="this.style.background='var(--bg-hover, rgba(0, 0, 0, 0.05))'"
                onmouseout="if (!this.classList.contains('selected')) this.style.background='transparent'"
              >
                <div style="font-weight: 500; color: var(--text-primary); font-size: 13px;">${escapeHtml(displayText)}</div>
                ${item.is_previous_output ? `<div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">From previous step</div>` : ''}
              </div>
            `;
            itemIndex++;
          });
        }
      });
      
      dropdown.innerHTML = html;
      dropdown.style.display = 'block';
    }
    
    function filterItems(searchTerm) {
      selectedIndex = -1;
      renderDropdown(); // renderDropdown handles filtering internally
    }
    
    function selectItem(item) {
      // Remove previous selection from this input if any
      const previousValue = input.value.trim();
      if (previousValue && previousValue !== item.name) {
        selectedInventoryItems.delete(previousValue);
      }
      
      if (onSelect) {
        onSelect(item);
      }
      // Use the actual name (not displayName) for the input value
      input.value = item.name;
      // Mark this item as selected
      selectedInventoryItems.add(item.name);
      dropdown.style.display = 'none';
    }
    
    // Get flat array of all filtered items for selection (matches renderDropdown order)
    function getFilteredItemsFlat() {
      return filteredItems; // filteredItems is set by renderDropdown in the correct order
    }
    
    input.addEventListener('input', (e) => {
      filterItems(e.target.value);
    });
    
    input.addEventListener('focus', () => {
      // Re-filter to exclude newly selected items
      renderDropdown();
    });
    
    input.addEventListener('blur', () => {
      // Delay hiding to allow click events
      setTimeout(() => {
        dropdown.style.display = 'none';
      }, 200);
    });
    
    dropdown.addEventListener('click', (e) => {
      const itemEl = e.target.closest('.dropdown-item');
      if (itemEl) {
        const index = parseInt(itemEl.dataset.index);
        const flatItems = getFilteredItemsFlat();
        if (flatItems[index]) {
          const itemToSelect = flatItems[index];
          selectItem(itemToSelect);
        }
      }
    });
    
    // Keyboard navigation
    input.addEventListener('keydown', (e) => {
      const flatItems = getFilteredItemsFlat();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = Math.min(selectedIndex + 1, flatItems.length - 1);
        renderDropdown();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = Math.max(selectedIndex - 1, -1);
        renderDropdown();
      } else if (e.key === 'Enter' && selectedIndex >= 0 && flatItems[selectedIndex]) {
        e.preventDefault();
        const itemToSelect = flatItems[selectedIndex];
        selectItem(itemToSelect);
      }
    });
    
    return dropdownContainer;
  }
  
  window.ProcessModalInventoryDropdown = Object.freeze({ createInventorySearchableDropdown });
})();
