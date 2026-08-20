#!/usr/bin/env python3
"""fpstate.py — SIGMA fp 萬能監控台 (all-purpose monitor) host reader + web server.

Reads live camera state over the USB shell's `mem read` and serves dashboard.html
+ /state.json. Each item is a pointer-chase + interpretation using the RE'd
addresses (notes/CAMERA_STATE_SOURCES.md, notes/AF_LIVE_STATE_MAP.md,
SIGMA_FP_INTERNAL_GYRO_ARCHIVE). Run with --mock to develop the UI without a camera;
the real backend needs the daemon to return mem-read payloads as HEX (Codex host item).

Usage:
  ./fpstate.py --mock                 # synthetic data, open http://localhost:8770/
  ./fpstate.py --socket /tmp/fpshell.sock   # real (needs hex-capable daemon)
"""
import argparse, http.server, json, math, os, socket, struct, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- addresses (from RE notes) ----------
A_GYRO_MBOX   = 0xC31E3FCC   # -> P (0x2E006004); ring_base = *(P+0x60); samples 8B {i16 X,Y,pad,Z}, /131 dps
A_ACCEL       = 0xC377790C   # MMA8452Q level cache: i16 X,Y,Z axis-remapped; g = raw/1024, ~100Hz
# ---- IMU one-call snapshot blob (camera/imu_snapshot.S) injected into the worker cave ----
# gathers accel XYZ + gyro-latest into RESULT in ONE `call`; host drains in ONE read (2 transactions).
# gyro latest sample = *(rb) - 4 ; rb = *(*(0xC31E3FCC)+0x60) ; scale /131 (=*(P+0x68)) dps, /1024 g.
SNAP_CODE, SNAP_RESULT = 0xC072F200, 0xC072F300
SNAP_WORDS = (
    0xE92D00F0, 0xE59F2058, 0xE59F1058, 0xE1D130F0, 0xE1D140F2, 0xE1D150F4, 0xE1C230B0,
    0xE1C240B2, 0xE1C250B4, 0xE59F1040, 0xE5911000, 0xE5916060, 0xE5967000, 0xE5827008,
    0xE2473004, 0xE1D340F0, 0xE1D350F2, 0xE1D300F6, 0xE1C240BC, 0xE1C250BE, 0xE1C201B0,
    0xE59F3014, 0xE5823014, 0xE8BD00F0, 0xE12FFF1E, 0xC072F300, 0xC377790C, 0xC31E3FCC,
    0x494D5530,
)
A_GAIN_G      = 0xC343A6A0   # +0x0c gain_state, +0x18 ISO/rel, +0x2c analog gain, +0x34 HCG byte
A_AF_DRIVE    = 0xC32065A0   # 4/8 = AF-C servo
A_AF_AREA     = 0xC32046A4   # 0 single /1 MF /3 tracking /5 global
A_AF_ROUTE    = 0xC32915B0
A_AF_CON_HI   = 0xC32985E8
A_AF_CON_LO   = 0xC32986B4
A_AF_PEAK_NOW = 0xC32915C4
A_AF_BODYMOT  = 0xC3404678   # +0x04 body-motion flag
A_DRIFT       = 0xC33D1958
A_AAT_BOX     = 0xC3033E00   # {i16 x,y,w,h}; conf @0xC3033E26
A_FACES       = 0xC37CCA9C   # 5 groups, stride 0x9C, rect@+0x3E0, mode@+0x3D0; 320x213 space
A_WORKER      = 0xC072F000   # our shell state ([0x5C]=cmds, [0x58]=faults)

# ---------- shell backend ----------
class Shell:
    def __init__(self, sockpath, mock=False):
        self.sockpath, self.mock = sockpath, mock
        self._t0 = time.time()
    MAXCHUNK = 44   # FPSH payload cap; larger reads are chunked
    def read_mem(self, addr, n):
        if self.mock:
            return self._mock(addr, n)
        out = bytearray()
        off = 0
        while off < n:
            c = min(self.MAXCHUNK, n - off)
            out += self._read1(addr + off, c)
            off += c
        return bytes(out)
    def _read1(self, addr, n):
        # one shell mem-read (<=44 bytes). The daemon's "payload=" is followed by the RAW payload
        # bytes (%.*s byte-copy). We take exactly n bytes after it (binary-safe, no hex needed).
        raw = self._round(f"ECHO mem read 0x{addr:08X} {n}\n")
        j = raw.find(b"payload_hex=")
        if j >= 0:
            return bytes.fromhex(raw[j+12:].split(b"\n",1)[0].decode())[:n]
        i = raw.find(b"payload=")
        if i < 0:
            raise IOError(f"unexpected: {raw[:80]!r}")
        return raw[i+8 : i+8+n]
    # ---- generic peek (deref ANY address via the deployed worker; no read-table entry needed) ----
    # inject-once routine @0xC072F100: ldr r1,[r0,#0x64]; ldr r2,[r1]; str r2,[r0,#0x68]; bx lr
    PEEK_CODE = 0xC072F100
    PEEK_ARG  = 0xC072F064   # STATE+0x64 (scratch): address to deref
    PEEK_RES  = 0xC072F068   # STATE+0x68 (scratch): 32-bit result
    PEEK_WORDS = (0xE5901064, 0xE5912000, 0xE5802068, 0xE12FFF1E)
    def _set_mem(self, addr, val):
        self._round(f"ECHO mem set 0x{addr:08X} 0x{val & 0xFFFFFFFF:08X}\n")
    def _call(self, addr):
        self._round(f"ECHO call 0x{addr:08X}\n")
    def _ensure_peek(self):
        if getattr(self, "_peek_ready", False): return
        for i, w in enumerate(self.PEEK_WORDS):
            self._set_mem(self.PEEK_CODE + 4*i, w)
        self._peek_ready = True
    def peek32(self, addr):
        if self.mock:
            return struct.unpack('<I', self._mock(addr, 4))[0]
        self._ensure_peek()
        self._set_mem(self.PEEK_ARG, addr)
        self._call(self.PEEK_CODE)
        return struct.unpack('<I', self.read_mem(self.PEEK_RES, 4))[0]
    # ---- one-call IMU snapshot: accel XYZ + gyro-latest in 2 transactions ----
    def _ensure_snap(self):
        if getattr(self, "_snap_ready", False): return
        for i, w in enumerate(SNAP_WORDS):
            self._set_mem(SNAP_CODE + 4*i, w)
        self._snap_ready = True
    def imu(self):
        if self.mock:
            t = time.time() - self._t0
            gx,gy,gz = 200*math.sin(t*1.7), 150*math.sin(t*1.1+1), 90*math.sin(t*0.7+2)
            ax,ay,az = 120*math.sin(t*0.5), 90*math.cos(t*0.4), 1024
            return {"accel":{"x":ax/1024,"y":ay/1024,"z":az/1024},
                    "gyro":{"x":gx/131,"y":gy/131,"z":gz/131}, "cursor":0}
        self._ensure_snap()
        self._call(SNAP_CODE)
        raw = self.read_mem(SNAP_RESULT, 0x18)
        if struct.unpack_from('<I', raw, 0x14)[0] != 0x494D5530:
            raise IOError("IMU snapshot magic mismatch")
        ax,ay,az = struct.unpack_from('<hhh', raw, 0)
        cur = struct.unpack_from('<I', raw, 8)[0]
        gx,gy,gz = struct.unpack_from('<hhh', raw, 0x0C)
        return {"accel":{"x":ax/1024.0,"y":ay/1024.0,"z":az/1024.0},
                "gyro":{"x":gx/131.0,"y":gy/131.0,"z":gz/131.0}, "cursor":cur}
    def _round(self, line):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(65)
        try:
            s.connect(self.sockpath); s.sendall(line.encode())
            buf = b""
            while len(buf) < 4096:
                chunk = s.recv(4096)
                if not chunk: break
                buf += chunk
                if b"\n" in buf and b"payload" in buf and len(buf) >= 60: break
            return buf
        finally:
            s.close()
    def _mock(self, addr, n):
        t = time.time() - self._t0
        b = bytearray(n)
        if addr == A_GYRO_MBOX: struct.pack_into('<I', b, 0, 0x2E006004)
        elif addr == 0x2E006004+0x60: struct.pack_into('<I', b, 0, 0x2E00644C)
        elif addr == 0x2E00644C: struct.pack_into('<I', b, 0, 8)           # head
        elif addr == 0x2E00644C+4: struct.pack_into('<hhhh', b, 0,
                int(2000*math.sin(t*1.7)), int(1500*math.sin(t*1.1+1)), int(900*math.sin(t*0.7+2)), 0)
        elif addr == A_ACCEL:                                   # peek word0: X,Y
            struct.pack_into('<hh', b, 0, int(120*math.sin(t*0.5)), int(90*math.cos(t*0.4)))
        elif addr == A_ACCEL+4:                                 # peek word1: Z
            struct.pack_into('<h', b, 0, 1024)
        elif addr == A_GAIN_G:
            struct.pack_into('<I', b, 0x0c, 3); struct.pack_into('<I', b, 0x18, 640)
            struct.pack_into('<I', b, 0x2c, 0x00010000); b[0x34] = 1
        elif addr == A_AF_DRIVE: struct.pack_into('<I', b, 0, 8 if int(t)%6<3 else 4)
        elif addr == A_AF_AREA: struct.pack_into('<I', b, 0, 3)
        elif addr == A_AF_ROUTE: struct.pack_into('<I', b, 0, int(t)%3)
        elif addr in (A_AF_CON_HI, A_AF_PEAK_NOW): struct.pack_into('<I', b, 0, int(1200+400*math.sin(t*2)))
        elif addr == A_AAT_BOX:
            struct.pack_into('<hhhh', b, 0, int(120+40*math.sin(t)), int(90+20*math.cos(t)), 70, 70)
            if n>0x26: struct.pack_into('<h', b, 0x26, 82)
        elif addr == A_FACES+0x3D0: struct.pack_into('<I', b, 0, 1)   # face mode on
        elif addr == A_FACES+0x3E0:
            struct.pack_into('<hhhh', b, 0, int(60+30*math.sin(t*0.6)), 70, 64, 64)
        elif addr == A_WORKER:
            struct.pack_into('<I', b, 0x5c, int(t*3)); struct.pack_into('<I', b, 0x58, 0)
        return bytes(b)

def u32(sh,a): return struct.unpack('<I', sh.read_mem(a,4))[0]

def imu_state(sh):
    """Fast IMU-only read (2 transactions) with derived level angles."""
    imu = sh.imu()
    a = imu["accel"]
    roll  = math.degrees(math.atan2(a["x"], math.hypot(a["y"],a["z"])))
    pitch = math.degrees(math.atan2(a["y"], math.hypot(a["x"],a["z"])))
    return {"ts": time.time(), "gyro": imu["gyro"],
            "accel": {**a, "roll":roll, "pitch":pitch,
                      "mag": math.sqrt(a["x"]**2+a["y"]**2+a["z"]**2)}}

# ---------- pollers ----------
_cache = {}
def poll(sh):
    st = {"source": "mock" if sh.mock else "usb-shell", "ts": time.time()}
    try:
        # ONE injected-snapshot call gathers gyro-latest + accel XYZ (2 transactions vs ~8)
        imu = sh.imu()
        st["gyro"] = imu["gyro"]
        gx,gy,gz = imu["accel"]["x"], imu["accel"]["y"], imu["accel"]["z"]
        # provisional level: gravity mostly on Z; roll = lateral tilt, pitch = fwd/back tilt
        roll  = math.degrees(math.atan2(gx, math.hypot(gy,gz)))
        pitch = math.degrees(math.atan2(gy, math.hypot(gx,gz)))
        st["accel"] = {"x":gx, "y":gy, "z":gz, "roll":roll, "pitch":pitch,
                       "mag": math.sqrt(gx*gx+gy*gy+gz*gz)}
    except Exception as e: st["imu_err"]=str(e)
    try:
        g = sh.read_mem(A_GAIN_G+0x0c, 0x2c)    # one 44B read covers gain_state..HCG
        st["exposure"] = {"gain_state": struct.unpack_from('<I',g,0x00)[0],
                          "iso": struct.unpack_from('<I',g,0x0c)[0],
                          "analog_gain": struct.unpack_from('<I',g,0x20)[0]/65536.0,
                          "hcg": bool(g[0x28])}
    except Exception as e: st["exposure_err"]=str(e)
    try:
        drive=u32(sh,A_AF_DRIVE); area=u32(sh,A_AF_AREA); route=u32(sh,A_AF_ROUTE)
        st["af"] = {"mode": {0:"single",1:"MF",3:"tracking",5:"global"}.get(area,str(area)),
                    "state": "searching" if drive in (4,8) else "idle",
                    "contrast_peak": u32(sh,A_AF_CON_HI),
                    "drift": u32(sh,A_DRIFT)&0xffff}
    except Exception as e: st["af_err"]=str(e)
    try:
        a = sh.read_mem(A_AAT_BOX, 0x28)
        x,y,w,h = struct.unpack_from('<hhhh',a,0); conf=struct.unpack_from('<h',a,0x26)[0]
        st["aat"] = {"x":x,"y":y,"w":w,"h":h,"confidence":conf}
    except Exception as e: st["aat_err"]=str(e)
    try:
        # targeted small reads (mem-read is <=44B; big-struct layout TBD via live probe)
        mode = u32(sh, A_FACES+0x3D0)
        x,y,w,h = struct.unpack('<hhhh', sh.read_mem(A_FACES+0x3E0, 8))
        st["faces"] = [{"x":x,"y":y,"w":w,"h":h}] if (mode and w>0) else []
    except Exception as e: st["faces_err"]=str(e)
    try:
        w = sh.read_mem(A_WORKER, 0x80)
        st["shell"] = {"commands": struct.unpack_from('<I',w,0x5c)[0],
                       "faults": struct.unpack_from('<I',w,0x58)[0]}
    except Exception as e: st["shell_err"]=str(e)
    return st

# ---------- server ----------
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path.startswith("/imu.json"):
            try: data = json.dumps(imu_state(self.server.shell)).encode()
            except Exception as e: data = json.dumps({"imu_err":str(e)}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        elif self.path.startswith("/state.json"):
            data = json.dumps(poll(self.server.shell)).encode()
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        else:
            try: body=open(os.path.join(HERE,"dashboard.html"),"rb").read()
            except OSError: body=b"dashboard.html missing"
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--socket", default=os.environ.get("FPSHELL_SOCKET","/tmp/fpshell.sock"))
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--port", type=int, default=8770)
    args=ap.parse_args()
    srv=http.server.ThreadingHTTPServer(("127.0.0.1",args.port), Handler)
    srv.shell=Shell(args.socket, mock=args.mock)
    print(f"SIGMA fp 萬能監控台 → http://localhost:{args.port}/   ({'MOCK' if args.mock else 'live '+args.socket})")
    srv.serve_forever()

if __name__=="__main__":
    main()
