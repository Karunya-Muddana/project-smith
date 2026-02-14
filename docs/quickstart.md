# Quickstart Guide

This guide will help you install and run Smith in under 10 minutes.

## Prerequisites

- Python 3.10 or higher
- pip package manager
- Git
- API keys for desired tools

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/Karunya-Muddana/project-smith.git
cd project-smith
```

### 2. Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
# Install Smith in editable mode
pip install -e .
```

This installs Smith and all required dependencies including:
- groq (LLM API client)
- yfinance (financial data)
- rich (CLI formatting)
- typer (CLI framework)
- requests, beautifulsoup4 (web scraping)

### 4. Configure Environment

Create a `.env` file in the project root directory:

```ini
# Required: LLM API key for planning and synthesis
GROQ_API_KEY="gsk_your_key_here"

# Optional: Google Search (required for google_search tool)
GOOGLE_API_KEY="AIzaSy_your_key_here"
SEARCH_ENGINE_ID="your_cx_here"

# Optional: Other tool configurations
# Add additional API keys as needed
```

**Note**: Tools without API keys will still be registered but will fail if called. The planner only uses tools for which you have configured credentials.

### 5. Verify Installation

Check that Smith is installed correctly:

```bash
# Verify CLI is available
smith --help

# Check Python package
python -c "from smith.core.orchestrator import smith_orchestrator; print('Smith installed successfully')"
```

## First Run

### Launch Interactive CLI

```bash
smith
```

You should see the Smith banner and prompt:

```
  ____   __  __  _____  _______  _    _
 / ___| |  \/  ||_   _||__   __|| |  | |
| (___  | \  / |  | |     | |   | |__| |
 \___ \ | |\/| |  | |     | |   |  __  |
 ____) || |  | | _| |_    | |   | |  | |
|_____/ |_|  |_||_____|   |_|   |_|  |_|

Smith v0.1.0 - Zero-Trust Agent Runtime
Type /help for commands or enter a request.

>
```

### Run Your First Task

Try a simple task:

```
> What is the current stock price of Apple?
```

Smith will:
1. Generate an execution plan (DAG)
2. Execute the `finance_fetcher` tool
3. Use `llm_caller` to format the response
4. Display the result

### Example Multi-Tool Workflow

```
> Research quantum computing developments and summarize the findings
```

This will trigger:
1. `google_search` or `arxiv_search` for research
2. `llm_caller` for synthesis
3. Formatted output

## CLI Commands Reference

Once in the Smith CLI, you have access to these commands:

| Command | Description |
|---------|-------------|
| `/help` | Display available commands |
| `/tools` | List all registered tools with descriptions |
| `/trace` | Show execution trace of last run |
| `/dag` | Export last execution DAG as JSON |
| `/inspect` | Display ASCII flowchart of DAG and trace |
| `/history` | Show conversation history |
| `/export` | Export session to markdown file |
| `/clear` | Clear the screen |
| `/quit` or `/exit` | Exit Smith |

## Programmatic Usage

You can also use Smith programmatically in your Python code:

```python
from smith.core.orchestrator import smith_orchestrator

# Execute a task
for event in smith_orchestrator("What is the weather in Berlin?"):
    # Handle different event types
    if event["type"] == "planning":
        print("Planning phase...")
    elif event["type"] == "tool_start":
        print(f"Executing: {event['payload']['tool']}")
    elif event["type"] == "final_answer":
        print("Result:", event["payload"]["response"])
    elif event["type"] == "error":
        print("Error:", event["message"])
```

## Verification Checklist

Confirm your installation is working:

- [ ] `smith` command launches CLI
- [ ] `/tools` shows list of available tools
- [ ] Simple query executes successfully
- [ ] Execution trace is visible with `/trace`
- [ ] No import errors or missing dependencies

## Common Issues

### Issue: "Command 'smith' not found"

**Solution**: Ensure you installed with `pip install -e .` and your virtual environment is activated.

### Issue: "GROQ_API_KEY not found"

**Solution**: Create a `.env` file in the project root with your API key.

### Issue: "Planning failed"

**Solution**: Check that your GROQ_API_KEY is valid and you have internet connectivity.

### Issue: Tool execution fails

**Solution**: Verify you have configured API keys for the specific tool. Use `/tools` to see which tools require credentials.

## Next Steps

- Read [architecture.md](architecture.md) to understand how Smith works
- Review [tools-spec.md](tools-spec.md) to learn about creating custom tools
- Explore [advanced-features.md](advanced-features.md) for sub-agents and fleet coordination
- Check [troubleshooting.md](troubleshooting.md) for detailed error resolution

## Success Indicators

You have successfully installed Smith when:

1. The CLI launches without errors
2. You can execute a simple task end-to-end
3. The execution trace shows tool calls and results
4. The final LLM synthesis produces a readable answer

If any of these fail, consult the troubleshooting guide or check the logs for specific error messages.

