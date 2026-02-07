# Contributing to GEDCOM MCP Server

Thank you for your interest in contributing! This document provides guidelines for setting up your development environment and contributing to the project.

## Development Setup

### Prerequisites

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

1. Install uv package manager:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Clone the repository:
   ```bash
   git clone git@github.com:sjmatta/gedcom-mcp.git
   cd gedcom-mcp
   ```

3. Install dependencies:
   ```bash
   uv sync
   ```

4. Install pre-commit hooks:
   ```bash
   uv run pre-commit install --install-hooks
   ```

## Running Tests

```bash
# Run all tests
uv run poe test

# Run specific test file
uv run pytest tests/test_places.py -v

# Run specific test
uv run pytest tests/test_core.py::test_search_individuals -v

# Run tests with coverage
uv run pytest --cov=gedcom_server tests/
```

## Code Quality

Before submitting a pull request, ensure all quality checks pass:

```bash
# Run all checks (lint, typecheck, test)
uv run poe check

# Individual checks:
uv run poe lint       # Run ruff linting
uv run poe format     # Run ruff formatting
uv run poe typecheck  # Run mypy type checking
```

### Pre-commit Hooks

Pre-commit hooks will automatically run when you commit:
- **Pre-commit**: ruff linting and formatting, mypy type checking
- **Pre-push**: pytest test suite

If a hook fails, fix the issues and commit again. You can also run hooks manually:
```bash
uv run pre-commit run --all-files
```

## Making Changes

### Workflow

1. Create a feature branch:
   ```bash
   git checkout -b feature/my-feature
   ```

2. Make your changes and write tests

3. Ensure all quality checks pass:
   ```bash
   uv run poe check
   ```

4. Commit your changes:
   ```bash
   git add .
   git commit -m "Add feature: description of changes"
   ```

5. Push your branch:
   ```bash
   git push origin feature/my-feature
   ```

6. Open a pull request on GitHub

### Commit Messages

Write clear, descriptive commit messages:
- Use present tense ("Add feature" not "Added feature")
- Start with a verb ("Add", "Fix", "Update", "Remove")
- Keep first line under 72 characters
- Add details in the body if needed

Good examples:
- `Add get_military_service tool for finding veterans`
- `Fix geocoding cache invalidation on GEDCOM update`
- `Update README with all 24 tools`

## Code Style

### Python Style Guidelines

- **Line length**: 100 characters maximum
- **Type hints**: Required for all new functions
- **Docstrings**: Required for public functions (Google style)
- **Naming**: Follow PEP 8 conventions
- **Imports**: Use ruff's import sorting (runs automatically)

### Type Hints Example

```python
def search_individuals(name: str, max_results: int = 50) -> list[dict]:
    """Search for individuals by name.

    Args:
        name: Name to search for (case-insensitive)
        max_results: Maximum results to return

    Returns:
        List of matching individuals with summary info
    """
    # Implementation
```

### Architecture Patterns

Follow existing patterns in the codebase:
- **Private functions**: Use `_` prefix (e.g., `_search_individuals`)
- **Public MCP tools**: Register in `mcp_tools.py`, implement in domain modules
- **State management**: Use `state` module for global data
- **Indexes**: Use O(1) lookups via indexes (surname_index, birth_year_index, etc.)

For detailed architecture documentation, see [CLAUDE.md](CLAUDE.md).

## Adding New Features

### Adding a New MCP Tool

1. Implement the tool in the appropriate domain module:
   - Core queries → `core.py`
   - Events → `events.py`
   - Places → `places.py`
   - Relationships → Add new module if needed

2. Register the tool in `mcp_tools.py`:
   ```python
   @mcp.tool()
   def my_new_tool(param: str) -> dict:
       """Tool description.

       Args:
           param: Parameter description

       Returns:
           Description of return value
       """
       return _my_new_tool(param)
   ```

3. Add tests in `tests/test_<module>.py`

4. Update documentation:
   - Add to README.md features list
   - Add to API.md reference
   - Add to CHANGELOG.md under [Unreleased]

### Optional Dependencies

For optional features (like semantic search), use lazy imports:
```python
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    logger.warning("sentence-transformers not installed...")
    # Provide graceful fallback
```

## Testing Guidelines

### Writing Tests

- Use fixtures from `conftest.py` for test data
- Test both success and error cases
- Use `pytest.skip()` when test data not available
- Keep tests focused and independent

### Test Organization

Tests mirror the module structure:
- `test_gedcom_server.py` - Core functionality
- `test_events.py` - Event-related tools
- `test_places.py` - Place-related tools
- `test_relationships.py` - Relationship calculations
- `test_edge_cases.py` - Edge cases and error handling

## Pull Request Guidelines

### Before Submitting

- [ ] All tests pass (`uv run poe test`)
- [ ] Linting passes (`uv run poe lint`)
- [ ] Type checking passes (`uv run poe typecheck`)
- [ ] Documentation updated (README, API.md, CHANGELOG)
- [ ] New code has tests
- [ ] Commit messages are clear

### PR Description

Include in your PR description:
- Summary of changes
- Motivation for the change
- Any breaking changes
- Testing performed

## Getting Help

- **Questions**: Open a [GitHub Discussion](https://github.com/sjmatta/gedcom-mcp/discussions)
- **Bugs**: Open a [GitHub Issue](https://github.com/sjmatta/gedcom-mcp/issues/new?template=bug_report.md)
- **Feature Requests**: Open a [GitHub Issue](https://github.com/sjmatta/gedcom-mcp/issues/new?template=feature_request.md)

## Code of Conduct

Be respectful and inclusive. We want everyone to feel welcome contributing to this project.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
