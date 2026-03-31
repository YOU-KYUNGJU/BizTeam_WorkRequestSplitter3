# BizTeam_WorkRequestSplitter3

QR 코드가 포함된 페이지를 기준으로 PDF를 여러 개의 작업요청 PDF로 분리하는 프로그램입니다.

## 주요 기능

- PDF 전체 페이지를 스캔해서 QR 코드가 있는 페이지를 문서 시작 페이지로 인식합니다.
- QR 문자열이 `@H2312603706@` 형태면 `H2312603706` 값을 추출해서 출력 파일명에 사용합니다.
- 각 구간에서 QR 페이지는 제외하고, 다음 QR 페이지 전까지의 본문 페이지만 새 PDF로 저장합니다.
- 같은 코드가 여러 번 나오면 `_2`, `_3` 같은 번호를 자동으로 붙입니다.

## 실행 환경

- Windows
- Python 3.11 이상 권장

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

인자 없이 실행하면 현재 작업 폴더의 PDF를 처리합니다.

## EXE 빌드

```bash
pyinstaller --noconfirm --clean --onefile --name BizTeam_WorkRequestSplitter3 src/main.py
```

생성 파일:

```text
dist\BizTeam_WorkRequestSplitter3.exe
```

## 출력 결과

- 출력 폴더: `output`
- 파일명 규칙: 각 구간 시작 QR 코드값
- 예시: `@N2322603706@` -> `output/N2322603706.pdf`

## 로그 수집

프로그램은 최소한의 사용 로그를 CSV로 남길 수 있습니다.

- 설정 파일: `conpig.ini`
- 기본 서버 경로 1: `\\fiti_fileserver\교육자료\RDMS자동화\Log\YYYY-MM-DD\`
- 기본 서버 경로 2: `\\192.168.1.7\교육자료\RDMS자동화\Log\YYYY-MM-DD\`
- 저장 파일 예시: `usage_log_mid-xxxxxxxxxxxx.csv`

수집 항목:

- 프로그램명 / 버전
- 실행 시작 시각 / 종료 시각 / 처리 시간
- 성공 여부 / 오류 코드
- 익명 PC 식별값
- 입력 PDF 파일명 해시
- 마스킹된 접수번호
- 페이지 수 / QR 감지 개수 / 생성된 출력 파일 수
- 폴더 처리 시 총 파일 수 / 성공 수 / 실패 수

민감 정보 처리:

- 원본 파일명은 저장하지 않고 해시만 저장합니다.
- 접수번호는 원문 대신 앞 6자리만 남기고 나머지는 `*`로 마스킹합니다.
- 로그 전송 실패 시 본기능은 계속 진행되고, `pending_logs` 폴더에 임시 저장한 뒤 다음 실행 시 재전송을 시도합니다.

## conpig.ini 예시

```ini
[logging]
enabled = true
root_1 = \\fiti_fileserver\교육자료\RDMS자동화\Log
root_2 = \\192.168.1.7\교육자료\RDMS자동화\Log
pending_dir = pending_logs
machine_id_file = machine_id.txt
log_file_prefix = usage_log
notice_text = 프로그램 개선 및 장애 분석을 위해 최소한의 사용 로그가 기록됩니다. 로그에는 실행 시각, 처리 건수, 페이지 수, 오류 정보, 익명화된 식별값이 포함되며 원본 파일명과 접수번호 원문은 저장하지 않습니다.
```

동작 방식:

1. 실행 시 `conpig.ini`가 없으면 자동 생성합니다.
2. `root_1`부터 순서대로 접근 가능한 로그 경로를 찾습니다.
3. 로그 저장이 실패하면 `pending_logs`에 JSON으로 임시 보관합니다.
4. 다음 실행에서 서버 연결이 가능하면 pending 로그를 CSV로 재반영합니다.

## 참고 사항

- QR 코드를 읽지 못한 PDF는 건너뜁니다.
- 같은 PDF 안에서 QR 페이지가 다시 나오면 새 출력 파일을 생성합니다.
- QR 페이지 뒤에 본문 페이지가 없으면 해당 구간은 저장하지 않습니다.
- QR 검출은 OpenCV `QRCodeDetector`를 사용합니다.
