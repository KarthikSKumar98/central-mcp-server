#!/usr/bin/env bash
# Build and exercise the artifacts that would be uploaded to PyPI.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

reuse_dist=false
if [[ ${1:-} == "--reuse-dist" ]]; then
  reuse_dist=true
elif [[ $# -ne 0 ]]; then
  echo "Usage: $0 [--reuse-dist]" >&2
  exit 2
fi

work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
export UV_CACHE_DIR=${UV_CACHE_DIR:-"$work_dir/uv-cache"}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

smoke_test() {
  local artifact=$1
  local environment=$2

  echo "==> Installing $(basename "$artifact")"
  uv venv "$environment"
  uv pip install --python "$environment/bin/python" "$artifact"
  "$environment/bin/python" -c "import server"
  PATH="$environment/bin:$PATH" command -v central-mcp-server >/dev/null \
    || fail "central-mcp-server console script was not installed"
  echo "PASS: $(basename "$artifact") installs, imports, and provides its console script"
}

if "$reuse_dist"; then
  echo "==> Reusing existing dist/ artifacts"
else
  echo "==> Building artifacts"
  rm -rf dist
  uv build
fi

shopt -s nullglob
wheels=(dist/*.whl)
sdists=(dist/*.tar.gz)
[[ ${#wheels[@]} -eq 1 ]] || fail "expected exactly one wheel in dist/"
[[ ${#sdists[@]} -eq 1 ]] || fail "expected exactly one sdist in dist/"

echo "==> Validating package metadata"
uv venv "$work_dir/twine"
uv pip install --python "$work_dir/twine/bin/python" twine
"$work_dir/twine/bin/python" -m twine check dist/*

smoke_test "${wheels[0]}" "$work_dir/wheel"
smoke_test "${sdists[0]}" "$work_dir/sdist"
echo "PASS: release rehearsal completed"
