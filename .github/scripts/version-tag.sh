#!/usr/bin/env bash
# main 에 합쳐진 커밋에 버전 태그 — v0.0.{PR번호}, 그 PR 이 닫은 이슈가 있으면 +{이슈}(여럿이면 +59.60).
# 화면 맨 위에 'v0.0.68 · 이슈 #59 · <커밋> · 반영' 으로 보인다(반영 쪽이 CT_VERSION 으로 넘김).
# PR 없이 들어온 커밋(직접 push)은 태그를 달지 않는다 — 번호를 지어내지 않는다.
#   사용: REPO=owner/name SHA=<커밋> GH_TOKEN=… version-tag.sh   (DRY_RUN=1 이면 태그 이름만 출력)
set -euo pipefail
: "${REPO:?}" "${SHA:?}"

# 합친 직후엔 커밋 ↔ PR 연결이 늦게 잡힐 수 있어 몇 번 다시 본다
pr=""
for _ in 1 2 3; do
  pr=$(gh api "repos/$REPO/commits/$SHA/pulls" --jq '[.[] | select(.merged_at != null) | .number] | first // empty')
  [ -n "$pr" ] && break
  [ "${DRY_RUN:-}" = 1 ] || sleep 10
done
if [ -z "$pr" ]; then
  echo "PR 없이 들어온 커밋 ${SHA:0:7} — 버전 태그 안 닮"
  exit 0
fi

issues=$(gh api graphql -F o="${REPO%/*}" -F n="${REPO#*/}" -F p="$pr" -f query='
  query($o: String!, $n: String!, $p: Int!) {
    repository(owner: $o, name: $n) { pullRequest(number: $p) { closingIssuesReferences(first: 10) { nodes { number } } } }
  }' --jq '[.data.repository.pullRequest.closingIssuesReferences.nodes[].number] | sort | map(tostring) | join(".")')

tag="v0.0.${pr}"
[ -n "$issues" ] && tag="${tag}+${issues}"

if [ "${DRY_RUN:-}" = 1 ]; then
  echo "$tag"
  exit 0
fi
# 같은 PR 의 태그가 이미 있으면 그대로(다시 돌려도 안전). v0.0.68 이 v0.0.680 과 헷갈리지 않게 정확히 비교
if gh api "repos/$REPO/git/matching-refs/tags/v0.0.${pr}" \
    --jq ".[].ref | select(. == \"refs/tags/v0.0.${pr}\" or startswith(\"refs/tags/v0.0.${pr}+\"))" | grep -q .; then
  echo "이미 있음: v0.0.${pr}… — 그대로 둠"
  exit 0
fi
gh api "repos/$REPO/git/refs" -f ref="refs/tags/$tag" -f sha="$SHA" >/dev/null
echo "버전 태그: $tag → ${SHA:0:7}"
