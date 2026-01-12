// Mock Data for Supply Chain Platform
// This file mirrors src/data/mockData.ts for Flask template compatibility

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

// ============================================================
// PROCESSES
// ============================================================
const mockProcesses = [
  {
    id: 'proc-001',
    name: 'Pharmaceutical Tablet Manufacturing',
    description: 'End-to-end tablet production from raw materials to packaged product',
    activeExecutions: 2,  // exec-001, exec-002
    completedExecutions: 1,  // exec-005 (173,800 tablets)
    createdAt: '2024-01-15',
    steps: [
      {
        id: 'step-001',
        stepNumber: 1,
        name: 'Raw Material Weighing',
        description: 'Weigh and verify all raw materials according to batch record',
        inputs: [
          { id: 'inp-001', name: 'API (Active Ingredient)', quantity: 50, unit: 'kg', isVariable: false },
          { id: 'inp-002', name: 'Excipient A', quantity: 25, unit: 'kg', isVariable: false },
          { id: 'inp-003', name: 'Excipient B', quantity: 15, unit: 'kg', isVariable: false },
        ],
        outputs: [
          { id: 'out-001', name: 'Weighed Materials', quantity: 90, unit: 'kg', isVariable: false },
        ],
      },
      {
        id: 'step-002',
        stepNumber: 2,
        name: 'Blending',
        description: 'Blend weighed materials in V-blender for homogeneity',
        inputs: [
          { id: 'inp-004', name: 'Weighed Materials', quantity: 90, unit: 'kg', isVariable: false },
        ],
        outputs: [
          { id: 'out-002', name: 'Blended Powder', quantity: 89.5, unit: 'kg', isVariable: true },
        ],
      },
      {
        id: 'step-003',
        stepNumber: 3,
        name: 'Granulation',
        description: 'Wet granulation process with binder solution',
        inputs: [
          { id: 'inp-005', name: 'Blended Powder', quantity: 89.5, unit: 'kg', isVariable: true },
          { id: 'inp-006', name: 'Binder Solution', quantity: 15, unit: 'L', isVariable: false },
        ],
        outputs: [
          { id: 'out-003', name: 'Wet Granules', quantity: 100, unit: 'kg', isVariable: true },
        ],
      },
      {
        id: 'step-004',
        stepNumber: 4,
        name: 'Drying',
        description: 'Fluid bed drying to target moisture content',
        inputs: [
          { id: 'inp-007', name: 'Wet Granules', quantity: 100, unit: 'kg', isVariable: true },
        ],
        outputs: [
          { id: 'out-004', name: 'Dried Granules', quantity: 88, unit: 'kg', isVariable: true },
        ],
      },
      {
        id: 'step-005',
        stepNumber: 5,
        name: 'Compression',
        description: 'Tablet compression using rotary press',
        inputs: [
          { id: 'inp-008', name: 'Dried Granules', quantity: 88, unit: 'kg', isVariable: true },
        ],
        outputs: [
          { id: 'out-005', name: 'Uncoated Tablets', quantity: 175000, unit: 'pcs', isVariable: true },
        ],
      },
      {
        id: 'step-006',
        stepNumber: 6,
        name: 'Coating',
        description: 'Film coating application',
        inputs: [
          { id: 'inp-009', name: 'Uncoated Tablets', quantity: 175000, unit: 'pcs', isVariable: true },
          { id: 'inp-010', name: 'Coating Solution', quantity: 8, unit: 'L', isVariable: false },
        ],
        outputs: [
          { id: 'out-006', name: 'Coated Tablets', quantity: 174500, unit: 'pcs', isVariable: true },
        ],
      },
    ],
  },
  {
    id: 'proc-002',
    name: 'Food Grade Oil Refining',
    description: 'Crude oil refining process for food-grade applications',
    activeExecutions: 1,
    completedExecutions: 3,
    createdAt: '2024-02-20',
    steps: [
      {
        id: 'step-007',
        stepNumber: 1,
        name: 'Degumming',
        description: 'Remove phospholipids and gums from crude oil',
        inputs: [
          { id: 'inp-011', name: 'Crude Oil', quantity: 1000, unit: 'L', isVariable: false },
          { id: 'inp-012', name: 'Phosphoric Acid', quantity: 2, unit: 'L', isVariable: false },
        ],
        outputs: [
          { id: 'out-007', name: 'Degummed Oil', quantity: 980, unit: 'L', isVariable: true },
        ],
      },
      {
        id: 'step-008',
        stepNumber: 2,
        name: 'Neutralization',
        description: 'Neutralize free fatty acids',
        inputs: [
          { id: 'inp-013', name: 'Degummed Oil', quantity: 980, unit: 'L', isVariable: true },
          { id: 'inp-014', name: 'Sodium Hydroxide', quantity: 5, unit: 'kg', isVariable: false },
        ],
        outputs: [
          { id: 'out-008', name: 'Neutralized Oil', quantity: 960, unit: 'L', isVariable: true },
        ],
      },
      {
        id: 'step-009',
        stepNumber: 3,
        name: 'Bleaching',
        description: 'Remove color pigments and impurities',
        inputs: [
          { id: 'inp-015', name: 'Neutralized Oil', quantity: 960, unit: 'L', isVariable: true },
          { id: 'inp-016', name: 'Bleaching Earth', quantity: 10, unit: 'kg', isVariable: false },
        ],
        outputs: [
          { id: 'out-009', name: 'Bleached Oil', quantity: 950, unit: 'L', isVariable: true },
        ],
      },
      {
        id: 'step-010',
        stepNumber: 4,
        name: 'Deodorization',
        description: 'Remove odors and volatile compounds',
        inputs: [
          { id: 'inp-017', name: 'Bleached Oil', quantity: 950, unit: 'L', isVariable: true },
        ],
        outputs: [
          { id: 'out-010', name: 'Refined Oil', quantity: 940, unit: 'L', isVariable: true },
        ],
      },
    ],
  },
  {
    id: 'proc-003',
    name: 'Electronic Component Assembly',
    description: 'PCB assembly and testing workflow',
    activeExecutions: 1,
    completedExecutions: 5,
    createdAt: '2024-03-10',
    steps: [
      {
        id: 'step-011',
        stepNumber: 1,
        name: 'Solder Paste Application',
        description: 'Apply solder paste to PCB pads',
        inputs: [
          { id: 'inp-018', name: 'Bare PCB', quantity: 100, unit: 'pcs', isVariable: false },
          { id: 'inp-019', name: 'Solder Paste', quantity: 50, unit: 'g', isVariable: false },
        ],
        outputs: [
          { id: 'out-011', name: 'Pasted PCB', quantity: 100, unit: 'pcs', isVariable: false },
        ],
      },
      {
        id: 'step-012',
        stepNumber: 2,
        name: 'Component Placement',
        description: 'Place SMD components on PCB',
        inputs: [
          { id: 'inp-020', name: 'Pasted PCB', quantity: 100, unit: 'pcs', isVariable: false },
          { id: 'inp-021', name: 'SMD Components Kit', quantity: 100, unit: 'units', isVariable: false },
        ],
        outputs: [
          { id: 'out-012', name: 'Populated PCB', quantity: 100, unit: 'pcs', isVariable: false },
        ],
      },
      {
        id: 'step-013',
        stepNumber: 3,
        name: 'Reflow Soldering',
        description: 'Reflow solder in oven',
        inputs: [
          { id: 'inp-022', name: 'Populated PCB', quantity: 100, unit: 'pcs', isVariable: false },
        ],
        outputs: [
          { id: 'out-013', name: 'Soldered PCB', quantity: 99, unit: 'pcs', isVariable: true },
        ],
      },
      {
        id: 'step-014',
        stepNumber: 4,
        name: 'Inspection & Testing',
        description: 'AOI and functional testing',
        inputs: [
          { id: 'inp-023', name: 'Soldered PCB', quantity: 99, unit: 'pcs', isVariable: true },
        ],
        outputs: [
          { id: 'out-014', name: 'Tested PCB (Pass)', quantity: 97, unit: 'pcs', isVariable: true },
          { id: 'out-015', name: 'Tested PCB (Fail)', quantity: 2, unit: 'pcs', isVariable: true },
        ],
      },
    ],
  },
];

// ============================================================
// EXECUTIONS
// 4 in-flight (2 pharma, 1 oil, 1 electronics)
// Completed: 1 pharma, 3 oil, 5 electronics
// ============================================================
const mockExecutions = [
  // ========== IN-FLIGHT EXECUTIONS ==========
  {
    id: 'exec-001',
    processId: 'proc-001',
    processName: 'Pharmaceutical Tablet Manufacturing',
    status: 'in-flight',
    currentStep: 4,
    totalSteps: 6,
    startedAt: '2024-12-28T08:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Raw Material Weighing', outputs: [{ id: 'out-001', name: 'Weighed Materials', quantity: 90, unit: 'kg', isVariable: false }], completedAt: '2024-12-28T09:30:00Z' },
      { stepNumber: 2, stepName: 'Blending', outputs: [{ id: 'out-002', name: 'Blended Powder', quantity: 89.2, unit: 'kg', isVariable: true }], completedAt: '2024-12-28T11:00:00Z' },
      { stepNumber: 3, stepName: 'Granulation', outputs: [{ id: 'out-003', name: 'Wet Granules', quantity: 99.5, unit: 'kg', isVariable: true }], completedAt: '2024-12-28T14:00:00Z' },
    ],
  },
  {
    id: 'exec-002',
    processId: 'proc-001',
    processName: 'Pharmaceutical Tablet Manufacturing',
    status: 'in-flight',
    currentStep: 2,
    totalSteps: 6,
    startedAt: '2024-12-30T08:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Raw Material Weighing', outputs: [{ id: 'out-001', name: 'Weighed Materials', quantity: 90, unit: 'kg', isVariable: false }], completedAt: '2024-12-30T09:45:00Z' },
    ],
  },
  {
    id: 'exec-003',
    processId: 'proc-002',
    processName: 'Food Grade Oil Refining',
    status: 'in-flight',
    currentStep: 2,
    totalSteps: 4,
    startedAt: '2024-12-31T06:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Degumming', outputs: [{ id: 'out-007', name: 'Degummed Oil', quantity: 978, unit: 'L', isVariable: true }], completedAt: '2024-12-31T10:00:00Z' },
    ],
  },
  {
    id: 'exec-004',
    processId: 'proc-003',
    processName: 'Electronic Component Assembly',
    status: 'in-flight',
    currentStep: 3,
    totalSteps: 4,
    startedAt: '2024-12-31T06:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Solder Paste Application', outputs: [{ id: 'out-011', name: 'Pasted PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-31T07:00:00Z' },
      { stepNumber: 2, stepName: 'Component Placement', outputs: [{ id: 'out-012', name: 'Populated PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-31T09:00:00Z' },
    ],
  },
  
  // ========== COMPLETED EXECUTIONS ==========
  // Pharma: 1 completed batch = 173,800 tablets
  {
    id: 'exec-005',
    processId: 'proc-001',
    processName: 'Pharmaceutical Tablet Manufacturing',
    status: 'completed',
    currentStep: 6,
    totalSteps: 6,
    startedAt: '2024-12-01T08:00:00Z',
    completedAt: '2024-12-02T16:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Raw Material Weighing', outputs: [{ id: 'out-001', name: 'Weighed Materials', quantity: 90, unit: 'kg', isVariable: false }], completedAt: '2024-12-01T09:30:00Z' },
      { stepNumber: 2, stepName: 'Blending', outputs: [{ id: 'out-002', name: 'Blended Powder', quantity: 89.1, unit: 'kg', isVariable: true }], completedAt: '2024-12-01T11:00:00Z' },
      { stepNumber: 3, stepName: 'Granulation', outputs: [{ id: 'out-003', name: 'Wet Granules', quantity: 99.8, unit: 'kg', isVariable: true }], completedAt: '2024-12-01T14:00:00Z' },
      { stepNumber: 4, stepName: 'Drying', outputs: [{ id: 'out-004', name: 'Dried Granules', quantity: 87.5, unit: 'kg', isVariable: true }], completedAt: '2024-12-01T18:00:00Z' },
      { stepNumber: 5, stepName: 'Compression', outputs: [{ id: 'out-005', name: 'Uncoated Tablets', quantity: 174200, unit: 'pcs', isVariable: true }], completedAt: '2024-12-02T10:00:00Z' },
      { stepNumber: 6, stepName: 'Coating', outputs: [{ id: 'out-006', name: 'Coated Tablets', quantity: 173800, unit: 'pcs', isVariable: true }], completedAt: '2024-12-02T16:00:00Z' },
    ],
  },
  // Oil: 3 completed batches = 938 + 942 + 940 = 2,820 L
  {
    id: 'exec-006',
    processId: 'proc-002',
    processName: 'Food Grade Oil Refining',
    status: 'completed',
    currentStep: 4,
    totalSteps: 4,
    startedAt: '2024-12-10T08:00:00Z',
    completedAt: '2024-12-11T16:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Degumming', outputs: [{ id: 'out-007', name: 'Degummed Oil', quantity: 982, unit: 'L', isVariable: true }], completedAt: '2024-12-10T12:00:00Z' },
      { stepNumber: 2, stepName: 'Neutralization', outputs: [{ id: 'out-008', name: 'Neutralized Oil', quantity: 958, unit: 'L', isVariable: true }], completedAt: '2024-12-10T16:00:00Z' },
      { stepNumber: 3, stepName: 'Bleaching', outputs: [{ id: 'out-009', name: 'Bleached Oil', quantity: 948, unit: 'L', isVariable: true }], completedAt: '2024-12-11T10:00:00Z' },
      { stepNumber: 4, stepName: 'Deodorization', outputs: [{ id: 'out-010', name: 'Refined Oil', quantity: 938, unit: 'L', isVariable: true }], completedAt: '2024-12-11T16:00:00Z' },
    ],
  },
  {
    id: 'exec-007',
    processId: 'proc-002',
    processName: 'Food Grade Oil Refining',
    status: 'completed',
    currentStep: 4,
    totalSteps: 4,
    startedAt: '2024-12-15T08:00:00Z',
    completedAt: '2024-12-16T16:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Degumming', outputs: [{ id: 'out-007', name: 'Degummed Oil', quantity: 979, unit: 'L', isVariable: true }], completedAt: '2024-12-15T12:00:00Z' },
      { stepNumber: 2, stepName: 'Neutralization', outputs: [{ id: 'out-008', name: 'Neutralized Oil', quantity: 962, unit: 'L', isVariable: true }], completedAt: '2024-12-15T16:00:00Z' },
      { stepNumber: 3, stepName: 'Bleaching', outputs: [{ id: 'out-009', name: 'Bleached Oil', quantity: 951, unit: 'L', isVariable: true }], completedAt: '2024-12-16T10:00:00Z' },
      { stepNumber: 4, stepName: 'Deodorization', outputs: [{ id: 'out-010', name: 'Refined Oil', quantity: 942, unit: 'L', isVariable: true }], completedAt: '2024-12-16T16:00:00Z' },
    ],
  },
  {
    id: 'exec-008',
    processId: 'proc-002',
    processName: 'Food Grade Oil Refining',
    status: 'completed',
    currentStep: 4,
    totalSteps: 4,
    startedAt: '2024-12-20T08:00:00Z',
    completedAt: '2024-12-21T16:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Degumming', outputs: [{ id: 'out-007', name: 'Degummed Oil', quantity: 985, unit: 'L', isVariable: true }], completedAt: '2024-12-20T12:00:00Z' },
      { stepNumber: 2, stepName: 'Neutralization', outputs: [{ id: 'out-008', name: 'Neutralized Oil', quantity: 965, unit: 'L', isVariable: true }], completedAt: '2024-12-20T16:00:00Z' },
      { stepNumber: 3, stepName: 'Bleaching', outputs: [{ id: 'out-009', name: 'Bleached Oil', quantity: 952, unit: 'L', isVariable: true }], completedAt: '2024-12-21T10:00:00Z' },
      { stepNumber: 4, stepName: 'Deodorization', outputs: [{ id: 'out-010', name: 'Refined Oil', quantity: 940, unit: 'L', isVariable: true }], completedAt: '2024-12-21T16:00:00Z' },
    ],
  },
  // PCB: 5 completed batches = 97 + 96 + 97 + 98 + 97 = 485 pcs
  {
    id: 'exec-009',
    processId: 'proc-003',
    processName: 'Electronic Component Assembly',
    status: 'completed',
    currentStep: 4,
    totalSteps: 4,
    startedAt: '2024-12-22T06:00:00Z',
    completedAt: '2024-12-22T14:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Solder Paste Application', outputs: [{ id: 'out-011', name: 'Pasted PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-22T07:00:00Z' },
      { stepNumber: 2, stepName: 'Component Placement', outputs: [{ id: 'out-012', name: 'Populated PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-22T09:00:00Z' },
      { stepNumber: 3, stepName: 'Reflow Soldering', outputs: [{ id: 'out-013', name: 'Soldered PCB', quantity: 99, unit: 'pcs', isVariable: true }], completedAt: '2024-12-22T11:00:00Z' },
      { stepNumber: 4, stepName: 'Inspection & Testing', outputs: [{ id: 'out-014', name: 'Tested PCB (Pass)', quantity: 97, unit: 'pcs', isVariable: true }, { id: 'out-015', name: 'Tested PCB (Fail)', quantity: 2, unit: 'pcs', isVariable: true }], completedAt: '2024-12-22T14:00:00Z' },
    ],
  },
  {
    id: 'exec-010',
    processId: 'proc-003',
    processName: 'Electronic Component Assembly',
    status: 'completed',
    currentStep: 4,
    totalSteps: 4,
    startedAt: '2024-12-24T06:00:00Z',
    completedAt: '2024-12-24T14:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Solder Paste Application', outputs: [{ id: 'out-011', name: 'Pasted PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-24T07:00:00Z' },
      { stepNumber: 2, stepName: 'Component Placement', outputs: [{ id: 'out-012', name: 'Populated PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-24T09:00:00Z' },
      { stepNumber: 3, stepName: 'Reflow Soldering', outputs: [{ id: 'out-013', name: 'Soldered PCB', quantity: 98, unit: 'pcs', isVariable: true }], completedAt: '2024-12-24T11:00:00Z' },
      { stepNumber: 4, stepName: 'Inspection & Testing', outputs: [{ id: 'out-014', name: 'Tested PCB (Pass)', quantity: 96, unit: 'pcs', isVariable: true }, { id: 'out-015', name: 'Tested PCB (Fail)', quantity: 2, unit: 'pcs', isVariable: true }], completedAt: '2024-12-24T14:00:00Z' },
    ],
  },
  {
    id: 'exec-011',
    processId: 'proc-003',
    processName: 'Electronic Component Assembly',
    status: 'completed',
    currentStep: 4,
    totalSteps: 4,
    startedAt: '2024-12-26T06:00:00Z',
    completedAt: '2024-12-26T14:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Solder Paste Application', outputs: [{ id: 'out-011', name: 'Pasted PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-26T07:00:00Z' },
      { stepNumber: 2, stepName: 'Component Placement', outputs: [{ id: 'out-012', name: 'Populated PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-26T09:00:00Z' },
      { stepNumber: 3, stepName: 'Reflow Soldering', outputs: [{ id: 'out-013', name: 'Soldered PCB', quantity: 99, unit: 'pcs', isVariable: true }], completedAt: '2024-12-26T11:00:00Z' },
      { stepNumber: 4, stepName: 'Inspection & Testing', outputs: [{ id: 'out-014', name: 'Tested PCB (Pass)', quantity: 97, unit: 'pcs', isVariable: true }, { id: 'out-015', name: 'Tested PCB (Fail)', quantity: 2, unit: 'pcs', isVariable: true }], completedAt: '2024-12-26T14:00:00Z' },
    ],
  },
  {
    id: 'exec-012',
    processId: 'proc-003',
    processName: 'Electronic Component Assembly',
    status: 'completed',
    currentStep: 4,
    totalSteps: 4,
    startedAt: '2024-12-28T06:00:00Z',
    completedAt: '2024-12-28T14:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Solder Paste Application', outputs: [{ id: 'out-011', name: 'Pasted PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-28T07:00:00Z' },
      { stepNumber: 2, stepName: 'Component Placement', outputs: [{ id: 'out-012', name: 'Populated PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-28T09:00:00Z' },
      { stepNumber: 3, stepName: 'Reflow Soldering', outputs: [{ id: 'out-013', name: 'Soldered PCB', quantity: 99, unit: 'pcs', isVariable: true }], completedAt: '2024-12-28T11:00:00Z' },
      { stepNumber: 4, stepName: 'Inspection & Testing', outputs: [{ id: 'out-014', name: 'Tested PCB (Pass)', quantity: 98, unit: 'pcs', isVariable: true }, { id: 'out-015', name: 'Tested PCB (Fail)', quantity: 1, unit: 'pcs', isVariable: true }], completedAt: '2024-12-28T14:00:00Z' },
    ],
  },
  {
    id: 'exec-013',
    processId: 'proc-003',
    processName: 'Electronic Component Assembly',
    status: 'completed',
    currentStep: 4,
    totalSteps: 4,
    startedAt: '2024-12-29T06:00:00Z',
    completedAt: '2024-12-29T14:00:00Z',
    stepOutputs: [
      { stepNumber: 1, stepName: 'Solder Paste Application', outputs: [{ id: 'out-011', name: 'Pasted PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-29T07:00:00Z' },
      { stepNumber: 2, stepName: 'Component Placement', outputs: [{ id: 'out-012', name: 'Populated PCB', quantity: 100, unit: 'pcs', isVariable: false }], completedAt: '2024-12-29T09:00:00Z' },
      { stepNumber: 3, stepName: 'Reflow Soldering', outputs: [{ id: 'out-013', name: 'Soldered PCB', quantity: 99, unit: 'pcs', isVariable: true }], completedAt: '2024-12-29T11:00:00Z' },
      { stepNumber: 4, stepName: 'Inspection & Testing', outputs: [{ id: 'out-014', name: 'Tested PCB (Pass)', quantity: 97, unit: 'pcs', isVariable: true }, { id: 'out-015', name: 'Tested PCB (Fail)', quantity: 2, unit: 'pcs', isVariable: true }], completedAt: '2024-12-29T14:00:00Z' },
    ],
  },
];

// ============================================================
// INVENTORY
// Matches mockData.ts structure with type field for categorization
// Raw = remaining stock after consumption
// Intermediate = WIP from in-flight executions
// Final = output from completed executions
// ============================================================
const mockInventory = [
  // ========== RAW MATERIALS ==========
  // Pharma (proc-001): 3 batches consumed (2 in-flight + 1 completed)
  { id: 'inv-001', name: 'API (Active Ingredient)', type: 'raw', quantity: 500, unit: 'kg', processId: 'proc-001', supplier: 'PharmaChem Inc', purchaseDate: '2024-12-01', supplierBatchNumber: 'PC-2024-1201', expiryDate: '2026-12-01' },
  { id: 'inv-002', name: 'Excipient A', type: 'raw', quantity: 250, unit: 'kg', processId: 'proc-001', supplier: 'ChemSupply Co', purchaseDate: '2024-11-15', supplierBatchNumber: 'CS-2024-1115', expiryDate: '2025-11-15' },
  { id: 'inv-003', name: 'Excipient B', type: 'raw', quantity: 180, unit: 'kg', processId: 'proc-001', supplier: 'ChemSupply Co', purchaseDate: '2024-11-15', supplierBatchNumber: 'CS-2024-1116', expiryDate: '2025-11-15' },
  { id: 'inv-004', name: 'Binder Solution', type: 'raw', quantity: 120, unit: 'L', processId: 'proc-001', supplier: 'ChemSupply Co', purchaseDate: '2024-11-20', supplierBatchNumber: 'CS-2024-1120' },
  { id: 'inv-005', name: 'Coating Solution', type: 'raw', quantity: 80, unit: 'L', processId: 'proc-001', supplier: 'CoatChem Ltd', purchaseDate: '2024-11-25', supplierBatchNumber: 'CC-2024-1125' },
  
  // Oil (proc-002): 4 batches consumed (1 in-flight + 3 completed)
  { id: 'inv-006', name: 'Crude Oil', type: 'raw', quantity: 5000, unit: 'L', processId: 'proc-002', supplier: 'OilSource Ltd', purchaseDate: '2024-12-10', supplierBatchNumber: 'OS-2024-1210' },
  { id: 'inv-007', name: 'Phosphoric Acid', type: 'raw', quantity: 42, unit: 'L', processId: 'proc-002', supplier: 'ChemSupply Co', purchaseDate: '2024-12-10', supplierBatchNumber: 'CS-2024-1210' },
  { id: 'inv-008', name: 'Sodium Hydroxide', type: 'raw', quantity: 80, unit: 'kg', processId: 'proc-002', supplier: 'ChemSupply Co', purchaseDate: '2024-12-10', supplierBatchNumber: 'CS-2024-1211' },
  { id: 'inv-009', name: 'Bleaching Earth', type: 'raw', quantity: 160, unit: 'kg', processId: 'proc-002', supplier: 'MineralCorp', purchaseDate: '2024-12-10', supplierBatchNumber: 'MC-2024-1210' },
  
  // PCB (proc-003): 6 batches consumed (1 in-flight + 5 completed)
  { id: 'inv-010', name: 'Bare PCB', type: 'raw', quantity: 1000, unit: 'pcs', processId: 'proc-003', supplier: 'PCB Masters', purchaseDate: '2024-12-20', supplierBatchNumber: 'PM-2024-1220' },
  { id: 'inv-011', name: 'SMD Components Kit', type: 'raw', quantity: 850, unit: 'units', processId: 'proc-003', supplier: 'ElectroParts', purchaseDate: '2024-12-22', supplierBatchNumber: 'EP-2024-1222' },
  { id: 'inv-012', name: 'Solder Paste', type: 'raw', quantity: 200, unit: 'g', processId: 'proc-003', supplier: 'SolderTech', purchaseDate: '2024-12-20', supplierBatchNumber: 'ST-2024-1220' },
  
  // ========== INTERMEDIATE PRODUCTS (from in-flight executions) ==========
  { id: 'inv-013', name: 'Wet Granules', type: 'intermediate', quantity: 99, unit: 'kg', processId: 'proc-001', executionId: 'exec-001' },
  { id: 'inv-014', name: 'Weighed Materials', type: 'intermediate', quantity: 90, unit: 'kg', processId: 'proc-001', executionId: 'exec-002' },
  { id: 'inv-015', name: 'Degummed Oil', type: 'intermediate', quantity: 978, unit: 'L', processId: 'proc-002', executionId: 'exec-003' },
  { id: 'inv-016', name: 'Populated PCB', type: 'intermediate', quantity: 100, unit: 'pcs', processId: 'proc-003', executionId: 'exec-004' },
  
  // ========== FINAL PRODUCTS (from completed executions) ==========
  { id: 'inv-017', name: 'Coated Tablets', type: 'final', quantity: 173800, unit: 'pcs', processId: 'proc-001' },
  { id: 'inv-018', name: 'Refined Oil', type: 'final', quantity: 2820, unit: 'L', processId: 'proc-002' },
  { id: 'inv-019', name: 'Tested PCB (Pass)', type: 'final', quantity: 485, unit: 'pcs', processId: 'proc-003' },
];

// ============================================================
// HELPER FUNCTIONS
// ============================================================
function getProcessById(id) {
  return mockProcesses.find(p => p.id === id);
}

function getExecutionsForProcess(processId) {
  return mockExecutions.filter(e => e.processId === processId);
}

function getExecutionsByProcessId(processId) {
  return mockExecutions.filter(e => e.processId === processId);
}

function getTotalActiveExecutions() {
  return mockExecutions.filter(e => e.status === 'in-flight').length;
}

function getTotalCompletedExecutions() {
  return mockExecutions.filter(e => e.status === 'completed').length;
}

function getInventoryByType(type) {
  return mockInventory.filter(i => i.type === type);
}

function getInventoryByProcessId(processId) {
  return mockInventory.filter(i => i.processId === processId);
}

function getInventoryForProcess(processId) {
  const processInventory = mockInventory.filter(i => i.processId === processId);
  return {
    raw: processInventory.filter(i => i.type === 'raw'),
    intermediate: processInventory.filter(i => i.type === 'intermediate'),
    final: processInventory.filter(i => i.type === 'final'),
  };
}

function getTotalInventoryCount() {
  return {
    raw: mockInventory.filter(i => i.type === 'raw').length,
    intermediate: mockInventory.filter(i => i.type === 'intermediate').length,
    final: mockInventory.filter(i => i.type === 'final').length,
    total: mockInventory.length,
  };
}