#!/bin/bash
# Pre-commit hook: tests, ruff format, ruff check

set -e

echo "🧪 Running tests..."
uv run pytest

echo "🖤 Running ruff format..."
if ! uvx ruff format --check .; then
    echo "❌ Ruff found formatting issues. To auto fix, run:"
    echo -e "\033[32muvx ruff format .\033[0m"
    exit 1
fi

echo "🧼 Running ruff check..."
if ! uvx ruff check .; then
    echo "❌ Ruff found linting issues. To auto fix, run:"
    echo -e "\033[32muvx ruff check . --fix\033[0m"
    exit 1
fi

echo "✅ Pre-commit checks passed!"
