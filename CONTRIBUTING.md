# Contributing to Frameshift

Thank you for your interest in contributing to Frameshift! This document provides guidelines and information for contributors.

## Code of Conduct

Please be respectful and constructive in all interactions. We're all here to build something useful together.

## Getting Started

### Prerequisites

- Python 3.9 or higher
- Git

### Development Setup

1. **Fork and clone the repository**

```bash
git clone https://github.com/YOUR_USERNAME/frameshift.git
cd frameshift
```

2. **Create a virtual environment**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install development dependencies**

```bash
pip install -e ".[dev]"
```

4. **Verify installation**

```bash
pytest
```

## Development Workflow

### Branch Naming

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring
- `test/` - Test additions or modifications

Example: `feature/add-batch-progress-bar`

### Making Changes

1. Create a new branch from `main`
2. Make your changes
3. Write or update tests
4. Run the test suite
5. Update documentation if needed
6. Submit a pull request

### Code Style

We use the following tools to maintain code quality:

- **Black** for code formatting
- **Ruff** for linting
- **MyPy** for type checking

Run all checks:

```bash
# Format code
black src tests

# Lint
ruff check src tests

# Type check
mypy src
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=frameshift --cov-report=html

# Run specific test file
pytest tests/test_analyzer.py

# Run tests matching a pattern
pytest -k "test_distribution"
```

## Submitting Changes

### Pull Request Process

1. Ensure all tests pass
2. Update the CHANGELOG.md with your changes
3. Update documentation if you've changed public APIs
4. Ensure your code follows the project style guidelines
5. Write a clear PR description explaining the changes

### PR Description Template

```markdown
## Summary
Brief description of what this PR does.

## Changes
- Change 1
- Change 2

## Testing
How was this tested?

## Checklist
- [ ] Tests pass
- [ ] Code is formatted (black)
- [ ] Linting passes (ruff)
- [ ] Type hints added
- [ ] Documentation updated
- [ ] CHANGELOG updated
```

## Reporting Issues

### Bug Reports

Please include:
- Python version
- Frameshift version
- Operating system
- Steps to reproduce
- Expected behavior
- Actual behavior
- Error messages/traceback

### Feature Requests

Please include:
- Use case description
- Proposed solution (if any)
- Alternatives considered

## Architecture Overview

```
frameshift/
├── src/frameshift/
│   ├── __init__.py      # Public API exports
│   ├── core.py          # Main FrameShift class
│   ├── config.py        # Configuration
│   ├── schema.py        # Schema inference
│   ├── types.py         # Type mappings
│   ├── chunker.py       # Data chunking & SQL generation
│   ├── analyzer.py      # Distribution & unique key analysis
│   ├── connection.py    # Connection handling
│   └── exceptions.py    # Custom exceptions
├── tests/               # Test suite
├── examples/            # Usage examples
└── docs/               # Documentation
```

### Key Components

- **FrameShift**: Main entry point, orchestrates all operations
- **SchemaInferer**: Analyzes DataFrames to infer Redshift schema
- **DataFrameChunker**: Splits data into chunks within size limits
- **DistributionAnalyzer**: Analyzes columns for DISTKEY suitability
- **UniqueKeyValidator**: Validates unique constraints

## Questions?

Feel free to open an issue for questions or discussions about contributing.

Thank you for contributing!
