export async function collectSample(sampleId,onProgress,signal) {
  const response=await fetch(`/api/samples/${encodeURIComponent(sampleId)}/collect`,{
    method:'POST',credentials:'same-origin',headers:{'X-WiaNews-Request':'1'},signal,
  });
  if(!response.ok||!response.body||!response.headers.get('content-type')?.includes('text/event-stream')){
    if(response.status===401)window.dispatchEvent(new Event('wianews-session-expired'));
    const data=await response.json().catch(()=>null);
    throw new Error(typeof data?.detail==='string'?data.detail:'뉴스 수집을 시작하지 못했습니다.');
  }
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
  try{
    while(true){
      const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done});
      let index;
      while((index=buffer.indexOf('\n\n'))!==-1){
        const block=buffer.slice(0,index);buffer=buffer.slice(index+2);
        const lines=block.split('\n'),type=lines.find(l=>l.startsWith('event:'))?.slice(6).trim();
        const raw=lines.filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trimStart()).join('\n');
        if(!raw)continue;const data=JSON.parse(raw);
        if(type==='error')throw new Error(data.message||'뉴스 분석에 실패했습니다.');
        if(type==='progress')onProgress(data);
        if(type==='done'){
          if(!data.sample_id||!Array.isArray(data.issues))throw new Error('수집 결과 형식이 올바르지 않습니다.');
          return data;
        }
      }
      if(buffer.length>2000000)throw new Error('수집 응답이 너무 큽니다.');
      if(done)throw new Error('수집 연결이 끊어졌습니다. 다시 시도해 주세요.');
    }
  }finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}
