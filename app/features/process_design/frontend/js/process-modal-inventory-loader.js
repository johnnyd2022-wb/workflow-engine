(function() {
  'use strict';

  // Load inventory items (all types)
  let inventoryCache = null;
  
  async function loadInventoryItems() {
    if (inventoryCache) {
      return inventoryCache;
    }
    
    try {
      // Load all inventory types - collect from multiple sources
      let items = [];
      // Get process ID from URL params (same way as flows2.html)
      const urlParams = new URLSearchParams(window.location.search);
      const processId = urlParams.get('id') || null;
      
      console.log('Loading inventory items, processId:', processId);
      
      // This is a name/unit/type picker -- view=compact drops the per-item enrichment
      // (system findings, producing-step hydration, audit history), ~10x smaller.
      // 1. Process-scoped items first (surfaces outputs of earlier steps in this workflow).
      if (processId) {
        try {
          const inventoryData = await CoreAPI.getInventory(null, processId, { compact: true });
          const processItems = inventoryData.inventory_items || [];
          items.push(...processItems);
        } catch (err) {
          console.warn('Failed to load inventory with processId:', err);
        }
      }

      // 2. All inventory (already includes raw materials; the dedupe below handles overlap).
      try {
        const allInventoryData = await CoreAPI.getInventory(null, null, { compact: true });
        const allItems = allInventoryData.inventory_items || [];
        items.push(...allItems);
      } catch (err) {
        console.warn('Failed to load all inventory:', err);
      }
      
      // Get unique inventory items by name and category (preserve category info)
      // Group by category first, then deduplicate within each category
      const categorizedItems = {
        raw_material: [],
        work_in_progress: [],
        final_product: []
      };
      const seenNamesByCategory = {
        raw_material: new Set(),
        work_in_progress: new Set(),
        final_product: new Set()
      };
      
      items.forEach(item => {
        if (item && item.name) {
          // Determine category - default to raw_material if not specified
          const category = item.inventory_type || 'raw_material';
          const categoryKey = category === 'work_in_progress' ? 'work_in_progress' : 
                             category === 'final_product' ? 'final_product' : 
                             'raw_material';
          
          // Only add if we haven't seen this name in this category; preserve full item (supplier, process_name, extra_data)
          if (!seenNamesByCategory[categoryKey].has(item.name)) {
            seenNamesByCategory[categoryKey].add(item.name);
            categorizedItems[categoryKey].push({
              ...item,
              name: item.name,
              unit: item.unit || '',
              category: categoryKey
            });
          }
        }
      });
      
      // Return categorized items
      console.log('Total inventory items by category:', {
        raw_material: categorizedItems.raw_material.length,
        work_in_progress: categorizedItems.work_in_progress.length,
        final_product: categorizedItems.final_product.length
      });
      
      inventoryCache = categorizedItems;
      return categorizedItems;
    } catch (error) {
      console.error('Failed to load inventory items:', error);
      console.error('Error details:', error.message, error.stack);
      // Return empty categorized structure on error
      return {
        raw_material: [],
        work_in_progress: [],
        final_product: []
      };
    }
  }
  
  function reset() {
    inventoryCache = null;
  }

  window.ProcessModalInventoryLoader = Object.freeze({ loadInventoryItems, reset });
})();
