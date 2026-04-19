import type { CSSProperties } from "react";

const opts: { p: "q" | "r" | "b" | "n"; label: string; sub: string }[] = [
  { p: "q", label: "Q", sub: "reactor" },
  { p: "r", label: "R", sub: "rail" },
  { p: "b", label: "B", sub: "diode" },
  { p: "n", label: "N", sub: "pulse" },
];

type Props = {
  onPick: (p: "q" | "r" | "b" | "n") => void;
  onCancel: () => void;
};

export function PromotionPicker({ onPick, onCancel }: Props) {
  return (
    <div style={backdrop}>
      <div style={panel}>
        <p style={title}>Promote</p>
        <p style={sub}>Choose a piece — underpromotion is rare but allowed.</p>
        <div style={row}>
          {opts.map((o) => (
            <button
              key={o.p}
              type="button"
              style={btn}
              onClick={() => onPick(o.p)}
              title={o.sub}
            >
              <span style={glyph}>{o.label}</span>
              <span style={tiny}>{o.sub}</span>
            </button>
          ))}
        </div>
        <button type="button" style={cancel} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

const backdrop: CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 50,
  background: "rgba(5,6,10,0.72)",
  backdropFilter: "blur(6px)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 16,
};

const panel: CSSProperties = {
  background: "linear-gradient(160deg, rgba(18,20,28,0.98), rgba(10,11,15,0.99))",
  border: "1px solid rgba(0,240,212,0.35)",
  borderRadius: 14,
  padding: "1.25rem 1.5rem",
  maxWidth: 360,
  boxShadow: "0 0 40px rgba(0,240,212,0.12), 0 24px 64px rgba(0,0,0,0.6)",
};

const title: CSSProperties = {
  fontFamily: "var(--font-display)",
  fontWeight: 800,
  fontSize: "1.25rem",
  margin: "0 0 0.35rem",
  color: "var(--copper)",
};

const sub: CSSProperties = {
  margin: "0 0 1rem",
  fontSize: 12,
  color: "var(--muted)",
  lineHeight: 1.45,
};

const row: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, 1fr)",
  gap: 8,
};

const btn: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 4,
  padding: "12px 8px",
  borderRadius: 10,
  border: "1px solid rgba(200,126,74,0.4)",
  background: "rgba(10,11,15,0.6)",
  color: "var(--text)",
  cursor: "pointer",
  fontFamily: "var(--font-mono)",
};

const glyph: CSSProperties = {
  fontSize: "1.5rem",
  fontWeight: 700,
  color: "var(--cyan)",
};

const tiny: CSSProperties = {
  fontSize: 9,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--muted)",
};

const cancel: CSSProperties = {
  marginTop: 12,
  width: "100%",
  padding: "8px 12px",
  borderRadius: 8,
  border: "1px solid rgba(200,126,74,0.25)",
  background: "transparent",
  color: "var(--muted)",
  cursor: "pointer",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
};
