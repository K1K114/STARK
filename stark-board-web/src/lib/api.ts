const base = () =>
  (import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, "");

export type MoveHintPhase = "idle" | "from" | "to";

export type SquareLedInfo = {
  square: string;
  base_led: number;
  side_led: number;
  rgb: number[];
};

export type MoveHintResponse = {
  phase: MoveHintPhase;
  uci: string | null;
  from_square: SquareLedInfo | null;
  to_square: SquareLedInfo | null;
  elapsed_sec: number;
  cycle_from_sec: number;
  cycle_to_sec: number;
};

export type GameStateResponse = {
  fen: string;
  turn: "white" | "black";
  mode: string | null;
  human_color: "white" | "black" | null;
  is_human_turn: boolean | null;
  game_status?: string | null;
  lichess_moves?: string | null;
};

export type ConnectMode = "training" | "playing" | "lichess";

export type ConnectRequestBody = {
  mode: ConnectMode;
  human_color: "white" | "black";
  game_id?: string;
  token?: string;
};

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${base()}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`${r.status} ${path}: ${t.slice(0, 200)}`);
  }
  return r.json() as Promise<T>;
}

export function getMoveHint(): Promise<MoveHintResponse> {
  return j("/hardware/move_hint");
}

export function getGameState(): Promise<GameStateResponse | null> {
  return fetch(`${base()}/game_state`, { headers: { Accept: "application/json" } }).then(
    (r) => (r.ok ? (r.json() as Promise<GameStateResponse>) : null)
  );
}

/** POST /connect — starts / resets session (same body can be sent again for new game). */
export function postConnect(body: ConnectRequestBody): Promise<unknown> {
  return j("/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postConnectTraining(): Promise<unknown> {
  return postConnect({ mode: "training", human_color: "white" });
}

/** POST /connect playing — you vs LC0 on `human_color`; requires LC0 on server. */
export function postConnectPlaying(): Promise<unknown> {
  return postConnect({ mode: "playing", human_color: "white" });
}

/** POST /hardware/move_hint — LED strip hint only (not a chess move on the server board). */
export function postHint(uci: string): Promise<MoveHintResponse> {
  return j("/hardware/move_hint", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uci }),
  });
}

/** POST /hardware/move_hint — clears LED hint. */
export function clearHint(): Promise<MoveHintResponse> {
  return j("/hardware/move_hint", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clear: true }),
  });
}

export type MakeMoveResponse = {
  ok?: boolean;
  fen: string;
  training_feedback?: unknown;
  engine_reply?: { uci: string; fen: string } | null;
};

/** POST /make_move — applies UCI on server board; requires POST /connect first. */
export function postMakeMove(uci: string): Promise<MakeMoveResponse> {
  return j("/make_move", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uci }),
  });
}
