type Props = {
  /** Which rank index 0–7 from bottom (rank1=0) is lit — same as API side_led. */
  activeSideLed: number | null;
  activeRgb: readonly [number, number, number] | null;
  phase: "idle" | "from" | "to";
};

function LedWell({
  active,
  rgb,
  label,
  vertical,
}: {
  active: boolean;
  rgb: readonly [number, number, number] | null;
  label: string;
  vertical: boolean;
}) {
  const [r, g, b] = rgb ?? [40, 42, 52];
  return (
    <div
      style={{
        display: "flex",
        flexDirection: vertical ? "row" : "column",
        alignItems: "center",
        gap: vertical ? 8 : 4,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: vertical ? 0 : 0.06,
        color: "var(--muted)",
        fontWeight: 600,
      }}
    >
      {vertical && (
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: 6,
            background: active ? `rgb(${r},${g},${b})` : "#1a1c24",
            border: active
              ? `1px solid rgba(255,255,255,0.35)`
              : "1px solid rgba(200,126,74,0.2)",
            boxShadow: active
              ? `0 0 18px rgb(${r},${g},${b}), inset 0 0 12px rgba(255,255,255,0.15)`
              : "inset 0 2px 6px rgba(0,0,0,0.5)",
            animation: active ? "pulse-glow 1.4s ease-in-out infinite" : "none",
          }}
        />
      )}
      <span style={{ minWidth: vertical ? 12 : 10, textAlign: "center", color: "var(--copper)" }}>
        {label}
      </span>
      {!vertical && (
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: 6,
            background: active ? `rgb(${r},${g},${b})` : "#1a1c24",
            border: active
              ? `1px solid rgba(255,255,255,0.35)`
              : "1px solid rgba(200,126,74,0.2)",
            boxShadow: active
              ? `0 0 18px rgb(${r},${g},${b}), inset 0 0 12px rgba(255,255,255,0.15)`
              : "inset 0 2px 6px rgba(0,0,0,0.5)",
            animation: active ? "pulse-glow 1.4s ease-in-out infinite" : "none",
          }}
        />
      )}
    </div>
  );
}

const FILES = "abcdefgh".split("");
/** Rank labels top → bottom on screen = 8 … 1 (chess diagram). */
const RANKS_VIS = [8, 7, 6, 5, 4, 3, 2, 1];

export function AxisLeds({ activeSideLed, activeRgb, phase }: Props) {
  const rgb = activeRgb ? ([activeRgb[0], activeRgb[1], activeRgb[2]] as const) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "stretch", gap: 10 }}>
        {/* Rank axis + LEDs: 8 down, label matches rank at that row */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            padding: "8px 0",
            minHeight: "min(72vmin, 420px)",
            borderRight: "1px solid var(--gridline)",
            paddingRight: 10,
          }}
        >
          {RANKS_VIS.map((rankLabel, visIdx) => {
            const sideLedForRow = 7 - visIdx;
            const active = phase !== "idle" && activeSideLed === sideLedForRow;
            return (
              <LedWell
                key={rankLabel}
                vertical
                label={String(rankLabel)}
                active={active && rgb !== null}
                rgb={active ? rgb : null}
              />
            );
          })}
        </div>
      </div>

      {/* File axis under board — rendered separately in parent; this is spacer for type export */}
    </div>
  );
}

export function FileLedRow({
  activeFile,
  activeRgb,
  phase,
}: {
  activeFile: number | null;
  activeRgb: readonly [number, number, number] | null;
  phase: "idle" | "from" | "to";
}) {
  const rgb = activeRgb ? ([activeRgb[0], activeRgb[1], activeRgb[2]] as const) : null;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(8, 1fr)",
        gap: 4,
        width: "min(72vmin, 420px)",
        marginTop: 6,
        paddingLeft: 38,
        boxSizing: "content-box",
      }}
    >
      {FILES.map((f, i) => {
        const active = phase !== "idle" && activeFile === i;
        return (
          <LedWell
            key={f}
            vertical={false}
            label={f}
            active={active && rgb !== null}
            rgb={active ? rgb : null}
          />
        );
      })}
    </div>
  );
}
