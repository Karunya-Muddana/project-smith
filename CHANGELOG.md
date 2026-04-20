# Changelog

All notable changes to Project Smith will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Plan repair and adaptive replanning on tool failure
- Result caching for deterministic tools
- Web UI for execution visualization
- Persistent conversation memory
- Advanced voice mode features (language selection, custom voices)

## [4.0.0] - 2026-04-20

### Major Changes
- **Complete API system removal**: Removed REST API layer; now CLI-only for streamlined architecture
- **LLM provider migration**: Switched from Groq to NVIDIA Nemotron (via OpenRouter)
- **Voice mode integration**: Added native voice input/output with full-screen terminal UI
- **Expanded tool ecosystem**: Added 7 new specialized tools (crypto, finance, SEC, technical analysis, code agent, deep summarizer, Gmail)
- **Advanced features**: Implemented caching, long-term memory/RAG, query routing, and fabrication guards

### Added
- **Voice Interface**: Full-screen voice mode with `faster-whisper` speech-to-text and `melo-tts` synthesis
- **New Tools**:
  - `code_agent` — Code analysis and generation
  - `crypto_fetcher` — Cryptocurrency market data
  - `financial_calculator` — Advanced financial calculations
  - `sec_filings` — SEC filing search and analysis
  - `technical_indicators` — Trading technical analysis tools
  - `gmail` — Email integration with OAuth
  - `deep_summarizer` — Multi-document deep summarization
- **Advanced Core Modules**:
  - `voice_mode.py` — Full-screen terminal voice UI
  - `agent_voice_module.py` — Voice-agent runtime integration
  - `cache_manager.py` — Deterministic result caching (TTL-based)
  - `memory/` — Long-term memory system with embeddings and RAG
  - `synthesis_router.py` — Intelligent routing between fast/heavy synthesis models
  - `query_router.py` — Smart query classification and routing
  - `report_renderer.py` — Formatted output rendering
  - `fabrication_guard.py` — Hallucination prevention and fact verification
  - `input_validators.py` — Robust input validation
  - `template_engine.py` — Dynamic prompt templating
  - `agent_state.py` — Agent lifecycle and state management
  - `resource_lock.py` — Thread-safe resource allocation
  - `fleet_coordinator.py` — Parallel multi-agent execution
- DuckDuckGo fallback for search (improved reliability)
- Model variants: heavy-synthesis and fast-synthesis configurations
- Conversation context reuse with `SMITH_CONTEXT_TURNS`
- Time-sensitive query detection with fresh data enforcement

### Removed
- REST API endpoints and FastAPI/Uvicorn
- Groq API support
- Multi-LLM provider routing
- `news_clusterer` tool (replaced with improved `news_fetcher`)
- API-specific configuration

### Changed
- All LLM calls route through NVIDIA Nemotron (OpenRouter proxy)
- CLI is the single primary interface (`smith` command)
- Config uses NVIDIA_LLM_API_KEY (OpenRouter API key)
- Simplified `.env` — only NVIDIA_LLM_API_KEY required for core functionality
- Enhanced error handling with fabrication guard verification
- Improved orchestrator with state tracking and resource locking
- Better planner with validation guardrails and cost optimization

### Improved
- **Performance**: Faster startup (no API server), caching reduces redundant calls
- **Reliability**: Hallucination prevention, input validation, result verification
- **User Experience**: Voice mode, rich CLI, better error messages
- **Debuggability**: Detailed state tracking, agent lifecycle logging
- **Scalability**: Fleet coordination, thread-safe resource management

### Migration from 3.x to 4.0
**Breaking Changes:**
- API endpoints removed; only CLI available
- GROQ_API_KEY → NVIDIA_LLM_API_KEY (OpenRouter)
- `NIM_BASE_URL` no longer needed (hardcoded to OpenRouter endpoint)

**Migration Steps:**
1. Update `.env`:
   ```ini
   # Remove GROQ_API_KEY
   NVIDIA_LLM_API_KEY="your_openrouter_key"
   ```
2. Remove any REST API client code; use `smith` CLI instead
3. Update automation to call CLI: `smith "your query"`
4. Enable voice mode with: `smith --voice`

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
| 4.0.0 | 2026-04-20 | Voice mode, NVIDIA NIM, API removed, streamlined architecture |
| 0.1.0 | 2026-02-14 | Sub-agents, fleet coordination, comprehensive docs |
| 0.0.3 | 2026-02-07 | Enhanced CLI, ASCII art, export commands |
| 0.0.2 | 2026-01-15 | Sub-agents, rate limiting, resilience improvements |
| 0.0.1 | 2025-12-29 | Initial release with core functionality |

---

## Migration Guides

### Migrating from 3.x to 4.0.0

**Breaking Changes:**
- REST API endpoints removed entirely
- GROQ_API_KEY replaced with NVIDIA NIM credentials
- API server no longer starts
- All interactions now through CLI or Python orchestrator

**Migration Steps:**

1. Update `.env` configuration:
   ```bash
   # Remove GROQ_API_KEY
   # Add NVIDIA NIM credentials
   NIM_API_KEY="your_key_here"
   NIM_BASE_URL="https://integrate.api.nvidia.com/v1"
   ```
2. Remove any API client code (no more HTTP calls to /api/ endpoints)
3. Use `smith` CLI command for all interactions
4. Enable voice mode with `smith --voice` if needed
5. Update any automation/tooling to use CLI instead of API

**New Features:**
- Voice input/output with `/voice` toggle
- Streamlined setup with single LLM provider
- Better performance without API server overhead

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
