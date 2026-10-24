"""Real MCP client/server handshakes, discovery and dispatch without models."""
from contextlib import asynccontextmanager
from datetime import timedelta
import importlib.metadata
import json
from pathlib import Path
import sys
from threading import Event
import time

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

from kronos_lab.mcp_server import create_mcp

ROOT = Path(__file__).resolve().parents[1]
TOOL_NAMES = {"forecast_kline", "forecast_signal", "forecast_compare", "forecast_batch", "job_status"}


class OfflineService:
    def __init__(self):
        self.calls = []

    def forecast(self, request):
        self.calls.append(("forecast", request))
        return {"summary": {"p_up": .75, "calibrated": False, "direction": "up"},
                "metadata": {"purpose": "offline protocol test"},
                "trajectories": [[[100., 102., 99., 101., 10., 1010.]]],
                "quantiles": {"q10": [100.], "q50": [101.], "q90": [102.]}}

    def compare(self, request):
        self.calls.append(("compare", request))
        return {"backend": "fake-chronos-for-dispatch-only", "symbol": request.symbol}

    def submit(self, kind, requests):
        self.calls.append((kind, requests))
        return {"job_id": "offline-job", "status": "queued"}

    def job_status(self, job_id):
        self.calls.append(("job_status", job_id))
        return {"job_id": job_id, "status": "completed", "result": []}


@asynccontextmanager
async def protocol_session(server):
    # Official MCP memory transport still serializes SessionMessage JSON-RPC
    # requests through the actual ClientSession and low-level server dispatcher.
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as group:
            low_level = server._mcp_server
            async def run_server():
                await low_level.run(*server_streams, low_level.create_initialization_options())
            group.start_soon(run_server)
            try:
                async with ClientSession(*client_streams, read_timeout_seconds=timedelta(seconds=5)) as client:
                    initialized = await client.initialize()
                    yield client, initialized
            finally:
                group.cancel_scope.cancel()


def structured(result):
    assert not result.isError, result
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def test_protocol_negotiates_lists_schemas_and_calls_each_tool():
    service = OfflineService()
    server = create_mcp(service)
    async def scenario():
        async with protocol_session(server) as (client, initialized):
            assert initialized.protocolVersion in SUPPORTED_PROTOCOL_VERSIONS
            assert initialized.serverInfo.name == "Kronos Forecasting Lab"
            assert initialized.capabilities.tools is not None
            assert "not calibrated confidence" in initialized.instructions
            assert importlib.metadata.version("mcp").split(".")[0] == "1"
            discovered = await client.list_tools()
            tools = {tool.name: tool for tool in discovered.tools}
            assert set(tools) == TOOL_NAMES
            assert tools["forecast_kline"].inputSchema["properties"]["symbol"]["default"] == "BTCUSDT"
            assert tools["forecast_batch"].inputSchema["properties"]["symbols"]["type"] == "array"

            result = structured(await client.call_tool("forecast_kline", {
                "symbol": "ETHUSDT", "timeframe": "4h", "lookback": 32,
                "horizon": 4, "sample_count": 8, "seed": 13}))
            assert result["summary"]["p_up"] == .75
            assert "trajectories" in result and "quantiles" in result
            request = service.calls[-1][1]
            assert (request.symbol, request.interval, request.lookback, request.horizon,
                    request.sample_count, request.seed) == ("ETHUSDT", "4h", 32, 4, 8, 13)

            signal = structured(await client.call_tool("forecast_signal", {"symbol": "BTCUSDT"}))
            assert set(signal) == {"summary", "metadata"}
            assert signal["summary"]["calibrated"] is False
            compared = structured(await client.call_tool("forecast_compare", {"symbol": "BTCUSDT"}))
            assert compared["symbol"] == "BTCUSDT" and service.calls[-1][0] == "compare"
            batch = structured(await client.call_tool("forecast_batch", {"symbols": ["BTCUSDT", "ETHUSDT"]}))
            assert batch == {"job_id": "offline-job", "status": "queued"}
            assert service.calls[-1][0] == "batch"
            assert [item.symbol for item in service.calls[-1][1]] == ["BTCUSDT", "ETHUSDT"]
            status = structured(await client.call_tool("job_status", {"job_id": batch["job_id"]}))
            assert status["status"] == "completed"
    anyio.run(scenario)


def test_protocol_validation_errors_do_not_dispatch_work():
    service = OfflineService()
    async def scenario():
        async with protocol_session(create_mcp(service)) as (client, _):
            for name, arguments in [
                ("forecast_kline", {"sample_count": 65}),
                ("forecast_kline", {"lookback": 500, "horizon": 13}),
                ("forecast_kline", {"symbol": "../../.env"}),
                ("forecast_batch", {"symbols": []}),
                ("forecast_batch", {"symbols": ["BTCUSDT"] * 17}),
                ("forecast_batch", {"symbols": "BTCUSDT"}),
                ("does_not_exist", {}),
            ]:
                response = await client.call_tool(name, arguments)
                assert response.isError is True
            assert service.calls == []
    anyio.run(scenario)


def test_job_status_responds_while_forecast_worker_is_blocked():
    class BlockingService(OfflineService):
        def __init__(self):
            super().__init__()
            self.started, self.release = Event(), Event()
        def forecast(self, request):
            self.started.set()
            if not self.release.wait(timeout=3):
                raise TimeoutError("Blocking fake was not released")
            return super().forecast(request)
    service = BlockingService()
    async def scenario():
        async with protocol_session(create_mcp(service)) as (client, _):
            results = []
            async def long_forecast():
                results.append(await client.call_tool("forecast_kline", {}))
            async with anyio.create_task_group() as group:
                started_at = time.monotonic()
                try:
                    group.start_soon(long_forecast)
                    with anyio.fail_after(1):
                        assert await anyio.to_thread.run_sync(service.started.wait, 2)
                        status = structured(await client.call_tool("job_status", {"job_id": "prior-job"}))
                    assert status["status"] == "completed"
                    assert time.monotonic() - started_at < 1
                    assert not results, "Forecast should still be waiting in its worker"
                finally:
                    service.release.set()
            assert len(results) == 1 and not results[0].isError
    anyio.run(scenario)


def test_real_stdio_entrypoint_initializes_and_discovers_tools():
    async def scenario():
        # Discovery and invalid-argument calls never reach a data provider or
        # trigger pretrained loading. This verifies the actual launch command.
        process = StdioServerParameters(command=sys.executable,
                    args=["-m", "kronos_lab.mcp_server"], cwd=ROOT, env={})
        with anyio.fail_after(15):
            async with stdio_client(process) as streams:
                async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=5)) as client:
                    handshake = await client.initialize()
                    assert handshake.protocolVersion in SUPPORTED_PROTOCOL_VERSIONS
                    assert {tool.name for tool in (await client.list_tools()).tools} == TOOL_NAMES
                    response = await client.call_tool("forecast_kline", {"sample_count": 1000})
                    assert response.isError is True
    anyio.run(scenario)


def test_real_stdio_forecast_keeps_noisy_diagnostics_off_protocol_stdout(tmp_path):
    script = tmp_path / "noisy_mcp_service.py"
    script.write_text("""import sys
import time
sys.path.insert(0, ROOT_PATH)
from kronos_lab.mcp_server import create_mcp

class NoisyService:
    def forecast(self, request):
        print('Loading weights from local directory', flush=True)
        for step in range(8):
            print('Noisy inference progress', step, flush=True)
            time.sleep(0.02)
        return {'summary': {'p_up': 0.75, 'calibrated': False}, 'metadata': {}}
    def job_status(self, job_id):
        return {'job_id': job_id, 'status': 'completed'}
    def close(self):
        print('Noisy worker shutdown', flush=True)

create_mcp(NoisyService()).run(transport='stdio')
""".replace("ROOT_PATH", repr(str(ROOT))))
    error_log = tmp_path / "mcp_stderr.log"
    protocol_errors = []

    async def message_handler(message):
        if isinstance(message, Exception):
            protocol_errors.append(message)

    async def scenario():
        process = StdioServerParameters(command=sys.executable, args=[str(script)], cwd=ROOT, env={})
        with anyio.fail_after(15), error_log.open("w") as diagnostics:
            async with stdio_client(process, errlog=diagnostics) as streams:
                async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=5),
                                         message_handler=message_handler) as client:
                    await client.initialize()
                    outputs = []
                    async def forecast():
                        outputs.append(structured(await client.call_tool("forecast_kline", {})))
                    async with anyio.create_task_group() as group:
                        group.start_soon(forecast)
                        await anyio.sleep(.05)
                        status = structured(await client.call_tool("job_status", {"job_id": "earlier-job"}))
                        assert status["status"] == "completed"
                    assert outputs[0]["summary"]["p_up"] == .75
    anyio.run(scenario)
    assert protocol_errors == [], "Non-JSON diagnostics corrupted the MCP protocol stream"
    diagnostics = error_log.read_text()
    assert "Loading weights from local directory" in diagnostics
    assert "Noisy inference progress" in diagnostics
    assert "Noisy worker shutdown" in diagnostics
