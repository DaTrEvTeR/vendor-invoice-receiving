import type { AuditEvent } from "@/lib/api";
import { dateTime } from "@/lib/format";

function describe(event: AuditEvent): string {
  const payload = event.payload;
  switch (event.action) {
    case "uploaded": {
      const error = payload.extraction_error as { code: string } | null;
      if (error) return `File not read (${error.code}).`;
      return `Read with parser ${String(payload.parser_key)}.`;
    }
    case "edited": {
      const changed = (payload.changed ?? {}) as Record<string, { from: unknown; to: unknown }>;
      const where = payload.line ? `Line ${String(payload.line)}: ` : "Header: ";
      const parts = Object.entries(changed).map(
        ([field, change]) => `${field} ${JSON.stringify(change.from)} → ${JSON.stringify(change.to)}`,
      );
      const reverted = (payload.reverted ?? []) as string[];
      if (reverted.length) parts.push(`reverted ${reverted.join(", ")}`);
      return where + (parts.join("; ") || "no change");
    }
    case "approved": {
      const accepted = (payload.accepted_discrepancies ?? []) as { code: string }[];
      return accepted.length
        ? `Accepted discrepancies: ${accepted.map((item) => item.code).join(", ")}.`
        : "No discrepancies.";
    }
    default:
      return payload.reason ? `Reason: ${String(payload.reason)}` : "";
  }
}

/** Who did what to this invoice, oldest first. */
export function AuditTrail({ events }: { events: AuditEvent[] }) {
  return (
    <section className="panel">
      <h2>Audit trail</h2>
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>Action</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.id}>
              <td>{dateTime(event.at)}</td>
              <td>{event.actor}</td>
              <td>{event.action}</td>
              <td>{describe(event)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
