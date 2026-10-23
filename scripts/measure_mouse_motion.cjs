// Deterministic transport/acceleration traces. Never move the system pointer.
const fs=require('node:fs');
const path=require('node:path');
const current=require('../android/app/src/main/assets/mouse.js');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const session='a'.repeat(24);

async function simulate(module,rtt,refresh=60,legacy=false){
  let clock=0,id=0,maxOutstanding=0;const jobs=new Map(),sent=[];
  const schedule=(fn,at)=>{jobs.set(++id,{fn,at});return id;};
  const timers={setInterval(){return ++id;},clearInterval(){}};
  const frames={requestAnimationFrame:fn=>schedule(fn,(Math.floor((clock+1e-7)/(1000/refresh))+1)*1000/refresh),cancelAnimationFrame:id=>jobs.delete(id)};
  let transport;
  transport=new module.MouseTransport({timers,frames,now:()=>clock,
    send:(cmd,fields)=>{
      if(cmd==='mouse_move'){
        sent.push({at:clock,dx:fields.dx});
        return new Promise(resolve=>schedule(()=>resolve({}),clock+rtt));
      }
      return Promise.resolve(cmd==='mouse_start'?{mouse_session:session,mouse_stream:2}:{});
    },
    stream:fields=>{
      sent.push({at:clock,x:fields.x});
      schedule(()=>transport.acknowledge({ok:true,mouse_session:session,seq:fields.seq}),clock+rtt);
      return true;
    }
  });
  await transport.start();
  for(let i=0;i<240;i++)schedule(()=>transport.move(3,0),i*1000/120);
  while(jobs.size){
    const [key,job]=[...jobs].sort((a,b)=>a[1].at-b[1].at||a[0]-b[0])[0];
    if(job.at>2500)break;
    jobs.delete(key);clock=job.at;job.fn();await flush();
    maxOutstanding=Math.max(maxOutstanding,legacy?Number(transport.inflight):transport.outstanding.size);
  }
  const steady=sent.filter(p=>p.at>=500&&p.at<2000);
  const intervals=steady.slice(1).map((p,i)=>p.at-steady[i].at);
  const result={rtt_ms:rtt,display_hz:refresh,packets_per_second:+(steady.length/1.5).toFixed(2),
    largest_send_gap_ms:+Math.max(...intervals).toFixed(3),
    final_x:legacy?sent.reduce((sum,p)=>sum+p.dx,0):sent.at(-1)?.x,
    outstanding_limit:legacy?1:24,maximum_observed_outstanding:maxOutstanding};
  transport.stop();return result;
}

function quantization(module){
  const a=new module.PointerAcceleration();a.reset(0,0,0);const gains=[];
  for(let i=1;i<=150;i++){
    a.sample(Math.round(i*1.7),0,i*8);
    if(i>10)gains.push(a.gain??(.65+Math.min(1,a.speed/900)*2.85));
  }
  return {steady_gain_range:+(Math.max(...gains)-Math.min(...gains)).toFixed(6)};
}

async function main(){
  const args=process.argv.slice(2),value=name=>args[args.indexOf(name)+1];
  const report={method:'Deterministic 120 Hz finger trace, render-aligned frame clock, delayed acknowledgements; not a physical WiFi latency test',current:[],quantization_current:quantization(current)};
  for(const refresh of [60,120])for(const rtt of [0,20,40,80])report.current.push(await simulate(current,rtt,refresh));
  if(args.includes('--baseline')){
    const baseline=require(path.resolve(value('--baseline')));report.baseline=[];report.quantization_baseline=quantization(baseline);
    for(const rtt of [0,20,40,80])report.baseline.push(await simulate(baseline,rtt,60,true));
  }
  for(const row of report.current){
    if(row.packets_per_second<row.display_hz*.95||Math.abs(row.final_x-720)>.001)throw Error('Motion regression: '+JSON.stringify(row));
  }
  if(args.includes('--output'))fs.writeFileSync(value('--output'),JSON.stringify(report,null,2));
  process.stdout.write(JSON.stringify(report,null,2)+'\n');
}
if(require.main===module)main().catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1;});
module.exports={simulate,quantization};
