# Changelog

All notable changes to Project Smith will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Plan repair and adaptive replanning on tool failure
- Result caching for deterministic tools
- Web UI for execution visualization
- Streaming execution updates
- Persistent conversation memory

## [0.1.0] - 2026-02-14

### Added
- Initial public release
- DAG-based planning system with LLM compilation
- Deterministic orchestrator with timeout and retry logic
- Seven built-in tools (LLM, Finance, Google Search, News, Weather, Web Scraper, ArXiv)
- Sub-agent delegation with depth limiting
- Fleet coordination for parallel multi-agent execution
- Resource locking to prevent deadlocks
- Per-tool rate limiting
- Interactive CLI with rich formatting
- ASCII banner and improved user experience
- CLI commands: /help, /tools, /trace, /dag, /inspect, /history, /export, /clear
- Execution trace export to markdown
- DAG visualization with ASCII flowcharts
- Comprehensive documentation suite
- API reference documentation
- Advanced features guide
- Deployment guide
- Contributing guidelines

### Changed
- Migrated from MongoDB to static registry.json for tool metadata
- Improved planner prompt with cost optimization rules
- Enhanced error messages and logging
- Refactored CLI into modular command structure

### Fixed
- Sub-agent deadlock issues with event key mismatches
- ASCII banner syntax warnings
- Unused import warnings from linting
- Rate limiting edge cases with concurrent requests

### Security
- Added dangerous tool approval mechanism
- Implemented resource locking for thread safety
- Input validation for tool parameters

## [0.0.3] - 2026-02-07

### Added
- ASCII art banner for CLI
- /diff command for execution comparison
- /export command for session export
- Enhanced CLI help system

### Changed
- Improved CLI user experience with rich formatting
- Refactored command handling

### Fixed
- Orchestrator deadlock after initial task submission
- Google search tool execution issues
- Dependency management in complex DAGs

## [0.0.2] - 2026-01-15

### Added
- Sub-agent delegation capability
- Global rate limiting with queue system
- Exponential backoff for API retries
- ASCII visual feedback in CLI

### Changed
- Reduced Google Gemini retries to single attempt
- Extended Groq exponential backoff for 429 errors
- Improved LLM integration resilience

### Fixed
- Final answer not displaying in CLI
- Sub-agent event handling
- Rate limit cascade issues

## [0.0.1] - 2025-12-29

### Added
- Core orchestrator with DAG execution
- Planner with multi-shot LLM approach
- Tool registry system
- Basic tool set (LLM, Finance, Google Search)
- Execution trace logging
- Timeout and retry mechanisms
- Initial CLI implementation

### Changed
- N/A (initial release)

### Fixed
- N/A (initial release)

---

## Version History Summary

| Version | Date | Key Features |
|---------|------|--------------|
| 0.1.0 | 2026-02-14 | Sub-agents, fleet coordination, comprehensive docs |
| 0.0.3 | 2026-02-07 | Enhanced CLI, ASCII art, export commands |
| 0.0.2 | 2026-01-15 | Sub-agents, rate limiting, resilience improvements |
| 0.0.1 | 2025-12-29 | Initial release with core functionality |

---

## Migration Guides

### Migrating from 0.0.x to 0.1.0

**Breaking Changes:**
- MongoDB dependency removed. Tool registry now uses static `registry.json` file.
- `tools_populator` script no longer needed.
- CLI command changed from `python -m smith.orchestrator` to `smith`.

**Migration Steps:**

1. Remove MongoDB configuration from `.env`
2. Update CLI launch command to `smith`
3. Remove any references to `tools_populator`
4. Update tool metadata in `src/smith/tools/registry.json` if you added custom tools

**New Features:**
- Sub-agents: Use for complex multi-step tasks
- Fleet coordination: Parallel execution of independent tasks
- Enhanced documentation: Check docs/ directory

---

## Deprecation Notices

### Deprecated in 0.1.0
- MongoDB-based tool registry (removed)
- `python -m smith.tools_populator` command (removed)
- `python -m smith.orchestrator` CLI launch (use `smith` instead)

---

## Contributors

- Karunya Muddana - Initial development and maintenance

---

## Links

- [Repository](https://github.com/Karunya-Muddana/project-smith)
- [Documentation](docs/README.md)
- [Issue Tracker](https://github.com/Karunya-Muddana/project-smith/issues)
