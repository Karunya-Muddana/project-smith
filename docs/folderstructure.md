# Project Architecture and Directory Map

**Smith Autonomous Agent Runtime**

This document provides an exhaustive reference for the file system structure, module responsibilities, and architectural boundaries of the Smith Runtime. It is intended for core maintainers, contributors, and systems integrators seeking a deep understanding of the codebase organization.

## 1\. High-Level Directory Structure

The project follows a modular, separation-of-concerns architecture. The core runtime (smith/) is distinct from documentation (docs/) and user examples (examples/).

project-smith/  
│  
├── docs/ # User and developer documentation  
│ ├── quickstart.md # Primary entry point for new users  
│ └── ... # API references and architectural guides  
│  
├── examples/ # Usage patterns and demonstration scripts  
│ └── ... # Non-executable, illustrative CLI prompts  
│  
├── smith/ # CORE RUNTIME ENGINE  
│ ├── \__init_\_.py # Package initialization  
│ ├── orchestrator.py # Execution engine (DAG processing)  
│ ├── planner.py # Semantic translation (NL -> JSON)  
│ ├── tool_loader.py # Dynamic reflection and import logic  
│ ├── tools_populator.py # Registry synchronization utility  
│ ├── DB_TOOLS.py # Database abstraction layer  
│ │  
│ └── tools/ # PLUG-AND-PLAY TOOL EXTENSIONS  
│ ├── ARXIV_FETCHER.py  
│ ├── FINANCE.py  
│ ├── GOOGLE_SEARCHER.py  
│ ├── LLM_CALLER.py  
│ ├── TOOL_DIAGNOSTICS.py  
│ └── WEATHER_FETCHER.py  
│  
├── docker-compose.yml # Infrastructure definition (MongoDB)  
├── agent_db.json # Local configuration/state cache  
├── readme.md # High-level project overview  
├── .env # Secrets and environment variables  
└── .gitignore # Version control exclusion rules  

## 2\. Directory-by-Directory Analysis

### 2.1 Documentation (docs/)

**Purpose:** This directory serves as the knowledge base for the project. It contains static resources, guides, and reference material for both end-users and platform developers.

**Key Components:**

- quickstart.md: The "Hello World" guide for setting up the environment and running the first agent command.
- **Architectural Guides:** Detailed explanations of the planner/orchestrator split (if present).

**Runtime Interaction:** None. Files in this directory are never read or executed by the runtime engine.

### 2.2 Examples (examples/)

**Purpose:** Contains illustrative usage patterns, sample natural language queries, and expected outputs.

**Usage:** These files serve as a reference implementation for users to understand how to phrase queries for the Planner. They are not automated test suites but rather educational artifacts.

### 2.3 Core Runtime (smith/)

**Purpose:** The smith/ directory contains the executable logic of the system. It is the "engine" that drives the agent.

#### Core Modules

| **Module** | **Classification** | **Responsibility** |
| --- | --- | --- |
| **orchestrator.py** | **Critical** | The runtime kernel. It accepts a JSON Directed Acyclic Graph (DAG) and executes it. It handles topological sorting, dependency resolution, failure recovery (on_fail logic), and execution tracing. It ensures the process is deterministic. |
| --- | --- | --- |
| **planner.py** | **Critical** | The semantic translator. It converts unstructured natural language inputs into structured, validatable JSON execution plans. It consults the Tool Registry to ensure only available tools are scheduled. |
| --- | --- | --- |
| **tool_loader.py** | **System** | The reflection engine. It handles the dynamic importing of Python files from the tools/ directory. It ensures that functions are loaded safely without hardcoded imports in the main codebase. |
| --- | --- | --- |
| **tools_populator.py** | **Utility** | The registry sync tool. It scans the tools/ directory, extracts METADATA objects, and upserts them into the MongoDB instance. This bridges the gap between the file system and the Planner's knowledge base. |
| --- | --- | --- |
| **DB_TOOLS.py** | **Infrastructure** | The Data Access Layer (DAL). It abstracts MongoDB interactions, providing clean interfaces for the Orchestrator and Planner to save state, retrieve logs, or query tool definitions. |
| --- | --- | --- |

#### Extension Layer (smith/tools/)

**Purpose:** This is the designated **Extension Point** for the system. It utilizes a "Plug-and-Play" architecture where the presence of a file implies its availability to the system.

**Current Toolset:**

| **Tool ID** | **File** | **Description** |
| --- | --- | --- |
| arxiv_search | ARXIV_FETCHER.py | Interface for the ArXiv API to retrieve scientific papers and abstracts. |
| --- | --- | --- |
| finance_fetcher | FINANCE.py | Market data retrieval tool for stock prices and financial metrics. |
| --- | --- | --- |
| Google Search | Google SearchER.py | General-purpose web search connector via Google Custom Search API. |
| --- | --- | --- |
| llm_caller | LLM_CALLER.py | The synthesis node. Calls an LLM to process intermediate data into human-readable text. |
| --- | --- | --- |
| tool_diagnostics | TOOL_DIAGNOSTICS.py | A meta-tool used to validate the integrity of other tools and the runtime environment. |
| --- | --- | --- |
| weather_fetcher | WEATHER_FETCHER.py | Retrieves meteorological data for specific geolocations. |
| --- | --- | --- |

**Development Standard:** Every file in this directory **MUST** expose:

1.  **METADATA (dict):** A JSON-schema definition of the tool's interface.
2.  **Callable Function:** The Python logic corresponding to the metadata function name.

## 3\. Root-Level Configuration

These files govern the environment in which the Smith Runtime operates.

| **File** | **Type** | **Function** |
| --- | --- | --- |
| docker-compose.yml | Infrastructure | Defines the local MongoDB container configuration. Essential for the persistence layer. |
| --- | --- | --- |
| agent_db.json | Configuration | Acts as a local cache for agent settings or lightweight state management. |
| --- | --- | --- |
| .env | Security | **CRITICAL.** Stores API keys (OpenAI, Google, etc.). This file is strictly excluded from version control to prevent credential leakage. |
| --- | --- | --- |
| readme.md | Documentation | The entry point for the repository, defining the project philosophy and quick setup steps. |
| --- | --- | --- |

## 4\. Governance and Modification Strategy

To maintain system stability while allowing for rapid feature expansion, strict governance rules apply to codebase modifications.

### Safe to Modify (Green Zone)

- **/smith/tools/:** This is the primary workspace for contributors. Adding files here is safe and expected.
- **docs/ & examples/:** Improvements to documentation are always encouraged.

### Advanced Modification Only (Amber Zone)

- **planner.py:** Modifications here alter how the AI "thinks" and plans. Changes can have cascading effects on plan validity.
- **orchestrator.py:** Changes here affect _how_ code is run. Incorrect modifications can break determinism or error handling.

### Do Not Modify (Red Zone)

- **tool_loader.py:** This logic is fragile and security-critical. Changes may break the dynamic loading mechanism.
- **DB_TOOLS.py:** Altering database schemas or access patterns can corrupt the agent's memory or tool registry.

## 5\. Operational Workflow

Understanding the interaction between files is crucial for development.

1.  **Development Phase:**
    - Developer creates smith/tools/NEW_TOOL.py.
    - Developer defines METADATA and implementation logic.
2.  **Registration Phase:**
    - Developer runs python -m smith.tools_populator.
    - tools_populator.py scans smith/tools/, validates METADATA, and updates MongoDB via DB_TOOLS.py.
3.  **Execution Phase:**
    - User launches python -m smith.orchestrator.
    - orchestrator.py initializes and waits for input.
    - User Input → planner.py (Reads MongoDB for available tools) → JSON DAG.
    - JSON DAG → orchestrator.py (Dynamically loads functions via tool_loader.py) → Results.

## 6\. Summary

The Smith Autonomous Agent Runtime is architected for **stability** and **extensibility**.

- **Logic** is centralized in smith/.
- **Extensions** are isolated in smith/tools/.
- **State** is managed via Dockerized MongoDB.

By adhering to this folder map and the associated governance rules, developers can extend the agent's capabilities indefinitely without risking the stability of the core execution engine.