import { useMemo, useState } from "react";
import { Link } from "react-router";
import { useWs } from "../context";
import { Icon } from "../icons";
import { Empty } from "../ui";
import { byDay, isoDay, monthGrid, splitByToday } from "./all";
import { speakerNames } from "./text";
import type { DocumentOut } from "./types";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Month calendar of meetings, the selected day's agenda beside it, and the upcoming list below. */
export function MeetingsCalendar({ docs, onView }: { docs: DocumentOut[]; onView: (id: string) => void }) {
  const today = isoDay(new Date());
  const [cursor, setCursor] = useState(() => { const d = new Date(); return { y: d.getFullYear(), m: d.getMonth() }; });
  const [day, setDay] = useState(today);
  const days = useMemo(() => monthGrid(cursor.y, cursor.m), [cursor]);
  const map = useMemo(() => byDay(docs), [docs]);
  const { upcoming, past } = useMemo(() => splitByToday(docs, today), [docs, today]);
  const title = new Date(cursor.y, cursor.m, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const move = (delta: number) => setCursor(({ y, m }) => { const d = new Date(y, m + delta, 1); return { y: d.getFullYear(), m: d.getMonth() }; });
  const goTo = (iso: string) => { const d = new Date(`${iso}T00:00:00`); setCursor({ y: d.getFullYear(), m: d.getMonth() }); setDay(iso); };
  const agenda = map.get(day) ?? [];
  const latest = past[0]?.meeting_date?.slice(0, 10);

  return (
    <div className="bento">
      <section className="tile w8 cal" aria-label="Calendar">
        <div className="tile-head">
          <h2 className="cal-title">{title}</h2>
          <div className="row">
            <button className="quiet" aria-label="Previous month" onClick={() => move(-1)}><Icon name="chevron" size={16} className="flip" /></button>
            <button onClick={() => goTo(today)}>Today</button>
            <button className="quiet" aria-label="Next month" onClick={() => move(1)}><Icon name="chevron" size={16} /></button>
          </div>
        </div>
        <div className="cal-grid" role="grid" aria-label={title}>
          {WEEKDAYS.map((w) => <div key={w} className="cal-wd" role="columnheader">{w}</div>)}
          {days.map((d) => {
            const iso = isoDay(d);
            const items = map.get(iso) ?? [];
            const out = d.getMonth() !== cursor.m;
            return (
              <button key={iso} type="button" role="gridcell" aria-selected={iso === day}
                aria-label={`${d.toDateString()}: ${items.length} meeting${items.length === 1 ? "" : "s"}`}
                className={`cal-day${out ? " out" : ""}${iso === today ? " today" : ""}${iso === day ? " on" : ""}`}
                onClick={() => setDay(iso)}>
                <span className="cal-n">{d.getDate()}</span>
                {items.slice(0, 2).map((m) => <span key={m.id} className="cal-ev">{m.title}</span>)}
                {items.length > 2 && <span className="cal-more">+{items.length - 2} more</span>}
              </button>
            );
          })}
        </div>
        {upcoming.length === 0 && latest && (
          <p className="muted small">No meeting from today on. <button className="link" onClick={() => goTo(latest)}>Jump to the latest meeting</button></p>
        )}
      </section>

      <section className="tile w4 agenda" aria-label="Agenda">
        <p className="eyebrow">{new Date(`${day}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</p>
        {agenda.length === 0 ? <Empty>No meeting this day.</Empty> : (
          <ul className="list-rows">{agenda.map((m) => <MeetingRow key={m.id} m={m} onView={onView} />)}</ul>
        )}
      </section>

      <section className="tile" aria-label="Upcoming meetings">
        <div className="tile-head"><h2 className="tile-title"><Icon name="calendar" />Upcoming</h2>
          <span className="muted small">{upcoming.length} from today on</span></div>
        {upcoming.length === 0 ? <Empty>No upcoming meeting. Meetings appear here when a transcript or a meeting is dated today or later.</Empty> : (
          <ul className="list-rows">{upcoming.slice(0, 20).map((m) => <MeetingRow key={m.id} m={m} onView={onView} withDate />)}</ul>
        )}
      </section>
    </div>
  );
}

function MeetingRow({ m, onView, withDate }: { m: DocumentOut; onView: (id: string) => void; withDate?: boolean }) {
  const { ws } = useWs();
  return (
    <li className="mrow">
      {withDate && <span className="date-chip">{(m.meeting_date ?? "").slice(5, 10)}</span>}
      <button type="button" className="row-link" onClick={() => onView(m.id)}>
        <span className="grow">
          <span className="ellipsis">{m.title}</span>
          <span className="muted small ellipsis">{speakerNames(m.speakers) || "no speaker"}</span>
        </span>
        {m.theme_labels.slice(0, 2).map((l) => <span key={l} className="chip">{l}</span>)}
      </button>
      <Link className="small mrow-acc" to={`/w/${ws.slug}/accounts/${m.account_id}`}>{m.account_name}</Link>
    </li>
  );
}
