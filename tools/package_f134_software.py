#!/usr/bin/env python3
"""Prepare local software assets for firmware F1.3.4; never publish anything."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'demos/appletini_demos/appletini_webserver'
DEMO=WEB.parent
SDK=ROOT/'libtini'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(command,cwd=ROOT,env=None,input=None,capture=False):
    return subprocess.run([str(p) for p in command],cwd=cwd,env=env,input=input,
                          stdout=subprocess.PIPE if capture else None,check=True).stdout
def savezip(path,files):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(name,(2026,10,29,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data)
    with zipfile.ZipFile(path) as z:assert z.testzip() is None
def fork(data):
    if data[:4]!=bytes.fromhex('00051600'):return data
    count=struct.unpack_from('>H',data,24)[0]
    entries=[struct.unpack_from('>III',data,26+i*12) for i in range(count)]
    parts=[(at,n) for kind,at,n in entries if kind==1]
    assert len(parts)==1
    at,n=parts[0];assert at+n==len(data)
    return data[at:at+n]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware',type=Path,required=True)
    parser.add_argument('--firmware-sha',required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'releases/1.3.4')
    parser.add_argument('--previous',type=Path,default=ROOT/'releases/1.1.0')
    parser.add_argument('--cc65-home',type=Path)
    parser.add_argument('--java-home',type=Path)
    parser.add_argument('--applecommander',type=Path,default=Path(os.environ.get('APPLECOMMANDER',r'C:\Users\hasse\tools\AppleCommander-ac-13.0.jar')))
    parser.add_argument('--skip-build',action='store_true',help='assemble already fresh canonical builds')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    assert sha(args.firmware)==args.firmware_sha
    env=os.environ.copy();bins=[]
    if args.cc65_home:bins.append(str(args.cc65_home/'bin'))
    if args.java_home:bins.insert(0,str(args.java_home/'bin'))
    env['PATH']=os.pathsep.join([*bins,env.get('PATH','')]);env['APPLECOMMANDER']=str(args.applecommander)
    ccargs=['--cc65-home',args.cc65_home] if args.cc65_home else []
    if not args.skip_build:
        run([sys.executable,'build_mono.py'],WEB,env)
        run(['cmd','/d','/c','build.bat'] if os.name=='nt' else ['sh','build.sh'],WEB,env)
        run([sys.executable,'tools/build.py',*ccargs],SDK,env)
        run([sys.executable,'tools/build.py',*ccargs,'--private','--build-dir','build/private'],SDK,env)
        run([sys.executable,'tools/release.py',*ccargs],SDK,env)
        run([sys.executable,'tools/build_appletini_demo_disk.py'],DEMO,env)
    run([sys.executable,'tools/package_mono_release.py','--output',out,
         '--firmware',args.firmware,'--firmware-sha',args.firmware_sha],WEB,env)

    spec=importlib.util.spec_from_file_location('release_disk',SDK/'tools/disk.py')
    disk=importlib.util.module_from_spec(spec);spec.loader.exec_module(disk)
    lock=json.loads((SDK/'tools/prodos-input.json').read_text());template=SDK/lock['path']
    assert sha(template)==lock['sha256']
    programs={n:(WEB/'build'/(n+'.SYSTEM')).read_bytes() for n in ('A2BROWSE','A2LEGACY','A2WEBSRV','A2IMG')}
    raw={n:fork(v) for n,v in programs.items()}
    image=disk.build_image(template.read_bytes(),raw['A2BROWSE'],'A2BROWSE.SYSTEM',
        files=[('A2LEGACY.SYSTEM',raw['A2LEGACY'],0xFF,0x2000)],volume='A2LYNX',max_program_bytes=0x9F00)
    (out/'A2LYNX.po').write_bytes(image)
    network=disk.build_image(template.read_bytes(),raw['A2BROWSE'],'A2BROWSE.SYSTEM',
        files=[(n+'.SYSTEM',raw[n],0xFF,0x2000) for n in ('A2LEGACY','A2WEBSRV','A2IMG')],
        volume='NETWORK',max_program_bytes=0x9F00)
    (out/'Appletini-Network-Apps.po').write_bytes(network)
    netfiles={n+'.SYSTEM':v for n,v in programs.items()}
    for name in ('LICENSE.txt','LICENSE-W5100.txt','SOURCE.txt'):
        netfiles['ip65/'+name]=(WEB/'ip65'/name).read_bytes()
    netfiles['README.txt']=b'A2LYNX is A2BROWSE.SYSTEM. Keep A2LEGACY.SYSTEM beside it for old-firmware fallback.\nA2WEBSRV.SYSTEM is the IP65 HTTP server; A2IMG.SYSTEM is the IP65 SHR image viewer.\nImport AppleSingle files with an aware ProDOS tool. Enable Ethernet in slot1.\n'
    savezip(out/'Appletini-Network-Apps.zip',netfiles)

    # Keep the showcase's established menu and provide an explicit ProDOS run path.
    showcase=out/'Appletini-Demos.po'
    shutil.copyfile(DEMO/'build/Appletini_Demos.po',showcase)
    java=shutil.which('java',path=env['PATH'])
    assert java and args.applecommander.is_file()
    def ac(*parts,data=None,capture=False):
        return run([java,'-jar',args.applecommander,*parts],env=env,input=data,capture=capture)
    mono={'A2MONO.SYSTEM':(WEB/'build/mono/A2MONO.bin').read_bytes()}
    mono.update({name:(WEB/'build/mono'/name).read_bytes() for name in ('MONO.WEB','MONO.NET','MONO.GIF','MONO.PNG','MONO.JPG')})
    for name,data in mono.items():
        ac('-p',showcase,name,'SYS' if name.endswith('.SYSTEM') else 'BIN','0x2000' if name.endswith('.SYSTEM') else '0x8B00',data=data)
        assert ac('-g',showcase,name,capture=True)==data,name
    combined={n:sha(WEB/'build'/(n+'.SYSTEM')) for n in programs}
    for name,data in raw.items():assert ac('-g',showcase,name+'.SYSTEM',capture=True)==data,name
    savezip(out/'Appletini-Demos.zip',{'Appletini_Demos.po':showcase.read_bytes()})
    readme='''Software for Appletini firmware F1.3.4

A2MONO.po boots the graphical HTTPS browser directly. A2MONO.zip installs it
on another volume. The welcome page is text-only and explains its controls.
A2LYNX.po boots the text browser with its separate legacy fallback.
Appletini-Network-Apps.po also contains A2WEBSRV and A2IMG.

Appletini-Demos.po includes current A2MONO, all five MONO.* overlays and the
updated native/legacy text browsers, server and image viewer. Its HGR menu
retains the established entries. To run A2MONO from this combined disk,
quit to ProDOS/Bitsy Bye and choose A2MONO.SYSTEM in the volume root, or
from Applesoft enter: PRINT CHR$(4);"-A2MONO.SYSTEM"
The standalone A2MONO.po is the direct browser boot path.

Use firmware F1.3.4. It automatically creates missing HTTPS seed pairs and
embeds 29 public roots. Replace/remove an old FAT-root ATNETCA.PEM and reboot.
See the browser README inside A2MONO.zip for display/memory requirements.

STARFALL is freshly rebuilt and byte-identical to Software 1.1.0. The SDK
archives contain current sources and rebuilt CPU/private examples. Other
game disks carry forward the accepted Software 1.1.0 bytes and original
media/licensing terms. No new board test of every retained game is claimed.
This is a coordinated software bundle for firmware F1.3.4, not a new SDK
semantic version. Nothing is published by this tool.

Current A2MONO validation covers its 25-row welcome and both HTTPS links,
no image I/O on home I, 14 download/TLS-message groups, four session/fault
groups, four reader-feature groups, 23 anchor groups and six mixed-image,
overlay-failure and mouse groups. Real Apple and
SmartPort ROMs boot the disk through its real ProDOS kernel. Standalone
6502 HTTP tests cover 16 redirect/mobile cases. Native firmware MbedTLS
verifies archive.org with the 29-root bundle, still rejects an old 28-root
override and rejects a wrong hostname. Verification rules remain enabled.
The user reports the preceding archive.org fix working on their card; this
does not claim a new full-release physical test. SDK CPU/private builds
and focused web/leaderboard host tests pass. Historical SDK evidence stays
separate from these current checks.
'''
    (out/'RELEASE_NOTES.md').write_text(readme)
    selected={'STARFALL.po':SDK/'build/starfall.po','libtini-source.zip':SDK/'dist/libtini-source.zip',
              'libtini-sdk.zip':SDK/'dist/libtini-local-release.zip'}
    previous=json.loads((args.previous/'RELEASE_MANIFEST.json').read_text())
    retained=[]
    for name in previous['assets']:
        if name in ('A2LYNX.po','Appletini-Demos.po','Appletini-Demos.zip',*selected):continue
        source=args.previous/name
        if source.suffix.lower() not in ('.po','.hdv'):continue
        selected[name]=source;retained.append(name)
    for name,source in selected.items():shutil.copyfile(source,out/name)
    assert sha(out/'STARFALL.po')==sha(args.previous/'STARFALL.po')
    validation=out/'validation'
    if validation.exists():
        savezip(out/'VALIDATION.zip',{p.relative_to(out).as_posix():p.read_bytes()
                                      for p in validation.rglob('*') if p.is_file()})
    records={}
    for p in sorted(out.iterdir()):
        if p.is_file() and p.suffix.lower()!='.log' and p.name not in ('SHA256SUMS.txt','RELEASE_MANIFEST.json','SOURCE_STATE.json'):
            records[p.name]={'bytes':p.stat().st_size,'sha256':sha(p)}
            if p.name in retained:
                records[p.name]['unchanged_from']='software1.1.0'
                assert sha(p)==previous['assets'][p.name]['sha256']
    git=run(['git','rev-parse','HEAD'],capture=True).decode().strip()
    status=run(['git','status','--short'],capture=True).decode()
    state={'head_commit':git,'working_tree_modified':bool(status.strip()),'status':status,
           'note':'Release is prepared from the current working tree; no commit, tag, push or publication is performed.'}
    (out/'SOURCE_STATE.json').write_text(json.dumps(state,indent=2)+'\n')
    report={'release':'Software for firmware F1.3.4','firmware_sha256':args.firmware_sha,
            'assets':records,'network_program_inputs':combined,
            'showcase_mono_programs':{n:hashlib.sha256(d).hexdigest() for n,d in mono.items()},
            'fresh_starfall_identical_to_1_1_0':True,'new_full_release_board_test':False}
    (out/'RELEASE_MANIFEST.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(out.iterdir()) if p.is_file() and p.suffix.lower()!='.log' and p.name!='SHA256SUMS.txt'),newline='\n')
    print(json.dumps({'release':str(out),'assets':len(records),'A2MONO.po':sha(out/'A2MONO.po'),
                      'A2MONO.zip':sha(out/'A2MONO.zip'),'A2LYNX.po':sha(out/'A2LYNX.po'),
                      'Appletini-Demos.po':sha(showcase),'published':False},indent=2))

if __name__=='__main__':main()
