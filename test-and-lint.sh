#!/bin/bash
# Pre-commit hook to run tests, black, and ruff

set -e

echo "🧪 Running tests..."
uv run pytest

echo "🖤 Running black..."
if ! uv run black . --check; then
    echo "❌ Black found formatting issues. To auto fix, run:"
    echo -e "\033[32muv run black .\033[0m"
    exit 1
fi

echo "🧼 Running ruff check..."
if ! uv run ruff check .; then
    echo "❌ Ruff found linting issues. To auto fix, run:"
    echo -e "\033[32muv run ruff check . --fix\033[0m"
    exit 1
fi

echo "✅ Pre-commit checks passed!"
