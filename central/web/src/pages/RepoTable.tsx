import { Fragment } from "react";
import type { CodeVersions, RepoBuild, ShapeRow } from "../api";
import Legend, { type LegendRow } from "../components/Legend";
import { HostBadge } from "./CicdCompare";
import { verParts } from "../vercmp";

// config 탭의 repo 보기 — 서비스마다 repo 프로젝트 · 빌드에 쓰는 런타임(repo CI 이미지) · 코드에 적힌 버전 · 실행 이미지(center) 비교

const major = (v?: string | null) => verParts(v)[0];

// 코드에 적힌 값(정확히 / 최소) 과 다른 버전 하나를 비교 — 다르면 true
function codeDiffers(
  code: CodeVersions,
  runtime: string,
  version?: string | null,
): boolean {
  const v = major(version);
  if (v === undefined) return false;
  if (runtime === "node" && code.node) {
    const c = major(code.node)!;
    return code.node_rule === "min" ? v < c : v !== c;
  }
  if (runtime === "java" && code.java) return v !== major(code.java);
  return false;
}

const codeText = (c: CodeVersions) =>
  c.node
    ? `node ${c.node_rule === "min" ? "≥" : ""}${c.node}`
    : c.java
      ? `java ${c.java}`
      : null;
const codeFrom = (c: CodeVersions) => (c.node ? c.node_from : "pom.xml");

// 확인할 것 — 빌드(repo CI 이미지) · 코드 · 실행(center 이미지) 셋 중 다른 것. [짧은 글, 뜻]
export function repoChecks(r: ShapeRow): [string, string][] {
  const code = r.repo?.code;
  const builds = (r.repo?.build ?? []).filter((b) => b.version);
  const out: [string, string][] = [];
  const run =
    r.runtime && r.runtime_version ? `${r.runtime} ${r.runtime_version}` : null;
  const codeT = code ? codeText(code) : null;
  for (const b of builds) {
    if (code && codeT && codeDiffers(code, b.runtime, b.version))
      out.push([
        "빌드≠코드",
        `빌드는 ${b.runtime} ${b.version}(CI 이미지 ${b.image}), 코드는 ${codeT}(${codeFrom(code)})`,
      ]);
    if (
      run &&
      r.runtime === b.runtime &&
      major(b.version) !== major(r.runtime_version)
    )
      out.push([
        "빌드≠실행",
        `빌드는 ${b.runtime} ${b.version}(CI 이미지 ${b.image}), 실행 이미지는 ${run}`,
      ]);
  }
  if (
    code &&
    codeT &&
    r.runtime &&
    codeDiffers(code, r.runtime, r.runtime_version)
  )
    out.push([
      "코드≠실행",
      `코드는 ${codeT}(${codeFrom(code)}), 실행 이미지는 ${run}`,
    ]);
  return out;
}

function buildCell(r: ShapeRow) {
  const repo = r.repo;
  if (repo && repo.read === false)
    return (
      <span
        className="miss-fail st-fail"
        title="repo CI(.gitlab-ci.yml)를 못 읽음 — 프로젝트 경로·토큰 권한 확인"
      >
        못 읽음
      </span>
    );
  const builds = repo?.build ?? [];
  if (builds.length === 0)
    return (
      <span
        className="muted"
        title="repo CI 의 job 에 런타임 이미지(node·java 등)가 없음 — shell 러너 서버에 깔린 것으로 빌드하거나 Dockerfile 안에서 빌드"
      >
        —
      </span>
    );
  return (
    <span className="exec-lines">
      {builds.map((b: RepoBuild) => (
        <span
          key={`${b.runtime}${b.version}`}
          className="exec-line"
          title={`CI 이미지 ${b.image} · job ${b.jobs.join(", ")}`}
        >
          <span className="ver">
            {b.runtime}
            {b.version ? ` ${b.version}` : ""}
          </span>
        </span>
      ))}
    </span>
  );
}

function codeCell(r: ShapeRow) {
  const c = r.repo?.code;
  const t = c ? codeText(c) : null;
  if (!c || !t)
    return (
      <span
        className="muted"
        title="repo 에 .nvmrc · package.json engines · pom.xml 버전이 없음"
      >
        —
      </span>
    );
  return (
    <span
      className="ver"
      title={`출처: ${codeFrom(c)}${c.nest ? ` · nest ${c.nest}` : ""}`}
    >
      {t}
    </span>
  );
}

function checkCell(r: ShapeRow) {
  const checks = repoChecks(r);
  if (checks.length === 0) return <span className="badge badge--ok">없음</span>;
  return (
    <span className="exec-lines">
      {checks.map(([label, why]) => (
        <span key={label} className="exec-line">
          <span className="badge badge--warn" title={why}>
            ⚠ {label}
          </span>
        </span>
      ))}
    </span>
  );
}

// 'g/sub/project' — '/' 에서만 줄바꿈(칸이 넓어지지 않게)
function ProjectPath({ path }: { path: string }) {
  return (
    <span className="mono grp-repo" title={`repo 프로젝트: ${path} (GitLab)`}>
      {path.split("/").map((part, i, arr) => (
        <span key={i} className="grp-repo-part">
          {part}
          {i < arr.length - 1 ? "/" : ""}
        </span>
      ))}
    </span>
  );
}

export const REPO_LEGEND: LegendRow[] = [
  {
    term: "node · java 버전",
    what: "빌드 → 코드 → 실행 순서로 비교",
    items: [
      ["빌드", "repo CI job 의 이미지(node:20-slim 등)"],
      ["코드", ".nvmrc · package.json · pom.xml"],
      ["실행", "center 가 만든 이미지(Dockerfile FROM)"],
    ],
  },
  {
    term: "확인할 것",
    what: "셋 중 다른 것",
    items: [
      [
        <span className="badge badge--warn">⚠ 빌드≠코드</span>,
        "CI 가 다른 버전으로 빌드",
      ],
      [
        <span className="badge badge--warn">⚠ 빌드≠실행</span>,
        "빌드와 실행 버전이 다름",
      ],
      [
        <span className="badge badge--warn">⚠ 코드≠실행</span>,
        "코드가 바라는 버전과 다름",
      ],
      [<span className="badge badge--ok">없음</span>, "모두 같음"],
    ],
  },
];

export default function RepoTable({ rows }: { rows: ShapeRow[] }) {
  // 그룹 → 서비스 → 타입 (빌드·배포 표와 같은 묶음)
  const split = (r: ShapeRow) => {
    const t = r.type ?? "";
    return t && r.service.endsWith(` ${t}`)
      ? { app: r.service.slice(0, -t.length - 1), kind: t }
      : { app: r.service, kind: t || "—" };
  };
  const byGroup = new Map<string, Map<string, ShapeRow[]>>();
  for (const r of rows) {
    const g = r.group || "기타";
    const apps = byGroup.get(g) ?? new Map<string, ShapeRow[]>();
    apps.set(split(r).app, [...(apps.get(split(r).app) ?? []), r]);
    byGroup.set(g, apps);
  }
  const ordered = [...byGroup.entries()]
    .sort(([a], [b]) =>
      a === "기타" ? 1 : b === "기타" ? -1 : a.localeCompare(b),
    )
    .map(([group, apps]) => ({
      group,
      apps: [...apps.entries()].sort(([a], [b]) => a.localeCompare(b)),
    }));

  return (
    <table className="grid grid--nowrap grid--dense">
      <thead>
        <tr className="th-band">
          <th rowSpan={2}>그룹</th>
          <th rowSpan={2}>서비스</th>
          <th rowSpan={2}>타입</th>
          <th rowSpan={2}>repo 프로젝트</th>
          <th colSpan={3} className="th-group">
            node · java 버전
            <span className="th-flow">
              repo CI 로 빌드 → 코드에 적힌 값 → center 이미지로 실행
            </span>
          </th>
          <th rowSpan={2}>확인할 것</th>
        </tr>
        <tr>
          <th className="th-sub">빌드 (repo CI 이미지)</th>
          <th className="th-sub">코드에 적힌 버전</th>
          <th className="th-sub">실행 (center 이미지)</th>
        </tr>
      </thead>
      <tbody>
        {ordered.map((g) => {
          const total = g.apps.reduce((n, [, rs]) => n + rs.length, 0);
          return (
            <Fragment key={g.group}>
              {g.apps.map(([app, rs], ai) =>
                rs.map((r, i) => {
                  const groupFirst = ai === 0 && i === 0;
                  return (
                    <tr
                      key={r.service}
                      className={
                        groupFirst
                          ? "grp-start"
                          : i === 0
                            ? "svc-start"
                            : undefined
                      }
                    >
                      {groupFirst && (
                        <td className="grp-cell" rowSpan={total}>
                          {g.group}
                          <div
                            className="muted"
                            style={{ fontWeight: 400, fontSize: 12 }}
                          >
                            서비스 {g.apps.length}개
                          </div>
                          <div className="grp-host">
                            <HostBadge host="gitlab" />
                          </div>
                        </td>
                      )}
                      {i === 0 && (
                        <td className="svc-cell" rowSpan={rs.length}>
                          {app}
                        </td>
                      )}
                      <td>{split(r).kind}</td>
                      <td>
                        {r.repo?.project ? (
                          <ProjectPath path={r.repo.project} />
                        ) : (
                          <span
                            className="muted"
                            title="대상 파일에 repo: 프로젝트를 안 적음(로컬 사본)"
                          >
                            —
                          </span>
                        )}
                      </td>
                      <td>{buildCell(r)}</td>
                      <td>{codeCell(r)}</td>
                      <td>
                        {r.runtime ? (
                          <span className="ver">
                            {r.runtime}
                            {r.runtime_version ? ` ${r.runtime_version}` : ""}
                          </span>
                        ) : (
                          <span
                            className="muted"
                            title="이 서비스와 연결된 config 폴더(Dockerfile)가 없음"
                          >
                            —
                          </span>
                        )}
                      </td>
                      <td>{checkCell(r)}</td>
                    </tr>
                  );
                }),
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

export function RepoLegend() {
  return (
    <Legend
      id="config-repo"
      rows={REPO_LEGEND}
      source="repo GitLab(.gitlab-ci.yml · .nvmrc · package.json · pom.xml) + center config repo(Dockerfile) — runner shape"
    />
  );
}
