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
