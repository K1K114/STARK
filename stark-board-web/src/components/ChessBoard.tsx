import type { ReactElement } from "react";
import { parseFenBoard, pieceGlyph, squareAt } from "../lib/fen";

export type BoardInteraction = {
  selectedSquare: string | null;
  legalEmpty: Set<string>;
  legalCapture: Set<string>;
  lastMove: { from: string; to: string } | null;
  onSquareClick: (sq: string) => void;
};

type Props = {
  fen: string;
  highlightSquares: Set<string>;
  highlightFrom: boolean;
  /** When false, squares do not accept moves (server says not your turn). */
  interactive?: boolean;
} & BoardInteraction;

const cellLight = "rgba(232, 228, 220, 0.08)";
const cellDark = "rgba(61, 42, 26, 0.45)";

export function ChessBoard({
  fen,
  highlightSquares,
  highlightFrom,
  interactive = true,
  selectedSquare,
  legalEmpty,
  legalCapture,
  lastMove,
  onSquareClick,
}: Props) {
  const board = parseFenBoard(fen);

  const cells: ReactElement[] = [];
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 8; col++) {
      const sq = squareAt(row, col);
      const p = board[row][col];
      const light = (row + col) % 2 === 0;
      const hi = highlightSquares.has(sq);
      const sel = selectedSquare === sq;
      const last = lastMove && (lastMove.from === sq || lastMove.to === sq);
      const cap = legalCapture.has(sq);
      const leg = legalEmpty.has(sq);

      let border = `1px solid ${light ? "rgba(200,126,74,0.15)" : "rgba(0,0,0,0.35)"}`;
      if (hi) {
        border = highlightFrom ? "2px solid var(--ember)" : "2px solid var(--cyan)";
      } else if (sel) {
        border = "2px solid var(--ember)";
      } else if (cap) {
        border = "2px solid rgba(255,107,44,0.85)";
      } else if (leg) {
        border = "2px solid rgba(0,240,212,0.45)";
      }

      const lastWash = last
        ? lastMove!.to === sq
          ? "rgba(0,240,212,0.12)"
          : "rgba(255,107,44,0.1)"
        : undefined;

      cells.push(
        <button
          type="button"
          key={sq}
          title={sq}
          disabled={!interactive}
          onClick={() => {
            if (interactive) onSquareClick(sq);
          }}
          style={{
            position: "relative",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "clamp(1rem, 3.5vw, 1.65rem)",
            fontWeight: 600,
            background: lastWash
              ? `linear-gradient(180deg, ${lastWash}, ${light ? cellLight : cellDark})`
              : light
                ? cellLight
                : cellDark,
            border,
            borderRadius: 4,
            color: p && p === p.toUpperCase() ? "#f5f2ea" : "#0d0c0b",
            textShadow:
              p && p === p.toUpperCase() ? "0 0 12px rgba(0,240,212,0.25)" : "none",
            boxShadow: hi
              ? "inset 0 0 20px rgba(0,240,212,0.08)"
              : sel
                ? "inset 0 0 18px rgba(255,107,44,0.15)"
                : "none",
            transition: "border 0.15s, box-shadow 0.15s, transform 0.12s",
            cursor: interactive ? "pointer" : "not-allowed",
            opacity: interactive ? 1 : 0.88,
            padding: 0,
            margin: 0,
            outline: "none",
          }}
        >
          {leg && !p ? (
            <span
              aria-hidden
              style={{
                position: "absolute",
                width: "22%",
                height: "22%",
                borderRadius: "50%",
                background: "radial-gradient(circle, var(--cyan), rgba(0,240,212,0.15))",
                boxShadow: "0 0 12px rgba(0,240,212,0.6)",
              }}
            />
          ) : null}
          {cap && p ? (
            <span
              aria-hidden
              style={{
                position: "absolute",
                inset: 3,
                borderRadius: 4,
                border: "2px dashed rgba(255,107,44,0.75)",
                pointerEvents: "none",
              }}
            />
          ) : null}
          {pieceGlyph(p)}
        </button>
      );
    }
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(8, minmax(0, 1fr))",
        gridTemplateRows: "repeat(8, minmax(0, 1fr))",
        gap: 3,
        width: "min(72vmin, 420px)",
        height: "min(72vmin, 420px)",
        padding: 10,
        opacity: interactive ? 1 : 0.94,
        background:
          "linear-gradient(145deg, rgba(18,20,28,0.95), rgba(10,11,15,0.98))",
        border: "1px solid rgba(200, 126, 74, 0.35)",
        borderRadius: 12,
        boxShadow:
          "0 0 0 1px rgba(0,240,212,0.06), 0 24px 48px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.04)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          background:
            "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,240,212,0.02) 2px, rgba(0,240,212,0.02) 4px)",
          pointerEvents: "none",
        }}
      />
      {cells}
    </div>
  );
}
