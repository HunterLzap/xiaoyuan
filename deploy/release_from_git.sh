#!/usr/bin/env bash
# Deploy or roll back Xiaodan voice assistant on the Linux cloud host from a clean Git mirror.
# Keeps /opt/xiaodan/shared/{.env,data,logs} decoupled from release code directories.
set -euo pipefail

BASE_DIR="${BASE_DIR:-/opt/xiaodan}"
REPO_DIR="${REPO_DIR:-${BASE_DIR}/repo}"
REPO_URL="${REPO_URL:-https://gitee.com/ryan406/xiaoyuan.git}"
SERVICE_NAME="${SERVICE_NAME:-xiaodan}"
APP_USER="${APP_USER:-voice-assistant}"
APP_GROUP="${APP_GROUP:-voice-assistant}"
REF="${REF:-main}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"
PIP_SYNC="auto"
ROLLBACK_TARGET=""
NO_FETCH=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: release_from_git.sh [options]
  --ref <branch|tag|sha>     Git ref to deploy (default: main)
  --repo-dir <path>          Git mirror directory (default: /opt/xiaodan/repo)
  --base-dir <path>          Install root containing releases/shared/current (default: /opt/xiaodan)
  --service <name>           systemd unit name to restart (default: xiaodan)
  --pip-sync                 Force running pip install -r requirements.txt
  --no-pip-sync              Skip pip install check
  --no-fetch                 Skip git fetch and deploy directly from local mirror ref
  --rollback <release-name>  Switch current symlink to an existing release dir and restart
  --keep <N>                 Keep latest N releases during pruning (default: 5)
  --dry-run                  Print actions without making changes
  -h, --help                 Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) REF="$2"; shift 2 ;;
    --repo-dir) REPO_DIR="$2"; shift 2 ;;
    --base-dir) BASE_DIR="$2"; shift 2 ;;
    --service) SERVICE_NAME="$2"; shift 2 ;;
    --pip-sync) PIP_SYNC="always"; shift ;;
    --no-pip-sync) PIP_SYNC="never"; shift ;;
    --no-fetch) NO_FETCH=1; shift ;;
    --rollback) ROLLBACK_TARGET="$2"; shift 2 ;;
    --keep) KEEP_RELEASES="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

log() { printf '[deploy] %s\n' "$*"; }
run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    eval "$@"
  fi
}

RELEASES_DIR="${BASE_DIR}/releases"
SHARED_DIR="${BASE_DIR}/shared"
VENV_DIR="${BASE_DIR}/.venv"
CACHE_DIR="${BASE_DIR}/.cache"
CURRENT_LINK="${BASE_DIR}/current"

switch_and_restart() {
  local target_dir="$1"
  local tmp_link="${BASE_DIR}/.current.next.$$"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] switch ${CURRENT_LINK} -> ${target_dir} and restart ${SERVICE_NAME}"
    return 0
  fi
  ln -sfn "$target_dir" "$tmp_link"
  mv -Tf "$tmp_link" "$CURRENT_LINK"
  log "current -> $(readlink -f "$CURRENT_LINK")"
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "${SERVICE_NAME}.service" --no-legend 2>/dev/null | grep -q "${SERVICE_NAME}"; then
    systemctl restart "${SERVICE_NAME}.service"
    sleep 1
    systemctl is-active "${SERVICE_NAME}.service"
    log "Restarted ${SERVICE_NAME}.service cleanly."
  else
    log "WARN: ${SERVICE_NAME}.service not found under systemd; restart service manually."
  fi
}

if [[ -n "$ROLLBACK_TARGET" ]]; then
  target="${RELEASES_DIR}/${ROLLBACK_TARGET}"
  [[ -d "$target" ]] || { echo "Rollback release not found: $target" >&2; exit 1; }
  log "Rolling back to ${ROLLBACK_TARGET}..."
  switch_and_restart "$target"
  exit 0
fi

for req in git tar; do
  command -v "$req" >/dev/null 2>&1 || { echo "Missing required command: $req" >&2; exit 1; }
done

if [[ ! -f "${SHARED_DIR}/.env" ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] WARN: ${SHARED_DIR}/.env not present locally"
  else
    echo "Missing ${SHARED_DIR}/.env; initialize shared runtime first." >&2
    exit 1
  fi
fi
if [[ "$DRY_RUN" -eq 0 ]]; then
  mkdir -p "${RELEASES_DIR}" "${SHARED_DIR}/data" "${SHARED_DIR}/logs" "${CACHE_DIR}"
fi

if [[ ! -d "${REPO_DIR}/.git" && ! -f "${REPO_DIR}/HEAD" ]]; then
  log "Cloning bare mirror repository into ${REPO_DIR}..."
  run "git clone --bare '${REPO_URL}' '${REPO_DIR}'"
fi

fetch_with_retry() {
  local attempt=1
  local max_attempts=3
  while [[ $attempt -le $max_attempts ]]; do
    if "$@"; then
      return 0
    fi
    if [[ $attempt -lt $max_attempts ]]; then
      log "WARN: fetch attempt ${attempt}/${max_attempts} failed, retrying in 2s..."
      sleep 2
    fi
    attempt=$((attempt + 1))
  done
  return 1
}

if [[ "$NO_FETCH" -eq 1 ]]; then
  log "Skipping fetch (--no-fetch) in ${REPO_DIR} (ref=${REF})..."
else
  log "Fetching updates in ${REPO_DIR} (ref=${REF})..."
fi
if [[ "$DRY_RUN" -eq 0 ]]; then
  IS_BARE="$(git -C "${REPO_DIR}" rev-parse --is-bare-repository)"
  if [[ "$IS_BARE" == "true" ]]; then
    if [[ "$NO_FETCH" -eq 0 ]]; then
      fetch_with_retry git -C "${REPO_DIR}" fetch --prune origin '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*'
    fi
    TARGET_COMMIT="$(git -C "${REPO_DIR}" rev-parse "${REF}")"
  else
    if [[ -n "$(git -C "${REPO_DIR}" status --porcelain)" ]]; then
      echo "Refusing deploy: ${REPO_DIR} has dirty working tree changes." >&2
      exit 1
    fi
    if [[ "$NO_FETCH" -eq 0 ]]; then
      fetch_with_retry git -C "${REPO_DIR}" fetch --prune origin
    fi
    if git -C "${REPO_DIR}" show-ref --verify --quiet "refs/remotes/origin/${REF}"; then
      TARGET_COMMIT="$(git -C "${REPO_DIR}" rev-parse "refs/remotes/origin/${REF}")"
    else
      TARGET_COMMIT="$(git -C "${REPO_DIR}" rev-parse "${REF}")"
    fi
  fi
  SHORT_SHA="$(git -C "${REPO_DIR}" rev-parse --short=7 "${TARGET_COMMIT}")"
  RELEASE_NAME="${SHORT_SHA}-$(date +%Y%m%d-%H%M%S)"
  RELEASE_DIR="${RELEASES_DIR}/${RELEASE_NAME}"
else
  TARGET_COMMIT="HEAD"
  SHORT_SHA="dryrun"
  RELEASE_NAME="dryrun-$(date +%Y%m%d-%H%M%S)"
  RELEASE_DIR="${RELEASES_DIR}/${RELEASE_NAME}"
fi

log "Exporting ${SHORT_SHA} (${TARGET_COMMIT}) to ${RELEASE_DIR}..."
if [[ "$DRY_RUN" -eq 0 ]]; then
  mkdir -p "${RELEASE_DIR}"
  git -C "${REPO_DIR}" archive --format=tar "${TARGET_COMMIT}" -- \
    backend deploy requirements.txt requirements-speech.txt scripts third_party AGENTS.md .env.example \
    | tar -xf - -C "${RELEASE_DIR}"

  ln -sfn "${SHARED_DIR}/.env" "${RELEASE_DIR}/.env"
  ln -sfn "${SHARED_DIR}/data" "${RELEASE_DIR}/data"
  ln -sfn "${SHARED_DIR}/logs" "${RELEASE_DIR}/logs"
  ln -sfn "${CACHE_DIR}" "${RELEASE_DIR}/.cache"

  cat >"${RELEASE_DIR}/release.json" <<EOF
{
  "commit": "${TARGET_COMMIT}",
  "short_sha": "${SHORT_SHA}",
  "ref": "${REF}",
  "release": "${RELEASE_NAME}",
  "deployed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

  chown -R "${APP_USER}:${APP_GROUP}" "${RELEASE_DIR}"
  chown -h "${APP_USER}:${APP_GROUP}" \
    "${RELEASE_DIR}/.env" "${RELEASE_DIR}/data" "${RELEASE_DIR}/logs" "${RELEASE_DIR}/.cache"
fi

need_pip=0
if [[ "$PIP_SYNC" == "always" ]]; then
  need_pip=1
elif [[ "$PIP_SYNC" == "auto" && "$DRY_RUN" -eq 0 ]]; then
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    need_pip=1
  elif [[ ! -f "${CURRENT_LINK}/requirements.txt" ]] || ! cmp -s "${CURRENT_LINK}/requirements.txt" "${RELEASE_DIR}/requirements.txt"; then
    need_pip=1
  fi
fi

if [[ "$need_pip" -eq 1 && -x "${VENV_DIR}/bin/pip" ]]; then
  log "Syncing Python dependencies into ${VENV_DIR}..."
  if [[ "$DRY_RUN" -eq 0 ]]; then
    PIP_CACHE_DIR="${CACHE_DIR}/pip" "${VENV_DIR}/bin/pip" install -r "${RELEASE_DIR}/requirements.txt"
  fi
fi

switch_and_restart "${RELEASE_DIR}"

if [[ "$DRY_RUN" -eq 0 && "$KEEP_RELEASES" =~ ^[0-9]+$ && "$KEEP_RELEASES" -gt 0 ]]; then
  active_name="$(basename "$(readlink -f "$CURRENT_LINK")")"
  old_releases="$(ls -1dt "${RELEASES_DIR}"/*/ 2>/dev/null | xargs -r -n1 basename || true)"
  count=0
  for name in $old_releases; do
    [[ "$name" == "$active_name" ]] && continue
    # Keep existing pre-git bd639a9 backups untouched unless manually removed; prune git-timestamped ones beyond KEEP_RELEASES.
    if [[ "$name" =~ ^[0-9a-f]{7}-[0-9]{8}-[0-9]{6}$ ]]; then
      count=$((count + 1))
      if [[ "$count" -ge "$KEEP_RELEASES" ]]; then
        log "Pruning old release: ${name}"
        rm -rf "${RELEASES_DIR:?}/${name}"
      fi
    fi
  done
fi

log "Deployment complete: ${RELEASE_NAME}"
