#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Package a fresh A2MONO build with durable, explicitly scoped evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mono_disk import extract

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def archive(path,entries):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as output:
        for name,data in sorted(entries.items()):
            item=zipfile.ZipInfo(name,(2026,10,29,0,0,0))
            item.compress_type=zipfile.ZIP_DEFLATED
            output.writestr(item,data)
    with zipfile.ZipFile(path) as check:
        assert check.testzip() is None
        for name,data in entries.items():assert check.read(name)==data

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=ROOT/'build/mono')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,default=ROOT/'evidence/F1.3.4')
    parser.add_argument('--firmware',type=Path,required=True)
    parser.add_argument('--firmware-sha',required=True)
    args=parser.parse_args()
    build=args.build.resolve();out=args.output.resolve();evidence=args.evidence.resolve()
    out.mkdir(parents=True,exist_ok=True)
    assert sha(args.firmware)==args.firmware_sha
    expected=json.loads((evidence/'current/runtime-inputs.json').read_text())
    for name,value in expected.items():assert sha(build/name)==value,name
    program=sha(build/'A2MONO.bin')
    ca=json.loads((ROOT/'https/roots.json').read_text())
    assert len(ca['roots'])==29 and sha(ROOT/'https/ATNETCA.PEM')==ca['sha256']
    meta=json.loads((build/'manifest.json').read_text())
    entries={name:(build/name).read_bytes() for name in meta['files']}
    # Use current project copies, not an old build's HTTPS directory.
    for p in sorted((ROOT/'https').iterdir()):
        if p.is_file():entries['HTTPS/'+p.name]=p.read_bytes()
    for name in ('README_MONO.md','LICENSE_MONO.txt','third_party/picojpeg/SOURCE.txt',
                 'third_party/picojpeg/picojpeg.c','third_party/picojpeg/picojpeg.h'):
        entries[name]=(ROOT/name).read_bytes()
    for p in sorted(evidence.rglob('*')):
        if p.is_file():entries['verification/'+p.relative_to(evidence).as_posix()]=p.read_bytes()
    for name in ('welcome-validation.json','download-browser.json','descriptor-investigation.json',
                 'reader-features.json','anchor-navigation.json','integration/integration.json'):
        report=json.loads((evidence/'current'/name).read_text())
        assert report['program_sha256']==program,(name,report['program_sha256'],program)
    source_files=[ROOT/name for name in ('build_mono.py','mono-system.cfg','mono_disk.py')]
    source_files+=list(ROOT.glob('mono_*.[chs]'))
    source_files+=list((ROOT/'http_client').rglob('*.c'))+list((ROOT/'http_client').rglob('*.s'))+list((ROOT/'http_client').rglob('*.h'))
    source_files+=[Path(__file__).resolve()]
    entries['SOURCE_HASHES.json']=(json.dumps({p.relative_to(ROOT).as_posix():sha(p)
                                              for p in sorted(source_files)},indent=2)+'\n').encode()
    notice=f'''A2MONO for Appletini firmware F1.3.4

Boot A2MONO.po on a SmartPort drive. For another ProDOS volume, import
AppleSingle A2MONO.SYSTEM and copy all five matching MONO.* overlays.
The text-only welcome explains the program and links to Appletini and
Example.com. Press G for a URL. Images wait for I on each page.

Matching FIRMWARE.BIN SHA-256:
{args.firmware_sha}
Firmware is supplied separately. Target 33 MHz or faster.

The bundled 29-root CA set includes Go Daddy Root Certificate Authority - G2.
An existing ATNETCA.PEM in the FAT SD root overrides embedded roots. Replace
it with HTTPS/ATNETCA.PEM, or remove it to use F1.3.4's embedded roots, and
reboot. Keep private seed files. A PEM inside the ProDOS image does not
change the ARM service's trust store.

The user accepted the preceding archive.org fix on a card. The new welcome
page has CPU/rendering/link tests; no new full-release board test is claimed.
Verification records distinguish native TLS, actual simulated CPU/ProDOS,
historical baselines and the current final runtime. Read README_MONO.md.
'''
    entries['README_A2MONO.txt']=notice.encode()
    manifest={'release':'Software for firmware F1.3.4','program_sha256':program,
              'firmware_sha256':args.firmware_sha,'ca_roots':29,'ca_sha256':ca['sha256'],
              'new_full_release_board_test':False,
              'files':{n:{'bytes':len(d),'sha256':hashlib.sha256(d).hexdigest()} for n,d in sorted(entries.items())}}
    entries['MANIFEST.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    disk=entries['A2MONO.po']
    assert extract(disk,'A2MONO.SYSTEM')==(build/'A2MONO.bin').read_bytes()
    for name in ('MONO.WEB','MONO.NET','MONO.GIF','MONO.PNG','MONO.JPG'):
        assert extract(disk,name)==entries[name]
    (out/'A2MONO.po').write_bytes(disk)
    archive(out/'A2MONO.zip',entries)
    (out/'A2MONO-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'A2MONO.po':sha(out/'A2MONO.po'),'A2MONO.zip':sha(out/'A2MONO.zip'),
                      'program_sha256':program,'zip_verified':True,'disk_contents_verified':True},indent=2))

if __name__=='__main__':main()
