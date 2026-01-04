// Mock Data for Supply Chain Platform

const UNITS_OF_MEASURE = [
    // Mass
    { value: 'kg', label: 'Kilograms (kg)', category: 'Mass' },
    { value: 'g', label: 'Grams (g)', category: 'Mass' },
    { value: 'mg', label: 'Milligrams (mg)', category: 'Mass' },
    { value: 'lb', label: 'Pounds (lb)', category: 'Mass' },
    { value: 'oz', label: 'Ounces (oz)', category: 'Mass' },
    { value: 'ton', label: 'Metric Tons', category: 'Mass' },
    
    // Volume
    { value: 'L', label: 'Liters (L)', category: 'Volume' },
    { value: 'mL', label: 'Milliliters (mL)', category: 'Volume' },
    { value: 'gal', label: 'Gallons (gal)', category: 'Volume' },
    { value: 'm3', label: 'Cubic Meters (m³)', category: 'Volume' },
    { value: 'ft3', label: 'Cubic Feet (ft³)', category: 'Volume' },
    
    // Count
    { value: 'units', label: 'Units', category: 'Count' },
    { value: 'pcs', label: 'Pieces', category: 'Count' },
    { value: 'boxes', label: 'Boxes', category: 'Count' },
    { value: 'pallets', label: 'Pallets', category: 'Count' },
    { value: 'containers', label: 'Containers', category: 'Count' },
    
    // Length
    { value: 'm', label: 'Meters (m)', category: 'Length' },
    { value: 'cm', label: 'Centimeters (cm)', category: 'Length' },
    { value: 'mm', label: 'Millimeters (mm)', category: 'Length' },
    { value: 'ft', label: 'Feet (ft)', category: 'Length' },
    { value: 'in', label: 'Inches (in)', category: 'Length' },
    
    // Time
    { value: 'sec', label: 'Seconds', category: 'Time' },
    { value: 'min', label: 'Minutes', category: 'Time' },
    { value: 'hr', label: 'Hours', category: 'Time' },
    { value: 'days', label: 'Days', category: 'Time' },
    
    // Area
    { value: 'm2', label: 'Square Meters (m²)', category: 'Area' },
    { value: 'ft2', label: 'Square Feet (ft²)', category: 'Area' },
    
    // Temperature
    { value: 'C', label: 'Celsius (°C)', category: 'Temperature' },
    { value: 'F', label: 'Fahrenheit (°F)', category: 'Temperature' },
    
    // Percentage
    { value: '%', label: 'Percentage (%)', category: 'Ratio' },
    { value: 'ppm', label: 'Parts per Million', category: 'Ratio' },
  ];
  
  const mockProcesses = [
    {
      id: 'proc-001',
      name: 'Widget Assembly Line A',
      description: 'Primary assembly process for consumer widgets',
      steps: [
        {
          id: 'step-001',
          stepNumber: 1,
          name: 'Raw Material Intake',
          description: 'Receive and quality check incoming materials',
          inputs: [
            { id: 'in-001', name: 'Aluminum Sheets', quantity: 100, unit: 'kg', isStatic: false },
            { id: 'in-002', name: 'Plastic Pellets', quantity: 50, unit: 'kg', isStatic: false },
          ],
          outputs: [
            { id: 'out-001', name: 'Verified Materials', quantity: 145, unit: 'kg', isStatic: false },
          ],
        },
        {
          id: 'step-002',
          stepNumber: 2,
          name: 'Component Fabrication',
          description: 'Machine and mold individual components',
          inputs: [
            { id: 'in-003', name: 'Verified Materials', quantity: 145, unit: 'kg', isStatic: false },
            { id: 'in-004', name: 'Machine Time', quantity: 4, unit: 'hr', isStatic: true },
          ],
          outputs: [
            { id: 'out-002', name: 'Aluminum Parts', quantity: 200, unit: 'pcs', isStatic: false },
            { id: 'out-003', name: 'Plastic Housings', quantity: 200, unit: 'pcs', isStatic: false },
          ],
        },
        {
          id: 'step-003',
          stepNumber: 3,
          name: 'Assembly',
          description: 'Combine components into finished widgets',
          inputs: [
            { id: 'in-005', name: 'Aluminum Parts', quantity: 200, unit: 'pcs', isStatic: false },
            { id: 'in-006', name: 'Plastic Housings', quantity: 200, unit: 'pcs', isStatic: false },
            { id: 'in-007', name: 'Screws', quantity: 800, unit: 'pcs', isStatic: false },
          ],
          outputs: [
            { id: 'out-004', name: 'Assembled Widgets', quantity: 200, unit: 'units', isStatic: false },
          ],
        },
        {
          id: 'step-004',
          stepNumber: 4,
          name: 'Quality Control',
          description: 'Inspect and test finished products',
          inputs: [
            { id: 'in-008', name: 'Assembled Widgets', quantity: 200, unit: 'units', isStatic: false },
          ],
          outputs: [
            { id: 'out-005', name: 'Approved Widgets', quantity: 195, unit: 'units', isStatic: false },
            { id: 'out-006', name: 'Rejected Units', quantity: 5, unit: 'units', isStatic: false },
          ],
        },
      ],
      activeExecutions: 3,
      completedExecutions: 47,
      createdAt: '2024-01-15',
    },
    {
      id: 'proc-002',
      name: 'Chemical Batch Processing',
      description: 'Controlled chemical mixing and reaction process',
      steps: [
        {
          id: 'step-005',
          stepNumber: 1,
          name: 'Ingredient Preparation',
          description: 'Measure and prepare chemical ingredients',
          inputs: [
            { id: 'in-009', name: 'Chemical A', quantity: 25, unit: 'L', isStatic: false },
            { id: 'in-010', name: 'Chemical B', quantity: 15, unit: 'L', isStatic: false },
            { id: 'in-011', name: 'Catalyst', quantity: 500, unit: 'mL', isStatic: true },
          ],
          outputs: [
            { id: 'out-007', name: 'Prepared Mix', quantity: 40, unit: 'L', isStatic: false },
          ],
        },
        {
          id: 'step-006',
          stepNumber: 2,
          name: 'Reaction Phase',
          description: 'Controlled reaction at specified temperature',
          inputs: [
            { id: 'in-012', name: 'Prepared Mix', quantity: 40, unit: 'L', isStatic: false },
            { id: 'in-013', name: 'Reaction Time', quantity: 2, unit: 'hr', isStatic: true },
            { id: 'in-014', name: 'Temperature', quantity: 85, unit: 'C', isStatic: true },
          ],
          outputs: [
            { id: 'out-008', name: 'Reacted Compound', quantity: 38, unit: 'L', isStatic: false },
          ],
        },
      ],
      activeExecutions: 1,
      completedExecutions: 124,
      createdAt: '2024-02-20',
    },
    {
      id: 'proc-003',
      name: 'Packaging Line B',
      description: 'Secondary packaging for bulk orders',
      steps: [
        {
          id: 'step-007',
          stepNumber: 1,
          name: 'Product Sorting',
          description: 'Sort products by size and type',
          inputs: [
            { id: 'in-015', name: 'Mixed Products', quantity: 500, unit: 'units', isStatic: false },
          ],
          outputs: [
            { id: 'out-009', name: 'Sorted Products', quantity: 500, unit: 'units', isStatic: false },
          ],
        },
      ],
      activeExecutions: 2,
      completedExecutions: 89,
      createdAt: '2024-03-10',
    },
  ];
  
  const mockExecutions = [
    {
      id: 'exec-001',
      processId: 'proc-001',
      status: 'in-progress',
      currentStep: 2,
      totalSteps: 4,
      startedAt: '2024-12-28T09:00:00Z',
      outputs: [
        { stepNumber: 1, name: 'Verified Materials', quantity: 145, unit: 'kg' },
      ],
    },
    {
      id: 'exec-002',
      processId: 'proc-001',
      status: 'in-progress',
      currentStep: 3,
      totalSteps: 4,
      startedAt: '2024-12-27T14:30:00Z',
      outputs: [
        { stepNumber: 1, name: 'Verified Materials', quantity: 145, unit: 'kg' },
        { stepNumber: 2, name: 'Aluminum Parts', quantity: 200, unit: 'pcs' },
        { stepNumber: 2, name: 'Plastic Housings', quantity: 200, unit: 'pcs' },
      ],
    },
    {
      id: 'exec-003',
      processId: 'proc-001',
      status: 'completed',
      currentStep: 4,
      totalSteps: 4,
      startedAt: '2024-12-26T08:00:00Z',
      completedAt: '2024-12-26T16:45:00Z',
      outputs: [
        { stepNumber: 1, name: 'Verified Materials', quantity: 145, unit: 'kg' },
        { stepNumber: 2, name: 'Aluminum Parts', quantity: 200, unit: 'pcs' },
        { stepNumber: 2, name: 'Plastic Housings', quantity: 200, unit: 'pcs' },
        { stepNumber: 3, name: 'Assembled Widgets', quantity: 200, unit: 'units' },
        { stepNumber: 4, name: 'Approved Widgets', quantity: 195, unit: 'units' },
        { stepNumber: 4, name: 'Rejected Units', quantity: 5, unit: 'units' },
      ],
    },
  ];
  
  const mockInventory = {
    raw: [
      { id: 'inv-001', name: 'Aluminum Sheets', quantity: 2500, unit: 'kg', supplier: 'MetalCorp Inc.', purchaseDate: '2024-12-15', batchNumber: 'AL-2024-1215', expiryDate: null },
      { id: 'inv-002', name: 'Plastic Pellets', quantity: 1800, unit: 'kg', supplier: 'PolymerWorld', purchaseDate: '2024-12-18', batchNumber: 'PP-2024-1218', expiryDate: null },
      { id: 'inv-003', name: 'Chemical A', quantity: 450, unit: 'L', supplier: 'ChemSupply Co.', purchaseDate: '2024-12-20', batchNumber: 'CA-2024-1220', expiryDate: '2025-06-20' },
      { id: 'inv-004', name: 'Chemical B', quantity: 280, unit: 'L', supplier: 'ChemSupply Co.', purchaseDate: '2024-12-20', batchNumber: 'CB-2024-1220', expiryDate: '2025-06-20' },
      { id: 'inv-005', name: 'Screws (M3)', quantity: 50000, unit: 'pcs', supplier: 'FastenerPro', purchaseDate: '2024-12-10', batchNumber: 'SC-2024-1210', expiryDate: null },
    ],
    intermediate: [
      { id: 'inv-006', name: 'Aluminum Parts', quantity: 850, unit: 'pcs', fromProcess: 'Widget Assembly Line A', createdAt: '2024-12-27' },
      { id: 'inv-007', name: 'Plastic Housings', quantity: 920, unit: 'pcs', fromProcess: 'Widget Assembly Line A', createdAt: '2024-12-27' },
      { id: 'inv-008', name: 'Reacted Compound', quantity: 156, unit: 'L', fromProcess: 'Chemical Batch Processing', createdAt: '2024-12-28' },
    ],
    final: [
      { id: 'inv-009', name: 'Approved Widgets', quantity: 4250, unit: 'units', fromProcess: 'Widget Assembly Line A', createdAt: '2024-12-28' },
      { id: 'inv-010', name: 'Packaged Bulk Orders', quantity: 89, unit: 'boxes', fromProcess: 'Packaging Line B', createdAt: '2024-12-28' },
    ],
  };
  
  // Helper functions
  function getProcessById(id) {
    return mockProcesses.find(p => p.id === id);
  }
  
  function getExecutionsForProcess(processId) {
    return mockExecutions.filter(e => e.processId === processId);
  }
  
  function getTotalActiveExecutions() {
    return mockProcesses.reduce((sum, p) => sum + p.activeExecutions, 0);
  }
  
  function getTotalCompletedExecutions() {
    return mockProcesses.reduce((sum, p) => sum + p.completedExecutions, 0);
  }
  
  function getTotalInventoryCount() {
    return {
      raw: mockInventory.raw.length,
      intermediate: mockInventory.intermediate.length,
      final: mockInventory.final.length,
      total: mockInventory.raw.length + mockInventory.intermediate.length + mockInventory.final.length,
    };
  }