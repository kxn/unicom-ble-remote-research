"""Bounded voice experiments. Only explicitly queued HID Output writes."""
import asyncio
import argparse
import json
import logging
import time
from pathlib import Path
from bumble.device import Device, DeviceConfiguration, Peer
from bumble.hci import Address
from bumble.keys import JsonKeyStore
from bumble.pairing import PairingConfig, PairingDelegate
from bumble.transport import open_transport

DEFAULT_WORK_DIR = Path(__file__).resolve().parents[1] / '.local' / 'session'

async def main(args):
    ROOT = args.work_dir.resolve()
    ROOT.mkdir(parents=True, exist_ok=True)
    if (ROOT/'voice-command.json').exists():
        raise RuntimeError('Stale voice-command.json exists; inspect and remove it before starting')
    session = str(int(time.time()))
    disconnected = asyncio.Event()
    release = asyncio.Event()
    armed = None
    active = None
    chars = {}
    with (ROOT / f'voice-{session}.jsonl').open('w', encoding='utf-8') as out:
        def emit(kind, **data):
            item = dict(time=time.time(), monotonic=time.monotonic(), kind=kind, **data)
            line = json.dumps(item, ensure_ascii=True)
            out.write(line+'\n'); out.flush()
            print(line, flush=True)
        async def trial(config):
            async def write(value, phase):
                emit('write_start', label=config['label'], handle=config['handle'], value=value, phase=phase)
                await asyncio.wait_for(chars[config['handle']].write_value(bytes.fromhex(value), with_response=True), 4)
                emit('write_ack', label=config['label'], phase=phase)
            try:
                await write(config['start'], 'start')
                try:
                    await asyncio.wait_for(release.wait(), 8)
                except asyncio.TimeoutError:
                    emit('watchdog_stop', label=config['label'])
            except Exception as e:
                emit('trial_error', error=repr(e))
            finally:
                if not disconnected.is_set():
                    try: await write(config['stop'], 'stop')
                    except Exception as e: emit('stop_error', error=repr(e))
                emit('trial_done', label=config['label'])
        def notification(handle, value):
            nonlocal armed, active
            emit('notify', handle=handle, value=value.hex())
            if handle == 59 and value[:3] == bytes.fromhex('820300'):
                release.set()
            if handle == 59 and value[:3] == bytes.fromhex('820301') and armed is not None:
                if active is None or active.done():
                    config, armed = armed, None
                    release.clear()
                    active = asyncio.create_task(trial(config))
        async with await open_transport(args.transport) as (source, sink):
            device = Device.from_config_with_hci(DeviceConfiguration(name='BLE Research', address=Address(args.local_address)), source, sink)
            device.keystore = JsonKeyStore.from_device(device, filename=str(ROOT/'pairing-keys.json'))
            device.pairing_config_factory = lambda c: PairingConfig(mitm=False, bonding=True, delegate=PairingDelegate(io_capability=PairingDelegate.NO_OUTPUT_NO_INPUT))
            await asyncio.wait_for(device.power_on(), 15)
            emit('connecting', log=f'voice-{session}.jsonl')
            conn = await device.connect(args.address, timeout=120)
            def on_disconnect(reason):
                emit('disconnected', reason=int(reason))
                disconnected.set()
            conn.on('disconnection', on_disconnect)
            emit('connected')
            try:
                await asyncio.wait_for(conn.pair(), 35)
                emit('paired', encryption=conn.encryption)
                peer = Peer(conn)
                await peer.discover_services()
                for service in peer.services:
                    await service.discover_characteristics()
                    for ch in service.characteristics:
                        chars[ch.handle] = ch
                        emit('characteristic', handle=ch.handle, uuid=str(ch.uuid), properties=int(ch.properties))
                        if int(ch.properties) & 16:
                            emit('subscribe_start', handle=ch.handle)
                            await asyncio.wait_for(ch.subscribe(lambda value, h=ch.handle: notification(h, value)), 10)
                            emit('subscribed', handle=ch.handle)
                for handle, reference in {56:'fb02',63:'fa02',59:'f801'}.items():
                    ch = chars.get(handle)
                    if ch is None:
                        raise RuntimeError(f'Expected report handle {handle} missing')
                    await ch.discover_descriptors()
                    references = [d for d in ch.descriptors if str(d.type).startswith('UUID-16:2908')]
                    if len(references) != 1 or (await references[0].read_value()).hex() != reference:
                        raise RuntimeError(f'Report reference mismatch at {handle}; refusing writes')
                emit('listening', seconds=1800)
                deadline = time.monotonic()+1800
                queue = ROOT/'voice-command.json'
                while not disconnected.is_set() and time.monotonic()<deadline:
                    if queue.exists():
                        config = json.loads(queue.read_text(encoding='utf-8-sig'))
                        queue.unlink()
                        if config.get('action') == 'stop': break
                        if config.get('handle') not in (56,63): raise ValueError('Only identified HID Output targets allowed')
                        for key in ('start','stop'):
                            if not 1 <= len(bytes.fromhex(config[key])) <= 20: raise ValueError('Bad payload size')
                        if active is not None and not active.done(): raise ValueError('Trial already active')
                        armed = config
                        emit('armed', **config)
                    await asyncio.sleep(.1)
            finally:
                release.set()
                if active is not None and not active.done():
                    await active
                if not disconnected.is_set():
                    await asyncio.wait_for(conn.disconnect(), 10)
                emit('done')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument('--address', default='0C:F3:DE:C6:AE:64/P')
    parser.add_argument('--transport', default='usb:0A12:0001')
    parser.add_argument('--local-address', default='F2:58:20:00:00:01')
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(parser.parse_args()))
