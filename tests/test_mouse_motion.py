import math
import time
import pytest
from desktop.mouse_motion import MotionTimeline, MotionWorker, PreciseWait
from desktop.mouse import MouseController
from desktop.protocol import validate


def frame(seq, t, x, y=0):
    return {"cmd": "mouse_frame", "seq": seq, "t": t, "x": x, "y": y, "mouse_session": "a"*24}


def test_interpolated_fractional_motion_has_exact_endpoint_and_no_prediction():
    line = MotionTimeline()
    line.submit(frame(1, 0, 10.7, -4.2), 10)
    assert line.tick(10) == (0, 0)
    first = line.tick(10.008)
    assert 0 < first[0] < 10 and -4 < first[1] <= 0
    last = line.tick(10.030)
    assert (first[0]+last[0], first[1]+last[1]) == (10, -4)
    assert line.tick(11) == (0, 0) and not line.pending(11)
    line.submit(frame(2, 30, 11.1, -4.9), 10.030)
    assert line.tick(10.06) == (1, 0)


def test_duplicates_and_reordering_cannot_replay_motion():
    line = MotionTimeline()
    line.submit(frame(2, 10, 8), 1)
    line.tick(1.03)
    assert not line.submit(frame(1, 9, 100), 1.03)
    assert not line.submit(frame(2, 10, 100), 1.04)
    assert not line.submit(frame(3, 8, 100), 1.05)
    assert line.tick(2) == (0, 0)


def test_same_timestamp_coalesces_and_long_idle_does_not_spread_new_motion_over_idle():
    line = MotionTimeline()
    line.submit(frame(1, 0, 1), 1)
    line.submit(frame(2, 0, 4), 1)
    assert line.tick(1.03) == (4, 0)
    line.submit(frame(3, 2000, 14), 3)
    assert line.tick(3) == (0, 0)
    assert 0 < line.tick(3.008)[0] < 10
    assert line.tick(3.1)[0] <= 10


def test_stale_network_travel_is_skipped_and_recovery_only_applies_fresh_delta():
    line = MotionTimeline()
    line.submit(frame(1, 0, 0), 10)
    line.tick(10.05)
    line.submit(frame(2, 16, 400), 10.250)
    assert line.tick(10.250) == (0, 0)
    line.submit(frame(3, 260, 410), 10.260)
    assert line.tick(10.30) == (10, 0)


def test_bursts_are_bounded_and_click_flushes_exact_final_target():
    line = MotionTimeline()
    for i in range(1, 200):
        line.submit(frame(i, i*.1, i*.25, -i*.25), 5+i*.0001)
    assert len(line.points) <= 32
    assert line.flush(5.02) == (49, -49)
    assert not line.pending(5.02) and line.tick(6) == (0, 0)


def test_fixed_output_splits_jittery_frames_into_smaller_steps_and_stops_at_last_point():
    line = MotionTimeline()
    packets = [(i/60+.020+[0,.004,-.003,.001][i%4], frame(i+1,i*1000/60,i*10)) for i in range(61)]
    deltas = []
    index = 0
    for tick in range(0, 1100):
        now=tick/1000
        while index<len(packets) and packets[index][0]<=now:
            line.submit(packets[index][1], now)
            index+=1
        if tick%8==0:
            dx,dy=line.tick(now)
            if dx: deltas.append(dx)
    assert sum(deltas)==600
    assert len(deltas)>100 and max(deltas)<=10
    assert line.tick(10)==(0,0)


class Capture:
    def __init__(self): self.events=[]
    def move(self,x,y): self.events.append(("move",x,y,time.monotonic()))
    def click(self,button): self.events.append((button,time.monotonic()))


def test_worker_click_barrier_and_teardown_no_post_exit_motion_or_thread():
    backend=Capture();worker=MotionWorker(backend)
    try:
        worker.submit(frame(1,0,40,-20))
        worker.click("left")
        assert sum(row[1] for row in backend.events if row[0]=="move")==40
        assert backend.events[-1][0]=="left"
        worker.submit(frame(2,16,60,-20))
    finally:
        worker.close()
    count=len(backend.events)
    time.sleep(.025)
    assert len(backend.events)==count and not worker.thread.is_alive()


def test_controller_stream_mode_scopes_frames_and_stops_worker_on_disconnect():
    backend=Capture();mouse=MouseController(backend)
    session=mouse.execute({"cmd":"mouse_start","stream":2},"a")["mouse_session"]
    try:
        with pytest.raises(RuntimeError,match="混用"):
            mouse.execute({"cmd":"mouse_move","mouse_session":session,"dx":1,"dy":0},"a")
        with pytest.raises(RuntimeError):
            mouse.execute({**frame(1,0,10),"mouse_session":session},"other")
        mouse.execute({**frame(1,0,10),"mouse_session":session},"a")
        mouse.execute({"cmd":"mouse_click","button":"right","mouse_session":session},"a")
        assert sum(row[1] for row in backend.events if row[0]=="move")==10
        assert backend.events[-1][0]=="right"
        worker=mouse.worker
        mouse.release("a")
        assert not worker.thread.is_alive()
    finally: mouse.release("a")


@pytest.mark.parametrize("field,value", [("x",True),("y",float("nan")),("t",-1),("x",1e10),("seq",0),("seq",1.2),("seq",False)])
def test_stream_fields_are_finite_bounded_and_strict(field,value):
    with pytest.raises(ValueError): validate({**frame(1,0,0),field:value})


def test_waitable_timer_waits_and_closes_its_handle():
    timer=PreciseWait()
    try:
        started=time.perf_counter();timer.wait(.003)
        assert time.perf_counter()-started>=.002
    finally: timer.close()
    assert timer.handle is None


@pytest.mark.parametrize("rate",[125,250,500,1000])
def test_output_rate_is_applied_and_idle_stats_do_not_claim_a_thousand_real_positions(rate):
    backend=Capture();mouse=MouseController(backend)
    result=mouse.execute({"cmd":"mouse_start","stream":2,"output_hz":rate},"a")
    try:
        assert result['mouse_output_hz']==rate
        assert mouse.worker.interval==1/rate
        session=result['mouse_session']
        stats=mouse.execute({"cmd":"mouse_keep","mouse_session":session},"a")['mouse_output']
        assert stats['target_hz']==rate
        assert stats['scheduled_hz']==0 and stats['position_updates_hz']==0
    finally: mouse.release("a")


@pytest.mark.parametrize("rate",[True,1000.0,0,999,1001,"1000",None,{}])
def test_arbitrary_output_rate_is_rejected_at_protocol_and_worker(rate):
    with pytest.raises(ValueError):validate({'cmd':'mouse_start','stream':2,'output_hz':rate})
    with pytest.raises(ValueError):MotionWorker(Capture(),output_hz=rate)


def test_1000_hz_interpolation_has_one_ms_steps_but_does_not_invent_new_input_positions():
    line=MotionTimeline();line.submit(frame(1,0,0),1)
    line.submit(frame(2,16,32),1.016)
    deltas=[line.tick(1+i*.001)[0] for i in range(50)]
    assert sum(deltas)==32 and len([dx for dx in deltas if dx])>=15
    assert line.tick(5)==(0,0)


@pytest.mark.parametrize("hz,expected_ms",[(60,17.67),(120,9.33),(240,5.17),(1000,4)])
def test_stable_fast_input_reduces_interpolation_delay_without_predicting(hz,expected_ms):
    line=MotionTimeline()
    for i in range(hz+1):
        line.submit(frame(i+1,i*1000/hz,i*10),5+i/hz)
        line.tick(5+i/hz)
    assert line.buffer*1000==pytest.approx(expected_ms,abs=.01)
    assert line.tick(7)[0]>=0
    assert line.applied_x==hz*10 and line.tick(8)==(0,0)


def test_jitter_increases_bounded_delay_smoothly_and_reordered_samples_cannot_train_it():
    line=MotionTimeline();previous=line.buffer
    for i in range(121):
        line.submit(frame(i+1,i*1000/60,i*10),5+i/60+[0,.004,-.003,.001][i%4])
        assert abs(line.buffer-previous)<=1/60*.05+1e-9
        previous=line.buffer
    assert .023<=line.buffer<=.024
    assert not line.submit(frame(120,1000,0),8)
    assert line.buffer==previous
    assert line.flush(8)[0]==1200 and line.tick(9)==(0,0)
