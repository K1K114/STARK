"""
StarkHacks 2026 — Autonomous Chess Board
Main game loop.

Usage:
    python main.py                           # local webcam, no YOLO
    python main.py --stub-gantry             # develop without S3 connected
    python main.py --no-vision               # skip CV (type moves manually)
    python main.py --p4-port /dev/tty.xxx    # P4 streams frames + runs inference
    python main.py --p4-port stub            # P4 stub for local dev
    python main.py --stub-voice --no-vision --stub-gantry   # [VOICE] logs, no TTS / no CV
    python main.py --voice --reference-audio magnus.wav --stub-gantry --no-vision

Setup:
    1. pip install -r requirements.txt
    2. Calibrate camera:  cd ../chess-vision && python calibration/calibrate.py
    3. Train model:       cd ../chess-vision && python training/train.py
    4. Run:               python main.py
"""

import sys
import os
import argparse
import cv2
import chess

# Reach into the sibling chess-vision repo for CV modules.
# Assumes repo layout: STARK/stark-chess/ and STARK/chess-vision/ are siblings.
CV_REPO = os.path.join(os.path.dirname(__file__), "..", "chess-vision")
sys.path.insert(0, os.path.abspath(CV_REPO))

from calibration.calibrate import load_calibration
from inference.board_state import BoardStateDetector
from inference.detect import PieceDetector

from game.chess_engine import ChessEngine
from game.game_state import GameState
from game.graveyard import Graveyard
from hardware.gantry import Gantry, GantryStub
from hardware.p4_camera import P4Camera, P4CameraStub
from hardware.voice import VoiceAnnouncer, VoiceAnnouncerStub, san_to_speech

# --- Paths (relative to stark-chess/) ---
CV_CALIBRATION = os.path.join(CV_REPO, "calibration", "calibration.json")
CV_MODEL = os.path.join(CV_REPO, "model", "best.pt")

# Flip to True once model is trained on your physical pieces.
# When True, YOLOv8 disambiguates moves where both orderings are legal.
# With --p4-port, inference runs on the P4 instead of locally.
USE_YOLO = False


def parse_args():
    p = argparse.ArgumentParser(description="Autonomous chess board controller")
    p.add_argument("--stub-gantry", action="store_true", help="Use GantryStub instead of real S3")
    p.add_argument("--no-vision", action="store_true", help="Skip camera — type moves manually")
    p.add_argument("--camera", type=int, default=0, help="Local webcam index (ignored when --p4-port is set)")
    p.add_argument("--p4-port", default=None,
                   help="Serial port for ESP32-P4 camera (e.g. /dev/tty.usbmodem1234). "
                        "Pass 'stub' to use P4CameraStub for local dev.")
    p.add_argument("--stockfish", default=None, help="Path to Stockfish binary")
    p.add_argument("--skill", type=int, default=10, help="Stockfish skill level 0–20")
    p.add_argument("--think-time", type=float, default=1.0, help="Seconds Stockfish thinks per move")
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


def _get_frame(cap, p4):
    """Read one frame from whichever source is active."""
    if p4 is not None:
        return p4.get_frame()
    ret, frame = cap.read()
    return frame if ret else None


def _get_yolo_snapshot(frame, p4, piece_detector):
    """Run YOLO on P4 or locally depending on what's connected."""
    if p4 is not None:
        return p4.infer()  # {square: piece_name} already
    if piece_detector is not None:
        return piece_detector.get_board_state(frame)
    return None


def main():
    args = parse_args()

    voice = None
    if args.stub_voice:
        voice = VoiceAnnouncerStub()
    elif args.voice:
        voice = VoiceAnnouncer(args.reference_audio)

    # --- Hardware setup ---
    GantryClass = GantryStub if args.stub_gantry else Gantry
    gantry = GantryClass()
    gantry.connect()

    # --- Vision setup ---
    cap = None
    p4 = None
    move_detector = None
    piece_detector = None
    calibration_data = None

    if not args.no_vision:
        if not os.path.exists(CV_CALIBRATION):
            print(f"ERROR: calibration.json not found at {CV_CALIBRATION}")
            print("Run: cd ../chess-vision && python calibration/calibrate.py")
            sys.exit(1)

        calibration_data = load_calibration(CV_CALIBRATION)

        if args.p4_port:
            # --- P4 path: camera lives on the P4, frames arrive over serial ---
            if args.p4_port == "stub":
                p4 = P4CameraStub()
                print("P4 camera: using stub (blank frames)")
            else:
                p4 = P4Camera(args.p4_port)
                print(f"P4 camera: connected on {args.p4_port}")
        else:
            # --- Local path: webcam plugged directly into laptop ---
            move_detector = BoardStateDetector(CV_CALIBRATION)
            print("Initialising local webcam…")
            cap = cv2.VideoCapture(args.camera)
            if not cap.isOpened():
                print("ERROR: Could not open webcam")
                sys.exit(1)

            if USE_YOLO:
                if os.path.exists(CV_MODEL):
                    piece_detector = PieceDetector(CV_MODEL, CV_CALIBRATION)
                    print("YOLOv8 model loaded (local).")
                else:
                    print(f"WARNING: best.pt not found at {CV_MODEL} — piece confirmation disabled")

    graveyard = Graveyard(calibration=calibration_data)
    if calibration_data and "graveyard_slots" in calibration_data:
        print("Graveyard CV positions loaded from calibration.")
    else:
        print("Graveyard running in software-only mode (no CV positions).")

    # --- Game setup ---
    engine_kwargs = {}
    if args.stockfish:
        engine_kwargs["stockfish_path"] = args.stockfish

    with ChessEngine(skill_level=args.skill, **engine_kwargs) as engine:
        state = GameState()
        print("\nGame started — human plays White\n")
        state.print_board()

        # Set initial reference frame
        if p4 is not None:
            p4.set_reference()
        elif move_detector:
            frame = _get_frame(cap, None)
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
                        if p4 is not None:
                            # P4 handles pixel diff + YOLO internally
                            move_str = p4.poll_move()
                            frame = None
                        else:
                            frame = _get_frame(cap, None)
                            if frame is None:
                                continue
                            move_str = move_detector.update(frame, gantry_moving=gantry.is_moving, board=state.board)

                        if move_str:
                            snapshot = None
                            if USE_YOLO and p4 is None:
                                snapshot = _get_yolo_snapshot(frame, None, piece_detector)
                            result = engine.process_human_move(state.board, move_str, board_snapshot=snapshot)
                            if result["status"] == "illegal":
                                rt = result["return_to"]
                                speak(
                                    voice,
                                    f"Illegal move, please return the piece to {rt}",
                                )
                                print(f"  Detected '{move_str}' — illegal, returning piece to {rt}")
                                gantry.return_to_origin(rt)
                            else:
                                human_move = result["move"]

                        # Q to quit (local webcam only)
                        if cap and cv2.waitKey(1) & 0xFF == ord("q"):
                            print("Quit signal received.")
                            gantry.close()
                            cap.release()
                            cv2.destroyAllWindows()
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

            else:
                # --- Engine's turn ---
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
                state.apply_move(engine_move, by="engine")
                esan = state.last_move().san
                speak(voice, f"I play {san_to_speech(esan)}")
                print(f"  Engine played: {esan}")
                state.print_board()

                # Update move-detection reference after gantry finishes
                if p4 is not None:
                    p4.set_reference()
                elif move_detector:
                    frame = _get_frame(cap, None)
                    if frame is not None:
                        move_detector.set_reference(frame)
                        if USE_YOLO:
                            snapshot = _get_yolo_snapshot(frame, None, piece_detector)
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
        if p4:
            p4.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
