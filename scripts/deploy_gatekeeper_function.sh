#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
deploy_host=${HARNESS_DEPLOY_HOST:-computer.jimmyhmiller.com}
remote_project=${HARNESS_DEPLOY_PROJECT:-/home/jimmyhmiller/Documents/Code/projects/coil-agent-harness}
remote_library=${HARNESS_DEPLOY_LIBRARY:-/etc/gatekeeper/funcs/libcoil_agent_harness.so}
service_name=${HARNESS_DEPLOY_SERVICE:-gatekeeper}
remote_coil=${HARNESS_DEPLOY_COIL:-/home/jimmyhmiller/Documents/Code/projects/coil/build/bin/coil}
remote_harness=${HARNESS_DEPLOY_HARNESS:-/usr/local/bin/coil-agent-harness}
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
ssh "$deploy_host" sh -s -- "$remote_project" "$revision" "$remote_library" "$service_name" "$remote_coil" "$remote_harness" <<'REMOTE'
set -eu

project_dir=$1
revision=$2
library=$3
service=$4
coil_bin=$5
harness_bin=$6
build_root=$(mktemp -d /tmp/coil-agent-harness-deploy.XXXXXX)
source_dir="$build_root/source"
artifact="$source_dir/build/libcoil_agent_harness.so"
harness_artifact="$source_dir/build/coil-agent-harness"
backup="$library.pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)"

cleanup() {
  rm -rf "$build_root"
}
trap cleanup EXIT INT TERM

git -C "$project_dir" fetch origin main
git -C "$project_dir" cat-file -e "$revision^{commit}"
mkdir -p "$source_dir"
git -C "$project_dir" archive "$revision" | tar -x -C "$source_dir"

test -x "$coil_bin"
PATH="$(dirname "$coil_bin"):$PATH" "$source_dir/scripts/build_gatekeeper_function.sh"
(
  cd "$source_dir"
  # Match the service library's Linux portability rule: use the platform shared
  # libcurl instead of Coil's executable-oriented bundled archives.
  PATH="$(dirname "$coil_bin"):$PATH" coil build src/main.coil -lcurl -o "$harness_artifact"
)
test -s "$artifact"
test -s "$harness_artifact"
nm -D "$artifact" | grep -q ' gk_abi_version$'
nm -D "$artifact" | grep -q ' gk_handle$'
nm -D "$artifact" | grep -q ' gk_describe$'
nm -D "$artifact" | grep -q ' gk_stream_read$'

sudo cp --preserve=mode,ownership "$library" "$backup"
sudo install -o root -g root -m 0755 "$harness_artifact" "$harness_bin"
sudo install -d -o root -g root -m 0755 /usr/local/libexec/coil-agent-harness
sudo install -o root -g root -m 0755 "$source_dir/scripts/launch_factory_service.sh" /usr/local/libexec/coil-agent-harness/launch_factory_service.sh
sudo install -o root -g root -m 0755 "$source_dir/scripts/run_factory_service.sh" /usr/local/libexec/coil-agent-harness/run_factory_service.sh
sudo install -o root -g root -m 0644 "$source_dir/deployment/gatekeeper-harness.conf" /etc/systemd/system/gatekeeper.service.d/40-harness.conf
sudo install -d -o gatekeeper -g gatekeeper -m 0750 /var/lib/gatekeeper/harness-workflows /var/lib/gatekeeper/harness-factory
sudo systemctl daemon-reload
sudo install -o root -g root -m 0755 "$artifact" "$library.new"
sudo mv "$library.new" "$library"
sudo systemctl restart "$service"
sudo systemctl is-active --quiet "$service"

installed_sha=$(sudo sha256sum "$library" | awk '{print $1}')
artifact_sha=$(sha256sum "$artifact" | awk '{print $1}')
test "$installed_sha" = "$artifact_sha"
printf 'Installed %s (sha256 %s); backup: %s\n' "$revision" "$installed_sha" "$backup"
REMOTE
