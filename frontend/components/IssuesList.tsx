import type { Issue, IssueKind } from "@/lib/api";

import { KindBadge } from "./Badges";

const SEVERITY: Record<IssueKind, number> = { terminal: 0, hard: 1, soft: 2, info: 3 };

/** Why the invoice (or a line) needs a person, most blocking first. */
export function IssuesList({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) return null;
  const sorted = [...issues].sort((a, b) => SEVERITY[a.kind] - SEVERITY[b.kind]);
  return (
    <ul className="issues">
      {sorted.map((issue) => (
        <li key={issue.id}>
          <KindBadge kind={issue.kind} /> {issue.message} <code className="muted">{issue.code}</code>
        </li>
      ))}
    </ul>
  );
}
