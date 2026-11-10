import fcntl,hashlib,json,os,pathlib,socket,subprocess,sys,time
root=pathlib.Path("/Users/dido/Developer.localized/SIGMAfp_re")
out=pathlib.Path(__file__).resolve().parent
sh=root/"fpSup/fp_usb_shell"
lease=open("/tmp/fp-af-fusion.lock","a+")
fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
meta={"owner":"Codex /root SensorLab LCD crop verification","pid":os.getpid(),"started":time.time(),"out":str(out),"state":"held"}
lease.seek(0);lease.truncate();lease.write(json.dumps(meta)+"\n");lease.flush()
daemon=None

def status(command):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(8);s.connect("/tmp/fpshd.sock");s.sendall(command.encode()+b"\n")
        data=b""
        while not data.endswith(b"\n"):
            part=s.recv(4096)
            if not part:break
            data+=part
    return data.decode().strip()

def start():
    global daemon
    ps=subprocess.check_output(["/bin/ps","-axo","pid=,comm="],text=True)
    owners=[x for x in ps.splitlines() if pathlib.Path(x.split(None,1)[1]).name=="fpshd"]
    if owners:raise RuntimeError("existing fpshd: "+repr(owners))
    try:
        ans=status("STATUS")
    except (FileNotFoundError,ConnectionRefusedError):pass
    else:raise RuntimeError("socket has an existing owner: "+ans)
    log=open(out/("fpshd-"+str(int(time.time()))+".log"),"ab",buffering=0)
    daemon=subprocess.Popen([str(sh/"fpshd"),"--timeout","2000"],cwd=sh,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    time.sleep(.3)
    if daemon.poll() is not None:raise RuntimeError("daemon did not start")
    meta["daemon_pid"]=daemon.pid
    meta["daemon_sha256"]=hashlib.sha256((sh/"fpshd").read_bytes()).hexdigest()
    (out/"owner.json").write_text(json.dumps(meta,indent=2)+"\n")
    return {"daemon_pid":daemon.pid,"host_status":status("STATUS")}

print(json.dumps({"lease_pid":os.getpid(),"out":str(out),"started":start()}),flush=True)
for line in sys.stdin:
    action=line.strip()
    if action=="status":print(json.dumps({"status":status("STATUS")}),flush=True)
    elif action=="stop_daemon":
        if daemon is None or daemon.poll() is not None:raise RuntimeError("owned daemon absent")
        ans=status("QUIT");assert ans=="OK bye",ans
        daemon.wait(timeout=8);print(json.dumps({"stopped":daemon.pid}),flush=True)
    elif action=="start_daemon":print(json.dumps(start()),flush=True)
    elif action=="release":
        meta["state"]="released";meta["released"]=time.time()
        lease.seek(0);lease.truncate();lease.write(json.dumps(meta)+"\n");lease.flush()
        (out/"owner-released.json").write_text(json.dumps(meta,indent=2)+"\n")
        print("lease released",flush=True);break
    else:print("unknown action",flush=True)
lease.close()
