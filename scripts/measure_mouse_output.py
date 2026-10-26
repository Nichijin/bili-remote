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


def measure(jitter, output_hz=1000, speed=2400, input_hz=60):
    backend=Capture();worker=MotionWorker(backend,output_hz=output_hz);timer=PreciseWait()
    started=time.perf_counter();cpu_started=time.process_time()
    try:
        for index in range(input_hz*2+1):
            stamp=index/input_hz
            due=started+stamp+([0,.004,-.003,.001][index%4] if jitter else 0)
            timer.wait(max(0,due-time.perf_counter()))
            worker.submit({"seq":index+1,"t":stamp*1000,"x":stamp*speed,"y":0})
        timer.wait(.050)
        stats=worker.stats()
    finally:
        worker.close();timer.close()
    count=len(backend.events)
    time.sleep(.025)
    assert len(backend.events)==count and not worker.thread.is_alive()
    assert sum(event[1] for event in backend.events)==speed*2
    elapsed=time.perf_counter()-started;cpu=time.process_time()-cpu_started
    steady=[e for e in backend.events if started+.25<=e[0]<=started+1.9]
    intervals=[(b[0]-a[0])*1000 for a,b in zip(steady,steady[1:])]
    x=0;lags=[]
    for stamp,dx,dy in backend.events:
        x+=dx
        if started+.6<=stamp<=started+1.9:lags.append((stamp-started-x/speed)*1000)
    return {"input_hz":input_hz,"target_output_hz":output_hz,"speed_pixels_per_second":speed,"jitter_ms":[0,4,-3,1] if jitter else [0],
            "output_updates_per_second":round((len(steady)-1)/(steady[-1][0]-steady[0][0]),2),
            "interval_p50_ms":round(statistics.median(intervals),3),
            "interval_p95_ms":round(percentile(intervals,.95),3),
            "interval_max_ms":round(max(intervals),3),"endpoint":speed*2,
            "source_to_output_lag_p50_ms":round(statistics.median(lags),3),
            "source_to_output_lag_p95_ms":round(percentile(lags,.95),3),
            "one_cpu_core_percent_coarse_estimate":round(cpu/elapsed*100,2),"cpu_measurement_note":"Windows process CPU accounting can round short runs to zero; zero does not mean no CPU cost","thread_stats":stats,
            "thread_stopped":True,"post_stop_output":0}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'.tooling/mouse-output.json');parser.add_argument('--assert-smooth',action='store_true');parser.add_argument('--all-rates',action='store_true');args=parser.parse_args()
    traces=[measure(jitter,rate) for rate in ([125,250,500,1000] if args.all_rates else [1000]) for jitter in (False,True)]
    traces.extend(measure(False,1000,input_hz=hz) for hz in (120,240))
    report={"method":"Actual Windows high-resolution timer and output thread, synthetic samples, capture backend; source-to-output lag excludes physical phone/WiFi and display scanout",
            "clocks":{name:vars(time.get_clock_info(name)) for name in ['monotonic','perf_counter']},
            "traces":traces}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    if args.assert_smooth:
        assert all(row['output_updates_per_second']>=row['target_output_hz']*.8 and row['interval_p95_ms']<3000/row['target_output_hz'] for row in report['traces']),report
        assert all(row['source_to_output_lag_p95_ms'] < (15 if row['input_hz']==120 else 10)
                   for row in report['traces'] if row['input_hz'] in (120,240)),report


if __name__=='__main__': main()
