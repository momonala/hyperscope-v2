#!/bin/bash
# Pre-commit hook to run tests, black, and ruff

set -e

echo "🧪 Running tests..."
uv run --with pytest --with pytest-cov pytest

echo "🖤 Running black..."
if ! uvx black . --check; then
    echo "❌ Black found formatting issues. To auto fix, run:"
    echo -e "\033[32muvx black .\033[0m"
    exit 1
fi

echo "🧼 Running ruff check..."
if ! uvx ruff check .; then
    echo "❌ Ruff found linting issues. To auto fix, run:"
    echo -e "\033[32muvx ruff check . --fix\033[0m"
    exit 1
fi

echo "✅ Pre-commit checks passed!"
