import { AppearanceSection, YouSection } from "./SettingsPersonal";
import "./settings.css";

/** Personal settings for every signed-in member: who you are, and how the app looks in this browser. */
export function MySettingsPage() {
  return (
    <section className="stack">
      <div className="page-head">
        <div><h1>My settings</h1><p className="muted">Your profile and how the app looks for you.</p></div>
      </div>
      <div className="stack mysettings">
        <YouSection />
        <AppearanceSection />
      </div>
    </section>
  );
}
