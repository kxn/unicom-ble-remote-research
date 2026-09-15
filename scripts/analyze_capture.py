"""Reassemble observed FC fragments without claiming an audio payload format."""
import argparse
import collections
import json
import struct
from pathlib import Path

def analyze(path):
    groups=[]
    current=None
    packets=0
    invalid=[]
    label='unlabeled'
    for line_no,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        event=json.loads(line)
        if event['kind']=='write_start' and event.get('phase')=='start':
            label=event['label']
        if event['kind']!='notify' or event.get('handle')!=52:
            continue
        value=bytes.fromhex(event['value'])
        packets+=1
        if len(value)!=20:
            invalid.append({'line':line_no,'reason':'unexpected_length','length':len(value)})
            continue
        seq,fragment=struct.unpack_from('<HH',value)
        if current is None or fragment==0 or current['sequence']!=seq:
            current={'sequence':seq,'label':label,'time':event['time'],'fragments':{},'source_lines':[]}
            groups.append(current)
        if fragment in current['fragments']:
            invalid.append({'line':line_no,'reason':'duplicate_fragment'})
        current['fragments'][fragment]=value[4:].hex()
        current['source_lines'].append(line_no)
    complete=[g for g in groups if set(g['fragments'])=={0,1,2}]
    for g in complete:
        parts=[bytes.fromhex(g['fragments'][i]) for i in range(3)]
        g['joined_content_hex']=b''.join(parts).hex()
        g['tail_repeats_fragment1']=parts[2][-4:]==parts[1][-4:]
        g['tail_repeats_sequence']=struct.unpack_from('<H',parts[2],10)[0]==g['sequence']
        g['unknown_u16_at_content_offset40']=struct.unpack_from('<H',parts[2],8)[0]
    summary={
        'fc_packets':packets,'groups':len(groups),'complete_groups':len(complete),
        'incomplete_groups':len(groups)-len(complete),'invalid_packets':invalid,
        'sequence_discontinuities':sum(b['sequence']!=((a['sequence']+1)&65535) for a,b in zip(groups,groups[1:])),
        'tail_data_matches':sum(g['tail_repeats_fragment1'] for g in complete),
        'tail_sequence_matches':sum(g['tail_repeats_sequence'] for g in complete),
        'groups_by_experiment':dict(collections.Counter(g['label'] for g in groups)),
        'warning':'Joined content includes unknown metadata; it is not a verified audio bitstream.',
    }
    return summary,groups

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    summary,groups=analyze(args.capture)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if args.output:
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        (args.output/'groups.jsonl').write_text(''.join(json.dumps(g)+'\n' for g in groups),encoding='utf-8')

if __name__=='__main__':
    main()
