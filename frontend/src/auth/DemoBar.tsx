import { useState } from "react";
import { useLocation } from "react-router";
import { ErrorNote, useAction, useLoad } from "../ui";
import "./auth.css";
import { useAuth } from "./context";
import { demoApi } from "./demoApi";
import { currentIdentity, identityLabel, landingPath, sortIdentities } from "./demoLogic";

/** Top-bar pieces for a demo session: the yellow mark, "Viewing as" menu and Exit demo. */
export function DemoBar() {
  const { user, membership, signOut, setMe } = useAuth();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const ids = useLoad(() => (user?.is_demo ? demoApi.identities() : Promise.resolve([])), [user?.id]);
  const a = useAction();
  if (!user?.is_demo) return null;
  const list = sortIdentities(ids.data ?? []);
  const cur = currentIdentity(list, membership?.app_user_id, membership?.role);
  const slug = membership?.workspace_slug ?? "";
  const pick = (as: string, role: "admin" | "rep") => a.run(async () => {
    const me = await demoApi.start(as);
    setMe(me);
    setOpen(false);
    const s = me.memberships[0]?.workspace_slug ?? slug;
    // Reload so every cache and loaded page is rebuilt for the new identity.
    window.location.assign(landingPath(pathname, s, role));
  });
  return (
    <>
      <span className="demo-mark" title="The demo workspace is rebuilt every night">Demo · resets nightly</span>
      <div className="user-menu demo-view">
        <button type="button" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          Viewing as: {cur ? identityLabel(cur) : "…"} ▾
        </button>
        {open && (
          <div className="pop" role="menu">
            {list.map((i) => (
              <button key={i.as} type="button" role="menuitem" disabled={a.busy} aria-current={cur?.as === i.as ? "true" : undefined}
                onClick={() => void pick(i.as, i.role)}>{identityLabel(i)}</button>
            ))}
            <ErrorNote error={a.error ?? ids.error} />
          </div>
        )}
      </div>
      <button type="button" className="quiet" onClick={() => void signOut()}>Exit demo</button>
    </>
  );
}
