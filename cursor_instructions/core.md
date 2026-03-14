Backend (Core Engine / Data Model / Execution Logic)

Purpose:
You are implementing the backend engine for a process execution platform.

The frontend UI already exists. Do not modify the UI. Your role is to implement the backend that matches the UI’s mental model and supports all required behavior. The UI is your reference for interaction patterns, colors, and flow, but it will not change.

High-level Architecture

Python backend

SQLAlchemy + Alembic

PostgreSQL with jsonb

Multi-tenant (org-scoped)

Auth, users, and orgs are finalized — do not modify them

Core Domain Concepts
Process (Flow)

Represents a reusable workflow definition

Stored as a DAG (Directed Acyclic Graph)

Contains ordered steps

Steps may have variable or constant inputs

Step (Sub-process)

Belongs to a process

Properties:

Step number (user-defined order)

Name

Description

Inputs and outputs:

Name

Quantity

Unit

Static vs variable flag

Execution

A runtime instance of a process

Each execution:

Walks the process DAG from start to finish

Tracks progress step-by-step

Execution Engine Requirements

Do not rely on inferred state

Implement explicit graph walking with materialized execution state

Required behavior:

Start execution

Create an execution record

Create execution-step records for each step

Mark first executable step as ready

Complete step

Persist actual input values used

Persist outputs produced

Store step execution data immutably (jsonb acceptable)

Advance execution to the next step(s)

Complete execution

Mark execution as completed

Must support:

Multiple in-flight executions per process

Clear determination of:

Current step

Completed steps

Outputs produced so far

Inventory & Traceability

Implement a basic inventory system:

Raw materials

Intermediate products

Final products

Inventory records must support:

Supplier

Purchase date

Supplier batch number (optional)

Expiry date (optional)

Execution outputs should be linkable to inventory items so that:

Raw materials are traceable through executions

Intermediate products are visible at each step

Final products are clearly attributable to executions

Start with a pragmatic model; jsonb is acceptable

Materialize execution steps now; leave room for future artifact/lineage tables

API Expectations

Implement APIs to support:

Creating and listing processes

Viewing a process and its steps

Creating and executing processes

Advancing executions step-by-step

Viewing in-flight and completed executions

Viewing inventory state derived from executions

APIs must be:

Org-scoped

Safe for concurrent executions

Explicit about execution state

UI Alignment (Reference Only)

The backend must fully support all features shown in the existing UI: process creation, step execution, inventory tracking, and execution history

Do not modify the UI

When implementing backend responses for front-end display:

Reference existing HTML/CSS elements and interactions to ensure complete backend support

Update the green/teal color used in visual indicators to match the blue used in settings.html and dashboard.html

Design Constraints

Optimize for correctness, auditability, and clarity

Avoid premature optimization

Favor explicit persisted state over derived state

Assume future needs for:

Compliance

Auditing

Lineage tracking

This system should feel closer to:

A workflow engine

A provenance tracker

A DAG execution system

Remember: Reference the frontend files under app/core/frontend to understand the requirements for the backend

Also: Use the shared components for the left and top pane on the new page so we get the org/user info and log out button on core

Also: Update settings.html and dashboard.html to add navigation to the new page core.html

Goal: Build a backend so the UI can always answer:

“What is happening, where, and why?”