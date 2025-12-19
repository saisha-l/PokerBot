from typing import List, Dict, Tuple, Optional
from bot import Bot
from type.poker_action import PokerAction
from type.round_state import RoundStateClient
import random

class SimplePlayer(Bot):
    def __init__(self):
        super().__init__()
        self.hand = []
        self.starting_chips = 1000
        self.current_chips = 1000
        self.big_blind_amount = 10
        self.small_blind_amount = 5
        self.game_count = 0
        self.all_players = []
        self.position = 0
        self.total_games_played = 0
        
        # Opponent tracking for exploitation
        self.opponent_stats = {}
        self.game_history = []
        
        # Tournament awareness
        self.blinds_increased = False
        self.late_tournament = False

    def on_start(self, starting_chips: int, player_hands: List[str], blind_amount: int, 
                 big_blind_player_id: int, small_blind_player_id: int, all_players: List[int]):
        """Called at the start of each game"""
        self.hand = player_hands
        self.starting_chips = starting_chips
        self.current_chips = starting_chips
        self.big_blind_amount = blind_amount
        self.small_blind_amount = blind_amount // 2
        self.all_players = all_players
        self.game_count += 1
        
        # Initialize opponent tracking
        for player_id in all_players:
            if player_id != self.id and player_id not in self.opponent_stats:
                self.opponent_stats[player_id] = {
                    'hands_played': 0,
                    'vpip': 0,  # Voluntarily put money in pot
                    'aggression': 0,
                    'fold_to_aggression': 0,
                    'showdowns_won': 0,
                    'total_showdowns': 0
                }

    def on_round_start(self, round_state: RoundStateClient, remaining_chips: int):
        """Called at the start of each betting round"""
        self.current_chips = remaining_chips
        self.position = self.calculate_position(round_state)
        
        # Detect if we're in late tournament (blinds increased or low stack)
        stack_bb = remaining_chips / self.big_blind_amount if self.big_blind_amount > 0 else 50
        self.late_tournament = stack_bb < 20 or self.game_count > 50

    def calculate_position(self, round_state: RoundStateClient) -> int:
        """Calculate position: 0=early, 1=middle, 2=late (button/cutoff)"""
        # In 6-handed, positions are roughly:
        # Early: UTG, UTG+1 (positions 0-1)
        # Middle: MP, HJ (positions 2-3) 
        # Late: CO, BTN (positions 4-5)
        
        # Since we don't have exact position info, estimate based on betting order
        # This is a simplified approach - in real tournament would track dealer button
        active_players = len([p for p in round_state.player_bets.keys() if str(p).isdigit()])
        
        if active_players <= 3:
            return 2  # Late position in short-handed
        elif self.game_count % 3 == 0:
            return 0  # Early
        elif self.game_count % 3 == 1:
            return 1  # Middle
        else:
            return 2  # Late

    def get_preflop_hand_strength(self, hole_cards: List[str]) -> float:
        """Advanced preflop hand evaluation optimized for 6-handed play"""
        if not hole_cards or len(hole_cards) != 2:
            return 0.2
            
        card1, card2 = hole_cards
        rank1, suit1 = card1[0], card1[1]
        rank2, suit2 = card2[0], card2[1]
        
        # Rank values for calculations
        rank_values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, 
                      '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
        
        val1, val2 = rank_values[rank1], rank_values[rank2]
        high_card = max(val1, val2)
        low_card = min(val1, val2)
        suited = suit1 == suit2
        gap = high_card - low_card
        
        # Premium pairs (AA-TT)
        if val1 == val2:
            if val1 >= 13:  # AA, KK
                return 0.95
            elif val1 >= 11:  # QQ, JJ
                return 0.85
            elif val1 >= 8:  # TT, 99, 88
                return 0.70
            else:  # 77-22
                return 0.55
        
        # Premium non-pairs
        if {rank1, rank2} == {'A', 'K'}:
            return 0.80 if suited else 0.75
        elif {rank1, rank2} == {'A', 'Q'}:
            return 0.70 if suited else 0.65
        elif {rank1, rank2} == {'A', 'J'}:
            return 0.65 if suited else 0.60
        elif {rank1, rank2} == {'K', 'Q'}:
            return 0.60 if suited else 0.55
        
        # Strong aces
        if high_card == 14:  # Ace
            if low_card >= 10:  # AT+
                return 0.60 if suited else 0.50
            elif suited and low_card >= 5:  # A5s+
                return 0.45
            elif suited:  # A4s-A2s
                return 0.35
            elif low_card >= 9:  # A9o+
                return 0.45
            else:
                return 0.25
        
        # Broadway combinations
        if high_card >= 11 and low_card >= 10:  # KQ, KJ, QJ, etc.
            return 0.55 if suited else 0.45
        elif high_card >= 12 and low_card >= 9:  # KT, K9, QT, Q9
            return 0.45 if suited else 0.35
        
        # Suited connectors and one-gappers
        if suited:
            if gap == 0:  # Suited connectors
                if high_card >= 9:  # T9s+
                    return 0.50
                elif high_card >= 6:  # 65s+
                    return 0.40
                else:
                    return 0.30
            elif gap == 1:  # Suited one-gappers
                if high_card >= 10:  # J9s+
                    return 0.45
                elif high_card >= 7:  # 86s+
                    return 0.35
                else:
                    return 0.25
        
        # Offsuit connectors (only strong ones)
        if gap == 0 and high_card >= 9:  # T9o+
            return 0.35
        
        # Weak hands
        return 0.20

    def get_stack_situation(self) -> str:
        """Determine stack situation for strategy adjustment"""
        bb_ratio = self.current_chips / self.big_blind_amount if self.big_blind_amount > 0 else 50
        
        if bb_ratio <= 10:
            return "critical"  # Push/fold mode
        elif bb_ratio <= 20:
            return "short"     # Tight aggressive
        elif bb_ratio <= 40:
            return "medium"    # Standard play
        else:
            return "deep"      # More speculative hands

    def calculate_pot_odds(self, round_state: RoundStateClient) -> float:
        """Calculate pot odds for decision making"""
        my_bet = self.get_my_current_bet(round_state)
        amount_to_call = round_state.current_bet - my_bet
        total_pot = round_state.pot + amount_to_call
        
        return amount_to_call / total_pot if total_pot > 0 else 0

    def get_my_current_bet(self, round_state: RoundStateClient) -> int:
        """Safely get our current bet amount"""
        if self.id in round_state.player_bets:
            return round_state.player_bets[self.id]
        elif str(self.id) in round_state.player_bets:
            return round_state.player_bets[str(self.id)]
        else:
            return 0

    def get_action(self, round_state: RoundStateClient, remaining_chips: int) -> Tuple[PokerAction, int]:
        """Main decision function - optimized for tournament play"""
        try:
            self.current_chips = remaining_chips
            my_bet = self.get_my_current_bet(round_state)
            amount_to_call = round_state.current_bet - my_bet
            pot_odds = self.calculate_pot_odds(round_state)
            stack_situation = self.get_stack_situation()
            
            # Safety checks
            if amount_to_call > remaining_chips:
                amount_to_call = remaining_chips
            
            # Preflop strategy
            if round_state.round_num == 1:
                return self.preflop_strategy(amount_to_call, remaining_chips, pot_odds, stack_situation)
            
            # Postflop strategy
            board = getattr(round_state, 'community_cards', [])
            return self.postflop_strategy(board, amount_to_call, remaining_chips, pot_odds, round_state)
            
        except Exception as e:
            print(f"Error in get_action: {e}")
            # Emergency fallback
            if amount_to_call == 0:
                return PokerAction.CHECK, 0
            elif amount_to_call <= remaining_chips // 20:
                return PokerAction.CALL, amount_to_call
            else:
                return PokerAction.FOLD, 0

    def preflop_strategy(self, amount_to_call: int, remaining_chips: int, 
                        pot_odds: float, stack_situation: str) -> Tuple[PokerAction, int]:
        """Tournament-optimized preflop strategy"""
        hand_strength = self.get_preflop_hand_strength(self.hand)
        
        # Position adjustment
        position_adjustment = 0.0
        if self.position == 2:  # Late position
            position_adjustment = 0.08
        elif self.position == 0:  # Early position
            position_adjustment = -0.08
            
        adjusted_strength = hand_strength + position_adjustment
        
        # Stack-specific strategy
        if stack_situation == "critical":  # ≤10 BB
            # Push/fold strategy
            if adjusted_strength >= 0.6:
                return PokerAction.RAISE, remaining_chips  # All-in
            elif amount_to_call == 0:
                return PokerAction.CHECK, 0
            elif adjusted_strength >= 0.4 and pot_odds < 0.3:
                return PokerAction.CALL, amount_to_call
            else:
                return PokerAction.FOLD, 0
                
        elif stack_situation == "short":  # 10-20 BB
            # Tight aggressive
            if amount_to_call == 0:
                if adjusted_strength >= 0.7:
                    return PokerAction.RAISE, min(remaining_chips, self.big_blind_amount * 4)
                elif adjusted_strength >= 0.5:
                    return PokerAction.CHECK, 0
                else:
                    return PokerAction.FOLD, 0
            else:
                if adjusted_strength >= 0.8:
                    return PokerAction.RAISE, remaining_chips  # All-in with premium
                elif adjusted_strength >= 0.6 and pot_odds < 0.4:
                    return PokerAction.CALL, amount_to_call
                else:
                    return PokerAction.FOLD, 0
        
        else:  # Medium/deep stack
            if amount_to_call == 0:
                if adjusted_strength >= 0.7:
                    bet_size = self.big_blind_amount * 3
                    return PokerAction.RAISE, min(bet_size, remaining_chips // 4)
                elif adjusted_strength >= 0.4:
                    if random.random() < 0.3:  # Sometimes limp with speculative hands
                        return PokerAction.CHECK, 0
                    else:
                        return PokerAction.CHECK, 0
                else:
                    return PokerAction.FOLD, 0
            else:
                if adjusted_strength >= 0.85:  # Premium hands
                    raise_size = min(amount_to_call * 3, remaining_chips // 3)
                    return PokerAction.RAISE, raise_size
                elif adjusted_strength >= 0.6:
                    if pot_odds < 0.35:
                        return PokerAction.CALL, amount_to_call
                    else:
                        return PokerAction.FOLD, 0
                elif adjusted_strength >= 0.4 and pot_odds < 0.2:  # Great odds
                    return PokerAction.CALL, amount_to_call
                else:
                    return PokerAction.FOLD, 0

    def postflop_strategy(self, board: List[str], amount_to_call: int, remaining_chips: int, 
                         pot_odds: float, round_state: RoundStateClient) -> Tuple[PokerAction, int]:
        """Tournament-optimized postflop strategy"""
        if not board:
            return PokerAction.FOLD, 0
            
        hand_strength = self.evaluate_postflop_hand(self.hand, board)
        stack_situation = self.get_stack_situation()
        
        # Conservative in tournament - avoid marginal spots
        if stack_situation in ["critical", "short"]:
            # Very tight postflop when short
            if amount_to_call == 0:
                if hand_strength >= 0.7:
                    bet_size = min(round_state.pot // 2, remaining_chips // 3)
                    return PokerAction.RAISE, bet_size
                else:
                    return PokerAction.CHECK, 0
            else:
                if hand_strength >= 0.8:
                    return PokerAction.RAISE, remaining_chips  # All-in with strong hands
                elif hand_strength >= 0.6 and pot_odds < 0.3:
                    return PokerAction.CALL, amount_to_call
                else:
                    return PokerAction.FOLD, 0
        else:
            # More aggressive with deeper stacks
            if amount_to_call == 0:
                if hand_strength >= 0.75:
                    bet_size = min(int(0.7 * round_state.pot), remaining_chips // 3)
                    return PokerAction.RAISE, bet_size
                elif hand_strength >= 0.5:
                    bet_size = min(int(0.4 * round_state.pot), remaining_chips // 4)
                    return PokerAction.RAISE, bet_size
                elif random.random() < 0.15:  # Occasional bluff
                    bet_size = min(int(0.5 * round_state.pot), remaining_chips // 5)
                    return PokerAction.RAISE, bet_size
                else:
                    return PokerAction.CHECK, 0
            else:
                if hand_strength >= 0.8:
                    raise_size = min(amount_to_call * 2, remaining_chips // 2)
                    return PokerAction.RAISE, raise_size
                elif hand_strength >= 0.6 and pot_odds < 0.4:
                    return PokerAction.CALL, amount_to_call
                elif hand_strength >= 0.4 and pot_odds < 0.25:
                    return PokerAction.CALL, amount_to_call
                else:
                    return PokerAction.FOLD, 0

    def evaluate_postflop_hand(self, hole_cards: List[str], board: List[str]) -> float:
        """Simple but effective postflop hand evaluation"""
        if not hole_cards or not board:
            return 0.3
            
        try:
            hole_ranks = [card[0] for card in hole_cards]
            hole_suits = [card[1] for card in hole_cards]
            board_ranks = [card[0] for card in board]
            board_suits = [card[1] for card in board]
            
            all_ranks = hole_ranks + board_ranks
            all_suits = hole_suits + board_suits
            
            # Count rank frequencies
            rank_counts = {}
            for rank in all_ranks:
                rank_counts[rank] = rank_counts.get(rank, 0) + 1
            
            # Find pairs, trips, etc.
            max_count = max(rank_counts.values())
            pair_count = sum(1 for count in rank_counts.values() if count >= 2)
            
            # Hand strength evaluation
            if max_count >= 4:  # Four of a kind
                return 0.95
            elif max_count >= 3 and pair_count >= 2:  # Full house
                return 0.90
            elif self.has_flush(hole_cards, board):  # Flush
                return 0.85
            elif self.has_straight(hole_cards, board):  # Straight
                return 0.80
            elif max_count >= 3:  # Three of a kind
                return 0.75
            elif pair_count >= 2:  # Two pair
                return 0.65
            elif max_count >= 2:  # One pair
                # Check if it's top pair
                if board_ranks and max(board_ranks, key=lambda x: '23456789TJQKA'.index(x)) in hole_ranks:
                    return 0.60  # Top pair
                else:
                    return 0.50  # Other pair
            else:
                # High card - check for strong draws
                if self.has_flush_draw(hole_cards, board) or self.has_straight_draw(hole_cards, board):
                    return 0.45
                else:
                    return 0.35
                    
        except Exception as e:
            print(f"Error evaluating hand: {e}")
            return 0.35

    def has_flush(self, hole_cards: List[str], board: List[str]) -> bool:
        """Check for flush"""
        all_suits = [card[1] for card in hole_cards + board]
        suit_counts = {}
        for suit in all_suits:
            suit_counts[suit] = suit_counts.get(suit, 0) + 1
        return max(suit_counts.values()) >= 5

    def has_flush_draw(self, hole_cards: List[str], board: List[str]) -> bool:
        """Check for flush draw"""
        all_suits = [card[1] for card in hole_cards + board]
        suit_counts = {}
        for suit in all_suits:
            suit_counts[suit] = suit_counts.get(suit, 0) + 1
        return max(suit_counts.values()) >= 4

    def has_straight(self, hole_cards: List[str], board: List[str]) -> bool:
        """Check for straight"""
        ranks = set(card[0] for card in hole_cards + board)
        rank_order = '23456789TJQKA'
        
        for i in range(len(rank_order) - 4):
            if all(rank in ranks for rank in rank_order[i:i+5]):
                return True
        return False

    def has_straight_draw(self, hole_cards: List[str], board: List[str]) -> bool:
        """Check for straight draw"""
        ranks = set(card[0] for card in hole_cards + board)
        rank_order = '23456789TJQKA'
        
        for i in range(len(rank_order) - 3):
            sequence = rank_order[i:i+4]
            if sum(1 for rank in sequence if rank in ranks) >= 3:
                return True
        return False

    def on_end_round(self, round_state: RoundStateClient, remaining_chips: int):
        """Track game progression"""
        self.current_chips = remaining_chips
        self.total_games_played += 1

    def on_end_game(self, round_state: RoundStateClient, player_score: float, all_scores: dict, active_players_hands: dict):
        """Analyze results for future games"""
        delta = player_score - self.starting_chips
        print(f"Game {self.game_count} finished: Delta = ${delta:.2f}, Total score = ${player_score:.2f}")
        
        # Track our performance for meta-game adjustments
        if hasattr(self, 'performance_history'):
            self.performance_history.append(delta)
        else:
            self.performance_history = [delta]
            
        # Keep only recent performance (last 10 games)
        if len(self.performance_history) > 10:
            self.performance_history = self.performance_history[-10:]
