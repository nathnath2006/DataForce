import { docFor } from "./catalog";
import { DocLink } from "./DocsPage";

/** One reason or warning text with its docs link (plain text when no page explains it). */
export function ReasonText({ text }: { text: string }) {
  const d = docFor(text);
  return <>{text}{d && <DocLink id={d.id} label={d.title} />}</>;
}

export function ReasonList({ reasons }: { reasons: string[] }) {
  return <ul className="reasons">{reasons.map((r, i) => <li key={i}><ReasonText text={r} /></li>)}</ul>;
}
