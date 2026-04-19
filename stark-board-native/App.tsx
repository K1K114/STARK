import { useCallback, useEffect, useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import { StatusBar } from "expo-status-bar";

const VOID = "#0a0b0f";
const PANEL = "#12141c";
const COPPER = "#c87e4a";
const CYAN = "#00f0d4";
const EMBER = "#ff6b2c";
const MUTED = "#7a7488";
const TEXT = "#e8e4dc";

const FILES = "abcdefgh".split("");
const RANKS_VIS = [8, 7, 6, 5, 4, 3, 2, 1];

type MoveHintPhase = "idle" | "from" | "to";

type SquareLedInfo = {
  square: string;
  base_led: number;
  side_led: number;
  rgb: number[];
};

type MoveHintResponse = {
  phase: MoveHintPhase;
  uci: string | null;
  from_square: SquareLedInfo | null;
  to_square: SquareLedInfo | null;
};

function apiBase(): string {
  return process.env.EXPO_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8000";
}

async function fetchHint(): Promise<MoveHintResponse> {
  const r = await fetch(`${apiBase()}/hardware/move_hint`);
  if (!r.ok) throw new Error(String(r.status));
  return r.json() as Promise<MoveHintResponse>;
}

async function postJson(path: string, body: object): Promise<void> {
  const r = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(String(r.status));
}

function parseFenBoard(fen: string): (string | null)[][] {
  const placement = fen.split(" ")[0];
  const ranks = placement.split("/");
  const board: (string | null)[][] = [];
  for (let r = 0; r < 8; r++) {
    const row: (string | null)[] = [];
    for (const ch of ranks[r]) {
      if (ch >= "1" && ch <= "8") {
        for (let k = 0; k < parseInt(ch, 10); k++) row.push(null);
      } else row.push(ch);
    }
    board.push(row);
  }
  return board;
}

function squareAt(row: number, col: number): string {
  return FILES[col] + String(8 - row);
}

const GLYPH: Record<string, string> = {
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

function Led({
  on,
  rgb,
  size,
}: {
  on: boolean;
  rgb: readonly [number, number, number] | null;
  size: number;
}) {
  const [r, g, b] = on && rgb ? rgb : [26, 28, 36];
  return (
    <View
      style={[
        styles.led,
        {
          width: size,
          height: size,
          borderRadius: size * 0.25,
          backgroundColor: `rgb(${r},${g},${b})`,
          borderWidth: on ? 1 : 1,
          borderColor: on ? "rgba(255,255,255,0.35)" : "rgba(200,126,74,0.2)",
          shadowColor: on ? `rgb(${r},${g},${b})` : "#000",
          shadowOpacity: on ? 0.9 : 0.4,
          shadowRadius: on ? 10 : 2,
          shadowOffset: { width: 0, height: 0 },
          elevation: on ? 6 : 0,
        },
      ]}
    />
  );
}

export default function App() {
  const { width } = useWindowDimensions();
  const boardPx = Math.min(width - 56, 340);
  const cell = boardPx / 8;
  const ledS = Math.max(14, Math.min(20, cell * 0.45));

  const [fen] = useState(
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
  );
  const [hint, setHint] = useState<MoveHintResponse | null>(null);
  const [log, setLog] = useState("");

  const tick = useCallback(() => {
    fetchHint()
      .then(setHint)
      .catch((e) => setLog(String(e)));
  }, []);

  useEffect(() => {
    tick();
    const id = setInterval(tick, 400);
    return () => clearInterval(id);
  }, [tick]);

  const phase = hint?.phase ?? "idle";
  const activeSide =
    phase !== "idle"
      ? phase === "from"
        ? hint?.from_square?.side_led ?? null
        : hint?.to_square?.side_led ?? null
      : null;
  const activeFile =
    phase !== "idle"
      ? phase === "from"
        ? hint?.from_square?.base_led ?? null
        : hint?.to_square?.base_led ?? null
      : null;
  const activeRgb =
    phase !== "idle"
      ? phase === "from" && hint?.from_square
        ? ([hint.from_square.rgb[0], hint.from_square.rgb[1], hint.from_square.rgb[2]] as const)
        : hint?.to_square
          ? ([hint.to_square.rgb[0], hint.to_square.rgb[1], hint.to_square.rgb[2]] as const)
          : null
      : null;

  const board = parseFenBoard(fen);
  const hiFrom = phase === "from" && hint?.from_square;
  const hiTo = phase === "to" && hint?.to_square;

  return (
    <View style={styles.root}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.kicker}>STARK · MATRIX</Text>
        <Text style={styles.title}>Signal board</Text>
        <Text style={styles.sub}>
          Axis LEDs mirror strips: ranks 8→1 (side), files a→h (base). API: {apiBase()}
        </Text>

        <View style={[styles.boardRow, { marginTop: 18 }]}>
          <View style={[styles.rankAxis, { height: boardPx }]}>
            {RANKS_VIS.map((rk, visIdx) => {
              const sideLed = 7 - visIdx;
              const on = phase !== "idle" && activeSide === sideLed;
              return (
                <View key={rk} style={styles.rankCell}>
                  <Led on={on && !!activeRgb} rgb={activeRgb} size={ledS} />
                  <Text style={styles.rankLbl}>{rk}</Text>
                </View>
              );
            })}
          </View>

          <View style={[styles.grid, { width: boardPx, height: boardPx }]}>
            {Array.from({ length: 8 }, (_, row) =>
              Array.from({ length: 8 }, (_, col) => {
                const sq = squareAt(row, col);
                const p = board[row][col];
                const light = (row + col) % 2 === 0;
                const fromSq = hiFrom?.square === sq;
                const toSq = hiTo?.square === sq;
                return (
                  <View
                    key={sq}
                    style={[
                      styles.cell,
                      {
                        width: cell,
                        height: cell,
                        backgroundColor: light ? "rgba(232,228,220,0.08)" : "rgba(61,42,26,0.45)",
                        borderWidth: fromSq || toSq ? 2 : 1,
                        borderColor: fromSq ? EMBER : toSq ? CYAN : "rgba(200,126,74,0.15)",
                      },
                    ]}
                  >
                    <Text
                      style={{
                        fontSize: cell * 0.52,
                        color: p && p === p.toUpperCase() ? "#f5f2ea" : "#0d0c0b",
                      }}
                    >
                      {p ? GLYPH[p] ?? p : ""}
                    </Text>
                  </View>
                );
              })
            ).flat()}
          </View>
        </View>

        <View style={[styles.fileRow, { width: boardPx + 40, paddingLeft: 36 }]}>
          {FILES.map((f, i) => {
            const on = phase !== "idle" && activeFile === i;
            return (
              <View key={f} style={styles.fileCell}>
                <Text style={styles.fileLbl}>{f}</Text>
                <Led on={on && !!activeRgb} rgb={activeRgb} size={ledS} />
              </View>
            );
          })}
        </View>

        <View style={styles.btns}>
          <Pressable
            style={({ pressed }) => [styles.btn, pressed && { opacity: 0.85 }]}
            onPress={async () => {
              try {
                await postJson("/connect", { mode: "training", human_color: "white" });
                setLog("session ok");
              } catch (e) {
                setLog(String(e));
              }
            }}
          >
            <Text style={styles.btnTxt}>Forge session</Text>
          </Pressable>
          <Pressable
            style={({ pressed }) => [styles.btnGhost, pressed && { opacity: 0.85 }]}
            onPress={async () => {
              try {
                await postJson("/hardware/move_hint", { uci: "e2e4" });
                tick();
              } catch (e) {
                setLog(String(e));
              }
            }}
          >
            <Text style={styles.btnTxt}>Test e2e4</Text>
          </Pressable>
          <Pressable
            style={({ pressed }) => [styles.btnGhost, pressed && { opacity: 0.85 }]}
            onPress={async () => {
              try {
                await postJson("/hardware/move_hint", { clear: true });
                tick();
              } catch (e) {
                setLog(String(e));
              }
            }}
          >
            <Text style={styles.btnTxt}>Clear</Text>
          </Pressable>
        </View>

        <Text style={styles.telemetry}>{hint ? JSON.stringify(hint, null, 2) : "{}"}</Text>
        {log ? <Text style={styles.log}>{log}</Text> : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: VOID },
  scroll: { padding: 20, paddingBottom: 48, alignItems: "center" },
  kicker: {
    fontSize: 10,
    letterSpacing: 4,
    color: CYAN,
    textAlign: "center",
    marginBottom: 4,
  },
  title: {
    fontSize: 28,
    fontWeight: "800",
    color: TEXT,
    textAlign: "center",
  },
  sub: { color: MUTED, textAlign: "center", marginTop: 8, fontSize: 12, maxWidth: 320 },
  boardRow: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  rankAxis: { justifyContent: "space-between", paddingVertical: 4, paddingRight: 6 },
  rankCell: { flexDirection: "row", alignItems: "center", gap: 6 },
  rankLbl: { color: COPPER, fontSize: 12, fontWeight: "700", width: 12, textAlign: "right" },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    borderWidth: 1,
    borderColor: "rgba(200,126,74,0.35)",
    borderRadius: 10,
    overflow: "hidden",
    backgroundColor: PANEL,
  },
  cell: { alignItems: "center", justifyContent: "center" },
  fileRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 10 },
  fileCell: { alignItems: "center", gap: 4 },
  fileLbl: { color: COPPER, fontSize: 11, fontWeight: "700" },
  led: {},
  btns: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 20, justifyContent: "center" },
  btn: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "rgba(0,240,212,0.45)",
    backgroundColor: "rgba(0,240,212,0.12)",
  },
  btnGhost: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "rgba(200,126,74,0.35)",
    backgroundColor: "rgba(18,20,28,0.6)",
  },
  btnTxt: { color: TEXT, fontSize: 11, fontWeight: "700", letterSpacing: 1 },
  telemetry: {
    marginTop: 16,
    padding: 12,
    borderRadius: 8,
    backgroundColor: "#0d0e12",
    color: "#9dffb8",
    fontSize: 10,
    width: "100%",
    maxWidth: 360,
  },
  log: { color: MUTED, marginTop: 8, fontSize: 11 },
});
