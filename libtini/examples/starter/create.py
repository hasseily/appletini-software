#!/usr/bin/env python3
"""Create an ordinary-file, self-contained C project; never links the SDK."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    destination=args.destination.expanduser().resolve()
    if destination.exists():raise SystemExit('Destination already exists: '+str(destination))
    selected=[]
    selected+=list((ROOT/'include').rglob('*.h'))
    selected+=[p for p in (ROOT/'src').glob('*') if p.suffix in ('.c','.h') and p.name!='diag.c']
    selected+=list((ROOT/'src/target').glob('*.s'))
    selected+=[ROOT/'cfg/libtini.cfg']
    selected+=[ROOT/'tools'/n for n in ('disk.py','setup_inputs.py','prodos-input.json','DEPENDENCIES.md')]
    inputs={}
    destination.mkdir(parents=True)
    for source in sorted(selected):
        if source.is_symlink() or (hasattr(source,'is_junction') and source.is_junction()):
            raise SystemExit('Required input is linked: '+str(source))
        name=source.relative_to(ROOT)
        target=destination/'runtime'/name
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        inputs[name.as_posix()]=hashlib.sha256(source.read_bytes()).hexdigest()
    for name in ('main.c','build.py'):
        shutil.copyfile(ROOT/'examples/starter'/name,destination/name)
    (destination/'.gitignore').write_text('/build/\n/runtime/build-inputs/\n__pycache__/\n*.py[cod]\n')
    (destination/'SDK_INPUTS.json').write_text(json.dumps(inputs,indent=2)+'\n')
    (destination/'README.md').write_text(
      '# My libtini project\n\nEdit `main.c`. All runtime sources and headers are ordinary copies under `runtime/`.\n'
      'No sibling checkout, temporary directory, SDK build output or link is required.\n\n'
      'Install Python 3.10+ and cc65 SDK2.19, then run:\n\n'
      '```powershell\npython runtime/tools/setup_inputs.py\npython build.py --cc65-home D:/Repos/cc65\n```\n\n'
      'Outputs: `build/APP.SYSTEM`, `build/APP.po`, map and labels. '
      '`--no-disk` builds without the separately installed ProDOS image.\n'
      'The documented baseline is existing Appletini F1.3.2; physical timing/output requires board validation. '
      'See runtime/tools/DEPENDENCIES.md for installed tools and ProDOS distribution terms.\n')
    print(destination)

if __name__=='__main__':main()
