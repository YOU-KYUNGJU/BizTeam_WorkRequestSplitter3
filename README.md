# BizTeam_WorkRequestSplitter3

PDF work-request splitter for scanned documents with a QR code on the first page.

## What It Does

- Reads the QR code on page 1 of each PDF.
- Extracts a code such as `H2312603706` from QR text like `@H2312603706@`.
- Removes the first page.
- Saves the remaining pages as `output/<code>.pdf`.
- Adds `_2`, `_3`, ... when the same filename already exists.

## Requirements

- Windows
- Python 3.11+ recommended
- Tesseract is not required

Python packages:

```bash
pip install pymupdf opencv-python numpy pillow pyinstaller
```

## Run With Python

Process a single PDF:

```bash
python src/main.py "C:\\path\\to\\file.pdf"
```

Process every PDF in a folder:

```bash
python src/main.py "C:\\path\\to\\folder"
```

Run without arguments:

```bash
python src/main.py
```

Without arguments, the program processes every PDF in the current working folder.

## Build EXE

```bash
pyinstaller --noconfirm --clean --onefile --name BizTeam_WorkRequestSplitter3 src/main.py
```

Built file:

```text
dist\BizTeam_WorkRequestSplitter3.exe
```

## Run EXE

Process a single PDF:

```bash
dist\\BizTeam_WorkRequestSplitter3.exe "C:\\path\\to\\file.pdf"
```

Process every PDF in a folder:

```bash
dist\\BizTeam_WorkRequestSplitter3.exe "C:\\path\\to\\folder"
```

Run without arguments:

```bash
dist\\BizTeam_WorkRequestSplitter3.exe
```

When the EXE runs without arguments, it processes PDFs in the same folder as the EXE.

## Output

- Output folder: `output`
- Filename source: QR value from page 1
- Example: `@N2322603706@` -> `output/N2322603706.pdf`

## Notes

- PDFs with fewer than 2 pages are skipped.
- Files without a readable QR code on the first page are skipped.
- The current implementation uses OpenCV `QRCodeDetector`.
