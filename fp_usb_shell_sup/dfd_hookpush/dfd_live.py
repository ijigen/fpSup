#!/usr/bin/env python3
"""DFD live 工作台 — 綠通道 AF-band profile via hook-push (BATCHPUSH), 瀏覽器 live 顯示。

背景執行緒配速迴圈:BATCHPUSH 1 綠幀(push_N_green 零拷貝推 → /tmp/batchpush.bin)+ peek mposm/peakNow,
解出 256 線綠 band profile,服務到 http://localhost:8771/。用 MF/半按 AF 掃焦看 profile 變化。
零 read_mem 大塊、零 RAWGRAB;綠資料走 hook-push 快路(~0.125ms/幀)。
"""
import sys, socket, struct, threading, time, json
sys.path.insert(0, 'monitor')
import fpstate as F
from http.server import BaseHTTPRequestHandler, HTTPServer

BATCHFILE='/tmp/batchpush.bin'; N=256
sh=F.Shell('/tmp/fpshell.sock', mock=False)
def si(a):
    return struct.unpack('<i', struct.pack('<I', sh.peek32(a)))[0]

def daemon_cmd(line, to=10):
    s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.settimeout(to)
    try:
        s.connect('/tmp/fpshell.sock'); s.sendall((line+'\n').encode()); b=b''
        while len(b)<512:
            c=s.recv(512)
            if not c: break
            b+=c
            if b'\n' in b: break
        return b.decode(errors='replace')
    finally: s.close()

STATE={'mposm':0,'peak':0,'peakmax':0,'gafpos':0,'alive':False,'profile':[],'greenlive':False}
LOCK=threading.Lock()

def poller():
    sh._ensure_peek()
    while True:
        try:
            mp=si(0xC3291958); pn=si(0xC32915C4); pmx=si(0xC32915C8); gp=si(0xC32914E0)
            green=si(0xC3404768)
            live = 0x44000000 <= (green & 0xFFFFFFFF) < 0x60000000
            r=daemon_cmd("BATCHPUSH 1024 1")
            prof=[0]*N
            if 'OK frames=1/1' in r:
                with open(BATCHFILE,'rb') as f: d=f.read(1024)
                if len(d)>=1024: prof=list(struct.unpack('<%di'%N, d))
            with LOCK:
                STATE.update(mposm=mp,peak=pn,peakmax=pmx,gafpos=gp,alive=True,profile=prof,greenlive=live)
        except Exception:
            with LOCK: STATE['alive']=False
        time.sleep(0.08)   # ~12Hz,配速 AF 更新率,避免 over-push

PAGE=("""<!doctype html><meta charset=utf-8><title>DFD Live</title>
<style>body{background:#0d0d0d;color:#ddd;font-family:ui-monospace,monospace;margin:16px}
h1{font-size:15px;color:#6f6}.v{font-size:20px;color:#fd6}.lab{color:#888;font-size:12px}
#s{color:#6f6}.dead{color:#f66}#g{color:#6f6}.off{color:#f80}canvas{background:#151515;border:1px solid #333;margin-top:10px}</style>
<h1>DFD Live 工作台 — 綠通道 AF-band profile (hook-push)</h1>
<div><span class=lab>shell</span> <span id=s>?</span> &nbsp;
<span class=lab>綠源</span> <span id=g>?</span> &nbsp;
<span class=lab>mposm</span> <span class=v id=mp>-</span> &nbsp;
<span class=lab>peakNow</span> <span class=v id=pn>-</span> &nbsp;
<span class=lab>band總和</span> <span id=sum>-</span></div>
<div class=lab style=margin-top:6px>半按 AF-C 讓「綠源」亮綠 → MF/掃焦看 profile 起伏(合焦=利、失焦=平)</div>
<canvas id=c width=900 height=320></canvas>
<script>
async function tick(){try{let d=await(await fetch('/data.json')).json();
 P('s',d.alive?'alive':'busy');document.getElementById('s').className=d.alive?'':'dead';
 P('g',d.greenlive?'LIVE':'off(半按AF)');document.getElementById('g').className=d.greenlive?'':'off';
 P('mp',d.mposm);P('pn',d.peak);P('sum',d.profile.reduce((a,b)=>a+Math.abs(b),0));draw(d.profile);}catch(e){}}
function P(id,v){document.getElementById(id).textContent=v;}
function draw(p){let c=document.getElementById('c'),g=c.getContext('2d');g.clearRect(0,0,c.width,c.height);
 if(!p||p.length<2)return;let mx=Math.max(...p.map(Math.abs))||1,W=c.width-20,H=c.height-30;
 g.strokeStyle='#6f6';g.lineWidth=1.4;g.beginPath();
 p.forEach((v,i)=>{let x=10+i/(p.length-1)*W,y=10+H-Math.abs(v)/mx*H;i?g.lineTo(x,y):g.moveTo(x,y);});g.stroke();
 g.fillStyle='#888';g.font='11px monospace';g.fillText('綠band線 0→'+(p.length-1)+'  峰='+mx,14,c.height-8);}
setInterval(tick,120);tick();
</script>""").encode('utf-8')

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path=='/data.json':
            with LOCK: body=json.dumps(STATE).encode()
            self.send_response(200); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(PAGE))); self.end_headers(); self.wfile.write(PAGE)

if __name__=='__main__':
    threading.Thread(target=poller,daemon=True).start()
    print('DFD Live 工作台: http://localhost:8771/')
    HTTPServer(('127.0.0.1',8771),H).serve_forever()
