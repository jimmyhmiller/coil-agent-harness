#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
deploy_host=${HARNESS_DEPLOY_HOST:-computer.jimmyhmiller.com}
remote_project=${HARNESS_DEPLOY_PROJECT:-/home/jimmyhmiller/Documents/Code/projects/coil-agent-harness}
remote_library=${HARNESS_DEPLOY_LIBRARY:-/etc/gatekeeper/funcs/libcoil_agent_harness.so}
service_name=${HARNESS_DEPLOY_SERVICE:-gatekeeper}
revision=${HARNESS_DEPLOY_REVISION:-$(git -C "$project_dir" rev-parse HEAD)}

if ! git -C "$project_dir" diff --quiet || ! git -C "$project_dir" diff --cached --quiet; then
  printf '%s\n' 'refusing to deploy a revision with uncommitted tracked changes' >&2
  exit 1
fi

git -C "$project_dir" merge-base --is-ancestor "$revision" origin/main || {
  printf '%s\n' "refusing to deploy $revision because it is not on origin/main" >&2
  exit 1
}

printf 'Deploying harness revision %s to %s\n' "$revision" "$deploy_host"
ssh "$deploy_host" sh -s -- "$remote_project" "$revision" "$remote_library" "$service_name" <<'REMOTE'
set -eu

project_dir=$1
revision=$2
library=$3
service=$4
worktree_root="$project_dir/.worktrees"
worktree="$worktree_root/deploy-$revision"
artifact="$worktree/build/libcoil_agent_harness.so"
backup="$library.pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)"

git -C "$project_dir" fetch origin main
git -C "$project_dir" cat-file -e "$revision^{commit}"
mkdir -p "$worktree_root"
git -C "$project_dir" worktree prune
if [ ! -d "$worktree" ]; then
  git -C "$project_dir" worktree add --detach "$worktree" "$revision"
fi
test "$(git -C "$worktree" rev-parse HEAD)" = "$revision"

PATH="$HOME/.local/bin:$PATH" "$worktree/scripts/build_gatekeeper_function.sh"
test -s "$artifact"
nm -D "$artifact" | grep -q ' gk_abi_version$'
nm -D "$artifact" | grep -q ' gk_handle$'
nm -D "$artifact" | grep -q ' gk_describe$'
nm -D "$artifact" | grep -q ' gk_stream_read$'

sudo cp --preserve=mode,ownership "$library" "$backup"
sudo install -o root -g root -m 0755 "$artifact" "$library.new"
sudo mv "$library.new" "$library"
sudo systemctl restart "$service"
sudo systemctl is-active --quiet "$service"

installed_sha=$(sha256sum "$library" | awk '{print $1}')
artifact_sha=$(sha256sum "$artifact" | awk '{print $1}')
test "$installed_sha" = "$artifact_sha"
printf 'Installed %s (sha256 %s); backup: %s\n' "$revision" "$installed_sha" "$backup"
REMOTE
