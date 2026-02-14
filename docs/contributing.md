# Contributing to Smith

Thank you for your interest in contributing to Smith. This document provides guidelines for contributing to the project.

## Development Setup

### Prerequisites

- Python 3.10 or higher
- Git
- pip package manager
- API keys for testing (GROQ_API_KEY minimum)

### Initial Setup

```bash
# Fork and clone repository
git clone https://github.com/YOUR_USERNAME/project-smith.git
cd project-smith

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"

# Verify installation
pytest
```

## Code Style Guidelines

### Python Style

Smith follows PEP 8 with these tools:

```bash
# Format code with Black
black .

# Lint with Ruff
ruff check .

# Type checking (optional)
mypy src/smith
```

### Code Formatting Rules

- Line length: 88 characters (Black default)
- Indentation: 4 spaces
- String quotes: Double quotes preferred
- Import order: stdlib, third-party, local

### Docstring Format

Use Google-style docstrings:

```python
def function_name(param1: str, param2: int) -> Dict[str, Any]:
    """
    Brief description of function.

    Longer description if needed.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        Description of return value

    Raises:
        ValueError: When param1 is invalid
    """
```

## Testing Requirements

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=smith --cov-report=html

# Run specific test file
pytest tests/test_llm_caller.py
```

### Writing Tests

All new features must include tests:

```python
# tests/test_new_feature.py
import pytest
from smith.core.new_feature import new_function

def test_new_function_success():
    """Test successful execution."""
    result = new_function("input")
    assert result["status"] == "success"

def test_new_function_error():
    """Test error handling."""
    result = new_function("")
    assert result["status"] == "error"
```

### Test Coverage Requirements

- Minimum 70% coverage for new code
- 100% coverage for critical paths (planner, orchestrator)
- Integration tests for new tools

## Pull Request Process

### Before Submitting

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following code style guidelines

3. **Add tests** for new functionality

4. **Run quality checks**:
   ```bash
   black .
   ruff check .
   pytest
   ```

5. **Update documentation** if needed

6. **Commit with clear messages**:
   ```bash
   git commit -m "Add feature: brief description"
   ```

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Tests added/updated
- [ ] All tests passing
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Documentation updated
- [ ] No breaking changes (or documented)
```

### Review Process

1. Submit PR with clear description
2. Automated checks must pass (CI/CD)
3. Code review by maintainer
4. Address review comments
5. Approval and merge

## Tool Development

### Creating a New Tool

1. **Create tool file** in `src/smith/tools/`:

```python
# src/smith/tools/MY_TOOL.py
from typing import Dict, Any

def my_tool_function(param1: str, param2: int = 10) -> Dict[str, Any]:
    """
    Tool function implementation.
    
    Args:
        param1: Description
        param2: Description with default
        
    Returns:
        Standardized response dict
    """
    try:
        # Tool logic here
        result = {"data": "value"}
        
        return {
            "status": "success",
            "result": result
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

# Tool metadata
METADATA = {
    "name": "my_tool",
    "description": "Clear description of what tool does",
    "function": "my_tool_function",
    "dangerous": False,
    "domain": "category",  # e.g., "data", "computation", "system"
    "output_type": "data",  # or "synthesis", "action"
    "parameters": {
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "Parameter description"
            },
            "param2": {
                "type": "integer",
                "description": "Parameter description",
                "default": 10
            }
        },
        "required": ["param1"]
    },
    "notes": "Additional information for planner"
}
```

2. **Add to registry**: Tool is automatically registered from `registry.json`

3. **Write tests**:

```python
# tests/test_my_tool.py
from smith.tools.MY_TOOL import my_tool_function

def test_my_tool_success():
    result = my_tool_function("test")
    assert result["status"] == "success"
```

4. **Update documentation**: Add tool to README and tools-spec.md

### Tool Best Practices

- **Return standardized format**: Always return `{"status": "success|error", ...}`
- **Handle errors gracefully**: Catch exceptions and return error status
- **Validate inputs**: Check parameters before processing
- **Keep stateless**: Tools should not maintain state between calls
- **Document thoroughly**: Clear descriptions for planner

## Documentation Guidelines

### Documentation Structure

- `README.md`: Project overview and quick start
- `docs/quickstart.md`: Detailed installation guide
- `docs/architecture.md`: System design
- `docs/api-reference.md`: API documentation
- `docs/tools-spec.md`: Tool development guide

### Writing Documentation

- Use clear, professional language
- Include code examples
- Keep examples up-to-date
- Use proper markdown formatting
- No emojis or informal language

### Updating Documentation

When adding features:
1. Update relevant documentation files
2. Add examples if applicable
3. Update CHANGELOG.md
4. Update API reference if public API changed

## Commit Message Guidelines

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Test additions/changes
- `chore`: Build process or auxiliary tool changes

### Examples

```
feat(tools): add weather forecasting tool

Implement weather_forecast tool using OpenWeatherMap API.
Includes 7-day forecast and current conditions.

Closes #123
```

```
fix(orchestrator): resolve deadlock in sub-agent execution

Sub-agents were not properly releasing semaphore on error.
Added try-finally block to ensure cleanup.

Fixes #456
```

## Issue Reporting

### Bug Reports

Include:
- Smith version
- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Error messages/logs
- Minimal reproducible example

### Feature Requests

Include:
- Use case description
- Proposed solution
- Alternative approaches considered
- Impact on existing functionality

## Code Review Checklist

### For Reviewers

- [ ] Code follows style guidelines
- [ ] Tests are comprehensive
- [ ] Documentation is updated
- [ ] No security vulnerabilities
- [ ] Performance considerations addressed
- [ ] Error handling is appropriate
- [ ] Breaking changes are documented

### For Contributors

- [ ] Self-review completed
- [ ] Tests added and passing
- [ ] Documentation updated
- [ ] Commit messages are clear
- [ ] No debug code or comments
- [ ] Code is well-commented

## Release Process

### Version Numbering

Smith follows Semantic Versioning (SemVer):
- MAJOR: Breaking changes
- MINOR: New features (backward compatible)
- PATCH: Bug fixes

### Release Checklist

1. Update version in `pyproject.toml`
2. Update CHANGELOG.md
3. Run full test suite
4. Create git tag
5. Push to repository
6. Create GitHub release

## Getting Help

- **Documentation**: Check docs/ directory first
- **Issues**: Search existing issues on GitHub
- **Discussions**: Use GitHub Discussions for questions
- **Email**: Contact maintainer for sensitive issues

## License

By contributing to Smith, you agree that your contributions will be licensed under the MIT License.
