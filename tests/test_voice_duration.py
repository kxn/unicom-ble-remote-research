import argparse
import asyncio
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from voice_probe import recording_limit, wait_recording_end, secure_connection

class DurationTests(unittest.IsolatedAsyncioTestCase):
    def test_limits(self):
        for value in ['0', '-1', '601', 'nan', 'inf']:
            with self.assertRaises(argparse.ArgumentTypeError): recording_limit(value)
        self.assertEqual(recording_limit('120'), 120)

    async def test_no_data_does_not_stop_before_host_limit(self):
        progress = []
        result = await wait_recording_end(asyncio.Event(), .06, progress.append, interval=.01)
        self.assertEqual(result, 'host_limit')
        self.assertGreaterEqual(len(progress), 2)

    async def test_release_stops_without_waiting_for_host_limit(self):
        event = asyncio.Event()
        asyncio.get_running_loop().call_later(.01, event.set)
        self.assertEqual(await wait_recording_end(event, 1, lambda _: None), 'release_event')

    async def test_async_tick_is_awaited(self):
        tick = AsyncMock()
        self.assertEqual(await wait_recording_end(asyncio.Event(), .04, tick, interval=.01), 'host_limit')
        self.assertGreater(tick.await_count, 0)
        self.assertTrue(all(call.args[0] < .04 for call in tick.await_args_list))

    async def test_existing_bond_uses_encryption_without_pairing(self):
        conn = SimpleNamespace(peer_address='peer', encryption=1, encrypt=AsyncMock(), pair=AsyncMock())
        keys = SimpleNamespace(ltk=None, ltk_central=object())
        store = SimpleNamespace(get=AsyncMock(return_value=keys))
        await secure_connection(conn, store, False, lambda *a, **k: None)
        conn.encrypt.assert_awaited_once()
        conn.pair.assert_not_awaited()

    async def test_failed_restore_does_not_silently_replace_bond(self):
        conn = SimpleNamespace(peer_address='peer', encryption=0,
                               encrypt=AsyncMock(side_effect=RuntimeError('missing peer key')), pair=AsyncMock())
        store = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(ltk=object())))
        with self.assertRaises(RuntimeError):
            await secure_connection(conn, store, False, lambda *a, **k: None)
        conn.pair.assert_not_awaited()

    async def test_explicit_pair_and_first_pair(self):
        for force in [False, True]:
            conn = SimpleNamespace(peer_address='peer', encryption=1, encrypt=AsyncMock(), pair=AsyncMock())
            store = SimpleNamespace(get=AsyncMock(return_value=None))
            await secure_connection(conn, store, force, lambda *a, **k: None)
            conn.pair.assert_awaited_once()
            conn.encrypt.assert_not_awaited()
