# Workflow Creator

This module provides a user interface for creating and managing workflows in the application. It allows users to define workflows that can store and process data through a web interface, without requiring direct code changes.

## Features

- Create new workflows with custom data storage
- Choose between creating new database tables or using existing ones
- Define custom table columns with various data types
- View and manage existing workflows
- Mobile-responsive interface

## Setup

1. Import the workflow creator blueprint in `app.py`:
```python
from workflows.workflow_creator.workflow_creator import workflow_creator
app.register_blueprint(workflow_creator)
```

2. Create the required database tables by running:
```python
from workflows.workflow_creator.create_tables import create_workflow_tables
create_workflow_tables()
```

## Usage

1. Access the workflow creator at `/workflow-creator`
2. Fill in the workflow details:
   - Name and description
   - Choose storage type (new table or existing table)
   - If creating a new table, define the columns
   - If using an existing table, select from available tables
3. Submit the form to create the workflow
4. View and manage created workflows in the list below the form

## Database Structure

The workflow creator uses two main tables:

1. `workflow_definitions`:
   - Stores workflow metadata and configuration
   - Contains table definitions for new workflows
   - Tracks workflow status and settings

2. `workflow_instances`:
   - Tracks individual runs of workflows
   - Stores input and output data
   - Records execution status and timing

## Adding New Features

To extend the workflow creator:

1. Add new fields to the workflow form in `workflow_creator.html`
2. Update the workflow creation logic in `workflow_creator.py`
3. Add any necessary database columns to `create_tables.py`
4. Test thoroughly with different workflow configurations

## Best Practices

1. Always validate user input before creating tables or workflows
2. Use appropriate data types for columns
3. Include proper error handling and user feedback
4. Keep workflow definitions simple and focused
5. Document any custom workflow configurations 