"""MCP stdio tools backed by the same forecasting service as the local API."""
from contextlib import asynccontextmanager, redirect_stdout
from functools import partial
import sys

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server
from .service import ForecastRequest, LabService


class _ProtocolSafeFastMCP(FastMCP):
    async def run_stdio_async(self):
        # The official transport captures its own wrapper of stdout.buffer on
        # entry. Redirect later Python prints for the whole serving lifetime,
        # rather than racing process-global redirects in concurrent workers.
        # The transport writer continues using its captured protocol stream.
        async with stdio_server() as (read_stream, write_stream):
            with redirect_stdout(sys.stderr):
                await self._mcp_server.run(read_stream, write_stream,
                    self._mcp_server.create_initialization_options())


def create_mcp(service=None):
    service = service or LabService()

    @asynccontextmanager
    async def service_lifespan(_server):
        try:
            yield
        finally:
            close = getattr(service, "close", None)
            if close is not None:
                # Keep diagnostics redirected until queued workers have drained.
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(close)

    server = _ProtocolSafeFastMCP("Kronos Forecasting Lab", lifespan=service_lifespan, instructions=(
        "Research forecasts, not trade instructions. p_up is an empirical sample fraction, "
        "not calibrated confidence. Never infer an accuracy probability from agreement."))

    @server.tool()
    async def forecast_kline(symbol: str = "BTCUSDT", timeframe: str = "1h", lookback: int = 128,
                       horizon: int = 12, sample_count: int = 20, seed: int = 42) -> dict:
        """Forecast OHLCVA with separate sample paths and raw 10/50/90% close quantiles."""
        request = ForecastRequest(symbol=symbol, interval=timeframe,
            lookback=lookback, horizon=horizon, sample_count=sample_count, seed=seed)
        return await anyio.to_thread.run_sync(partial(service.forecast, request))

    @server.tool()
    async def forecast_signal(symbol: str = "BTCUSDT", timeframe: str = "1h", lookback: int = 128,
                        horizon: int = 12, sample_count: int = 20, seed: int = 42) -> dict:
        """Return mean-path direction and sample voting separately; no confidence claim."""
        result = await forecast_kline(symbol, timeframe, lookback, horizon, sample_count, seed)
        return {"summary": result["summary"], "metadata": result["metadata"]}

    @server.tool()
    async def forecast_compare(symbol: str = "BTCUSDT", timeframe: str = "1h", lookback: int = 128,
                         horizon: int = 12, sample_count: int = 20) -> dict:
        """Compare Kronos with the optional Chronos-2 backend on identical historical data."""
        request = ForecastRequest(symbol=symbol, interval=timeframe,
            lookback=lookback, horizon=horizon, sample_count=sample_count)
        return await anyio.to_thread.run_sync(partial(service.compare, request))

    @server.tool()
    def forecast_batch(symbols: list[str], timeframe: str = "1h", lookback: int = 128,
                       horizon: int = 12, sample_count: int = 20) -> dict:
        """Queue up to 16 symbols; each symbol reports a result or an isolated error."""
        if not 1 <= len(symbols) <= 16:
            raise ValueError("Provide 1..16 symbols")
        return service.submit("batch", [ForecastRequest(symbol=symbol, interval=timeframe,
            lookback=lookback, horizon=horizon, sample_count=sample_count) for symbol in symbols])

    @server.tool()
    def job_status(job_id: str) -> dict:
        """Read a queued batch job; completed results are retained in bounded session memory."""
        return service.job_status(job_id)

    return server


def main():
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()
