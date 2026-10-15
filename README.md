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

## Workspace 생성

Docker CLI와 Linux 컨테이너를 실행하는 Docker 엔진이 필요합니다.

```bash
dam -w dev init
```

`dev`라는 컨테이너를 만들고 시작합니다. 필요한 이미지는 자동으로 빌드합니다.
등록된 이름으로 다시 초기화하거나 관계없는 동명 컨테이너가 있으면 오류입니다.

`-w`는 `--workspace`의 축약형이며 명령 앞에 지정합니다. 이름은 영숫자로
시작하고 영숫자·`-`·`_`·`.`을 사용하며 64자까지 가능합니다.

설정은 `~/.config/dam`에 저장하므로 어느 디렉터리에서 실행해도 같은 workspace를
사용합니다. 기본 계정은 `node`입니다. `/home` 전체는 workspace별 Docker 볼륨에
저장되어 컨테이너를 재생성해도 유지됩니다. 컨테이너 재생성은 실행 중 프로세스를
종료하며 tmux 세션을 자동으로 복원하지 않습니다.

Codex는 필요한 사용자가 컨테이너의 자기 계정에서 설치합니다. 해당 계정의 셸에서
다음 명령을 실행합니다.

```bash
npm install -g @openai/codex@latest
hash -r
codex --version
```

같은 명령으로 업데이트합니다. `NPM_CONFIG_PREFIX`가 `$HOME/.local`로 설정되어
실행 파일은 사용자별 `$HOME/.local/bin`에 설치됩니다. 설치한 버전은 홈 볼륨에
보존되며, 업데이트 후 실행 중이던 Codex를 종료하고 다시 시작합니다.

최초 계정 초기화 때 호스트의 Codex·tmux·Vim·Neovim 설정을 가져옵니다.
호스트 인증·기록은 복사하지 않으며 컨테이너에서 각 도구에 로그인해야 합니다.
Docker 엔진은 호스트의 설정·마운트 경로에 접근할 수 있어야 합니다.
