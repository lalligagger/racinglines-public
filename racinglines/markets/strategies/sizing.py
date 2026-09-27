"""Position sizing shared by the taker strategies."""


def target_shares(fair, price, cost, min_edge, stake_per_edge, max_stake):
    """(yes_shares, no_shares) to hold: nothing unless |fair - price| >= min_edge; otherwise
    a stake of stake_per_edge x |edge| (capped at max_stake) on the cheap side, paying cost
    per share on top of the price (YES at price, NO at 1 - price)."""
    edge = fair - price
    if abs(edge) < min_edge:
        return 0.0, 0.0
    stake = min(max_stake, stake_per_edge * abs(edge))
    return (stake / (price + cost), 0.0) if edge > 0 else (0.0, stake / (1 - price + cost))
