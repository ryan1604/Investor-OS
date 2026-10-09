from collections.abc import Mapping

from app.schemas import PortfolioAccountSummary, PortfolioPosition

PnlData = Mapping[tuple[str, int], Mapping[str, float | None]]
MarketData = Mapping[int, Mapping[str, float]]
AccountValues = Mapping[tuple[str, str, str], float]
AccountPnlData = Mapping[str, Mapping[str, float | None]]


def percent(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / abs(denominator) * 100


def merge_portfolio_rows(
    positions: list[PortfolioPosition],
    market_data: MarketData,
    pnl_data: PnlData,
) -> list[PortfolioPosition]:
    merged_positions: list[PortfolioPosition] = []

    for position in positions:
        values = market_data.get(position.con_id, {})
        last_price = values.get("last")
        previous_close = values.get("close")
        change_percent = None
        position_pnl_data = (
            pnl_data.get((position.account, position.con_id), {})
            if position.con_id is not None
            else {}
        )
        position_daily_pnl = position_pnl_data.get("daily_pnl")
        unrealized_pnl = position_pnl_data.get("unrealized_pnl")
        realized_pnl = position_pnl_data.get("realized_pnl")
        market_value = position_pnl_data.get("market_value")
        cost_basis = (
            position.quantity * position.average_cost
            if position.average_cost is not None
            else None
        )

        if last_price is not None and previous_close:
            change_percent = (last_price - previous_close) / previous_close * 100

        merged_positions.append(
            position.model_copy(
                update={
                    "last_price": last_price,
                    "change_percent": change_percent,
                    "pnl": position_daily_pnl,
                    "pnl_percent": None,
                    "realized_pnl": realized_pnl,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_percent": percent(
                        unrealized_pnl,
                        cost_basis,
                    ),
                    "market_value": market_value,
                    "cost_basis": cost_basis,
                    "average_price": position.average_cost,
                    "net_liquidity": None,
                    "net_liquidity_percent": None,
                }
            )
        )

    return merged_positions


def account_value(
    account: str,
    key: str,
    account_summary_values: AccountValues,
) -> float | None:
    usd_value = account_summary_values.get((account, key, "USD"))
    if usd_value is not None:
        return usd_value

    for account_name, account_key, currency in account_summary_values:
        if account_name == account and account_key == key:
            return account_summary_values[(account_name, account_key, currency)]

    return None


def account_value_with_currency(
    account: str,
    key: str,
    account_summary_values: AccountValues,
) -> tuple[float | None, str | None]:
    for account_name, account_key, currency in account_summary_values:
        if account_name == account and account_key == key:
            return account_summary_values[(account_name, account_key, currency)], currency

    return None, None


def build_account_summary(
    account: str,
    account_summary_values: AccountValues,
    account_pnl_data: AccountPnlData,
) -> PortfolioAccountSummary:
    account_pnl_values = account_pnl_data.get(account, {})
    net_liquidation = account_value(
        account,
        "NetLiquidation",
        account_summary_values,
    )
    _, net_liquidation_currency = account_value_with_currency(
        account,
        "NetLiquidation",
        account_summary_values,
    )
    daily_pnl = account_pnl_values.get("daily_pnl")
    unrealized_pnl = account_pnl_values.get("unrealized_pnl")
    market_value = account_value(
        account,
        "GrossPositionValue",
        account_summary_values,
    )
    cash_total_sgd, _ = account_value_with_currency(
        account,
        "cash_total_sgd",
        account_summary_values,
    )
    cash_total_usd, _ = account_value_with_currency(
        account,
        "cash_total_usd",
        account_summary_values,
    )
    cash_total, _ = account_value_with_currency(
        account,
        "cash_total",
        account_summary_values,
    )

    return PortfolioAccountSummary(
        account=account,
        currency=net_liquidation_currency or "USD",
        net_liquidation=net_liquidation,
        daily_pnl=daily_pnl,
        daily_pnl_percent=percent(daily_pnl, net_liquidation),
        unrealized_pnl=unrealized_pnl,
        market_value=market_value,
        maintenance_margin=account_value(
            account,
            "MaintMarginReq",
            account_summary_values,
        ),
        excess_liquidity=account_value(
            account,
            "ExcessLiquidity",
            account_summary_values,
        ),
        buying_power=account_value(
            account,
            "BuyingPower",
            account_summary_values,
        ),
        cash_total_sgd=cash_total_sgd,
        cash_total_usd=cash_total_usd,
        cash_total=cash_total,
    )


def attach_account_summaries(
    positions: list[PortfolioPosition],
    summaries: list[PortfolioAccountSummary],
) -> list[PortfolioPosition]:
    summaries_by_account = {summary.account: summary for summary in summaries}
    enriched_positions: list[PortfolioPosition] = []

    for position in positions:
        summary = summaries_by_account.get(position.account)
        net_liquidation = summary.net_liquidation if summary else None
        enriched_positions.append(
            position.model_copy(
                update={
                    "net_liquidity": net_liquidation,
                    "net_liquidity_percent": percent(
                        position.market_value,
                        net_liquidation,
                    ),
                    "pnl_percent": percent(position.pnl, net_liquidation),
                }
            )
        )

    return enriched_positions
