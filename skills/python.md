# Python Skill Pack — 30 Commands

```yaml
# Package Management
- intent: "install python package {{package}}"
  command: "pip install {{package}}"
  tags: [python, pip, install]

- intent: "install specific version {{package}}"
  command: "pip install {{package}}=={{version}}"
  tags: [python, pip, install, version]

- intent: "uninstall python package {{package}}"
  command: "pip uninstall -y {{package}}"
  tags: [python, pip, uninstall]

- intent: "show installed package info {{package}}"
  command: "pip show {{package}}"
  tags: [python, pip, info]

- intent: "list installed packages"
  command: "pip list --outdated"
  tags: [python, pip, list, outdated]

- intent: "freeze requirements"
  command: "pip freeze > requirements.txt"
  tags: [python, pip, freeze]

- intent: "install from requirements"
  command: "pip install -r requirements.txt"
  tags: [python, pip, requirements]

- intent: "install package with pipenv"
  command: "pipenv install {{package}}"
  tags: [python, pipenv, install]

- intent: "install dev package with pipenv"
  command: "pipenv install --dev {{package}}"
  tags: [python, pipenv, dev]

- intent: "add package with poetry"
  command: "poetry add {{package}}"
  tags: [python, poetry, install]

- intent: "add dev package with poetry"
  command: "poetry add --group dev {{package}}"
  tags: [python, poetry, dev]

- intent: "install dependencies with uv"
  command: "uv pip install -r pyproject.toml"
  tags: [python, uv, install]

- intent: "add package with uv"
  command: "uv add {{package}}"
  tags: [python, uv, add]

- intent: "sync environment with uv"
  command: "uv sync"
  tags: [python, uv, sync]

- intent: "show outdated packages with uv"
  command: "uv pip list --outdated"
  tags: [python, uv, outdated]

# Testing
- intent: "run tests with pytest"
  command: "pytest tests/ -v"
  tags: [python, pytest, test]

- intent: "run tests with coverage"
  command: "pytest tests/ --cov=src --cov-report=term-missing"
  tags: [python, pytest, coverage]

- intent: "run specific test {{test}}"
  command: "pytest tests/{{test}} -v"
  tags: [python, pytest, specific]

- intent: "run tests matching {{pattern}}"
  command: "pytest -k \"{{pattern}}\" -v"
  tags: [python, pytest, pattern]

- intent: "run tests with tox"
  command: "tox"
  tags: [python, tox, test]

- intent: "run doctests"
  command: "python3 -m pytest --doctest-modules src/"
  tags: [python, doctest, test]

# Linting & Formatting
- intent: "lint with ruff"
  command: "ruff check src/ tests/"
  tags: [python, ruff, lint]

- intent: "fix lint issues with ruff"
  command: "ruff check --fix src/ tests/"
  tags: [python, ruff, lint, fix]

- intent: "type check with mypy"
  command: "mypy src/ --ignore-missing-imports"
  tags: [python, mypy, types]

- intent: "format with black"
  command: "black src/ tests/"
  tags: [python, black, format]

- intent: "check formatting with black"
  command: "black --check src/ tests/"
  tags: [python, black, format, check]

- intent: "sort imports with isort"
  command: "isort src/ tests/"
  tags: [python, isort, imports]

- intent: "lint and format everything"
  command: "ruff check --fix src/ tests/ && black src/ tests/ && isort src/ tests/"
  tags: [python, lint, format, all]

# Virtual Environments
- intent: "create virtual environment"
  command: "python3 -m venv .venv"
  tags: [python, venv, create]

- intent: "activate virtual environment"
  command: "source .venv/bin/activate"
  tags: [python, venv, activate]

- intent: "create conda environment {{name}}"
  command: "conda create -n {{name}} python=3.12 -y"
  tags: [python, conda, create]

- intent: "list conda environments"
  command: "conda env list"
  tags: [python, conda, list]

- intent: "build python package"
  command: "python3 -m build"
  tags: [python, build, package]

- intent: "upload to pypi"
  command: "python3 -m twine upload dist/*"
  tags: [python, pypi, upload]

- intent: "run python script"
  command: "python3 {{script}}"
  tags: [python, run]
```
