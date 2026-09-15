"""Queue one named, bounded experiment for the running voice probe."""
import argparse
import json
import os
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', choices=['fb','fa','stop'])
    parser.add_argument('--work-dir', type=Path, default=Path(__file__).resolve().parents[1]/'.local/session')
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True,exist_ok=True)
    target = args.work_dir/'voice-command.json'
    if target.exists():
        parser.error('A command is already pending; do not overwrite it')
    command = {'action':'stop'} if args.experiment=='stop' else {
        'label':args.experiment+'_single_01_00', 'handle':56 if args.experiment=='fb' else 63,
        'start':'01','stop':'00',
    }
    temporary = target.with_suffix('.tmp')
    with temporary.open('x',encoding='utf-8') as f:
        json.dump(command,f)
    try:
        # On Windows rename refuses to overwrite an existing destination.
        if os.name == 'nt':
            temporary.rename(target)
        else:
            os.link(temporary,target)
            temporary.unlink()
    finally:
        if temporary.exists(): temporary.unlink()
    print(json.dumps(command))

if __name__=='__main__':
    main()
