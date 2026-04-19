"""
StarkHacks 2026 — Autonomous Chess Board
Main game loop.

Usage:
    python main.py                                          # local Stockfish
    python main.py --server-url http://localhost:8000       # LC0 via STARK server
    python main.py --stub-gantry                            # develop without S3 connected
    python main.py --no-vision                              # skip CV (type moves manually)
    python main.py --stub-voice --no-vision --stub-gantry   # [VOICE] logs, no TTS / no CV
    python main.py --voice --reference-audio magnus.wav --stub-gantry --no-vision

Setup:
    1. pip install -r requirements.txt
    2. Calibrate camera:  cd ../chess-vision && python calibration/calibrate.py
    3. Train model:       cd ../chess-vision && python training/train.py
    4. Run:               python main.py
    5. (optional) Start server: cd ../server && uvicorn server.main:app --reload
"""

import sys
import os
import argparse
import chess
from contextlib import nullcontext

# Paths into sibling chess-vision repo (CV imports only when vision is enabled).
CV_REPO = os.path.join(os.path.dirname(__file__), "..", "chess-vision")


def _ensure_chess_vision_on_path() -> None:
    root = os.path.abspath(CV_REPO)
    if root not in sys.path:
        sys.path.insert(0, root)


from game.chess_engine import ChessEngine
from game.game_state import GameState
from game.graveyard import Graveyard
from hardware.gantry import Gantry, GantryStub
from hardware.voice import VoiceAnnouncer, VoiceAnnouncerStub, san_to_speech

# --- Paths (relative to stark-chess/) ---
CV_CALIBRATION = os.path.join(CV_REPO, "calibration", "calibration.json")
CV_MODEL = os.path.join(CV_REPO, "model", "best.pt")


# ---------------------------------------------------------------------------
# Server client — talks to server/main.py (FastAPI) over HTTP
# ---------------------------------------------------------------------------

class ServerClient:
    """HTTP client for the STARK FastAPI server (server/main.py).

    Connects as 'playing' mode: human submits moves, LC0 on the server replies.
    The server also sets /hardware/move_hint so the ESP32 LEDs light automatically.
    """

    def __init__(self, base_url: str):
        try:
            import requests as _r
        except ImportError as exc:
            raise ImportError(
                "requests is required for --server-url. "
                "Run: pip install requests"
            ) from exc
        self._r = _r
        self._base = base_url.rstrip("/")

    def connect(self, mode: str = "playing", human_color: str = "white") -> None:
        resp = self._r.post(
            f"{self._base}/connect",
            json={"mode": mode, "human_color": human_color},
            timeout=10,
        )
        resp.raise_for_status()
        print(f"  Connected to STARK server: {self._base} (mode={mode}, you={human_color})")

    def make_move(self, uci: str) -> str | None:
        """POST /make_move — submits human UCI; returns engine reply UCI or None on game over."""
        resp = self._r.post(
            f"{self._base}/make_move",
            json={"uci": uci},
            timeout=30,
        )
        resp.raise_for_status()
        er = resp.json().get("engine_reply")
        return er["uci"] if er else None

    def get_game_state(self) -> dict | None:
        """GET /game_state — returns fen, turn, mode, is_human_turn, game_status."""
        resp = self._r.get(f"{self._base}/game_state", timeout=5)
        if not resp.ok:
            return None
        return resp.json()

    def post_hint(self, uci: str) -> None:
        """POST /hardware/move_hint — lights from/to squares on ESP32 LEDs."""
        self._r.post(
            f"{self._base}/hardware/move_hint",
            json={"uci": uci},
            timeout=5,
        ).raise_for_status()

    def clear_hint(self) -> None:
        """POST /hardware/move_hint {clear: true} — turns off LED hint after gantry finishes."""
        self._r.post(
            f"{self._base}/hardware/move_hint",
            json={"clear": True},
            timeout=5,
        ).raise_for_status()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Autonomous chess board controller")
    p.add_argument("--stub-gantry", action="store_true", help="Use GantryStub instead of real S3")
    p.add_argument("--no-vision", action="store_true", help="Skip camera — type moves manually")
    p.add_argument("--camera", type=int, default=0, help="Webcam index")
    p.add_argument("--roboflow-key", default=os.environ.get("ROBOFLOW_API_KEY"),
                   help="Roboflow API key for hosted piece detection (or set ROBOFLOW_API_KEY env var)")
    p.add_argument("--stockfish", default=None, help="Path to Stockfish binary (local mode only)")
    p.add_argument("--skill", type=int, default=10, help="Stockfish skill level 0–20 (local mode only)")
    p.add_argument("--think-time", type=float, default=1.0, help="Seconds Stockfish thinks per move (local mode only)")
    p.add_argument(
        "--server-url",
        default=None,
        help="URL of the STARK FastAPI server (e.g. http://localhost:8000). "
             "When set, LC0 on the server drives engine moves instead of local Stockfish.",
    )
    p.add_argument("--debug-cv", action="store_true",
                   help="Show live board-view window with piece labels from last detection")
    p.add_argument("--voice", action="store_true", help="Enable VoxCPM voice announcements (reference .wav clone)")
    p.add_argument(
        "--reference-audio",
        default=None,
        help="Path to Magnus (or other) reference .wav for --voice",
    )
    p.add_argument("--stub-voice", action="store_true", help="Print [VOICE] lines instead of loading VoxCPM")
    args = p.parse_args()
    if args.voice and not args.stub_voice:
        if not args.reference_audio:
            p.error("--reference-audio is required with --voice (or use --stub-voice)")
        if not os.path.isfile(args.reference_audio):
            p.error(f"--reference-audio not found: {args.reference_audio}")
    return args


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def speak(voice, text: str) -> None:
    if voice:
        voice.say(text)


def get_human_move_from_keyboard(board, voice=None):
    """Fallback when --no-vision: type a UCI move like 'e2e4'."""
    while True:
        raw = input("  Your move (UCI, e.g. e2e4): ").strip()
        try:
            move = chess.Move.from_uci(raw)
            if board.is_legal(move):
                return move
            from_sq = raw[:2] if len(raw) >= 2 else "the correct square"
            speak(voice, f"Illegal move, please return the piece to {from_sq}")
            print("  Illegal move, try again.")
        except ValueError:
            speak(voice, "Invalid move format, try again.")
            print("  Invalid format, try again.")


def _get_frame(cap):
    ret, frame = cap.read()
    return frame if ret else None


def _get_yolo_snapshot(frame, piece_detector):
    if piece_detector is not None:
        return piece_detector.get_board_state(frame)
    return None


def _show_board_debug(cv2, frame, piece_detector, last_detections):
    if hasattr(piece_detector, "debug_board_view"):
        view = piece_detector.debug_board_view(frame, last_detections)
    else:
        view = frame
    cv2.imshow("STARK — Board View", view)
    cv2.waitKey(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    voice = None
    if args.stub_voice:
        voice = VoiceAnnouncerStub()
    elif args.voice:
        voice = VoiceAnnouncer(args.reference_audio)

    # --- Server client (optional; replaces local Stockfish when provided) ---
    server_client = None
    if args.server_url:
        server_client = ServerClient(args.server_url)
        server_client.connect(mode="playing", human_color="white")

    # --- Hardware setup ---
    GantryClass = GantryStub if args.stub_gantry else Gantry
    gantry = GantryClass()
    gantry.connect()

    # --- Vision setup (opencv only loaded when camera / vision is used) ---
    cap = None
    move_detector = None
    piece_detector = None
    calibration_data = None
    opencv = None

    if not args.no_vision:
        _ensure_chess_vision_on_path()
        import cv2

        opencv = cv2
        from calibration.calibrate import load_calibration
        from inference.board_state import BoardStateDetector
        from inference.detect import PieceDetector

        if not os.path.exists(CV_CALIBRATION):
            print(f"ERROR: calibration.json not found at {CV_CALIBRATION}")
            print("Run: cd ../chess-vision && python calibration/calibrate.py")
            sys.exit(1)

        calibration_data = load_calibration(CV_CALIBRATION)
        move_detector = BoardStateDetector(CV_CALIBRATION)
        print("Initialising local webcam…")
        cap = opencv.VideoCapture(args.camera)
        if not cap.isOpened():
            print("ERROR: Could not open webcam")
            sys.exit(1)

        if args.roboflow_key:
            from inference.detect import RoboflowDetector
            piece_detector = RoboflowDetector(args.roboflow_key, CV_CALIBRATION)
            print("Roboflow piece detector enabled.")
        elif os.path.exists(CV_MODEL):
            piece_detector = PieceDetector(CV_MODEL, CV_CALIBRATION)
            print("YOLOv8 model loaded (local).")
        else:
            print("No piece detector — move disambiguation disabled.")

    graveyard = Graveyard(calibration=calibration_data)
    if calibration_data and "graveyard_slots" in calibration_data:
        print("Graveyard CV positions loaded from calibration.")
    else:
        print("Graveyard running in software-only mode (no CV positions).")

    # --- Engine setup: local Stockfish or server (LC0) ---
    engine_kwargs = {}
    if args.stockfish:
        engine_kwargs["stockfish_path"] = args.stockfish

    # Use nullcontext when server drives moves so we skip the Stockfish process.
    engine_cm = (
        ChessEngine(skill_level=args.skill, **engine_kwargs)
        if server_client is None
        else nullcontext()
    )

    with engine_cm as engine:
        state = GameState()
        mode_label = f"server ({args.server_url})" if server_client else "Stockfish"
        print(f"\nGame started — human plays White | engine: {mode_label}\n")
        state.print_board()

        _last_detections = []   # updated each time piece_detector runs
        _pending_engine_uci: str | None = None  # set by server.make_move in human turn

        # Set initial reference frame
        if move_detector:
            frame = _get_frame(cap)
            if frame is not None:
                move_detector.set_reference(frame)

        # ---------------------------------------------------------------
        # Main game loop
        # ---------------------------------------------------------------
        while not state.is_over():
            human_move = None

            if state.turn == "white":
                # --- Human's turn ---
                print("Waiting for human move…")
                speak(voice, "Your move")

                if args.no_vision:
                    human_move = get_human_move_from_keyboard(state.board, voice=voice)
                else:
                    while human_move is None:
                        frame = _get_frame(cap)
                        if frame is None:
                            continue
                        move_str = move_detector.update(frame, gantry_moving=gantry.is_moving, board=state.board)

                        if args.debug_cv and frame is not None:
                            _show_board_debug(opencv, frame, piece_detector, _last_detections)

                        if move_str:
                            snapshot = None
                            if piece_detector is not None:
                                _last_detections = piece_detector.detect(frame)
                                snapshot = {d["square"]: d["piece"]
                                            for d in sorted(_last_detections,
                                                            key=lambda d: d["confidence"])}
                            result = ChessEngine.process_human_move(state.board, move_str, board_snapshot=snapshot)
                            if result["status"] == "illegal":
                                rt = result["return_to"]
                                speak(
                                    voice,
                                    f"Illegal move, please return the piece to {rt}",
                                )
                                print(f"  Detected '{move_str}' — illegal, returning piece to {rt}")
                                gantry.return_to_origin(rt)
                                if server_client is not None:
                                    try:
                                        server_client.post_hint(rt + rt)
                                    except Exception:
                                        pass
                            else:
                                human_move = result["move"]

                        # Q to quit (local webcam only)
                        if cap and opencv.waitKey(1) & 0xFF == ord("q"):
                            print("Quit signal received.")
                            gantry.close()
                            cap.release()
                            opencv.destroyAllWindows()
                            sys.exit(0)

                # If capture, tell human where to place the taken piece
                if state.board.is_capture(human_move):
                    captured = state.board.piece_at(human_move.to_square)
                    if captured:
                        slot = graveyard.get_slot_for(captured.color, captured.piece_type)
                        if slot:
                            graveyard.mark_occupied(slot, str(captured))
                            pname = chess.piece_name(captured.piece_type).title()
                            speak(
                                voice,
                                f"Place the captured {pname} in graveyard slot {graveyard.slot_label(slot)}",
                            )
                            print(f"\n  >>> Place the captured {pname} "
                                  f"in graveyard slot {graveyard.slot_label(slot)}")
                            print(f"      ({graveyard.slot_position_hint(slot)}) <<<\n")
                        else:
                            overflow_sq = graveyard.find_overflow_square(state.board, chess.square_name(human_move.to_square))
                            print(f"\n  >>> Graveyard full for this piece type!")
                            if overflow_sq:
                                speak(voice, f"Graveyard is full, place it on {overflow_sq}")
                                print(f"      Place it temporarily on {overflow_sq} — LED will flash. <<<\n")
                            else:
                                speak(voice, "Graveyard is full; place the piece off the board as directed.")

                state.apply_move(human_move, by="human")
                san = state.last_move().san
                speak(voice, f"You played {san_to_speech(san)}")
                print(f"  Human played: {san}")
                state.print_board()

                if state.is_over():
                    break

                # If server mode, get engine reply now (server applies human move + LC0 reply atomically)
                if server_client is not None:
                    print("Server computing LC0 response…")
                    speak(voice, "I'm thinking")
                    _pending_engine_uci = server_client.make_move(human_move.uci())

            else:
                # --- Engine's turn ---
                if server_client is not None:
                    # Engine move was already fetched at end of human turn above
                    engine_move_uci = _pending_engine_uci
                    _pending_engine_uci = None
                    if engine_move_uci is None:
                        break  # server returned no engine reply → game over
                    engine_move = chess.Move.from_uci(engine_move_uci)
                else:
                    print("Stockfish thinking…")
                    speak(voice, "I'm thinking")
                    engine_move = engine.get_best_move(state.board, time_limit=args.think_time)
                    if engine_move is None:
                        break

                if state.board.is_capture(engine_move):
                    captured = state.board.piece_at(engine_move.to_square)
                    if captured:
                        slot = graveyard.get_slot_for(captured.color, captured.piece_type)
                        if slot:
                            graveyard.mark_occupied(slot, str(captured))
                            pname = chess.piece_name(captured.piece_type).title()
                            speak(voice, f"I captured your {pname}")
                            print(f"  Captured {pname} → graveyard {graveyard.slot_label(slot)}")
                        else:
                            overflow_sq = graveyard.find_overflow_square(state.board, chess.square_name(engine_move.to_square))
                            if overflow_sq:
                                speak(voice, f"Graveyard is full, place it on {overflow_sq}")
                                print(f"  Graveyard full — overflow to {overflow_sq}. LED will flash.")
                            else:
                                speak(voice, "Graveyard is full; place the piece off the board as directed.")
                                print("  Graveyard full and no overflow square — piece dragged off board.")

                gantry.execute(engine_move, board=state.board)
                # Gantry physically completed the move — clear LED hint on server
                if server_client is not None:
                    try:
                        server_client.clear_hint()
                    except Exception:
                        pass
                state.apply_move(engine_move, by="engine")
                esan = state.last_move().san
                speak(voice, f"I play {san_to_speech(esan)}")
                print(f"  Engine played: {esan}")
                state.print_board()

                # Update move-detection reference after gantry finishes
                if move_detector:
                    frame = _get_frame(cap)
                    if frame is not None:
                        move_detector.set_reference(frame)
                        if piece_detector is not None:
                            snapshot = _get_yolo_snapshot(frame, piece_detector)
                            if snapshot:
                                graveyard.scan_with_cv(frame, piece_detector)

        # ---------------------------------------------------------------
        # Game over
        # ---------------------------------------------------------------
        print("\n" + "=" * 40)
        print("GAME OVER")
        outcome = state.outcome_message()
        print(outcome)
        print("=" * 40 + "\n")
        speak(voice, outcome)

        gantry.home()
        gantry.close()
        if cap:
            cap.release()
        if opencv is not None:
            opencv.destroyAllWindows()


if __name__ == "__main__":
    main()
