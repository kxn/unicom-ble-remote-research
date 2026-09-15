"""Export lossless packet/group views, with checksums; no codec assumptions."""
import argparse
import csv
import hashlib
import json
import struct
from pathlib import Path
from analyze_capture import analyze

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    root=args.root.resolve()
    source=root/'data/raw/voice-1789484721.jsonl'
    summary,groups=analyze(source)
    summary['source']='data/raw/voice-1789484721.jsonl'
    output=root/'data/derived'
    output.mkdir(parents=True,exist_ok=True)
    (output/'groups.jsonl').write_text(''.join(json.dumps(g)+'\n' for g in groups),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    events=[json.loads(line) for line in source.read_text().splitlines()]
    streams={}
    label='unlabeled'
    for line_no,event in enumerate(events,1):
        if event['kind']=='write_start' and event.get('phase')=='start': label=event['label']
        if event['kind']=='notify' and event.get('handle')==52:
            streams.setdefault(label,[]).append((line_no,event))
    for label,packets in streams.items():
        with (output/(label+'.packets.csv')).open('w',newline='',encoding='utf-8') as f:
            writer=csv.writer(f)
            writer.writerow(['source_line','unix_time','monotonic','group_sequence_le','fragment_le','att_value_hex'])
            for line_no,event in packets:
                seq,frag=struct.unpack_from('<HH',bytes.fromhex(event['value']))
                writer.writerow([line_no,event['time'],event['monotonic'],seq,frag,event['value']])
        (output/(label+'.att20.bin')).write_bytes(b''.join(bytes.fromhex(e['value']) for _,e in packets))
        subset=[g for g in groups if g['label']==label]
        if any('joined_content_hex' not in g for g in subset): raise ValueError('Incomplete group')
        (output/(label+'.content48.bin')).write_bytes(b''.join(bytes.fromhex(g['joined_content_hex']) for g in subset))
    files=sorted((root/'data/raw').glob('*'))+sorted(output.glob('*'))
    files+=sorted((root/'docs').glob('*-evidence.jsonl'))
    manifest={'hash_algorithm':'SHA-256','files':[
        {'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in files if p.is_file()
    ]}
    (root/'data/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    main()
