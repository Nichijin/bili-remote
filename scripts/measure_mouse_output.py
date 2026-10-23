"""Measure the real output worker/timer with synthetic input and a capture backend.

Never inject into the user's desktop. This measures this host's scheduling,
not the phone's touch rate, WiFi latency or display scanout.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desktop.mouse_motion import MotionWorker, PreciseWait


class Capture:
    def __init__(self): self.events=[]
    def move(self,x,y): self.events.append((time.perf_counter(),x,y))
    def click(self,button): raise AssertionError("No clicks in timing measurement")


def percentile(values,percent):
    return sorted(values)[round((len(values)-1)*percent)]


def measure(jitter):
    backend=Capture();worker=MotionWorker(backend);timer=PreciseWait()
    started=time.perf_counter()
    try:
        for index in range(121):
            stamp=index/60
            due=started+stamp+([0,.004,-.003,.001][index%4] if jitter else 0)
            timer.wait(max(0,due-time.perf_counter()))
            worker.submit({"seq":index+1,"t":stamp*1000,"x":stamp*240,"y":0})
        timer.wait(.050)
    finally:
        worker.close();timer.close()
    count=len(backend.events)
    time.sleep(.025)
    assert len(backend.events)==count and not worker.thread.is_alive()
    assert sum(event[1] for event in backend.events)==480
    steady=[e for e in backend.events if started+.25<=e[0]<=started+1.9]
    intervals=[(b[0]-a[0])*1000 for a,b in zip(steady,steady[1:])]
    return {"input_hz":60,"jitter_ms":[0,4,-3,1] if jitter else [0],
            "output_updates_per_second":round((len(steady)-1)/(steady[-1][0]-steady[0][0]),2),
            "interval_p50_ms":round(statistics.median(intervals),3),
            "interval_p95_ms":round(percentile(intervals,.95),3),
            "interval_max_ms":round(max(intervals),3),"endpoint":480,
            "thread_stopped":True,"post_stop_output":0}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'.tooling/mouse-output0512.json');parser.add_argument('--assert-smooth',action='store_true');args=parser.parse_args()
    report={"method":"Actual Windows high-resolution timer and output thread, synthetic 60 Hz samples, capture backend; no real pointer injection or WiFi measurement",
            "clocks":{name:vars(time.get_clock_info(name)) for name in ['monotonic','perf_counter']},
            "traces":[measure(False),measure(True)]}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    if args.assert_smooth:
        assert all(row['output_updates_per_second']>=95 and row['interval_p95_ms']<20 for row in report['traces']),report


if __name__=='__main__': main()
