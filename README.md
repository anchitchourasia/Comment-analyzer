# Comment Analyzer

A lightweight Python utility for analyzing live-chat comments against configurable checks. The project is designed as a simple foundation for identifying comments that match predefined keywords or rules.

## Features

- Analyze live-chat comments using configurable checks.
- Keep detection rules outside the Python source code with `checks.json`.
- Use a separate utility to work with a live-chat ID.
- Simple script-based structure that is easy to extend.

## Project Structure

| File | Description |
| --- | --- |
| `analyzer 4.py` | Main comment-analysis script. |
| `checks.json` | JSON configuration containing the checks used by the analyzer. |
| `livechat id generator.py` | Utility related to obtaining or generating a live-chat ID. |

## How It Works

```text
Live-chat source
      ↓
Live-chat ID
      ↓
Read comments
      ↓
Load checks.json
      ↓
Compare comments with configured checks
      ↓
Identify matching comments
```

The analyzer is rule-based. It does not require a machine-learning model; its behavior depends on the checks defined in `checks.json` and the logic implemented in the analyzer script.

## Requirements

- Python 3.9 or newer is recommended.
- Access to the live-chat source used by the scripts.
- Any third-party Python packages imported by the scripts.

Because this repository currently does not include a `requirements.txt` file, install the dependencies required by the imports in the Python files before running the project.

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/anchitchourasia/Comment-analyzer.git
cd Comment-analyzer
```

### 2. Review the checks

Open `checks.json` and configure the keywords or rules that should be detected. Keep the JSON valid when making changes.

### 3. Obtain the live-chat ID

Run the live-chat ID utility and follow the input expected by the script:

```bash
python "livechat id generator.py"
```

### 4. Run the analyzer

```bash
python "analyzer 4.py"
```

The exact prompts, inputs, and output depend on the current implementation of the scripts.

## Configuration

`checks.json` is the project’s external configuration file. Keeping checks in JSON makes it possible to update the detection rules without changing the Python code.

When editing the file:

- Use valid JSON syntax.
- Preserve the structure expected by `analyzer 4.py`.
- Add only the keywords or values that should be analyzed.

## Current Scope

This project is intentionally lightweight and currently focuses on script-based, rule-driven analysis. It does not provide a web dashboard, persistent database, REST API, authentication system, or automated test suite.

## Recommended Improvements

Potential future enhancements include:

- Rename scripts using standard Python naming conventions.
- Add a `requirements.txt` or `pyproject.toml` file.
- Add command-line arguments instead of hard-coded or interactive inputs.
- Add case-insensitive text matching and comment normalization.
- Add error handling for invalid input, unavailable chats, and API failures.
- Add structured logging and CSV/JSON output.
- Add unit tests for configuration loading and comment analysis.
- Store API keys and other secrets in environment variables.

## Security

Do not commit API keys, access tokens, passwords, or other secrets to the repository. Use environment variables or a local `.env` file that is excluded through `.gitignore`.

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Make focused changes.
4. Test the scripts locally.
5. Open a pull request with a clear description of the change.

## License

No license is currently specified for this repository. Add a license file if you want others to use, modify, or redistribute the project under defined terms.

## Author

Created and maintained by [anchitchourasia](https://github.com/anchitchourasia).