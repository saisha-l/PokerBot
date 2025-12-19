from typing import List, Dict, Tuple
from bot import Bot
from type.poker_action import PokerAction
from type.round_state import RoundStateClient
import random

# ======================================================
# CARD UTILITIES
# ======================================================

RANKS = '23456789TJQKA'
SUITS = 'shdc'


def build_deck(excluded: List[str]) -> List[str]:
    """Return a deck excluding known cards."""
    return [r + s for r in RANKS for s in SUITS if r + s not in excluded]


def hand_score(cards: List[str]) -> Tuple:
    """
    Lightweight 7-card hand evaluator for Monte Carlo comparison.
    Returns a tuple where higher is better.
    """
    ranks = sorted([RANKS.index(c[0]) for c in cards], reverse=True)
    suits = [c[1] for c in cards]

    rank_counts = {r: ranks.count(r) for r in set(ranks)}
    counts = sorted(rank_counts.values(), reverse=True)

    is_flush = max(suits.count(s) for s in set(suits)) >= 5

    unique = sorted(set(ranks), reverse=True)
    is_straight = any(
        unique[i] - unique[i + 4] == 4
        for i in range(len(unique) - 4)
    )

    if is_straight and is_flush:
        return (8, max(unique))
    if counts[0] == 4:
        return (7, )
    if counts[0] == 3 and counts[1] >= 2:
        return (6, )
    if is_flush:
        return (5, ranks)
    if is_straight:
        return (4, max(unique))
    if counts[0] == 3:
        return (3, )
    if counts[0] == 2 and counts[1] == 2:
        return (2, )
    if counts[0] == 2:
        return (1, )
    return (0, ranks)


# ======================================================
# BOT IMPLEMENTATION
# ======================================================

class SimplePlayer(Bot):
    def __init__(self):
        super().__init__()
        self.hand = []
        self.current_chips = 0
        self.big_blind_amount = 10
        self.all_players = []
        self.position = 0
        self.game_count = 0

    # --------------------------------------------------
    # GAME LIFECYCLE
    # --------------------------------------------------

    def on_start(
        self,
        starting_chips: int,
        player_hands: List[str],
        blind_amount: int,
        big_blind_player_id: int,
        small_blind_player_id: int,
        all_players: List[int]
    ):
        self.hand = player_hands
        self.current_chips = starting_chips
        self.big_blind_amount = blind_amount
        self.all_players = all_players
        self.game_count += 1

    def on_round_start(self, round_state: RoundStateClient, remaining_chips: int):
        self.current_chips = remaining_chips
        self.position = self.calculate_position(round_state)

    # --------------------------------------------------
    # POSITION & STACK
    # --------------------------------------------------

    def calculate_position(self, round_state: RoundStateClient) -> int:
        active = len(round_state.player_bets)
        if active <= 3:
            return 2
        return self.game_count % 3

    def get_stack_situation(self) -> str:
        bb = self.current_chips / self.big_blind_amount
        if bb <= 10:
            return "critical"
        elif bb <= 20:
            return "short"
        elif bb <= 40:
            return "medium"
        return "deep"

    # --------------------------------------------------
    # POT ODDS
    # --------------------------------------------------

    def get_my_bet(self, round_state: RoundStateClient) -> int:
        return round_state.player_bets.get(self.id, 0) or \
               round_state.player_bets.get(str(self.id), 0)

    def calculate_pot_odds(self, round_state: RoundStateClient) -> float:
        my_bet = self.get_my_bet(round_state)
        call_amt = round_state.current_bet - my_bet
        pot = round_state.pot + call_amt
        return call_amt / pot if pot > 0 else 1

    # --------------------------------------------------
    # MONTE CARLO EQUITY
    # --------------------------------------------------

    def monte_carlo_equity(
        self,
        hole_cards: List[str],
        board: List[str],
        iterations: int = 800
    ) -> float:
        wins = ties = 0
        num_opponents = max(1, len(self.all_players) - 1)

        known = hole_cards + board

        for _ in range(iterations):
            deck = build_deck(known)
            random.shuffle(deck)

            opponents = [
                [deck.pop(), deck.pop()]
                for _ in range(num_opponents)
            ]

            needed = 5 - len(board)
            sim_board = board + [deck.pop() for _ in range(needed)]

            my_score = hand_score(hole_cards + sim_board)
            opp_best = max(hand_score(o + sim_board) for o in opponents)

            if my_score > opp_best:
                wins += 1
            elif my_score == opp_best:
                ties += 1

        return (wins + 0.5 * ties) / iterations

    # --------------------------------------------------
    # MAIN DECISION
    # --------------------------------------------------

    def get_action(
        self,
        round_state: RoundStateClient,
        remaining_chips: int
    ) -> Tuple[PokerAction, int]:

        self.current_chips = remaining_chips
        my_bet = self.get_my_bet(round_state)
        call_amt = round_state.current_bet - my_bet
        pot_odds = self.calculate_pot_odds(round_state)
        stack = self.get_stack_situation()

        if call_amt > remaining_chips:
            call_amt = remaining_chips

        # PREFLOP (simple heuristic)
        if round_state.round_num == 1:
            if call_amt == 0:
                return PokerAction.CHECK, 0
            if pot_odds < 0.25:
                return PokerAction.CALL, call_amt
            return PokerAction.FOLD, 0

        # POSTFLOP (Monte Carlo)
        board = getattr(round_state, 'community_cards', [])
        if not board:
            return PokerAction.FOLD, 0

        equity = self.monte_carlo_equity(
            self.hand,
            board,
            iterations=600 if stack in ["critical", "short"] else 1000
        )

        if call_amt == 0:
            if equity > 0.65:
                bet = min(int(0.6 * round_state.pot), remaining_chips)
                return PokerAction.RAISE, bet
            return PokerAction.CHECK, 0

        if equity > pot_odds:
            if equity > 0.8:
                return PokerAction.RAISE, min(call_amt * 2, remaining_chips)
            return PokerAction.CALL, call_amt

        return PokerAction.FOLD, 0

    # --------------------------------------------------
    # ROUND / GAME END
    # --------------------------------------------------

    def on_end_round(self, round_state: RoundStateClient, remaining_chips: int):
        self.current_chips = remaining_chips

    def on_end_game(
        self,
        round_state: RoundStateClient,
        player_score: float,
        all_scores: dict,
        active_players_hands: dict
    ):
        print(f"Game finished. Final stack: {player_score}")
