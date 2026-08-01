#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"
export NVM_DIR="${NVM_DIR:-${HOME}/.nvm}"
export ASTRO_TELEMETRY_DISABLED=1

if [[ ! -s "${NVM_DIR}/nvm.sh" ]]; then
    echo "ERROR: NVM was not found at ${NVM_DIR}/nvm.sh" >&2
    echo "Install NVM, then run: nvm install 22.12.0" >&2
    exit 1
fi

# NVM is a shell function, so every non-interactive Make/Honcho process must
# source it before selecting the version declared by frontend/.nvmrc.
# shellcheck source=/dev/null
source "${NVM_DIR}/nvm.sh"
cd "${FRONTEND_DIR}"
nvm use --silent
# npm scripts prepend every ancestor's node_modules/.bin to PATH. This machine
# has a stale ~/node_modules/.bin/node (v19), so put NVM's selected bin first
# again after npm has rewritten the environment.
export PATH="${NVM_BIN}:${PATH}"
hash -r

if [[ ! -d node_modules ]]; then
    echo "Installing frontend dependencies with npm ci..."
    npm ci
fi

echo "Starting frontend with Node $(node --version)"
MODE="${1:-dev}"
if [[ $# -gt 0 ]]; then
    shift
fi

# A stale ~/node_modules/.bin/node (v19) on this machine is prepended by
# `npm run`, shadowing NVM's selected binary. Invoke Astro with the selected
# Node executable directly so package-script PATH rewriting cannot replace it.
ASTRO_CLI="${FRONTEND_DIR}/node_modules/astro/bin/astro.mjs"
if [[ "${MODE}" == "cli" ]]; then
    exec node "${ASTRO_CLI}" "$@"
fi
exec node "${ASTRO_CLI}" "${MODE}" "$@"
