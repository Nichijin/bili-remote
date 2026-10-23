"""Check the actual EXE's authenticated mouse stream without moving/clicking.

Uses temporary pairing/settings, a unique instance identity and loopback port.
All cumulative coordinates are exactly zero; no native input is injected.
"""
import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from websockets.asyncio.client import connect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desktop.trust import TrustStore


async def check(port,token):
    url=f'ws://127.0.0.1:{port}'
    async with connect(url) as ws:
        await ws.send(json.dumps({'role':'remote','device_id':'packaged-mouse-test','token':token}))
        assert json.loads(await ws.recv())['ok']
        await ws.send(json.dumps({'id':1,'cmd':'mouse_start','stream':2}))
        result=json.loads(await ws.recv())
        assert result['ok'] and result['result']['mouse_stream']==2
        session=result['result']['mouse_session']
        for i in range(1,121):
            # Never replace zero coordinates with a real movement in this test.
            await ws.send(json.dumps({'cmd':'mouse_frame','mouse_session':session,'seq':i,'t':i*8,'x':0,'y':0}))
        for i in range(1,121):
            ack=json.loads(await asyncio.wait_for(ws.recv(),3))
            assert ack=={'type':'mouse_ack','ok':True,'seq':i,'mouse_session':session}
        await ws.send(json.dumps({'id':2,'cmd':'mouse_end','mouse_session':session}))
        assert json.loads(await ws.recv())['ok']
        await ws.send(json.dumps({'id':3,'cmd':'mouse_keep','mouse_session':session}))
        assert not json.loads(await ws.recv())['ok']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,default=ROOT/'dist/BiliRemote-Desktop.exe');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='bili-mouse-package-') as directory:
        data=Path(directory);trust=TrustStore(data/'trust.json');token=trust.allow('packaged-mouse-test','isolated fixture')
        (data/'settings.json').write_text(json.dumps({'show_feedback':False}),encoding='utf-8')
        with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        identity='BiliRemote-MousePackage-'+uuid.uuid4().hex
        env={**os.environ,'BILI_REMOTE_DATA_DIR':str(data),'BILI_REMOTE_INSTANCE_NAME':identity,'BILI_REMOTE_WINDOW_TITLE':identity,'BILI_REMOTE_PORT':str(port),'BILI_REMOTE_DISCOVERY_PORT':'0','BILI_REMOTE_BIND_HOST':'127.0.0.1'}
        process=subprocess.Popen([str(args.exe),'--background'],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+15
            while True:
                assert process.poll() is None,'Packaged application exited'
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.1): break
                except OSError:
                    if time.monotonic()>deadline:raise TimeoutError('Packaged service unavailable')
                    time.sleep(.05)
            asyncio.run(check(port,token))
        finally:
            if process.poll() is None:
                subprocess.run([str(args.exe),'--quit'],env=env,creationflags=subprocess.CREATE_NO_WINDOW,check=True,timeout=10)
                process.wait(timeout=15)
        report={'actual_exe':True,'stream_v2_negotiated':True,'ordered_acknowledgements':120,'mode_end_rejects_old_lease':True,'isolated_data_and_ports':True,'native_input_injected':False,'clean_exit':True}
        (ROOT/'.tooling/packaged-mouse0512.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))


if __name__=='__main__': main()
