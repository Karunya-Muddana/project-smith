# Smith 🕵️‍♂️
**The Zero-Trust Agent Runtime that actually works.**

Welcome to Project Smith! Build autonomous agents that you can actually trust. No more infinite loops, no more hallucinations wiping your database—just deterministic, reliable execution.

---

## Why Smith?
Building agents is hard. Most "autonomous" frameworks are just `while(true)` loops that guess what to do next. That's scary in production.

**Smith is different.**
- **Plan First, Act Later**: We use a "Planner" to verify the entire sequence of actions *before* execution starts.
- **No Infinite Loops**: Since we use a DAG (Directed Acyclic Graph), the agent literally *cannot* loop forever.
- **You are in Control**: Sensitive tools (like deleting files) require your explicit "Y/N" approval.

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
Create a `.env` file with your API keys. We use Google Gemini because it's fast and smart.
```ini
GOOGLE_API_KEY="AIzaSy..."
# Optional:
SEARCH_ENGINE_ID="..."
```

### 3. Run It!
We have a handy script to test everything live:
```bash
python scripts/live_test_ops.py
```

## 🧠 How it Works (The Cool Part)

### The Architecture
1.  **Planner (The Architect)**: You say "Check stock price of Apple". The Planner writes a JSON blueprint.
2.  **Orchestrator (The Conductor)**: Runs the blueprint step-by-step.
    - Step 1: `finance_fetcher` -> Gets AAPL price.
    - Step 2: `llm_caller` -> Summarizes it for you.
3.  **Tools**: Simple Python functions in `src/smith/tools`. Adding a new tool is as easy as writing a function!

## 🧪 Development & Testing
We take quality seriously!
- **Run Tests**: `pytest`
- **Lint Code**: `ruff check .`
- **Format Code**: `black .`

## 📂 Project Structure
- `src/smith/`: The core engine code.
- `scripts/`: Helpful scripts for testing and debugging.
- `tests/`: Unit tests to keep things stable.

---
*Built with ❤️ by Karunya Muddana.*
