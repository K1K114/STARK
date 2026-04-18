"""
StarkHacks 2026 — Autonomous Chess Board
Main game loop.

Usage:
    python main.py                  # full hardware mode
    python main.py --stub-gantry    # develop without ESP32 connected
    python main.py --no-vision      # skip CV (type moves manually for testing)

Setup:
    1. pip install -r requirements.txt
    2. Calibrate camera:  cd ../chess-vision && python calibration/calibrate.py
    3. Train model:       cd ../chess-vision && python training/train.py
    4. Run:               python main.py
"""

import sys
import os
import argparse
import time
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
from hardware.gantry import Gantry, GantryStub

# --- Paths (relative to stark-chess/) ---
CV_CALIBRATION = os.path.join(CV_REPO, "calibration", "calibration.json")
CV_MODEL = os.path.join(CV_REPO, "model", "best.pt")


def parse_args():
    p = argparse.ArgumentParser(description="Autonomous chess board controller")
    p.add_argument("--stub-gantry", action="store_true", help="Use GantryStub instead of real ESP32")
    p.add_argument("--no-vision", action="store_true", help="Skip camera — type moves manually")
    p.add_argument("--camera", type=int, default=0, help="Webcam index (default 0)")
    p.add_argument("--stockfish", default=None, help="Path to Stockfish binary")
    p.add_argument("--skill", type=int, default=10, help="Stockfish skill level 0–20")
    p.add_argument("--think-time", type=float, default=1.0, help="Seconds Stockfish thinks per move")
    return p.parse_args()


def get_human_move_from_keyboard(board):
    """Fallback when --no-vision: type a UCI move like 'e2e4'."""
    while True:
        raw = input(f"  Your move (UCI, e.g. e2e4): ").strip()
        try:
            move = chess.Move.from_uci(raw)
            if board.is_legal(move):
                return move
            print("  Illegal move, try again.")
        except ValueError:
            print("  Invalid format, try again.")


def main():
    args = parse_args()

    # --- Hardware setup ---
    GantryClass = GantryStub if args.stub_gantry else Gantry
    gantry = GantryClass()
    gantry.connect()

    # --- Vision setup ---
    cap = None
    move_detector = None
    piece_detector = None

    if not args.no_vision:
        if not os.path.exists(CV_CALIBRATION):
            print(f"ERROR: calibration.json not found at {CV_CALIBRATION}")
            print("Run: cd ../chess-vision && python calibration/calibrate.py")
            sys.exit(1)

        print("Initialising camera…")
        cap = cv2.VideoCapture(args.camera)
        if not cap.isOpened():
            print("ERROR: Could not open webcam")
            sys.exit(1)

        move_detector = BoardStateDetector(CV_CALIBRATION)

        if os.path.exists(CV_MODEL):
            piece_detector = PieceDetector(CV_MODEL, CV_CALIBRATION)
            print("YOLOv8 model loaded.")
        else:
            print(f"WARNING: best.pt not found at {CV_MODEL} — piece confirmation disabled")

    # --- Game setup ---
    engine_kwargs = {}
    if args.stockfish:
        engine_kwargs["stockfish_path"] = args.stockfish

    with ChessEngine(skill_level=args.skill, **engine_kwargs) as engine:
        state = GameState()
        print("\nGame started — human plays White\n")
        state.print_board()

        # Set initial reference frame
        if move_detector and cap:
            ret, frame = cap.read()
            if ret:
                move_detector.set_reference(frame)

        # ---------------------------------------------------------------
        # Main game loop
        # ---------------------------------------------------------------
        while not state.is_over():
            human_move = None

            if state.turn == "white":
                # --- Human's turn ---
                print("Waiting for human move…")

                if args.no_vision:
                    human_move = get_human_move_from_keyboard(state.board)
                else:
                    # Poll camera until board_state_detector triggers
                    while human_move is None:
                        ret, frame = cap.read()
                        if not ret:
                            continue

                        move_str = move_detector.update(frame, gantry_moving=gantry.is_moving)
                        if move_str:
                            human_move = engine.parse_move(state.board, move_str)
                            if human_move is None:
                                print(f"  Detected '{move_str}' — not a legal move, waiting…")
                                # Don't update reference yet; keep watching

                        # Press Q to quit
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            print("Quit signal received.")
                            gantry.close()
                            if cap:
                                cap.release()
                            cv2.destroyAllWindows()
                            sys.exit(0)

                # Apply human move
                state.apply_move(human_move, by="human")
                print(f"  Human played: {state.last_move().san}")
                state.print_board()

                if state.is_over():
                    break

            else:
                # --- Engine's turn ---
                print("Stockfish thinking…")
                engine_move = engine.get_best_move(state.board, time_limit=args.think_time)
                if engine_move is None:
                    break

                # Apply move in game state first, then send to gantry
                # (gantry.execute needs the board BEFORE the move to detect captures)
                gantry.execute(engine_move, board=state.board)
                state.apply_move(engine_move, by="engine")
                print(f"  Engine played: {state.last_move().san}")
                state.print_board()

                # Update CV reference after gantry finishes
                if move_detector and cap:
                    ret, frame = cap.read()
                    if ret:
                        move_detector.set_reference(frame)

        # ---------------------------------------------------------------
        # Game over
        # ---------------------------------------------------------------
        print("\n" + "=" * 40)
        print("GAME OVER")
        print(state.outcome_message())
        print("=" * 40 + "\n")

        gantry.home()
        gantry.close()
        if cap:
            cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
