"""Audit screenshot registration, then apply a source-bound visual review."""
import argparse
import json
from pathlib import Path
from voxel_mapper.view_registration import audit, apply_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    for name in ('audit','apply'):
        cmd = sub.add_parser(name)
        for option in ('dataset','reference','output'):
            cmd.add_argument('--'+option,type=Path,required=True)
        if name=='audit':
            cmd.add_argument('--long-side',type=int,default=1024)
        else:
            for option in ('primary','repeat','review'):
                cmd.add_argument('--'+option,type=Path,required=True)
            cmd.add_argument('--buffer-m',type=float,default=32.)
    args = parser.parse_args()
    if args.command=='audit':
        report = audit(args.dataset,args.reference,args.output,long_side=args.long_side)
        print(json.dumps({'views':len(report['views']),'validated_candidates':sum(r['status']=='validated_relative_candidate' for r in report['views'])}))
    else:
        report = apply_review(args.dataset,args.reference,json.loads(args.primary.read_text()),
                              json.loads(args.repeat.read_text()),json.loads(args.review.read_text()),
                              args.output,buffer_m=args.buffer_m)
        print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
