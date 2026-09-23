# 담(dam) - 격리 환경 생성기

Codex/gh/glab를 사용하는 Linux 작업 환경입니다.

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
`build`와 실행 중인 컨테이너의 `sync`는 컨테이너 `~/.bashrc`에 `alias vi=nvim`도 중복 없이 추가합니다.
`~/.bashrc`에서 `/workspace/.bashrc`가 있으면 함께 불러오도록 설정합니다.
`/workspace/.bashrc`는 사용자가 직접 관리하며, `sync`는 이 파일을 생성하거나 수정하지 않습니다.
새 셸부터 적용되며, 이미 열린 셸에서는 `source ~/.bashrc`로 반영합니다.

tmux에서 `Ctrl-b d`로 분리한 뒤 다시 `./dam ws1 tmux coding`으로 연결할 수 있습니다.
컨테이너가 재시작되면 tmux 프로세스/세션은 종료되지만 파일과 인증 정보는 유지됩니다.

같은 워크스페이스에 여러 세션을 만들려면 각각 다른 이름을 지정합니다.
같은 이름으로 실행하면 기존 세션에 다시 연결하며, 런처로 연 세션은 같은 컨테이너와 워크스페이스, `node` 홈, CLI 로그인을 사용합니다.

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

## 계정 전환

컨테이너에 미리 준비한 일반 계정 중 `users` 그룹에 속하는 계정끼리는 비밀번호 없이 전환할 수 있습니다.
기본 계정 `node`도 이 그룹에 속합니다.
대상 계정은 UID 1000 이상이어야 하며, `root`/시스템 계정/그룹에 속하지 않은 계정으로의 전환은 거부합니다.

```bash
# alice는 이미 컨테이너에 생성하고 users 그룹에 넣은 계정
su - alice
cd /workspace
tmux new-session -A -s coding

# 이전 셸로 복귀
exit
```

`su USER`와 `su - USER` 모두 사용할 수 있습니다.
`su - USER`는 해당 사용자의 홈으로 이동합니다.
`su USER -c COMMAND`로 직접 실행할 때도 Codex/gh/glab, npm, XDG 설정 경로와 PATH는 대상 사용자의 홈을 기준으로 초기화합니다.
로그인 정보, Git 개인 설정과 tmux 세션은 각 Linux 계정의 홈과 UID를 사용합니다.
런처의 `shell`, `exec`, `tmux`, `sessions`는 항상 `node`로 실행합니다.

추가 계정의 생성과 홈 보존은 관리자가 준비해야 합니다.
런처는 `node` 홈 볼륨을 유지하며 설정 동기화도 `node` 홈에 적용합니다.
추가 계정에 공통 사용자 설정을 초기화할 때는 해당 계정으로 `dam-user-env python3 /usr/local/lib/dam/import-settings.py --user-only`를 실행합니다.
모든 그룹 구성원은 서로 신뢰한다는 전제이며, 비밀번호 없는 계정 전환은 사용자 간 보안 경계가 아닙니다.

## CLI 로그인 — 사용자마다 한 번

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

## 작업 공간

`/workspace`에서 일반 파일을 다루거나 Git 저장소를 클론해 작업할 수 있습니다.

```bash
cd /workspace
gh repo clone OWNER/REPO
# 또는: glab repo clone GROUP/REPO
# 또는: git clone https://git.example.com/GROUP/REPO.git
cd REPO
codex
nvim .
```

`/workspace`는 선택한 워크스페이스의 호스트 디렉토리(`ws1` → `dam/workspaces/ws1`)를 연결한 bind mount입니다.
작업할 디렉토리에서 Codex를 실행하면 되고, 여러 작업을 동시에 진행할 때는 tmux 창을 나누거나 이름이 다른 세션을 사용하면 됩니다.
도구는 현재 Linux 사용자의 홈과 CLI 로그인을 사용합니다.

컨테이너 시작 시 `/workspace` 디렉토리 자체에만 공용 `users` 그룹, 그룹 읽기/쓰기/실행 권한과 setgid를 적용합니다.
`umask 0002`와 디렉토리의 그룹 상속으로 일반적인 방식으로 만든 새 파일과 하위 디렉토리를 공유합니다.
기존 파일과 하위 디렉토리의 소유권·권한은 변경하지 않으며, 애플리케이션이 `0600`처럼 명시적으로 제한한 파일은 자동으로 공유하지 않습니다.
`sync`는 설정만 동기화하며 작업 공간 권한을 변경하지 않습니다.
기본 계정 `node`는 `users` 그룹에 속합니다.
`/workspace`에서 GID 변경, Unix 권한, setgid 상속을 지원하는 파일시스템만 지원합니다.
권한 변경 요청이 오류를 반환하면 시작을 중단합니다. 변경 요청을 성공으로 처리하면서 실제로 적용하지 않는 파일시스템은 지원하지 않으며, 별도로 감지하지 않습니다.

사용자 네임스페이스로 UID/GID를 재매핑하지 않는 Linux 호스트에서는 컨테이너 시작 시 `os.fchown`과 `os.fchmod`가 호스트 작업 공간 디렉토리 자체의 GID와 권한을 직접 변경합니다.
소유자 UID는 유지하고, 그룹은 컨테이너 `users` 그룹의 GID(현재 기본 이미지에서는 `100`)로 변경합니다.
호스트에서도 같은 숫자 GID가 적용되며, 호스트의 그룹 이름은 `users`와 다를 수 있습니다.
기존 소유자·기타 사용자 권한을 유지하면서 그룹 읽기/쓰기/실행 권한과 setgid를 추가하고, setuid와 sticky bit는 제거합니다.
예를 들어 `0700`은 `2770`, `0755`는 `2775`가 됩니다. 이 변경은 컨테이너를 중지하거나 삭제해도 호스트에 남습니다.

그룹을 상속하는 디렉토리에서 `umask 0002`로 일반적인 방식으로 만든 새 파일과 하위 디렉토리는 호스트에서도 같은 GID의 그룹 쓰기를 허용합니다.
기존 파일과 하위 디렉토리의 소유권·권한은 변경하지 않지만, 상위 경로를 통과할 수 있는 해당 호스트 그룹 사용자는 작업 공간 바로 아래 항목을 삭제하거나 이름을 바꿀 수 있습니다.
여러 사용자가 쓰는 Linux 호스트에서는 의도하지 않은 쓰기 권한이 생기지 않도록 상위 경로의 접근 권한과 해당 GID의 그룹 구성원을 확인하세요.
Docker Desktop이나 사용자 네임스페이스를 사용하는 환경에서는 호스트와 컨테이너 사이의 GID·권한 매핑이 다를 수 있습니다.

## 공유와 분리

아래 홈 경로는 기본 `node` 계정 기준입니다.
다른 계정으로 전환하면 해당 사용자의 홈을 사용합니다.

| 항목 | 호스트 경로 | 컨테이너 경로 | 동작 |
| --- | --- | --- | --- |
| 작업 공간 | `dam/workspaces/{WORKSPACE}` | `/workspace` | 읽기/쓰기 공유 |
| 워크스페이스 Bash 설정 | `dam/workspaces/{WORKSPACE}/.bashrc` | `/workspace/.bashrc` | 읽기/쓰기 공유, 존재하면 source, `sync`는 생성하거나 수정하지 않음 |
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

공통 설정 동기화는 **호스트 -> 컨테이너 단방향**입니다.
`./dam WORKSPACE`, `./dam WORKSPACE tmux SESSION`, `./dam WORKSPACE exec`, `./dam WORKSPACE sync`를 실행할 때 갱신합니다.
컨테이너에서 수정한 공통 설정은 다음 동기화 때 덮어쓸 수 있으므로 공통 설정은 호스트에서 편집해야 합니다.
컨테이너에서만 적용하고 싶은 설정은 `/workspace/.bashrc`에 설정하세요.
이 파일은 동기화되지 않습니다.
실행 중인 tmux에는 `tmux source-file ~/.tmux.conf`로 반영하고, 실행중인 Codex/Neovim은 다시 실행할 때 반영됩니다.

Codex는 공통 설정을 시스템 설정 계층에서 읽습니다.
공통 설정의 스킬/에이전트 경로는 `/mnt/host-settings`의 읽기 전용 자산을 참조하며, 특정 사용자의 홈에 종속되지 않습니다.
시스템 설정은 root가 관리하고 사용자 설정 가져오기는 인증 정보, 기록, 개인 Codex 설정을 보존합니다.
컨테이너 전용 변경과 프로젝트 신뢰 설정은 쓰기 가능한 `~/.codex/config.toml`에 저장되며 공통 설정보다 우선합니다.
호스트의 macOS 전용 MCP, 알림 명령, 데스크톱 설정, 프로젝트 신뢰 목록, 설치된 플러그인/마켓플레이스 설정은 가져오지 않습니다.
CLI용 플러그인은 컨테이너에서 설치하세요.
Codex 기본 `.system` 스킬은 컨테이너 CLI가 관리하며, 호스트의 사용자 스킬만 공유합니다.
호스트의 Neovim 설정이 참조하는 `.vimrc`와 `.vim`의 설정 파일도 함께 동기화합니다.

호스트의 Codex `auth.json`, 대화 기록, gh/glab 설정, `.gitconfig`, `.ssh`, SSH agent, Docker 소켓은 연결하지 않습니다.
호스트의 인증 토큰 환경변수도 전달하지 않습니다.
공유 설정은 `.host-settings/`에 생성되며 Git 추적과 Docker 이미지 빌드에서 제외됩니다.
컨테이너 시작 시 root로 `/workspace` 디렉토리 자체의 공유 권한을 준비한 뒤 일반 실행 프로세스는 `node`로 전환합니다.
런처의 셸과 명령도 항상 `node`로 실행합니다.
파일 권한 설정과 사용자 권한 전환, 프로세스 종료에 필요한 `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `SETUID`, `SETGID`만 컨테이너에 부여합니다.
`su`의 계정 전환을 위해 `no-new-privileges`를 설정하지 않습니다.
호스트 네트워크는 사용하지 않습니다.
`/workspace`에 연결된 호스트 작업 공간의 파일은 컨테이너에서 수정/삭제할 수 있습니다.

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
./dam ws1 down                   # ws1 컨테이너 삭제, 홈 볼륨/작업 공간 유지
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

워크스페이스 이름 검증, 프로젝트 분리, build 실행 순서와 실패 처리, tmux 세션 이름 전달, 검증, 세션 목록 조회, 공통 설정과 사용자 설정의 분리, 인증 정보 보존과 셸 초기화는 임시 디렉토리와 Docker 명령 대역을 사용하는 테스트로 확인합니다.

```bash
python3 -m unittest discover -s tests -v
```
