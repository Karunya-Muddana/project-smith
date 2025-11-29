## 🚀 Quick Start

This section gets you from zero to a running autonomous Smith agent in a few minutes.

### 1. Clone the repository
```bash
git clone https://github.com/<your-repo>/project-smith.git
cd project-smith
```

### 2. Create & activate a Python virtual environment
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Mac / Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Set up `.env`
Create a file named `.env` in the project root and add API keys for the tools you want to use.

Example:
```
GOOGLE_API_KEY=your_key
SEARCH_ENGINE_ID=your_cx
WEATHER_API_KEY=your_key
```

> Tools without API keys still work — the agent only calls what you request.

### 5. Start MongoDB
Smith requires a running MongoDB instance.

Default expected URI:
```
mongodb://root:password@localhost:27017/project_smith?authSource=admin
```

If you run via Docker:
```bash
docker compose up -d
```

### 6. Populate the Tool Registry
Smith scans the `/smith/tools` folder and registers all tools automatically.

```bash
python -m smith.tools_populator
```

You should see logs like:
```
Registered: google_search
Registered: weather_fetcher
Registered: finance_fetcher
...
```

### 7. Launch the autonomous agent CLI
```bash
python -m smith.orchestrator
```

You’ll see:
```
[SYSTEM] SMITH ENGINE v3.x (DAG)
> Command (or 'exit'):
```

### 8. Run your first workflow
Try something guaranteed to work:

```
google_search "latest AI trends 2025"; then llm_caller → summarize
```

This will:
1. call Google Search
2. send results to the LLM
3. return a summary

### 9. Multi-tool workflow (more complex demo)
```
google_search "top tech companies in Germany";
weather_fetcher Berlin;
finance_fetcher price AAPL;
then llm_caller → combine into an investment report
```

Smith automatically:
- generates a JSON DAG plan,
- runs tools in correct order,
- injects all data into the final LLM call,
- prints the result.

### 10. Add your first new tool (optional)
Drop any Python file into:
```
/smith/tools/
```
with a valid `METADATA` block and a callable function.

Then re-scan:
```bash
python -m smith.tools_populator
```

The planner will start using the tool automatically when user requests match its parameters.

---

### Success Checkpoint
If you see:
```
Planner produced a valid DAG with N node(s).
```
you’re good — the system is fully operational.

If you see:
```
Planning failed
```
jump to the Troubleshooting section later in the docs.

---

**You are now ready to build autonomous workflows and plug in new tools without touching the core engine.**
