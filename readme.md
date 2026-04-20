# Smith

[![Version](https://img.shields.io/badge/version-4.0.0-blue.svg)](https://github.com/Karunya-Muddana/project-smith)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**Zero-Trust Autonomous Agent Runtime with Deterministic Execution**

Smith is a production-grade autonomous agent framework that eliminates the unpredictability of traditional LLM-based agents. By using a compiler-runtime architecture with DAG-based planning, Smith guarantees deterministic execution, prevents infinite loops, and provides complete audit trails.

---

## Overview

Traditional autonomous agents operate as reactive loops where LLMs make runtime decisions about tool execution. This approach introduces unpredictability, infinite loop risks, and debugging challenges that make production deployment difficult.

Smith takes a fundamentally different approach:

**Compile-Time Planning**: Natural language requests are compiled into validated execution graphs (DAGs) before any tools execute.

**Deterministic Runtime**: The orchestrator executes the DAG exactly as planned with no improvisation or runtime LLM decisions.

**Mathematical Guarantees**: DAG structure makes infinite loops mathematically impossible.

**Complete Traceability**: Every decision and execution step is logged for audit and debugging.

### Key Differentiators

- **No Infinite Loops**: DAG structure prevents cycles by design
- **Predictable Costs**: All tool calls are known before execution begins
- **Audit Trail**: Complete execution trace for compliance and debugging
- **Separation of Concerns**: Planning, execution, and synthesis are isolated
- **Production-Ready**: Built-in timeout, retry, rate limiting, and resource locking
- **Voice-First (v4.0+)**: Native speech input/output with full-screen terminal UI
- **Hallucination Prevention**: Fabrication guard prevents false information
- **Persistent Memory**: Long-term memory system with RAG capabilities
- **Intelligent Routing**: Query classification and smart tool selection

---

## Architecture

Smith operates as a three-stage pipeline:

```
User Request → Planner (Compiler) → DAG (Bytecode) → Orchestrator (Runtime) → Result
```

### Components

**Planner**: Compiles natural language into validated JSON DAGs using LLM-based code generation with strict schema validation.

**Orchestrator**: Executes DAG nodes deterministically with timeout enforcement, retry logic, and failure handling.

**Tools**: Stateless functions with metadata-driven schemas. Tools are plug-and-play with no core engine modifications required.

**Sub-Agents**: Recursive agent delegation for complex multi-step tasks with depth limiting.

**Fleet Coordinator**: Parallel multi-agent execution for independent workloads.

See [docs/architecture.md](docs/architecture.md) for detailed architecture documentation.

---

## What's New in v4.0

Smith v4.0 is a major architectural overhaul focused on streamlining the codebase and adding advanced AI capabilities:

**Major Updates:**
- **Removed API system**: CLI-only architecture for faster development and simpler deployment
- **Voice mode**: Full-screen terminal UI with native speech recognition and synthesis
- **NVIDIA Nemotron LLM**: Unified LLM provider via OpenRouter for better performance
- **Advanced safety**: Fabrication guard prevents hallucinations and verifies facts
- **Memory system**: Long-term memory with RAG for context-aware responses
- **7 new tools**: Crypto, finance calculations, SEC filings, technical indicators, code analysis, deep summarization, and Gmail integration
- **Intelligent routing**: Query classification and smart tool selection
- **Enhanced caching**: Deterministic result caching with TTL-based expiration

See [CHANGELOG.md](CHANGELOG.md) for complete v4.0 release notes.

---

## Installation

### Prerequisites

- Python 3.10 or higher
- pip package manager
- NVIDIA_LLM_API_KEY (via OpenRouter for Nemotron models)
- API keys for optional tools (Google Search, etc.)

### Quick Install

```bash
# Clone repository
git clone https://github.com/Karunya-Muddana/project-smith.git
cd project-smith

# Install package
pip install -e .
```

### Configuration

Create a `.env` file in the project root:

```ini
# Required: NVIDIA LLM API key (OpenRouter proxy for Nemotron)
NVIDIA_LLM_API_KEY="your_key_here"

# Optional: Additional tool APIs
GOOGLE_API_KEY="AIzaSy..."
SEARCH_ENGINE_ID="..."
```

See [docs/quickstart.md](docs/quickstart.md) for detailed installation instructions.

---

## Usage

### Interactive CLI

Launch the Smith CLI:

```bash
smith
```

Example session:

```
> Research the latest developments in quantum computing

[Planning] Generating execution plan...
[Execution] Running 3 tools...
[Complete] Research complete.

Quantum computing has seen significant advances in 2026...
```

### Voice Mode (v4.0+)

Launch the CLI with native voice interface:

```bash
smith --voice
```

Features:
- **Speech-to-text**: Automatic speech recognition using Whisper
- **Natural interaction**: Speak requests and hear responses
- **Full-screen UI**: Real-time visualization of agent pipeline
- **Fallback to text**: Automatically switches to typed input if audio hardware unavailable

Example voice session:

```
⚡ SMITH · VOICE MODE
🎤 Listening...
> "Research recent AI regulation changes"

STATUS                          PIPELINE
◉ PROCESSING                    ① google_search ✓
▁▂▅▇█▇▅▂▁                     ② deep_summarizer ►

🔊 Speaking response...
```

Requirements:
- `faster-whisper` - Speech recognition
- `melo-tts` - Text-to-speech synthesis
- Audio input/output hardware

### Python API

```python
from smith.core.orchestrator import smith_orchestrator

# Execute a task programmatically
for event in smith_orchestrator("What is the stock price of AAPL?"):
    if event["type"] == "final_answer":
        print(event["payload"]["response"])
```

### CLI Commands

- `/help` - Display available commands
- `/tools` - List all registered tools
- `/trace` - Show execution trace of last run
- `/dag` - Export last execution DAG as JSON
- `/inspect` - Display ASCII flowchart of DAG and trace
- `/history` - Show conversation history
- `/export` - Export session to markdown
- `/voice` - Toggle voice mode on/off
- `/clear` - Clear screen
- `/quit` or `/exit` - Exit Smith

---

## Available Tools

Smith includes the following built-in tools:

| Tool | Description | Requirements |
|------|-------------|--------------|
| `llm_caller` | LLM reasoning via NVIDIA Nemotron (OpenRouter) | NVIDIA_LLM_API_KEY |
| `finance_fetcher` | Stock prices and financial data | None |
| `google_search` | Web search (DuckDuckGo fallback) | GOOGLE_API_KEY (optional) |
| `news_fetcher` | Latest news articles | None |
| `weather_fetcher` | Weather information | None |
| `web_scraper` | Extract text from URLs | None |
| `arxiv_search` | Search academic papers | None |
| `code_agent` | Code analysis and generation | NVIDIA_LLM_API_KEY |
| `crypto_fetcher` | Cryptocurrency data | None |
| `financial_calculator` | Advanced financial calculations | None |
| `sec_filings` | SEC filing search and analysis | None |
| `technical_indicators` | Trading technical analysis | None |
| `gmail` | Email integration | Google OAuth |
| `deep_summarizer` | Deep multi-document summarization | NVIDIA_LLM_API_KEY |
| `sub_agent` | Delegate tasks to child agents | None |

Run `/tools` in the CLI for detailed tool information.

---

## Development

### Running Tests

```bash
# Run test suite
pytest

# Run with coverage
pytest --cov=smith
```

### Code Quality

```bash
# Lint code
ruff check .

# Format code
black .
```

### Project Structure

```
project-smith/
├── src/smith/              # Core engine
│   ├── core/              # Orchestrator, planner, validators
│   ├── tools/             # Tool implementations
│   ├── cli/               # Command-line interface
│   ├── planner.py         # DAG planning logic
│   ├── registry.py        # Tool registry loader
│   └── tool_loader.py     # Dynamic tool loading
├── tests/                 # Test suite
├── scripts/               # Development scripts
├── docs/                  # Documentation
└── pyproject.toml         # Package configuration
```

---

## Documentation

- [Quickstart Guide](docs/quickstart.md) - Installation and first steps
- [Architecture Overview](docs/architecture.md) - System design and components
- [Planner Documentation](docs/planner.md) - DAG planning system
- [Orchestrator Documentation](docs/orchestrator.md) - Execution engine
- [Tool Specification](docs/tools-spec.md) - Tool development guide
- [Troubleshooting](docs/troubleshooting.md) - Common issues and solutions

---

## Contributing

Contributions are welcome. Please see [docs/contributing.md](docs/contributing.md) for guidelines.

---

## License

Project Smith is released under the MIT License. See [LICENSE](LICENSE) for details.

---

## Author

**Karunya Muddana**  
BTech Computer Science, AI/ML & MLOps  
[LinkedIn](https://www.linkedin.com/in/karunya-muddana/)

---

## Acknowledgments

Smith draws conceptual inspiration from compiler pipelines, operating system runtimes, and MLOps safety patterns. All design and implementation are original work.

