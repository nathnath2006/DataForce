import { useState } from "react";
import { useWs } from "../context";
import { Icon } from "../icons";
import { applyAppearance, readAppearance, saveAppearance, type Appearance } from "../appearance";
import { setThemeChoice, useThemeChoice, type ThemeChoice } from "../theme";
import { Tag } from "../ui";

/** Segmented control: one choice out of a few. */
function Seg<V extends string>(props: { label: string; value: V; options: [V, string][]; onChange: (v: V) => void }) {
  return (
    <div className="pref">
      <span className="pref-label">{props.label}</span>
      <div className="seg" role="group" aria-label={props.label}>
        {props.options.map(([v, l]) => (
          <button key={v} type="button" aria-pressed={props.value === v} onClick={() => props.onChange(v)}>{l}</button>
        ))}
      </div>
    </div>
  );
}

export function YouSection() {
  const { users, actingAs } = useWs();
  const me = users.find((u) => u.id === actingAs) ?? null;
  return (
    <section className="tile">
      <h2 className="tile-title"><Icon name="user" />You</h2>
      {me ? (
        <dl className="facts">
          <dt>Name</dt><dd>{me.display_name}</dd>
          <dt>Email</dt><dd>{me.email ?? "—"}</dd>
          <dt>Role</dt><dd><Tag>{me.role}</Tag></dd>
        </dl>
      ) : <p className="muted">Nobody is selected under “Acting as” (top right).</p>}
      <div className="note" role="note">
        <strong>Password.</strong> There is no login yet: DataForce runs on this computer only and “Acting as” is a
        label. Each person gets an email and password, and can change it here, when login arrives (milestone M3b).
      </div>
    </section>
  );
}

export function AppearanceSection() {
  const theme = useThemeChoice();
  const [a, setA] = useState<Appearance>(readAppearance);
  const update = (patch: Partial<Appearance>) => {
    const next = { ...a, ...patch };
    setA(next); saveAppearance(next); applyAppearance(next);
  };
  return (
    <section className="tile">
      <h2 className="tile-title"><Icon name="palette" />Appearance</h2>
      <p className="muted small">Saved in this browser only. They change how the app looks, never what it computes.</p>
      <div className="prefs">
        <Seg<ThemeChoice> label="Theme" value={theme} onChange={setThemeChoice}
          options={[["system", "System"], ["light", "Light"], ["dark", "Dark"]]} />
        <Seg label="Density" value={a.density} onChange={(density) => update({ density })}
          options={[["comfortable", "Comfortable"], ["compact", "Compact"]]} />
        <Seg label="Text size" value={a.text} onChange={(text) => update({ text })}
          options={[["standard", "Standard"], ["large", "Large"]]} />
        <Seg label="Motion" value={a.motion} onChange={(motion) => update({ motion })}
          options={[["system", "Follow the system"], ["reduced", "Reduced"]]} />
      </div>
    </section>
  );
}

export function MailSection() {
  return (
    <section className="tile">
      <h2 className="tile-title"><Icon name="mail" />Your mailbox</h2>
      <Tag kind="mute">not available yet</Tag>
      <p>
        Each person will connect their own mailbox here (Gmail or Outlook, read-only), not the admin for
        everyone. It needs login first, so that a mailbox belongs to one person and nobody else can read it.
      </p>
      <ul className="small muted mail-plan">
        <li>Only emails exchanged with addresses of your CRM contacts are kept; everything else is skipped.</li>
        <li>Each kept email is filed under its contact, account and open deal, with the same evidence rules as meetings.</li>
        <li>You can disconnect at any time, which deletes the token and the copied emails.</li>
      </ul>
    </section>
  );
}
