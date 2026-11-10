#!/usr/bin/env python3
"""Decode a previously saved 176-byte SLTP state. Offline only."""
import argparse
import json
import pathlib
import struct

FIELDS='magic version req_mode req_seq seen_seq active_seq done_seq phase mode error reject_seq reject_error task_id task_rc accepted_us phase_us done_us n_events cine_at_arm busy_at_arm'.split()
OFF={n:4*i for i,n in enumerate(FIELDS)}
PHASES='idle arm_wait play_held play_settle ok_held observe s1_held exit_wait done rejected init_failed'.split()
KEYS=['','PLAYON','PLAYOFF','OKON','OKOFF','S1ON','S1OFF']
ERRORS=['none','bad_mode','not_cine','record_busy','active','task_create_failed','task_start_failed']

def parse(raw):
    if len(raw)<176:raise ValueError('need the full 176-byte state')
    d=dict(zip(FIELDS,struct.unpack_from('<20I',raw)))
    if (d['magic'],d['version'])!=(0x31505453,1) or d['n_events']>6:raise ValueError('not SLTP v1 state')
    d['phase_name']=PHASES[d['phase']] if d['phase']<len(PHASES) else 'unknown'
    d['error_name']=ERRORS[d['error']] if d['error']<len(ERRORS) else 'unknown'
    d['events']=[]
    for i in range(d['n_events']):
        key,entered,returned,rc=struct.unpack_from('<4I',raw,80+16*i)
        d['events'].append(dict(key=KEYS[key] if key<len(KEYS) else 'unknown',entered_us=entered,
                                returned_us=returned,rc=rc,
                                since_accept_us=(entered-d['accepted_us'])&0xffffffff))
    d['sequence_completed']=d['phase']==8 and d['done_seq']==d['active_seq'] and bool(d['done_seq'])
    d['physical_exit_verified']=False
    return d

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('state',type=pathlib.Path)
    a=ap.parse_args();print(json.dumps(parse(a.state.read_bytes()),indent=2))
