import { useState } from "react";
import { useAuth } from "../auth";
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
  const { user, membership } = useAuth();
  return (
    <section className="tile">
      <h2 className="tile-title"><Icon name="user" />You</h2>
      {user ? (
        <dl className="facts">
          <dt>Name</dt><dd>{user.display_name}</dd>
          <dt>Email</dt><dd>{user.email}</dd>
          <dt>Role</dt><dd><Tag>{membership?.role ?? (user.is_admin ? "admin" : "rep")}</Tag></dd>
        </dl>
      ) : <p className="muted">Not signed in.</p>}
      <div className="note" role="note">
        <strong>Password.</strong> You cannot change it here yet. If you forgot it or want a new one, ask the
        workspace admin: they reset passwords in People and access.
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
