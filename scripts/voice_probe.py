"""Bounded voice experiments. Only explicitly queued HID Output writes."""
import asyncio
import argparse
import json
import logging
import math
import inspect
import time
from pathlib import Path
from bumble.device import Device, DeviceConfiguration, Peer
from bumble.hci import Address, OwnAddressType
from bumble.keys import JsonKeyStore
from bumble.pairing import PairingConfig, PairingDelegate
from bumble.transport import open_transport
from voice_audio import NativeIco, Recording, DEFAULT_LIBRARY

DEFAULT_WORK_DIR = Path(__file__).resolve().parents[1] / '.local' / 'session'

def recording_limit(value):
    seconds = float(value)
    if not math.isfinite(seconds) or not 1 <= seconds <= 600:
        raise argparse.ArgumentTypeError('Recording limit must be 1..600 seconds')
    return seconds

async def wait_recording_end(release, timeout, progress, interval=5):
    """Observe stalls without stopping early; only release or host limit ends this wait."""
    started = time.monotonic()
    while True:
        remaining = timeout - (time.monotonic()-started)
        if remaining <= 0:
            return 'host_limit'
        try:
            await asyncio.wait_for(release.wait(), min(interval, remaining))
            return 'release_event'
        except asyncio.TimeoutError:
            elapsed = time.monotonic()-started
            if elapsed >= timeout:
                return 'host_limit'
            result = progress(elapsed)
            if inspect.isawaitable(result):
                await result

async def secure_connection(conn, keystore, force_pair, emit):
    keys = await keystore.get(str(conn.peer_address))
    if not force_pair and keys is not None and (keys.ltk is not None or keys.ltk_central is not None):
        emit('bond_restore_start')
        await asyncio.wait_for(conn.encrypt(), 15)
        emit('bond_restored', encryption=conn.encryption)
    else:
        emit('pair_start', forced=force_pair)
        await asyncio.wait_for(conn.pair(), 35)
        emit('paired', encryption=conn.encryption)
    if not conn.encryption:
        raise RuntimeError('Encryption not enabled; refusing GATT experiments')

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
    decoder = NativeIco(args.decoder) if args.record_voice else None
    recording = None
    last_audio = 0.0
    recording_number = 0
    ready = False
    release_source = None
    with (ROOT / f'voice-{session}.jsonl').open('w', encoding='utf-8') as out:
        def emit(kind, **data):
            item = dict(time=time.time(), monotonic=time.monotonic(), kind=kind, **data)
            line = json.dumps(item, ensure_ascii=True)
            out.write(line+'\n'); out.flush()
            print(line, flush=True)
        async def trial(config):
            nonlocal recording, last_audio, release_source
            end_reason = 'trial_error'
            limit = args.max_record_seconds if args.record_voice else 8
            async def write(value, phase):
                emit('write_start', label=config['label'], handle=config['handle'], value=value, phase=phase)
                await asyncio.wait_for(chars[config['handle']].write_value(bytes.fromhex(value), with_response=True), 4)
                emit('write_ack', label=config['label'], phase=phase)
            try:
                await write(config['start'], 'start')
                last_refresh = 0.0
                async def progress(elapsed):
                    nonlocal last_refresh, release_source
                    emit('recording_progress', label=config['label'], elapsed=elapsed,
                         frames=recording.frames if recording else None,
                         seconds_without_fc=time.monotonic()-last_audio if recording else None)
                    if args.refresh_start_seconds and elapsed-last_refresh >= args.refresh_start_seconds:
                        last_refresh = elapsed
                        # Do not turn a stopped stream into repeated new recordings.
                        if release.is_set() or not recording or not recording.frames or time.monotonic()-last_audio > 1:
                            emit('refresh_skipped', label=config['label'], reason='not_streaming')
                            return
                        try:
                            await write(config['start'], 'refresh_start_candidate')
                        except Exception as e:
                            recording.fail('refresh write error: '+repr(e))
                            release_source = 'refresh_write_error'
                            release.set()
                end_reason = await wait_recording_end(release, limit, progress)
                if end_reason == 'host_limit':
                    emit('watchdog_stop', label=config['label'], limit_seconds=limit)
                else:
                    end_reason = release_source or 'session_stop'
            except Exception as e:
                if recording is not None: recording.fail('start/trial error: '+repr(e))
                emit('trial_error', error=repr(e))
            finally:
                emit('recording_end_requested', label=config['label'], reason=end_reason)
                if not disconnected.is_set():
                    try: await write(config['stop'], 'stop')
                    except Exception as e:
                        if recording is not None: recording.fail('stop write error: '+repr(e))
                        emit('stop_error', error=repr(e))
                if recording is not None:
                    # Keep accepting tail packets after release/stop, bounded to 1 second.
                    drain_start = time.monotonic()
                    while not disconnected.is_set() and time.monotonic()-drain_start < 1:
                        await asyncio.sleep(.05)
                        if time.monotonic()-max(last_audio, drain_start) >= .3:
                            break
                    if disconnected.is_set(): recording.fail('disconnected during recording')
                    result = recording.finish()
                    result.update(end_reason=end_reason, host_limit_seconds=limit)
                    (recording.path.with_suffix('.json')).write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
                    emit('audio_saved', **result)
                    recording = None
                emit('trial_done', label=config['label'])
        def notification(handle, value):
            nonlocal armed, active, recording, last_audio, recording_number, release_source
            emit('notify', handle=handle, value=value.hex())
            if handle == 52 and recording is not None:
                last_audio = time.monotonic()
                try: recording.feed(value)
                except Exception as e: recording.fail('decode error: '+repr(e))
                if recording.errors:
                    release_source = 'audio_error'
                    release.set()
            if handle == 59 and value[:3] == bytes.fromhex('820300'):
                emit('remote_mic_up', ignored_for_stop=args.ignore_mic_up)
                if not args.ignore_mic_up:
                    release_source = 'remote_mic_up'
                    release.set()
            if handle == 59 and value[:3] == bytes.fromhex('820301') and ready and (armed is not None or args.record_voice):
                if active is None or active.done():
                    if args.record_voice:
                        recording_number += 1
                        label = f'ico_{session}_{recording_number:03}'
                        config = dict(label=label, handle=56, start='01', stop='00')
                        recording = Recording(decoder, ROOT/'audio'/f'{label}.wav')
                        last_audio = time.monotonic()
                        emit('audio_started', label=label)
                    else:
                        config, armed = armed, None
                    release.clear()
                    release_source = None
                    active = asyncio.create_task(trial(config))
        async with await open_transport(args.transport) as (source, sink):
            device = Device.from_config_with_hci(DeviceConfiguration(name='BLE Research', address=Address(args.local_address)), source, sink)
            device.keystore = JsonKeyStore.from_device(device, filename=str(ROOT/'pairing-keys.json'))
            device.pairing_config_factory = lambda c: PairingConfig(mitm=False, bonding=True,
                identity_address_type=PairingConfig.AddressType.PUBLIC,
                delegate=PairingDelegate(io_capability=PairingDelegate.NO_OUTPUT_NO_INPUT))
            await asyncio.wait_for(device.power_on(), 15)
            emit('connecting', log=f'voice-{session}.jsonl', own_address=str(device.public_address), own_address_type='public')
            conn = await device.connect(args.address, timeout=120, own_address_type=OwnAddressType.PUBLIC)
            def on_disconnect(reason):
                nonlocal release_source
                emit('disconnected', reason=int(reason))
                disconnected.set()
                release_source = 'disconnected'
                release.set()
            conn.on('disconnection', on_disconnect)
            emit('connected')
            try:
                await secure_connection(conn, device.keystore, args.pair, emit)
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
                for handle, reference in {52:'fc01',56:'fb02',63:'fa02',59:'f801'}.items():
                    ch = chars.get(handle)
                    if ch is None:
                        raise RuntimeError(f'Expected report handle {handle} missing')
                    await ch.discover_descriptors()
                    references = [d for d in ch.descriptors if str(d.type).startswith('UUID-16:2908')]
                    if len(references) != 1 or (await references[0].read_value()).hex() != reference:
                        raise RuntimeError(f'Report reference mismatch at {handle}; refusing writes')
                ready = True
                emit('listening', seconds=1800, record_voice=args.record_voice,
                     max_record_seconds=args.max_record_seconds, ignore_mic_up=args.ignore_mic_up,
                     refresh_start_seconds=args.refresh_start_seconds)
                deadline = time.monotonic()+1800
                queue = ROOT/'voice-command.json'
                while not disconnected.is_set() and time.monotonic()<deadline:
                    if queue.exists():
                        config = json.loads(queue.read_text(encoding='utf-8-sig'))
                        queue.unlink()
                        if config.get('action') == 'stop': break
                        if args.record_voice: raise ValueError('Recording mode accepts only stop; mic key controls FB automatically')
                        if config.get('handle') not in (56,63): raise ValueError('Only identified HID Output targets allowed')
                        for key in ('start','stop'):
                            if not 1 <= len(bytes.fromhex(config[key])) <= 20: raise ValueError('Bad payload size')
                        if active is not None and not active.done(): raise ValueError('Trial already active')
                        armed = config
                        emit('armed', **config)
                    await asyncio.sleep(.1)
            finally:
                ready = False
                release.set()
                if active is not None and not active.done():
                    await active
                if not disconnected.is_set():
                    try:
                        await asyncio.wait_for(conn.disconnect(), 10)
                    except Exception as e:
                        emit('disconnect_cleanup_error', error=repr(e))
                emit('done')
                if decoder is not None: decoder.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument('--address', default='0C:F3:DE:C6:AE:64/P')
    parser.add_argument('--transport', default='usb:0A12:0001')
    parser.add_argument('--local-address', default='F2:58:20:00:00:01')
    parser.add_argument('--record-voice', action='store_true', help='Explicitly enable FB 01/00 on each mic press/release, decode FC to WAV')
    parser.add_argument('--max-record-seconds', type=recording_limit, default=8,
                        help='Host watchdog for recording mode, 1..600 seconds (default: 8)')
    parser.add_argument('--decoder', type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument('--pair', action='store_true', help='Explicitly replace bonding via pairing instead of restoring saved encryption')
    parser.add_argument('--ignore-mic-up', action='store_true',
                        help='Bounded experiment: log remote mic-up but stop only at host limit, error or session stop')
    parser.add_argument('--refresh-start-seconds', type=int, choices=(0, 5, 10), default=0,
                        help='Experimental: repeat known FB 01 while FC is flowing; not a verified keepalive')
    logging.basicConfig(level=logging.WARNING)
    args = parser.parse_args()
    if (args.ignore_mic_up or args.refresh_start_seconds) and not args.record_voice:
        parser.error('Recording experiment options require --record-voice')
    asyncio.run(main(args))
