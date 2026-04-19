import { Chess } from "chess.js";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  clearHint,
  getGameState,
  getMoveHint,
  postConnectPlaying,
  postConnectTraining,
  postHint,
  postMakeMove,
  type GameStateResponse,
  type MoveHintResponse,
} from "./lib/api";
import { AxisLeds, FileLedRow } from "./components/AxisLeds";
import { ChessBoard } from "./components/ChessBoard";
import { PromotionPicker } from "./components/PromotionPicker";

const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

function usePoll(intervalMs: number, fn: () => void) {
  useEffect(() => {
    fn();
    const t = setInterval(fn, intervalMs);
    return () => clearInterval(t);
  }, [fn, intervalMs]);
}

function uciFromVerbose(m: { from: string; to: string; promotion?: string }) {
  return m.from + m.to + (m.promotion ?? "");
}

export default function App() {
  const chess = useMemo(() => new Chess(), []);
  const [fen, setFen] = useState(START_FEN);
  const fenRef = useRef(fen);
  fenRef.current = fen;
  const [hint, setHint] = useState<MoveHintResponse | null>(null);
  const [snapshot, setSnapshot] = useState<GameStateResponse | null>(null);
  const [status, setStatus] = useState<string>("");
  const [apiBase] = useState(() => import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000");
  const [sessionActive, setSessionActive] = useState(false);

  /** Training: server accepts any legal move — keep UI in sync. Playing: only when it's your color. */
  const canPlay =
    sessionActive &&
    snapshot !== null &&
    (snapshot.mode === "training" || snapshot.is_human_turn === true);

  const [selectedSquare, setSelectedSquare] = useState<string | null>(null);
  const [lastMove, setLastMove] = useState<{ from: string; to: string } | null>(null);
  const [pendingPromotion, setPendingPromotion] = useState<{ from: string; to: string } | null>(
    null
  );

  useEffect(() => {
    chess.load(fen);
  }, [fen, chess]);

  useEffect(() => {
    if (!canPlay) {
      setSelectedSquare(null);
      setPendingPromotion(null);
    }
  }, [canPlay]);

  const tick = useCallback(async () => {
    try {
      const gs = await getGameState();
      if (gs?.fen) {
        setSnapshot(gs);
        setFen(gs.fen);
        setSessionActive(true);
      } else {
        setSnapshot(null);
        setSessionActive(false);
      }
    } catch {
      setSnapshot(null);
      setSessionActive(false);
    }
    try {
      const h = await getMoveHint();
      setHint(h);
    } catch {
      setHint(null);
    }
  }, []);

  usePoll(380, tick);

  const { legalEmpty, legalCapture } = useMemo(() => {
    const empty = new Set<string>();
    const cap = new Set<string>();
    if (!canPlay || !selectedSquare) return { legalEmpty: empty, legalCapture: cap };
    const moves = chess.moves({ square: selectedSquare as never, verbose: true });
    for (const m of moves) {
      const isCap =
        Boolean(m.captured) ||
        (typeof m.flags === "string" && m.flags.includes("e"));
      if (isCap) cap.add(m.to);
      else empty.add(m.to);
    }
    return { legalEmpty: empty, legalCapture: cap };
  }, [chess, selectedSquare, canPlay]);

  const submitUci = useCallback(
    async (uci: string) => {
      try {
        const res = await postMakeMove(uci);
        const newFen = res.engine_reply?.fen ?? res.fen;
        setFen(newFen);
        if (res.engine_reply?.uci) {
          const u = res.engine_reply.uci;
          setLastMove({ from: u.slice(0, 2), to: u.slice(2, 4) });
        } else {
          setLastMove({ from: uci.slice(0, 2), to: uci.slice(2, 4) });
        }
        setSelectedSquare(null);
        setPendingPromotion(null);
        setStatus(
          res.engine_reply
            ? `OK — POST /make_move then engine_reply ${res.engine_reply.uci}`
            : `OK — POST /make_move { "uci": "${uci}" }`
        );
        tick();
      } catch (e) {
        setStatus(String(e));
        chess.load(fenRef.current);
      }
    },
    [tick, chess]
  );

  const onSquareClick = useCallback(
    (sq: string) => {
      if (pendingPromotion) return;
      if (!sessionActive) {
        setStatus("Call POST /connect first — then POST /make_move from the board.");
        return;
      }
      if (!canPlay) {
        setStatus(
          `GET /game_state → mode=${snapshot?.mode} is_human_turn=${String(snapshot?.is_human_turn)} — cannot POST /make_move now.`
        );
        return;
      }

      const turn = chess.turn();
      const at = chess.get(sq as never);

      if (!selectedSquare) {
        if (at && at.color === turn) {
          setSelectedSquare(sq);
          setStatus(`${turn === "w" ? "White" : "Black"} · ${sq}`);
        }
        return;
      }

      if (selectedSquare === sq) {
        setSelectedSquare(null);
        setStatus("");
        return;
      }

      const from = selectedSquare;
      if (at && at.color === turn) {
        setSelectedSquare(sq);
        setStatus(`${turn === "w" ? "White" : "Black"} · ${sq}`);
        return;
      }

      const candidates = chess.moves({ square: from as never, verbose: true }).filter((m) => m.to === sq);
      if (!candidates.length) {
        setStatus("Illegal trace — try another square.");
        return;
      }

      const promotions = candidates.filter((m) => m.promotion);
      if (promotions.length > 1) {
        setPendingPromotion({ from, to: sq });
        return;
      }

      const pick = promotions[0] ?? candidates[0];
      void submitUci(uciFromVerbose(pick));
    },
    [canPlay, chess, pendingPromotion, selectedSquare, sessionActive, snapshot, submitUci]
  );

  const highlights = new Set<string>();
  let highlightFrom = true;
  if (hint && hint.phase !== "idle" && hint.from_square && hint.to_square) {
    if (hint.phase === "from") {
      highlights.add(hint.from_square.square);
      highlightFrom = true;
    } else {
      highlights.add(hint.to_square.square);
      highlightFrom = false;
    }
  }

  const activeFile =
    hint && hint.phase !== "idle"
      ? hint.phase === "from"
        ? hint.from_square?.base_led ?? null
        : hint.to_square?.base_led ?? null
      : null;
  const activeSide =
    hint && hint.phase !== "idle"
      ? hint.phase === "from"
        ? hint.from_square?.side_led ?? null
        : hint.to_square?.side_led ?? null
      : null;
  const activeRgb =
    hint && hint.phase !== "idle"
      ? hint.phase === "from" && hint.from_square
        ? ([hint.from_square.rgb[0], hint.from_square.rgb[1], hint.from_square.rgb[2]] as const)
        : hint.to_square
          ? ([hint.to_square.rgb[0], hint.to_square.rgb[1], hint.to_square.rgb[2]] as const)
          : null
      : null;

  const turnLabel = snapshot?.turn ?? (chess.turn() === "w" ? "white" : "black");
  const humanColor = snapshot?.human_color ?? "—";
  const modeLabel = snapshot?.mode ?? "—";
  const humanTurnLabel =
    snapshot?.is_human_turn === true
      ? "you may POST /make_move"
      : snapshot?.is_human_turn === false
        ? "observe / engine"
        : "—";

  return (
    <div
      style={{
        minHeight: "100%",
        position: "relative",
        zIndex: 1,
        padding: "clamp(1rem, 4vw, 2rem)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "1.25rem",
      }}
    >
      {pendingPromotion ? (
        <PromotionPicker
          onCancel={() => {
            setPendingPromotion(null);
            setSelectedSquare(null);
          }}
          onPick={(p) => {
            const { from, to } = pendingPromotion;
            void submitUci(from + to + p);
          }}
        />
      ) : null}

      <header style={{ textAlign: "center", maxWidth: 640 }}>
        <p
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: "0.35em",
            color: "var(--cyan)",
            margin: "0 0 0.35rem",
            textTransform: "uppercase",
          }}
        >
          stark / matrix
        </p>
        <h1
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 800,
            fontSize: "clamp(1.75rem, 5vw, 2.75rem)",
            margin: 0,
            lineHeight: 1.05,
            background: "linear-gradient(105deg, var(--text), var(--copper) 55%, var(--cyan))",
            WebkitBackgroundClip: "text",
            color: "transparent",
          }}
        >
          Signal board
        </h1>
        <p style={{ color: "var(--muted)", fontSize: 13, marginTop: "0.6rem", lineHeight: 1.55 }}>
          FEN and turn always follow <code style={{ color: "var(--cyan)" }}>GET /game_state</code>.{" "}
          <strong>Training</strong>: any legal move is sent (matches server).{" "}
          <strong>Playing</strong>: clicks only when{" "}
          <code style={{ color: "var(--cyan)" }}>is_human_turn</code> is true; response may include LC0{" "}
          <code style={{ color: "var(--cyan)" }}>engine_reply</code>. LEDs follow{" "}
          <code style={{ color: "var(--cyan)" }}>GET /hardware/move_hint</code>.
        </p>
        <div
          style={{
            marginTop: 10,
            display: "inline-flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 6,
            padding: "8px 16px",
            borderRadius: 12,
            border: "1px solid rgba(0,240,212,0.25)",
            background: "rgba(10,11,15,0.65)",
            fontSize: 11,
            letterSpacing: "0.06em",
            color: sessionActive ? "var(--cyan)" : "var(--muted)",
            maxWidth: 420,
            textAlign: "center",
          }}
        >
          <span>
            <strong>session</strong> {sessionActive ? "active" : "inactive"} ·{" "}
            <strong>mode</strong> {modeLabel} · <strong>human_color</strong> {humanColor}
          </span>
          <span>
            <strong>turn</strong> {turnLabel} · <strong>is_human_turn</strong>{" "}
            {String(snapshot?.is_human_turn)} → {humanTurnLabel}
          </span>
        </div>
      </header>

      <div style={{ display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 12 }}>
        <AxisLeds
          phase={hint?.phase ?? "idle"}
          activeSideLed={activeSide}
          activeRgb={activeRgb}
        />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <ChessBoard
            fen={fen}
            highlightSquares={highlights}
            highlightFrom={highlightFrom}
            interactive={canPlay}
            selectedSquare={selectedSquare}
            legalEmpty={legalEmpty}
            legalCapture={legalCapture}
            lastMove={lastMove}
            onSquareClick={onSquareClick}
          />
          <FileLedRow
            phase={hint?.phase ?? "idle"}
            activeFile={activeFile}
            activeRgb={activeRgb}
          />
        </div>
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          justifyContent: "center",
          alignItems: "stretch",
        }}
      >
        <button
          type="button"
          title='Body: { "mode": "training", "human_color": "white" } — call again to reset FEN to start.'
          onClick={async () => {
            try {
              await postConnectTraining();
              setSessionActive(true);
              setSelectedSquare(null);
              setLastMove(null);
              setPendingPromotion(null);
              setStatus('OK — POST /connect (training)');
              tick();
            } catch (e) {
              setSessionActive(false);
              setSnapshot(null);
              setStatus(String(e));
            }
          }}
          style={btnPrimary}
        >
          <span style={{ display: "block", fontSize: 10, opacity: 0.85, marginBottom: 2 }}>
            POST /connect
          </span>
          <span style={{ fontSize: 11 }}>mode=training · human_color=white</span>
        </button>
        <button
          type="button"
          title='Body: { "mode": "playing", "human_color": "white" } — requires LC0 on server; POST /make_move only on your turn.'
          onClick={async () => {
            try {
              await postConnectPlaying();
              setSessionActive(true);
              setSelectedSquare(null);
              setLastMove(null);
              setPendingPromotion(null);
              setStatus('OK — POST /connect (playing)');
              tick();
            } catch (e) {
              setSessionActive(false);
              setSnapshot(null);
              setStatus(String(e));
            }
          }}
          style={btnGhost}
        >
          <span style={{ display: "block", fontSize: 10, opacity: 0.85, marginBottom: 2 }}>
            POST /connect
          </span>
          <span style={{ fontSize: 11 }}>mode=playing · human_color=white</span>
        </button>
        <button
          type="button"
          title='Body: { "uci": "e2e4" } — LED hint only; does not change chess position.'
          onClick={async () => {
            try {
              await postHint("e2e4");
              setStatus('OK — POST /hardware/move_hint { "uci": "e2e4" }');
            } catch (e) {
              setStatus(String(e));
            }
          }}
          style={btnGhost}
        >
          <span style={{ display: "block", fontSize: 10, opacity: 0.85, marginBottom: 2 }}>
            POST /hardware/move_hint
          </span>
          <span style={{ fontSize: 11 }}>{`{ "uci": "e2e4" }`}</span>
        </button>
        <button
          type="button"
          title='Body: { "clear": true }'
          onClick={async () => {
            try {
              await clearHint();
              setStatus('OK — POST /hardware/move_hint { "clear": true }');
            } catch (e) {
              setStatus(String(e));
            }
          }}
          style={btnGhost}
        >
          <span style={{ display: "block", fontSize: 10, opacity: 0.85, marginBottom: 2 }}>
            POST /hardware/move_hint
          </span>
          <span style={{ fontSize: 11 }}>{`{ "clear": true }`}</span>
        </button>
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          justifyContent: "center",
          width: "100%",
          maxWidth: 900,
        }}
      >
        <pre
          style={{
            flex: "1 1 280px",
            margin: 0,
            padding: 14,
            borderRadius: 10,
            background: "rgba(10,11,15,0.85)",
            border: "1px solid rgba(200,126,74,0.2)",
            color: "#f0d4a8",
            fontSize: 10,
            lineHeight: 1.45,
            overflow: "auto",
            maxHeight: 220,
          }}
        >
          {snapshot ? JSON.stringify(snapshot, null, 2) : "// GET /game_state (no session)"}
        </pre>
        <pre
          style={{
            flex: "1 1 280px",
            margin: 0,
            padding: 14,
            borderRadius: 10,
            background: "rgba(10,11,15,0.85)",
            border: "1px solid rgba(0,240,212,0.12)",
            color: "#9dffb8",
            fontSize: 10,
            lineHeight: 1.45,
            overflow: "auto",
            maxHeight: 220,
          }}
        >
          {hint ? JSON.stringify(hint, null, 2) : "// GET /hardware/move_hint"}
        </pre>
      </div>
      {status && (
        <p style={{ margin: 0, fontSize: 12, color: "var(--muted)" }}>
          {status} · <code style={{ color: "var(--cyan)" }}>{apiBase}</code>
        </p>
      )}
    </div>
  );
}

const btnPrimary: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  fontWeight: 600,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  padding: "10px 18px",
  borderRadius: 8,
  border: "1px solid rgba(0,240,212,0.45)",
  background: "linear-gradient(165deg, rgba(0,240,212,0.2), rgba(18,20,28,0.9))",
  color: "var(--text)",
  cursor: "pointer",
};

const btnGhost: CSSProperties = {
  ...btnPrimary,
  border: "1px solid rgba(200,126,74,0.35)",
  background: "rgba(18,20,28,0.6)",
};
