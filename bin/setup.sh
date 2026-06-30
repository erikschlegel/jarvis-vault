#!/usr/bin/env bash
#
# setup.sh
# First-run bootstrap for the jarvis-vault LLM Wiki engine.
#
# Standalone and pre-uv: detects the toolchain, installs what is missing (with
# confirmation), creates and wires an external vault, seeds it via wiki-init,
# and registers the MCP retrieval server. Idempotent and safe to re-run.
#
# Usage: bin/setup.sh [--check] [--yes] [--no-build]
#                     [--vault-parent <dir>] [--vault-name <name>]

set -euo pipefail

# --- Constants ---------------------------------------------------------------

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly REPO_ROOT
readonly MIN_PYTHON_MINOR=12
readonly MCP_SERVER_NAME="jarvis-vault"
readonly DEFAULT_VAULT_PARENT="${HOME}/obsidian"
readonly DEFAULT_VAULT_NAME="jarvis-vault"
readonly UV_INSTALL_URL="https://astral.sh/uv/install.sh"

# --- Options (set by parse_args) ---------------------------------------------

CHECK_ONLY=false
ASSUME_YES=false
BUILD_INDEX=true
VAULT_PARENT=""
VAULT_NAME=""

# --- Output helpers ----------------------------------------------------------

log() {
  printf '\n========== %s ==========\n' "$1"
}

info() {
  printf '  %s\n' "$1"
}

warn() {
  printf 'WARNING: %s\n' "$1" >&2
}

err() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: bin/setup.sh [OPTIONS]

Bootstrap the jarvis-vault engine: toolchain, vault, index, and MCP server.

Options:
  --check                  Report status read-only; make no changes.
  --yes                    Assume yes for every prompt (non-interactive).
  --no-build               Skip the search-index build (offline-friendly).
  --vault-parent <dir>     Directory that will contain the vault folder.
                           Default: ~/obsidian
  --vault-name <name>      Vault folder name. Default: jarvis-vault
  --help, -h               Show this help message.

The vault is created at <vault-parent>/<vault-name>, holding wiki/ and raw/
as siblings, with WIKI_VAULT pointing at <...>/wiki. An already-configured
WIKI_VAULT is reused as-is.
EOF
}

# --- Argument parsing --------------------------------------------------------

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --check)
        CHECK_ONLY=true
        shift
        ;;
      --yes|-y)
        ASSUME_YES=true
        shift
        ;;
      --no-build)
        BUILD_INDEX=false
        shift
        ;;
      --vault-parent)
        if [[ -z "${2:-}" || "$2" == --* ]]; then
          err "--vault-parent requires a directory argument"
        fi
        VAULT_PARENT="$2"
        shift 2
        ;;
      --vault-name)
        if [[ -z "${2:-}" || "$2" == --* ]]; then
          err "--vault-name requires a name argument"
        fi
        VAULT_NAME="$2"
        shift 2
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        printf 'Unknown option: %s\n' "$1" >&2
        usage
        exit 2
        ;;
    esac
  done
}

# --- Small utilities ---------------------------------------------------------

have() {
  command -v "$1" &>/dev/null
}

# Prompt for yes/no. Returns 0 for yes. Honors --yes and non-interactive stdin.
confirm() {
  local prompt="$1"
  if [[ "${ASSUME_YES}" == true ]]; then
    return 0
  fi
  if [[ ! -t 0 ]]; then
    return 1
  fi
  local reply
  read -r -p "${prompt} [y/N] " reply
  [[ "${reply}" =~ ^[Yy]$ ]]
}

# Python interpreter usable by uv, if any meets the minimum.
python_ok() {
  have uv && uv run python -c \
    "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, ${MIN_PYTHON_MINOR}) else 1)" \
    &>/dev/null
}

# Resolve WIKI_VAULT through the engine's own layered .env discovery.
resolved_vault() {
  have uv || return 1
  uv run --directory "${REPO_ROOT}" python -c \
    "from wiki_core import paths; v = paths.find_vault(); print(v) if v else exit(1)" \
    2>/dev/null
}

# Update or append KEY=VALUE in an env file, preserving comments and order.
set_env_var() {
  local key="$1" value="$2" file="$3" tmp
  if grep -qE "^${key}=" "${file}" 2>/dev/null; then
    tmp="$(mktemp)"
    awk -v k="${key}" -v v="${value}" \
      'BEGIN { FS = "=" } $1 == k { print k "=" v; next } { print }' \
      "${file}" >"${tmp}"
    mv "${tmp}" "${file}"
  else
    printf '%s=%s\n' "${key}" "${value}" >>"${file}"
  fi
}

# --- Detection (read-only) ---------------------------------------------------

print_status() {
  local label="$1" ok="$2" detail="$3" marker
  if [[ "${ok}" == true ]]; then
    marker="ok  "
  else
    marker="MISSING"
  fi
  printf '  [%-7s] %-16s %s\n' "${marker}" "${label}" "${detail}"
}

detect() {
  log "Detecting toolchain and vault"

  if have uv; then
    print_status "uv" true "$(uv --version 2>/dev/null || echo present)"
  else
    print_status "uv" false "not installed"
  fi

  if python_ok; then
    print_status "python" true ">= 3.${MIN_PYTHON_MINOR}"
  else
    print_status "python" false "need >= 3.${MIN_PYTHON_MINOR} (uv can install it)"
  fi

  if have git; then
    print_status "git" true "$(git --version 2>/dev/null | awk '{print $3}')"
  else
    print_status "git" false "not installed (optional, for vault history)"
  fi

  local vault
  if vault="$(resolved_vault)"; then
    print_status "WIKI_VAULT" true "${vault}"
    if [[ -f "${vault}/index.md" ]]; then
      print_status "vault seeded" true "${vault}/index.md"
    else
      print_status "vault seeded" false "run wiki-init to seed"
    fi
    if [[ -f "${vault}/.wiki_index/meta.json" ]]; then
      print_status "index built" true "${vault}/.wiki_index"
    else
      print_status "index built" false "run wiki-init or wiki-search build"
    fi
  else
    print_status "WIKI_VAULT" false "not configured (.env)"
  fi
}

# --- Install / configure -----------------------------------------------------

ensure_uv() {
  if have uv; then
    return 0
  fi
  log "Installing uv"
  if ! confirm "Install uv via ${UV_INSTALL_URL}?"; then
    cat >&2 <<EOF
uv is required. Install it manually, then re-run this script:
  curl -LsSf ${UV_INSTALL_URL} | sh
  (see https://docs.astral.sh/uv/ for alternatives)
EOF
    exit 1
  fi
  curl -LsSf "${UV_INSTALL_URL}" | sh
  # The installer drops uv in ~/.local/bin; surface it for the rest of this run.
  export PATH="${HOME}/.local/bin:${PATH}"
  have uv || err "uv installation did not put 'uv' on PATH; open a new shell and re-run"
}

ensure_python() {
  if python_ok; then
    return 0
  fi
  log "Installing Python 3.${MIN_PYTHON_MINOR}"
  info "uv will fetch a managed CPython build."
  uv python install "3.${MIN_PYTHON_MINOR}"
}

ensure_deps() {
  log "Installing dependencies (uv sync)"
  uv sync --directory "${REPO_ROOT}"
}

ensure_env_and_vault() {
  local env_file="${REPO_ROOT}/.env"
  local example="${REPO_ROOT}/.env.example"

  local vault
  if vault="$(resolved_vault)"; then
    info "Reusing configured WIKI_VAULT: ${vault}"
    OBSIDIAN_ROOT="$(cd -- "${vault}/.." && pwd -P)"
    WIKI_VAULT_PATH="${vault}"
    return 0
  fi

  log "Configuring the vault"

  local parent="${VAULT_PARENT:-${DEFAULT_VAULT_PARENT}}"
  local name="${VAULT_NAME:-${DEFAULT_VAULT_NAME}}"
  OBSIDIAN_ROOT="${parent}/${name}"

  if [[ -z "${VAULT_PARENT}" && -z "${VAULT_NAME}" && "${ASSUME_YES}" != true && -t 0 ]]; then
    local reply
    read -r -p "Where should your vault live? [${OBSIDIAN_ROOT}] " reply
    if [[ -n "${reply}" ]]; then
      OBSIDIAN_ROOT="${reply/#\~/${HOME}}"
    fi
  fi

  WIKI_VAULT_PATH="${OBSIDIAN_ROOT}/wiki"
  info "Vault root:  ${OBSIDIAN_ROOT}"
  info "WIKI_VAULT:  ${WIKI_VAULT_PATH}"

  mkdir -p "${WIKI_VAULT_PATH}" "${OBSIDIAN_ROOT}/raw"

  if [[ ! -f "${env_file}" ]]; then
    if [[ -f "${example}" ]]; then
      cp "${example}" "${env_file}"
      info "Created .env from .env.example"
    else
      : >"${env_file}"
    fi
  fi
  set_env_var "WIKI_VAULT" "${WIKI_VAULT_PATH}" "${env_file}"
  info "Set WIKI_VAULT in ${env_file}"
}

run_wiki_init() {
  log "Seeding the vault (wiki-init)"
  local init_args=()
  if [[ "${BUILD_INDEX}" != true ]]; then
    init_args+=("--no-build")
  fi
  uv run --directory "${REPO_ROOT}" wiki-init "${init_args[@]}"
  relocate_obsidian_config
}

# wiki-init seeds the template (including .obsidian/) into WIKI_VAULT (the wiki/
# subfolder). The shipped graph config scopes to `path:wiki/`, so .obsidian
# belongs at the vault root one level up. Move it there once.
relocate_obsidian_config() {
  local from="${WIKI_VAULT_PATH}/.obsidian"
  local to="${OBSIDIAN_ROOT}/.obsidian"
  if [[ -d "${from}" && ! -d "${to}" ]]; then
    mv "${from}" "${to}"
    info "Moved Obsidian config to vault root: ${to}"
  fi
}

# --- MCP registration --------------------------------------------------------

register_mcp() {
  log "Registering the MCP retrieval server"

  if [[ -f "${REPO_ROOT}/.vscode/mcp.json" ]]; then
    info "VS Code: .vscode/mcp.json present (auto-discovered after trust)."
  else
    warn "VS Code: .vscode/mcp.json missing; see SETUP.md to add it."
  fi

  if have copilot; then
    if copilot mcp get "${MCP_SERVER_NAME}" &>/dev/null; then
      info "Copilot CLI: '${MCP_SERVER_NAME}' already registered."
    elif confirm "Register '${MCP_SERVER_NAME}' with the GitHub Copilot CLI?"; then
      copilot mcp add "${MCP_SERVER_NAME}" -- \
        uv run --directory "${REPO_ROOT}" wiki-mcp
      info "Copilot CLI: registered '${MCP_SERVER_NAME}'."
    else
      info "Skipped Copilot CLI registration. Run later:"
      info "  copilot mcp add ${MCP_SERVER_NAME} -- uv run --directory ${REPO_ROOT} wiki-mcp"
    fi
  else
    info "Copilot CLI not found. To register once installed:"
    info "  copilot mcp add ${MCP_SERVER_NAME} -- uv run --directory ${REPO_ROOT} wiki-mcp"
    info "See SETUP.md for the ~/.copilot/mcp-config.json block."
  fi
}

# --- Verification ------------------------------------------------------------

verify() {
  log "Verifying setup (wiki-doctor)"
  if uv run --directory "${REPO_ROOT}" wiki-doctor; then
    log "Setup complete"
    info "Next steps and troubleshooting: SETUP.md"
  else
    warn "Some checks did not pass. See the report above and SETUP.md."
  fi
}

# --- Orchestration -----------------------------------------------------------

run_check() {
  detect
  if have uv && [[ -f "${REPO_ROOT}/.venv/bin/python" || -d "${REPO_ROOT}/.venv" ]]; then
    log "Read-only diagnostics (wiki-doctor)"
    uv run --directory "${REPO_ROOT}" wiki-doctor || true
  fi
  info "--check made no changes."
}

main() {
  parse_args "$@"

  if [[ "${CHECK_ONLY}" == true ]]; then
    run_check
    exit 0
  fi

  detect
  ensure_uv
  ensure_python
  ensure_deps
  ensure_env_and_vault
  run_wiki_init
  register_mcp
  verify
}

main "$@"
