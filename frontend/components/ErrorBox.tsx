import type { Issue } from "@/lib/api";

import { KindBadge } from "./Badges";

type ShortIssue = Pick<Issue, "code" | "kind" | "message" | "line_no">;

/** An error message, with the issues the server gave as the reason, if any. */
export function ErrorBox({ error, issues = [] }: { error?: string; issues?: ShortIssue[] }) {
  if (!error) return null;
  return (
    <div className="error" role="alert">
      <p>{error}</p>
      {issues.length > 0 && (
        <ul className="issues">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`}>
              <KindBadge kind={issue.kind} /> {issue.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
