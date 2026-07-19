# Autonomous Engineering Runtime (AER)

## A Frontier Architecture for Agentic Software Engineering

> **Vision:** Build an autonomous software engineering organization
> rather than a single coding agent. Every capability is represented as
> a specialist skill. Deterministic systems answer everything they can,
> while frontier models reason only where semantic judgement is
> required.

------------------------------------------------------------------------

# Core Principles

1.  **Deterministic First**
    -   Prefer AST analysis, static analysis, dependency graphs,
        coverage analysis and benchmarks before invoking an LLM.
    -   Every confirmed reasoning outcome should become a deterministic
        rule where possible.
2.  **Persistent Knowledge**
    -   Skills never start from zero.
    -   Maintain continuously updated repository intelligence.
3.  **Specialisation**
    -   Each engineering discipline is represented by an independent
        skill with clear responsibilities.
4.  **Adversarial Verification**
    -   Independent model families review one another.
    -   Never rely solely on self-review.
5.  **Continuous Learning**
    -   Skills improve through measured outcomes.
    -   New deterministic checks are extracted from validated findings.
6.  **Model Agnostic**
    -   Claude, Codex and future models are interchangeable workers.

------------------------------------------------------------------------

# Repository Intelligence Layer

Shared knowledge:

-   File hashes
-   ASTs
-   Symbol graph
-   Dependency graph
-   Call graph
-   Architecture map
-   Ownership
-   ADRs
-   API contracts
-   Database schema
-   Test mapping
-   Coverage history
-   Performance baselines
-   Security boundaries
-   Historical findings
-   Previous PR outcomes

Each specialist may maintain domain overlays while using this shared
substrate.

------------------------------------------------------------------------

# Event Driven Runtime

``` text
Repository Event
        │
        ▼
Repository Intelligence Updated
        │
        ▼
Reasoning Router
        │
        ▼
Relevant Specialist Skills
        │
        ▼
Deterministic Preflight
        │
        ▼
LLM Reasoning Only If Required
        │
        ▼
Independent Adversarial Review
        │
        ▼
Validation
        │
        ▼
Commit / PR / CI
        │
        ▼
Feedback Into Knowledge Base
```

------------------------------------------------------------------------

# Specialist Skills

## Architecture

-   Boundary validation
-   Dependency direction
-   Coupling
-   ADR compliance

## Security

-   Authentication
-   Authorization
-   Secrets
-   Injection
-   Supply chain
-   Trust boundaries

## Performance

-   Hot paths
-   SQL
-   Memory
-   Concurrency
-   Caching

## Reliability

-   Retry logic
-   Timeouts
-   Circuit breakers
-   Failure modes

## Database

-   Migrations
-   Indexes
-   Transactions
-   ORM efficiency

## Testing

-   Unit tests
-   Integration tests
-   Mutation testing
-   Coverage

## Test Reviewer

-   Independently reviews generated tests
-   Detects weak assertions
-   Finds missing edge cases

## UX

-   Accessibility
-   Playwright generation
-   User journeys

## Documentation

-   API docs
-   ADR updates
-   Changelogs

## Observability

-   Logs
-   Metrics
-   Traces
-   Alerts

## Release

-   Versioning
-   PR creation
-   CI monitoring
-   Automated repair
-   Deployment readiness

------------------------------------------------------------------------

# Self Authoring Skills

A Skill Author:

-   creates new skills
-   updates existing skills
-   generates deterministic preflight
-   writes documentation
-   proposes graph registrations

The Mapping Graph validates and registers skills.

No skill directly mutates production routing.

------------------------------------------------------------------------

# Mapping Graph

Each skill declares:

-   capabilities
-   triggers
-   dependencies
-   inputs
-   outputs
-   allowed delegations
-   deterministic preflight
-   cost budget
-   confidence thresholds

Graph traversal determines execution order.

------------------------------------------------------------------------

# Deterministic Preflight

Every skill executes:

1.  Repository delta analysis
2.  Relevant symbol detection
3.  Domain-specific scanners
4.  Existing evidence lookup

Only unresolved semantic questions invoke an LLM.

------------------------------------------------------------------------

# Cross Model Adversarial Review

Example:

1.  Claude implements.
2.  Codex independently reviews without seeing Claude's conclusions.
3.  Findings reconciled.
4.  Disagreements resolved using evidence.

Maker and checker should ideally belong to different model families.

------------------------------------------------------------------------

# Closed Loop Engineering

Implementation

↓

Testing

↓

Independent Review

↓

Security

↓

Performance

↓

PR

↓

CI

↓

Pipeline monitoring

↓

Automatic repair

↓

Merge

------------------------------------------------------------------------

# Learning Loop

``` text
Model discovers issue
        │
        ▼
Issue verified
        │
        ▼
Deterministic rule generated
        │
        ▼
Knowledge graph updated
        │
        ▼
Future occurrences detected without LLM
```

------------------------------------------------------------------------

# Evaluation Layer

Every skill records:

-   precision
-   recall
-   accepted findings
-   rejected findings
-   escaped defects
-   latency
-   cost
-   CI failures prevented
-   developer acceptance

Poor performers are improved or retired.

------------------------------------------------------------------------

# Safety

-   Immutable skill versions
-   Shadow mode
-   Rollback
-   Execution budgets
-   Cycle detection
-   Maximum delegation depth
-   Evidence ledger
-   Human approval for high-risk actions

------------------------------------------------------------------------

# North Star

The objective is **not** maximum autonomy.

The objective is to build a software engineering system that:

-   continuously improves
-   continuously remembers
-   continuously verifies
-   continuously measures itself
-   continuously reduces the need for AI reasoning

The end state is an engineering runtime where deterministic software
performs routine engineering work and frontier models are reserved for
genuinely novel reasoning. Every validated insight becomes part of the
system's permanent engineering capability.
