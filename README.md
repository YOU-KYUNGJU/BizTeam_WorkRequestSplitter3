# BizTeam_WorkRequestSplitter3

QR 코드가 포함된 표지 페이지를 기준으로 스캔 PDF를 여러 개의 작업요청서 PDF로 분리하는 프로그램입니다.

## 주요 기능

- PDF 전체 페이지를 스캔하여 QR 코드가 있는 페이지를 새 구간의 시작 페이지로 인식합니다.
- QR 문자열이 `@H2312603706@` 형태일 때 `H2312603706` 값을 추출해 파일명으로 사용합니다.
- 각 구간에서 QR 코드가 있는 표지 페이지는 제외하고, 다음 QR 페이지가 나오기 전까지의 본문 페이지만 저장합니다.
- 같은 코드가 여러 번 나오면 `_2`, `_3` 같은 번호를 자동으로 붙입니다.

## 실행 환경

- Windows
- Python 3.11 이상 권장
- Tesseract 불필요

필요 패키지:

```bash
pip install pymupdf opencv-python numpy pillow pyinstaller
```

## Python으로 실행

단일 PDF 처리:

```bash
python src/main.py "C:\\path\\to\\file.pdf"
```

폴더 내 모든 PDF 처리:

```bash
python src/main.py "C:\\path\\to\\folder"
```

인자 없이 실행:

```bash
python src/main.py
```

인자 없이 실행하면 현재 작업 폴더에 있는 PDF 파일들을 처리합니다.

## EXE 빌드

```bash
pyinstaller --noconfirm --clean --onefile --name BizTeam_WorkRequestSplitter3 src/main.py
```

생성 파일:

```text
dist\BizTeam_WorkRequestSplitter3.exe
```

## EXE 실행

단일 PDF 처리:

```bash
dist\\BizTeam_WorkRequestSplitter3.exe "C:\\path\\to\\file.pdf"
```

폴더 내 모든 PDF 처리:

```bash
dist\\BizTeam_WorkRequestSplitter3.exe "C:\\path\\to\\folder"
```

인자 없이 실행:

```bash
dist\\BizTeam_WorkRequestSplitter3.exe
```

EXE를 인자 없이 실행하면 EXE 파일이 있는 폴더의 PDF들을 처리합니다.

## 출력 결과

- 출력 폴더: `output`
- 파일명 기준: 각 구간 시작 페이지의 QR 값
- 예시: `@N2322603706@` -> `output/N2322603706.pdf`

## 동작 방식

1. PDF의 모든 페이지를 순서대로 확인합니다.
2. QR 코드가 검출된 페이지를 새 문서의 시작점으로 기록합니다.
3. 해당 QR 페이지 다음 장부터 다음 QR 페이지 직전까지를 하나의 PDF로 저장합니다.
4. 문서 마지막까지 같은 방식으로 반복합니다.

## 참고 사항

- QR 코드를 읽지 못한 PDF는 건너뜁니다.
- 같은 PDF 안에서 새로운 QR 페이지가 다시 나타나면 새 출력 파일을 생성합니다.
- QR 페이지 뒤에 본문 페이지가 하나도 없으면 해당 구간은 저장하지 않습니다.
- QR 검출은 OpenCV `QRCodeDetector`를 사용합니다.
