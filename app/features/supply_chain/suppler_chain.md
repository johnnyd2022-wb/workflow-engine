# This file outlines how the supply chain feature is to be built

# Key features for context
The supply chain feature will be a core component of an application I am developing.
The supply chain is built using a DAG which will enable tracing of any custom processes from inputs, outputs and connections

# General Notes and example to reference for thought process
I want the ability to `execute` processes where inputs are user defined and these inputs transform into user defined outputs which flow through as inputs to future process steps and so on. This is to enable tracing per execution.
This then feeds into outputs which are taken as inputs on future processes and eventually will lead to sales data showing the current state of a execution through `completed` processes and remaining (`pending`) processes in the exection allowing a visible DAG graph highlighting where executions are in or flight
I will need a way to determine tracing from first input to processed sales to give a full end to end tracing system that works for any business type

# Process executions
After I created parent process and sub processes with inputs, outputs and connections, I want the ability to perform executions of the parent process. This allows me to track inputs for batches and give me the ability to start tracing my supply chain with batches or whatever other fields I want.

Process executions should track using a unique execution ID to give the tracing ability. When all sub processes in the execution have been completed then there should be a Excutions heading showing the visual view with a green pulse around the completed steps to highlight done steps

For example, I run a Gin distillery. I might create the following process using this DAG
 -  Process name: Distilling example1 flavor Gin
    - inputs:
        - input1: name: juniper berries, quantity: 50, measurment: grams, input batch: __PROMPT ON EXECUTION__, notes: not applicable, type: raw material, source/supplier: Alembics
        - input2: name: orris root, quantity: 10, measurment: grams, input batch: __PROMPT ON EXECUTION__, notes: not applicable, type: raw material, source/supplier: Alembics
    - outputs:
        - output1: name: example1 flavor Gin concentrate, quantity: 1.8, measurement: litres, output batch: __PROMPT ON EXECUTION__, notes: something describing the output for others to understand, category: intermediate product
    - connections:
        - connection1: from process: Distilling example1 flavor Gin, to process: Dilute Gin, connection type: direct, status: active
         notes: something describing the connection for others to udnerstand

 - Process name: Dilute Gin
    - inputs:
        - input1: __INHERITED FROM CONNECTED OUTPUT__
        - input2: name: water, quanitity: 30, measurement: litres, input batch: not applicable/null, notes: not applicable, type: raw material, source: Petone Acquifer
        - input3: name: ethanol, quantity: 24, measurement: litres, input batch: __PROMPT ON EXECUTION__, notes: 96.4% ethanol, type: raw material, source: Southern Grain Spirits
    - outputs:
        - output1: name: Gin, quantity: 57, measurement: litres, output batch: __PROMPT ON EXECUTION__, notes: something describing the output for others to understand, category: intermediate product
    - connections:
        - connection1: from process: Dilute Gin, to process: Age Gin, connection type: direct, status: active
         notes: something describing the connection for others to udnerstand

 - process name: Age Gin
    - inputs:
        input1: __INHERITED FROM CONNECTED OUTPUT__
    - outputs:
        - output1: name: Aged Gin, quantity: 57, measurement: litres, output batch: __PROMPT ON EXECUTION__, notes: something describing the output for others to understand, category: intermediate product
    - connections:
        - connection1: from process: Age Gin, to process: Bottle Gin, connection type: direct, status: active

 - process name: Bottle Gin
    - inputs:
        - input1: __INHERITED FROM CONNECTED OUTPUT__
    - outputs:
        - output1: name: Bottled Gin, quantity: __PROMPT ON EXECUTION__, measurement: bottles, input batch: __PROMPT ON EXECUTION__, notes: something describing output for others to understand, category: finished product
    - connections:
        - connection1: from process: Bottle Gin, to process: sales, connection type: direct, status: active

 - process name: sales
    - outputs:
        - output1: name: sales, quantity: __QUERY_DB__, measurement: bottles, input batch: __PROMPT ON EXECUTION__, notes: not applicable, type: final product, source: not applicable

Do not just assume this needs to only work for a distillery. I plan on selling this to all businesses that use supply chain manufacturing processes and should be able to provide an easy tracing system for any use case.

# Frontend code
All frontend code is stored in features/supply_chain/frontend
 - All frontend code is to be responsive to screen size
 - No UI objects should exceed the browser window size and scroll bars should only be visible if tables or content exceeds browser window size so the UI remains clean
 - Where possible create reusable components that can be applied without duplicating the same code
 - Styling / CSS should follow existing code in the frontend/ folder. I will change it all eventually but that way its all contained in the same location
- NEVER USE BROWSER POP UPS - ALWAYS USE NICELY STYLED CSS POP UPS FOR SUCCESS OR FAILURE MESSAGES


# Backend Code
All backend code is stored in features/supply_chain/backend
 - All components that are created in the UI should have all CRUD API operations available to call even if we do not currently reference them - this will allow future work to utilize them
 - APIs should be used everywhere possible. I will be creating tests to check APIs continue to work before deployments go out
 - I will eventually cleanup backend.py and have only the main flask routes there and API routes stored in the support folder
    - Do not refactor anything to move to the support folder yet but put all new APIs there going forward. I will sort the refactor later

# Questions
Ask me questions if you're ever unsure, never make assumptions.