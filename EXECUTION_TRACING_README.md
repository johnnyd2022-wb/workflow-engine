# Execution-Based Tracing System

A comprehensive supply chain tracing system that enables full traceability from raw materials through manufacturing processes to final sales using execution IDs as the backbone for batch lineage.

## 🎯 Overview

This system implements the execution-centric lineage approach discussed in the ChatGPT conversation, where execution IDs serve as the universal key for traceability instead of manually propagating inputs and outputs through each process node in the DAG.

## 🏗️ Architecture

### Database Schema

The system uses several new database tables:

- **`supply_chain_parent_executions`** - Stores parent process executions with batch IDs
- **`supply_chain_sub_executions`** - Stores sub-process executions linked to parent executions
- **`supply_chain_execution_sales_mapping`** - Maps executions to sales for full traceability
- **`supply_chain_execution_lineage`** - Stores execution lineage relationships

### Key Features

1. **Execution-Centric Tracing**: Uses execution IDs as the backbone for all traceability
2. **Automatic Mapping**: Automatically maps sales to executions based on batch references
3. **Manual Override**: Allows manual mapping for complex scenarios
4. **Beautiful UI**: Modern, responsive tracing visualization page
5. **Search & Filter**: Find executions, sales, or batches across the system
6. **Real-time Statistics**: Live dashboard showing mapping status

## 🚀 Getting Started

### 1. Database Setup

Run the database initialization to create the new tables:

```bash
python initialize.py
```

This will create all the required tables for the execution tracing system.

### 2. Access the Tracing Page

Navigate to the execution tracing page:

```
http://localhost:5000/supply-chain/execution-tracing
```

### 3. API Endpoints

The system provides several API endpoints:

#### Execution Lineage
- `GET /api/supply-chain/executions/{id}/lineage` - Get full execution lineage tree
- `GET /api/supply-chain/executions/{id}/sales` - Get linked sales for an execution

#### Sales Integration
- `GET /api/supply-chain/sales/unmapped` - Get sales without execution mapping
- `POST /api/supply-chain/sales/{id}/auto-map` - Attempt automatic mapping
- `GET /api/supply-chain/sales/{id}/trace` - Trace sales back to source

#### Search & Statistics
- `GET /api/supply-chain/traceability/search` - Search executions, sales, or batches
- `GET /api/supply-chain/executions/stats` - Get execution statistics

#### Mapping Operations
- `POST /api/supply-chain/executions/{id}/map-sales` - Map execution to sales
- `GET /api/supply-chain/sales/{id}/suggestions` - Get execution suggestions

## 📊 Usage Examples

### Example 1: Gin Distillery Process

1. **Create Execution**: Start "Gin Batch #2024-001" execution
2. **Track Progress**: System tracks each sub-process completion
3. **Generate Outputs**: Final bottling creates "Bottled Gin Batch #2024-001"
4. **Sales Integration**: When bottles are sold, system maps sales to execution
5. **Full Traceability**: User can trace from sale back to original juniper berries

### Example 2: Automatic Mapping

When a new sale is created with batch information:

```python
# This happens automatically when sales are inserted
from features.supply_chain.backend.sales_execution_mapping import attempt_automatic_sales_mapping

result = attempt_automatic_sales_mapping(sales_id)
# Returns: {'success': True, 'mappings_created': 2, 'mappings': [...]}
```

### Example 3: Manual Mapping

For complex scenarios, manual mapping is available:

```python
from features.supply_chain.backend.sales_execution_mapping import create_manual_sales_mapping

result = create_manual_sales_mapping(
    execution_id=123,
    sales_id=456,
    product_name="Premium Gin 750ml",
    quantity_sold=24,
    batch_reference="Gin Batch #2024-001",
    mapping_notes="Manual mapping due to batch split"
)
```

## 🔍 Tracing Flow

### From Sales to Source

1. **Start with Sale**: User searches for a specific sale or invoice
2. **Find Mappings**: System finds all execution mappings for that sale
3. **Trace Lineage**: System walks the execution lineage tree
4. **Show Full Path**: Display complete path from raw materials to sale

### From Execution to Sales

1. **Start with Execution**: User selects an execution (e.g., "Gin Batch #2024-001")
2. **Show Sub-processes**: Display all sub-processes and their status
3. **Find Sales**: Show all sales linked to this execution
4. **Display Timeline**: Show the complete journey from start to sale

## 🎨 Frontend Features

### Beautiful Tracing Page

The tracing page (`execution_tracing.html`) provides:

- **Modern Design**: Glassmorphism UI consistent with existing supply chain pages
- **Interactive Search**: Search executions, sales, or batches
- **Visual Flow**: DAG visualization showing supply chain flow
- **Statistics Dashboard**: Live statistics on executions and mappings
- **Mapping Interface**: Easy-to-use interface for manual mapping

### Key UI Components

- **Search Section**: Find any execution, sale, or batch
- **Statistics Grid**: Live statistics on system status
- **Flow Diagram**: Visual representation of supply chain flow
- **Execution Tree**: Hierarchical display of executions
- **Sales Panel**: Show linked sales with batch information
- **Mapping Modal**: Interface for creating manual mappings

## 🔧 Configuration

### Automatic Mapping Settings

The automatic mapping system can be configured by modifying the `sales_execution_mapping.py` file:

```python
# Confidence thresholds
BATCH_MATCH_CONFIDENCE = 0.8
PRODUCT_MATCH_CONFIDENCE = 0.6
TIMING_MATCH_CONFIDENCE = 0.5

# Date ranges for suggestions
SUGGESTION_DATE_RANGE_DAYS = 30
```

### Database Configuration

Ensure your database connection is properly configured in `initialize.py` and that the new tables are created.

## 🧪 Testing

Run the integration test script to verify everything is working:

```bash
python test_execution_tracing.py
```

This will test:
- Database table existence
- API endpoint accessibility
- Sales mapping module functionality
- Frontend page availability

## 📈 Benefits

### For Users

1. **Simplified Tracing**: Use execution IDs as the backbone for all traceability
2. **Universal Application**: Works for any business type (distillery, manufacturing, etc.)
3. **Human-Friendly**: Batch names and execution IDs are meaningful to users
4. **Flexible**: Supports both automatic and manual mapping scenarios

### For Developers

1. **Scalable**: Efficient queries using execution relationships
2. **Maintainable**: Clean separation of concerns
3. **Extensible**: Easy to add new features and integrations
4. **Testable**: Comprehensive test coverage

## 🔮 Future Enhancements

1. **Advanced Analytics**: Machine learning for better mapping suggestions
2. **Export Functionality**: Export traceability reports
3. **Mobile Support**: Mobile-optimized tracing interface
4. **Integration APIs**: Connect with external systems
5. **Real-time Updates**: WebSocket support for live updates

## 🤝 Contributing

When adding new features:

1. Follow the existing code structure
2. Add comprehensive tests
3. Update this documentation
4. Ensure backward compatibility
5. Follow the established UI/UX patterns

## 📝 License

This system is part of the larger supply chain management application and follows the same licensing terms.

---

**Note**: This system implements the execution-centric lineage approach discussed in the ChatGPT conversation, providing a clean, scalable solution for supply chain traceability that works for any business type.
