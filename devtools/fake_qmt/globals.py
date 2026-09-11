"""QMT module-level functions injected into the loaded server.py namespace."""

from __future__ import annotations


def build_qmt_globals(store, context):
    """Return the QMT globals the server looks up via globals().get(name)."""

    def get_trade_detail_data(account_id, account_type, datatype):
        return store.get_trade_detail_data(account_id, account_type, datatype)

    def passorder(*args, **kwargs):
        if len(args) < 7:
            return None
        side = "BUY" if args[0] == 23 else "SELL"
        symbol = args[3]
        price = args[5]
        volume = args[6]
        strategy_name = args[7] if len(args) > 7 and isinstance(args[7], str) else ""
        return store.place_order(symbol, side, price, volume, strategy_name)

    def cancel(*args, **kwargs):
        if not args:
            return False
        return store.cancel_order(args[0])

    def can_cancel_order(*args, **kwargs):
        if not args:
            return False
        return store.can_cancel(args[0])

    def get_instrument_detail(symbol):
        return context.get_instrument_detail(symbol)

    return {
        "get_trade_detail_data": get_trade_detail_data,
        "passorder": passorder,
        "cancel": cancel,
        "can_cancel_order": can_cancel_order,
        "get_instrument_detail": get_instrument_detail,
    }
