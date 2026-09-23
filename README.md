# 담(dam) - 격리 환경 생성기

여러 저장소를 클론하고 Codex/gh/glab를 사용하는 Linux 작업 환경입니다.

`git`, `tmux`, Node.js/npm, `glab`, `gh`, Python/pip/venv/pipx, `codex`, `nvim`을 설치합니다.
Apple Silicon(arm64)과 Intel/AMD(amd64)를 지원합니다.

## 처음 실행
호스트에 Linux 컨테이너를 실행할 수 있는 Docker 엔진, Bash, Docker CLI, Docker Compose(`docker compose`), Python 3.11 이상이 필요합니다.
명령은 현재 Docker CLI의 연결 설정을 사용합니다.
Docker 엔진에서 워크스페이스와 `.host-settings/` 경로에 접근할 수 있어야 하며, 원격 엔진에 로컬 경로가 자동으로 공유되지는 않습니다.

```bash
docker info
./dam {workspace} build
./dam {workspace} tmux {session}
```

빌드 플랫폼을 지정하려면 사용할 아키텍처에 맞춰 다음 중 하나를 실행합니다.

```bash
# ARM64로 빌드
DOCKER_DEFAULT_PLATFORM=linux/arm64 ./dam workspace-arm build

# AMD64로 빌드
DOCKER_DEFAULT_PLATFORM=linux/amd64 ./dam workspace-amd build
```

첫 인자는 워크스페이스 이름입니다.
`./dam ws1`는 `dam/workspaces/ws1`를 사용하는 컨테이너의 일반 셸로 들어갑니다.

`./dam ws1 tmux coding`은 `coding` tmux 세션을 만들거나 다시 연결합니다.
`./dam WORKSPACE tmux SESSION`의 세션 이름은 필수입니다.
이름을 생략하면 워크스페이스 생성이나 설정 동기화, 컨테이너 시작 없이 오류로 종료합니다.

`build`는 이미지를 빌드한 뒤 해당 워크스페이스의 컨테이너를 백그라운드에서 실행합니다.

tmux에서 `Ctrl-b d`로 분리한 뒤 다시 `./dam ws1 tmux coding`으로 연결할 수 있습니다.
컨테이너가 재시작되면 tmux 프로세스/세션은 종료되지만 파일과 인증 정보는 유지됩니다.

같은 워크스페이스에 여러 세션을 만들려면 각각 다른 이름을 지정합니다.
같은 이름으로 실행하면 기존 세션에 다시 연결하며, 모든 세션은 같은 컨테이너와 워크스페이스, 홈, CLI 계정을 사용합니다.

```bash
./dam ws1 tmux coding         # coding 세션 생성 또는 연결
./dam ws1 tmux review         # review 세션 생성 또는 연결
./dam ws1 sessions            # ws1의 tmux 세션 목록
```

지정하는 세션 이름은 비어 있거나 `.`, `:`, 줄바꿈을 포함할 수 없습니다.
공백이 있는 이름은 `./dam ws1 tmux "code review"`처럼 따옴표로 감쌉니다.

## 여러 워크스페이스

```bash
./dam ws1 build               # dam/workspaces/ws1를 /workspace로 연결하고 빌드
./dam ws1 tmux coding         # ws1 컨테이너의 coding 세션에 연결
./dam ws2 build               # dam/workspaces/ws2용 별도 컨테이너와 홈 볼륨 생성
./dam "project with spaces"   # 이름에 공백이 있으면 따옴표 사용
```

워크스페이스는 `dam` 스크립트가 있는 디렉토리의 **`workspaces/<이름>`**에 생성합니다.
예를 들어 `./dam ws3 build`는 `dam/workspaces/ws3`를 사용합니다.
다른 디렉토리에서 스크립트를 호출해도 같은 위치를 사용합니다.
디렉토리가 없으면 `build`, `shell`, `tmux`, `exec`, `sync`, `config` 실행 시 생성합니다.
`workspaces/`는 Git 추적과 Docker 이미지 빌드에서 제외됩니다.

워크스페이스 디렉토리의 정규화한 절대경로를 기준으로 `dam-<폴더이름>-<경로해시>`라는 Compose 프로젝트 이름을 생성합니다.
서로 다른 위치에 설치한 `dam`은 같은 워크스페이스 이름을 사용해도 별도 컨테이너를 사용합니다.
워크스페이스마다 홈 볼륨, Codex 기록, gh/glab 로그인과 tmux 세션이 구분되므로 처음 사용할 때 해당 컨테이너에서 로그인합니다.
호스트에서 가져오는 공통 설정은 동일합니다.

홈 볼륨 이름은 `<프로젝트 이름>_dev-home`입니다.
`./dam WORKSPACE config`로 경로, 프로젝트 이름, 홈 볼륨 이름을 확인할 수 있습니다.

## 계정 로그인 — 컨테이너 안에서 한 번

```bash
# Codex: 호스트와 별도로 로그인합니다. 같은 ChatGPT 계정을 선택해도 됩니다.
codex login --device-auth

# GitHub: 브라우저에서 컨테이너용 계정으로 승인합니다.
gh auth login --hostname github.com --git-protocol https --web

# GitLab: gitlab.com 대신 회사 GitLab 도메인을 쓸 수 있습니다.
glab auth login --hostname gitlab.com --git-protocol https --device

# 커밋 작성자 정보는 로그인 계정과 별개입니다.
git config --global user.name '컨테이너용 이름'
git config --global user.email '컨테이너용 이메일'

codex login status
gh auth status
glab auth status
git config --global --list
```

표시된 URL/코드는 호스트 브라우저에서 열면 됩니다.
Codex device login은 ChatGPT 보안 설정 또는 워크스페이스 정책에서 허용되어 있어야 합니다.

GitLab device login은 서버 17.9 이상에서 지원됩니다.
지원하지 않는 서버에서는 `glab auth login --hostname YOUR_GITLAB --git-protocol https`로 대화형 토큰 로그인을 사용합니다.

## 저장소 작업

```bash
cd /workspace
gh repo clone OWNER/REPO
# 또는: glab repo clone GROUP/REPO
# 또는: git clone https://git.example.com/GROUP/REPO.git
cd REPO
codex
nvim .
```

`/workspace`는 선택한 워크스페이스의 호스트 디렉토리(`ws1` → `dam/workspaces/ws1`)와 연결됩니다.
저장소마다 Codex를 실행하면 되고, 여러 저장소를 동시에 작업할 때는 tmux 창을 나누거나 이름이 다른 세션을 사용하면 됩니다.
같은 컨테이너의 모든 저장소는 같은 홈과 CLI 계정을 사용합니다.

## 공유와 분리

| 항목 | 호스트 경로 | 컨테이너 경로 | 동작 |
| --- | --- | --- | --- |
| 클론한 저장소 | `dam/workspaces/{WORKSPACE}` | `/workspace` | 읽기/쓰기 공유 |
| Codex 공통 설정 | `~/.codex/config.toml` | `/etc/codex/config.toml` | 호스트에서 단방향 동기화 |
| Codex 사용자 스킬 | `~/.codex/skills`, `~/.agents/skills` | `/home/node/.codex/skills`, `/home/node/.agents/skills` | 사용자 스킬만 복사한 뒤 읽기 전용으로 연결 |
| Codex 선택적 rules/agents/AGENTS.md | `~/.codex/rules`, `~/.codex/agents`, `~/.codex/AGENTS.md` | `/home/node/.codex/rules`, `/home/node/.codex/agents`, `/home/node/.codex/AGENTS.md` | 존재하는 항목을 복사한 뒤 읽기 전용으로 연결 |
| tmux 설정 | `~/.tmux.conf` | `/home/node/.tmux.conf` | 호스트에서 단방향 동기화, 읽기 전용으로 연결 |
| Neovim 설정 | `~/.config/nvim` | `/home/node/.config/nvim` | 쓰기 가능한 설정 사본으로 단방향 동기화 |
| Vim 설정 | `~/.vimrc`, `~/.vim` | `/home/node/.vimrc`, `/home/node/.vim` | 선택한 설정 파일만 쓰기 가능한 사본으로 단방향 동기화 |
| Codex 로그인/대화/컨테이너 설정 | -- | `/home/node/.codex` | 컨테이너 볼륨에 보관 |
| gh 로그인 | -- | `/home/node/.config/gh` | 컨테이너 볼륨에 보관 |
| glab 로그인 | -- | `/home/node/.config/glab-cli` | 컨테이너 볼륨에 보관 |
| Git 설정/SSH 키/도구 캐시 | -- | `/home/node` | 컨테이너 볼륨에 보관 |

공유는 **호스트 -> 컨테이너 단방향**입니다.
`./dam WORKSPACE`, `./dam WORKSPACE tmux SESSION`, `./dam WORKSPACE exec`, `./dam WORKSPACE sync`를 실행할 때 갱신합니다.
컨테이너에서 수정한 공유 설정은 다음 동기화 때 덮어쓸 수 있으므로 공통 설정은 호스트에서 편집하세요.
실행 중인 tmux에는 `tmux source-file ~/.tmux.conf`로 반영하고, 실행중인 Codex/Neovim은 다시 실행할 때 반영됩니다.

Codex는 공통 설정을 시스템 설정 계층에서 읽습니다.
컨테이너 전용 변경과 프로젝트 신뢰 설정은 쓰기 가능한 `~/.codex/config.toml`에 저장되며 공통 설정보다 우선합니다.
호스트의 macOS 전용 MCP, 알림 명령, 데스크톱 설정, 프로젝트 신뢰 목록, 설치된 플러그인/마켓플레이스 설정은 가져오지 않습니다.
CLI용 플러그인은 컨테이너에서 설치하세요.
Codex 기본 `.system` 스킬은 컨테이너 CLI가 관리하며, 호스트의 사용자 스킬만 공유합니다.
호스트의 Neovim 설정이 참조하는 `.vimrc`와 `.vim`의 설정 파일도 함께 동기화합니다.

호스트의 Codex `auth.json`, 대화 기록, gh/glab 설정, `.gitconfig`, `.ssh`, SSH agent, Docker 소켓은 연결하지 않습니다.
호스트의 인증 토큰 환경변수도 전달하지 않습니다.
공유 설정은 `.host-settings/`에 생성되며 Git 추적과 Docker 이미지 빌드에서 제외됩니다.
컨테이너는 일반 사용자 `node`로 실행하고 추가 권한과 호스트 네트워크를 사용하지 않습니다.
호스트 파일 중 `/workspace`에 연결된 저장소는 컨테이너에서 수정/삭제할 수 있습니다.

## 관리

```bash
./dam ws1 sync                   # ws1 컨테이너에 호스트 설정 다시 반영
./dam ws1 config                 # Docker 데몬 없이 경로/설정 검사
./dam ws1 exec codex --version
./dam ws1 exec nvim --version
./dam ws1 ps
./dam ws1 sessions               # ws1 컨테이너의 tmux 세션 목록
./dam ws1 logs --tail 50
./dam ws1 stop                   # ws1 컨테이너 중지
./dam ws1 down                   # ws1 컨테이너 삭제, 홈 볼륨/저장소 유지
./dam ws1 build                  # 이미지 다시 빌드하고 컨테이너 실행
./dam ws1 build --no-cache       # 캐시 없이 다시 빌드해 Codex 최신 버전 설치 후 컨테이너 실행
./dam ws1                        # ws1 컨테이너 셸 접속
./dam ws2 tmux coding            # 별도 ws2 컨테이너의 coding 세션에 연결
```

명령은 선택한 워크스페이스의 Compose 프로젝트에만 적용됩니다.
`sessions`는 설정을 동기화하거나 중지된 컨테이너를 시작하지 않습니다.
컨테이너가 실행 중이 아니면 세션을 조회할 수 없다는 안내를 출력하고, 실행 중이면 `tmux list-sessions` 결과를 출력합니다.
실행 중인 컨테이너에 tmux 서버가 없으면 tmux의 기본 오류 메시지와 종료 상태를 반환합니다.
인증 정보와 기록은 해당 프로젝트의 홈 볼륨에 남습니다.
`./dam WORKSPACE down -v`는 그 홈 볼륨까지 삭제하므로 초기화할 때만 사용하세요.

Node.js는 24 계열이며 Neovim/gh/OS 패키지는 빌드 시 공식 APT 저장소에서 설치합니다.

## 테스트

워크스페이스 이름 검증, 프로젝트 분리, build 실행 순서와 실패 처리, tmux 세션 이름 전달, 검증, 세션 목록 조회는 임시 디렉토리와 Docker 명령 대역을 사용하는 테스트로 확인합니다.

```bash
python3 -m unittest discover -s tests -v
```
