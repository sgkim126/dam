# dam

## 개발 환경

macOS 또는 Linux에서 [uv](https://docs.astral.sh/uv/getting-started/installation/)를
준비합니다. uv 0.13.1 이상을 사용합니다.
macOS에서 Homebrew를 사용한다면 `brew install uv`로 설치할 수 있습니다.

저장소 디렉터리에서 잠긴 개발 환경을 준비합니다. 필요한 Python 3.11 이상이
없으면 uv가 Python을 내려받습니다.

```bash
uv sync --locked
```

Python 파일의 포맷을 적용하려면 다음 명령을 실행합니다.

```bash
make format
```

파일을 변경하지 않고 포맷과 린트를 검사하려면 다음 명령을 실행합니다.

```bash
make lint
```

GitHub CI도 같은 `make lint` 명령을 실행합니다.

`make lint`는 포맷 검사에 이어 Ruff 린트 검사도 실행합니다.
사용하지 않는 import 등의 코드 오류가 발견되면 실패하며 파일은 변경하지 않습니다.

## 설치

저장소 디렉터리에서 다음 명령을 실행합니다.

```bash
uv tool install .
uv tool update-shell
```

새 터미널을 열면 어느 디렉터리에서든 `dam`을 실행할 수 있습니다.
일반 설치는 원본 저장소를 이동하거나 삭제해도 유지됩니다.

## 도움말

```bash
dam --help
```

명령 없이 `dam`만 실행해도 도움말을 표시합니다.
도움말은 Docker를 실행하거나 사용자 설정을 생성하지 않습니다.

## 테스트와 빌드

저장소 디렉터리에서 테스트와 패키지 설치 검사를 실행하고 배포 파일을 빌드합니다.

```bash
make test
uv run --no-sync python scripts/check_package.py
uv build
```

빌드 결과는 `dist/`에 생성됩니다.
GitHub CI도 같은 테스트와 패키지 설치 검사 명령을 실행합니다.
