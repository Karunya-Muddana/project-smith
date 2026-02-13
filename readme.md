# Smith 🕵️‍♂️
**The Zero-Trust Agent Runtime that actually works.**

Welcome to Project Smith! Build autonomous agents that you can actually trust. No more infinite loops, no more hallucinations wiping your database—just deterministic, reliable execution.

---

## Why Smith?
Building agents is hard. Most "autonomous" frameworks are just `while(true)` loops that guess what to do next. That's scary in production.

**Smith is different.**
- **Plan First, Act Later**: We use a "Planner" to verify the entire sequence of actions *before* execution starts.
- **No Infinite Loops**: Since we use a DAG (Directed Acyclic Graph), the agent literally *cannot* loop forever.
- **You are in Control**: Sensitive tools (like deleting files) can require your explicit "Y/N" approval.

## 🚀 Quick Start

### 1. Install
```bash
# Clone the repo
git clone https://github.com/Karunya-Muddana/project-smith.git
cd project-smith

# Install in editable mode (so your changes apply instantly)
pip install -e .
```

### 2. Configure
Create a `.env` file with your API keys:
```ini
GROQ_API_KEY="gsk_..."
# Optional:
GOOGLE_API_KEY="AIzaSy..."
SEARCH_ENGINE_ID="..."
```

### 3. Run It!
Start the interactive CLI:
```bash
smith
```

Or use the Python API:
```python
from smith.core.orchestrator import smith_orchestrator

for event in smith_orchestrator("What is the stock price of AAPL?"):
    if event["type"] == "final_answer":
        print(event["payload"]["response"])
```

## 🧠 How it Works (The Cool Part)

### The Architecture
1.  **Planner (The Architect)**: You say "Check stock price of Apple". The Planner writes a JSON blueprint (DAG).
2.  **Orchestrator (The Conductor)**: Runs the blueprint step-by-step.
    - Step 1: `finance_fetcher` → Gets AAPL price.
    - Step 2: `llm_caller` → Summarizes it for you.
3.  **Tools**: Simple Python functions in `src/smith/tools`. Adding a new tool is as easy as writing a function!

### CLI Commands
Once you run `smith`, you have access to these commands:
- `/help` - Show available commands
- `/tools` - List all available tools
- `/trace` - Show execution trace of last run
- `/dag` - Export last execution DAG as JSON
- `/inspect` - Show ASCII flowchart of DAG and trace
- `/history` - Show conversation history
- `/export` - Export session to markdown file
- `/clear` - Clear the screen
- `/quit` or `/exit` - Exit Smith

## 🧪 Development & Testing
We keep it simple!
- **Run Tests**: `pytest` - Tests verify LLM caller works and orchestrator loads
- **Lint Code**: `ruff check .`
- **Format Code**: `black .`

Our test suite is intentionally minimal, focusing on:
1. **LLM Caller** - Verifies the LLM can be called successfully
2. **Orchestrator Loading** - Ensures the orchestrator imports and initializes without errors

## 📂 Project Structure
```
project-smith/
├── src/smith/           # Core engine code
│   ├── core/           # Orchestrator and core logic
│   ├── tools/          # Available tools (LLM, Finance, Google Search, etc.)
│   ├── cli/            # CLI interface
│   ├── planner.py      # DAG planning logic
│   ├── registry.py     # Tool registry
│   └── tool_loader.py  # Dynamic tool loading
├── tests/              # Simplified test suite
├── scripts/            # Helper scripts for testing and debugging
└── docs/               # Documentation
```

## 🛠️ Available Tools
Smith comes with several built-in tools:
- **LLM Caller** - Access to Llama 3.3 70B via Groq for reasoning and summarization
- **Finance Fetcher** - Get stock prices and financial data via yfinance
- **Google Search** - Search the web (requires API key)
- **News Fetcher** - Fetch latest news articles
- **Weather Fetcher** - Get weather information

Run `/tools` in the CLI to see all available tools.

---
*Built with ❤️ by Karunya Muddana.*

