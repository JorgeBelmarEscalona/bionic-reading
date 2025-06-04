# Bionic Reading

This tool modifies EPUB files by bolding portions of the text. It includes a GUI and a simple CLI.

## Requirements
Install dependencies:
```bash
pip install -r requirements.txt
```

## Running the GUI
Launching the application creates a `settings.json` file to remember your language and theme preferences.
```bash
python Bionic.py
```

## Running from the command line
```bash
python cli.py -d OUTPUT_DIR file1.epub file2.epub
```

## Running tests
Use `pytest` to run the unit tests:
```bash
pytest
```

## Packaging
To build a standalone executable:
```bash
pyinstaller --onefile Bionic.py
```
