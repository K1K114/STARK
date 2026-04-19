const FILES = "abcdefgh";

export function parseFenBoard(fen: string): (string | null)[][] {
  const placement = fen.split(" ")[0];
  const ranks = placement.split("/");
  const board: (string | null)[][] = [];
  for (let r = 0; r < 8; r++) {
    const row: (string | null)[] = [];
    for (const ch of ranks[r]) {
      if (ch >= "1" && ch <= "8") {
        for (let k = 0; k < parseInt(ch, 10); k++) row.push(null);
      } else {
        row.push(ch);
      }
    }
    board.push(row);
  }
  return board;
}

export function squareAt(row: number, col: number): string {
  return FILES[col] + String(8 - row);
}

const UNICODE: Record<string, string> = {
  p: "\u265f",
  n: "\u265e",
  b: "\u265d",
  r: "\u265c",
  q: "\u265b",
  k: "\u265a",
  P: "\u2659",
  N: "\u2658",
  B: "\u2657",
  R: "\u2656",
  Q: "\u2655",
  K: "\u2654",
};

export function pieceGlyph(p: string | null): string {
  if (!p) return "";
  return UNICODE[p] ?? p;
}
