import '@kitware/vtk.js/Rendering/Profiles/Geometry';
import vtkGenericRenderWindow from '@kitware/vtk.js/Rendering/Misc/GenericRenderWindow';
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor';
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper';
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData';
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray';
import vtkColorTransferFunction from '@kitware/vtk.js/Rendering/Core/ColorTransferFunction';

const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const names = {u:'速度', p:'压力', rho:'密度', T:'温度', phi:'液相体积分数', flags:'格点标记', material:'材料编号', object:'对象编号'};
const states = {succeeded:'计算完成', failed:'失败 · 可查看完整输出', cancelled:'终止 · 部分结果', timed_out:'超时 · 部分结果', interrupted:'服务中断', running:'正在计算', starting:'正在启动', validating:'正在校验', cancelling:'正在终止'};
const active = new Set(['validating','starting','running','cancelling']);
const fmt = x => Number.isFinite(x) ? Number(x.toPrecision(6)).toString() : '—';
let token, sources=[], selected=null, meta=null, slice=null, axis=2, frame=0, index=0, view='xy', sequence=0, generation=0, playing=false, uploading=false;
let window3d, renderer, renderWindow, sliceObject, domainObject, geometryObjects=[], shift=[0,0,0];
const lut=vtkColorTransferFunction.newInstance();
const ramp=[[0,.129,.224,.592],[.27,.098,.651,.824],[.5,.475,.812,.678],[.74,.965,.863,.412],[1,.808,.271,.169]];
const catColors=[[.18,.35,.65],[.95,.64,.21],[.26,.67,.59],[.78,.31,.31],[.62,.44,.75],[.44,.56,.64],[.86,.5,.67],[.56,.67,.28]];
function notice(message=''){ $('#notice').hidden=!message; $('#notice').textContent=message; }
async function api(path,options={}){
  const headers={...options.headers};
  if(options.method&&options.method!=='GET') headers['X-Workbench-Token']=token;
  if(options.json!==undefined){headers['Content-Type']='application/json';options.body=JSON.stringify(options.json);delete options.json;}
  const response=await fetch('/api'+path,{...options,headers,signal:options.signal||AbortSignal.timeout(options.method==='POST'?300000:60000)});
  if(!response.ok){let error='请求失败 ('+response.status+')';try{error=(await response.json()).error||error;}catch{}throw Error(error);}
  return options.binary ? response.arrayBuffer() : response.json();
}
function initRenderer(){
  window3d=vtkGenericRenderWindow.newInstance({background:[.933,.949,.969]});
  window3d.setContainer($('#renderer'));renderer=window3d.getRenderer();renderWindow=window3d.getRenderWindow();
  new ResizeObserver(()=>window3d.resize()).observe($('#renderer'));window3d.resize();
}
function object(points,polys,values=null,direct=false){
  const data=vtkPolyData.newInstance();data.getPoints().setData(points,3);data.getPolys().setData(polys);
  const mapper=vtkMapper.newInstance();mapper.setInputData(data);
  let scalars;
  if(values){
    scalars=vtkDataArray.newInstance({name:'field',values,numberOfComponents:direct?3:1});data.getPointData().setScalars(scalars);
    if(direct) mapper.setColorModeToDirectScalars();
    else{mapper.setLookupTable(lut);mapper.setUseLookupTableScalarRange(true);mapper.setInterpolateScalarsBeforeMapping(true);}
  }else mapper.setScalarVisibility(false);
  const actor=vtkActor.newInstance();actor.setMapper(mapper);renderer.addActor(actor);
  return {actor,mapper,data,scalars};
}
function dispose(obj){if(!obj)return;renderer.removeActor(obj.actor);obj.actor.delete();obj.mapper.delete();obj.scalars?.delete();obj.data.delete();}
function clearScene(){dispose(sliceObject);dispose(domainObject);geometryObjects.forEach(dispose);sliceObject=domainObject=null;geometryObjects=[];slice=null;renderWindow.render();}
function domain(){
  const b=meta.bounds.map((v,a)=>v.map(x=>x-shift[a])),points=[];
  for(let z=0;z<2;z++)for(let y=0;y<2;y++)for(let x=0;x<2;x++)points.push(b[0][x],b[1][y],b[2][z]);
  domainObject=object(new Float32Array(points),new Uint32Array([4,0,1,3,2,4,4,5,7,6,4,0,1,5,4,4,2,3,7,6,4,0,2,6,4,4,1,3,7,5]));
  domainObject.actor.getProperty().setRepresentationToWireframe();domainObject.actor.getProperty().setColor(.57,.65,.74);domainObject.actor.getProperty().setOpacity(.55);
  domainObject.actor.setVisibility($('#show-domain').checked);
}
function orient(which=view){
  view=which;if(!meta)return;
  const camera=renderer.getActiveCamera(),extent=Math.max(...meta.bounds.map(b=>b[1]-b[0])),dirs={xy:[0,0,1],xz:[0,-1,0],yz:[1,0,0],iso:[1,-1,1]};
  camera.setFocalPoint(0,0,0);camera.setPosition(...dirs[which].map(v=>v*extent*3));camera.setViewUp(...(which==='xy'?[0,1,0]:[0,0,1]));camera.setParallelProjection(true);
  renderer.resetCamera(meta.bounds.flatMap((b,a)=>b.map(v=>v-shift[a])));camera.setParallelScale(camera.getParallelScale()*1.16);
  renderer.resetCameraClippingRange();renderWindow.render();$$('[data-view]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.view===which));
}
function categoryColor(value){return catColors[Math.abs(Math.round(value))%catColors.length];}
function makeSlice(){
  if(!slice||!meta)return;dispose(sliceObject);
  const [xs,ys]=slice.coordinates,nx=xs.length,ny=ys.length,a=slice.axes,category=['flags','object','material'].includes($('#field').value),points=[],polys=[],colors=[];
  const point=(x,y)=>{const p=[0,0,0];p[axis]=slice.position;p[a[0]]=x;p[a[1]]=y;return p.map((v,i)=>v-shift[i]);};
  if(category || nx===1 || ny===1){
    // Constant nearest-node tiles for IDs: never interpolate object/material/flag numbers.
    for(let j=0;j<ny;j++)for(let i=0;i<nx;i++){
      const value=slice.values[j*nx+i];if(value===null)continue;
      const x0=i?(xs[i-1]+xs[i])/2:xs[0]-meta.spacing[a[0]]/2,x1=i+1<nx?(xs[i+1]+xs[i])/2:xs[i]+meta.spacing[a[0]]/2;
      const y0=j?(ys[j-1]+ys[j])/2:ys[0]-meta.spacing[a[1]]/2,y1=j+1<ny?(ys[j+1]+ys[j])/2:ys[j]+meta.spacing[a[1]]/2;
      const offset=points.length/3;for(const [x,y] of [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]){points.push(...point(x,y));colors.push(...(category?categoryColor(value).map(c=>Math.round(c*255)):[value]));}
      polys.push(3,offset,offset+1,offset+2,3,offset,offset+2,offset+3);
    }
  }else{
    for(let j=0;j<ny;j++)for(let i=0;i<nx;i++)points.push(...point(xs[i],ys[j]));
    for(let j=0;j<ny-1;j++)for(let i=0;i<nx-1;i++){
      const q=j*nx+i,vertices=[q,q+1,q+nx+1,q+nx];
      if(vertices.every(k=>slice.values[k]!==null))polys.push(3,vertices[0],vertices[1],vertices[2],3,vertices[0],vertices[2],vertices[3]);
    }
    colors.push(...slice.values.map(v=>v??0));
  }
  sliceObject=object(new Float32Array(points),new Uint32Array(polys),category?new Uint8Array(colors):new Float32Array(colors),category);
  sliceObject.actor.getProperty().setLighting(false);sliceObject.actor.setVisibility($('#show-slice').checked);
  $('#category-legend').hidden=!category;$('#colorbar').hidden=category;
  if(category){
    const legend=$('#category-legend');legend.replaceChildren();
    const title=document.createElement('strong');title.textContent='离散值 · 无插值';legend.append(title);
    [...new Set(slice.values.filter(v=>v!==null))].sort((a,b)=>a-b).forEach(v=>{const row=document.createElement('div'),swatch=document.createElement('i');swatch.style.background='rgb('+categoryColor(v).map(c=>Math.round(c*255)).join(',')+')';row.append(swatch,document.createTextNode(String(v)));legend.append(row);});
  }
  applyRange();
}
function applyRange(){
  if(!slice)return;
  if($('#auto-range').checked){$('#range-min').value=fmt(slice.range[0]);$('#range-max').value=fmt(slice.range[1]);}
  let low=Number($('#range-min').value),high=Number($('#range-max').value);
  if(!Number.isFinite(low)||!Number.isFinite(high)||low>high || (!$('#auto-range').checked&&low===high)){notice('色标范围需要有限数值，并且最小值小于最大值。');return;}
  const original=[low,high];if(low===high){const pad=Math.max(Math.abs(low)*1e-6,1e-9);low-=pad;high+=pad;}
  lut.removeAllPoints();ramp.forEach(([v,r,g,b])=>lut.addRGBPoint(low+v*(high-low),r,g,b));lut.setMappingRange(low,high);lut.updateRange();
  $('#color-min').textContent=fmt(original[0]);$('#color-max').textContent=fmt(original[1]);$('#range-note').textContent=original[0]===original[1]?'恒定场值':$('#auto-range').checked?'当前切片范围':'固定范围';
  renderWindow.render();
}
function rotate(p,axis,degrees){
  const norm=Math.hypot(...axis);if(!Number.isFinite(norm)||norm===0)throw Error('STL 旋转轴无效');
  const [x,y,z]=axis.map(v=>v/norm),c=Math.cos(degrees*Math.PI/180),s=Math.sin(degrees*Math.PI/180),d=p[0]*x+p[1]*y+p[2]*z;
  return [p[0]*c+(y*p[2]-z*p[1])*s+x*d*(1-c),p[1]*c+(z*p[0]-x*p[2])*s+y*d*(1-c),p[2]*c+(x*p[1]-y*p[0])*s+z*d*(1-c)];
}
function stl(buffer,transform){
  const d=new DataView(buffer);if(buffer.byteLength<84)throw Error('STL 文件不完整');
  const count=d.getUint32(80,true);if(!count||count*50+84!==buffer.byteLength)throw Error('需要二进制 STL');
  const t=transform,points=new Float64Array(count*9),lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
  for(let i=0;i<count;i++)for(let v=0;v<3;v++){
    let p=[0,1,2].map(a=>d.getFloat32(84+i*50+12+v*12+a*4,true));
    if(t?.mode==='scale')p=p.map((x,a)=>(x-(t.pivot?.[a]||0))*t.factor);
    if(t)p=rotate(p,t.axis||[1,0,0],t.degrees||0);
    if(t?.mode==='scale')p=p.map((x,a)=>x+t.translation[a]);
    p.forEach((x,a)=>{if(!Number.isFinite(x))throw Error('STL 坐标或变换无效');points[i*9+v*3+a]=x;lo[a]=Math.min(lo[a],x);hi[a]=Math.max(hi[a],x);});
  }
  const scale=t?.mode==='fit'?t.size/Math.max(...hi.map((v,a)=>v-lo[a])):1,output=new Float32Array(points.length),polys=new Uint32Array(count*4);
  for(let i=0;i<points.length;i++){const a=i%3;output[i]=(t?.mode==='fit'?(points[i]-(lo[a]+hi[a])/2)*scale+t.center[a]:points[i])-shift[a];if(!Number.isFinite(output[i]))throw Error('STL 包围盒或变换无效');}
  for(let i=0;i<count;i++)polys.set([3,i*3,i*3+1,i*3+2],i*4);
  return object(output,polys);
}
async function loadGeometry(id,epoch){
  const list=$('#geometry-list');list.replaceChildren();
  if(!meta.geometries.length)list.textContent='没有 STL 快照';
  for(let i=0;i<meta.geometries.length;i++){
    const g=meta.geometries[i],row=document.createElement('div'),label=document.createElement('span');label.textContent='◇ '+g.id;row.append(label);list.append(row);
    if(!g.available){const note=document.createElement('small');note.textContent=g.reason;row.append(note);continue;}
    try{
      const buffer=await api('/results/'+id+'/geometry?index='+i,{binary:true});if(epoch!==generation)return;
      const obj=stl(buffer,g.transform);obj.actor.getProperty().setColor(.78,.81,.84);obj.actor.getProperty().setAmbient(.3);obj.actor.getProperty().setDiffuse(.7);obj.actor.getProperty().setOpacity(Number($('#opacity').value));obj.actor.setVisibility($('#show-stl').checked);geometryObjects.push(obj);renderWindow.render();
    }catch(e){if(epoch!==generation)return;const note=document.createElement('small');note.textContent=e.message;row.append(note);}
  }
}
function selectOptions(select,items,value){select.replaceChildren(...items.map(([v,t])=>{const option=document.createElement('option');option.value=v;option.textContent=t;return option;}));if(items.some(x=>x[0]===value))select.value=value;}
function fieldUI(){
  const available=meta.frames[frame].fields,old=$('#field').value;
  selectOptions($('#field'),meta.fields.filter(f=>available.includes(f.id)).map(f=>[f.id,names[f.id]+' · '+f.id]),available.includes(old)?old:available.includes('u')?'u':available[0]);
  const f=meta.fields.find(f=>f.id===$('#field').value),vector=f.components===3,component=$('#component').value;
  selectOptions($('#component'),vector?[['magnitude','速度大小 |u|'],['x','X 分量'],['y','Y 分量'],['z','Z 分量']]:[['scalar','标量']],component);
  $('#component').disabled=!vector;$('#field-note').textContent=f.id==='p'?'相对 fluid.rho 参考密度的表压。':f.id==='flags'?'格点位掩码，编号颜色不表示大小。':('输出单位：'+f.unit);
  $('#color-unit').textContent=f.unit;
}
function sliceUI(){
  $('#slice-slider').max=meta.dimensions[axis]-1;$('#slice-slider').value=index;
  const first=meta.origin[axis],last=first+(meta.dimensions[axis]-1)*meta.spacing[axis];
  $('#position').min=first;$('#position').max=last;$('#position').step=meta.spacing[axis];$('#position').value=fmt(first+index*meta.spacing[axis]);$('#position-unit').textContent=meta.coordinate_unit;
  $('#slice-start').textContent=fmt(first);$('#slice-end').textContent=fmt(last);
  $('#slice-note').textContent='格点 '+index+' / '+(meta.dimensions[axis]-1)+' · '+['X','Y','Z'][axis]+' 方向，吸附到格点中心。';
  $$('[data-axis]').forEach(b=>b.setAttribute('aria-pressed',Number(b.dataset.axis)===axis));
}
async function updateSlice(){
  if(!meta)return;const seq=++sequence,epoch=generation,id=selected;
  fieldUI();sliceUI();const f=meta.frames[frame];
  $('#busy').hidden=false;$('#time-slider').value=frame;$('#frame-select').value=String(frame);
  try{
    const query=new URLSearchParams({field:$('#field').value,step:f.step,axis,index,component:$('#component').value});
    const data=await api('/results/'+id+'/slice?'+query);
    if(seq!==sequence||epoch!==generation)return;
    slice=data;makeSlice();$('#empty').hidden=true;$('#field-caption').textContent=names[$('#field').value]+' · '+$('#component').selectedOptions[0].textContent;
    const t=f.time===null?'时间未知':fmt(f.time)+(meta.unit_mode==='si'?' s':meta.unit_mode==='lattice'?' lu':'（原始时间单位）');
    $('#frame-caption').textContent='Step '+(meta.step_known?f.step:'未知')+' / '+t;
    $('#slice-caption').textContent=['X','Y','Z'][axis]+' = '+fmt(data.position)+' '+meta.coordinate_unit;
    $('#scene-title').textContent=['YZ','XZ','XY'][axis]+' 切片 / '+names[$('#field').value];
    $('#sampling').textContent=(data.sampled?'抽样预览 · ':'原始格点 · ')+data.coordinates.map(c=>c.length).join(' × ')+(data.invalid?' · 无效值 '+data.invalid:'');
    $('#time-detail').textContent='第 '+(frame+1)+' / '+meta.frames.length+' 帧 · '+t+' · 仅展示实际输出';
    $('#value-range').textContent='切片值域 '+fmt(data.range[0])+' ～ '+fmt(data.range[1]);
  }catch(e){if(seq!==sequence||epoch!==generation)return;dispose(sliceObject);sliceObject=null;slice=null;$('#empty').hidden=false;$('#colorbar').hidden=true;$('#category-legend').hidden=true;notice(e.message);stopPlayback();renderWindow.render();}
  finally{if(seq===sequence)$('#busy').hidden=true;}
}
function renderSources(){
  $('#source-count').textContent=sources.length;const list=$('#source-list');list.replaceChildren();
  for(const source of sources){
    const b=document.createElement('button');b.className='source-item'+(source.id===selected?' active':'')+(source.status==='succeeded'||source.kind!=='job'?' completed':'');b.dataset.source=source.id;
    const dot=document.createElement('span');dot.className='dot';const text=document.createElement('div'),title=document.createElement('strong'),sub=document.createElement('small');title.textContent=source.name;sub.textContent=(states[source.status]||'已导入')+' · '+new Date(source.created_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});text.append(title,sub);b.append(dot,text);b.onclick=()=>loadSource(source.id);list.append(b);
  }
  if(!sources.length)list.textContent='暂无计算或导入记录';
}
async function refresh(){sources=(await api('/results')).datasets;renderSources();}
function stopPlayback(){playing=false;$('#play').textContent='播放';}
async function loadSource(id){
  stopPlayback();generation++;sequence++;const epoch=generation;selected=id;meta=null;slice=null;clearScene();notice();renderSources();$('#controls').disabled=true;$('#empty').hidden=false;$('#colorbar').hidden=true;$('#category-legend').hidden=true;$('#geometry-list').replaceChildren();$('#field-caption').textContent='';$('#frame-caption').textContent='';$('#slice-caption').textContent='';$('#busy').hidden=false;
  for(const selector of ['#previous','#play','#next','#time-slider','#frame-select'])$(selector).disabled=true;
  history.replaceState(null,'','/results.html?source='+encodeURIComponent(id));
  const source=sources.find(s=>s.id===id);$('#case-name').textContent=source?.name||'结果数据';
  if(active.has(source?.status)){$('#busy').hidden=true;notice('此任务仍在计算，完成后将自动加载流场。');return;}
  try{
    const data=await api('/results/'+id+'/metadata');if(epoch!==generation)return;meta=data;frame=data.frames.length-1;axis=2;index=Math.floor((meta.dimensions[axis]-1)/2);shift=meta.bounds.map(b=>(b[0]+b[1])/2);
    $('#controls').disabled=false;$('#frame-count').textContent=meta.frames.length+' 帧';$('#provenance').textContent=(meta.unit_mode==='si'?'SI 物理单位':meta.unit_mode==='lattice'?'格子单位':'单位未知')+' · 真实 VTK · '+(source?.kind==='job'?'计算快照':'手动导入');
    $('#monitor-link').hidden=!id.startsWith('job-');$('#monitor-link').href='/?mode=run&job='+encodeURIComponent(id.slice(4));
    const facts=[['网格',meta.dimensions.join(' × ')],['格距',meta.spacing.map(fmt).join(' / ')+' '+meta.coordinate_unit],['坐标', 'VTK 格点中心'],['原始文件',meta.frames.reduce((n,f)=>n+f.fields.length,0)+' 个 VTK']];
    $('#data-facts').replaceChildren(...facts.flatMap(([name,value])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;return[dt,dd];}));
    $('#warnings').textContent=meta.warnings.join(' ');$('#auto-range').checked=true;$('#range-min').disabled=$('#range-max').disabled=true;
    selectOptions($('#frame-select'),meta.frames.map((f,i)=>[String(i),'Step '+(meta.step_known?f.step:'未知')+(f.time===null?'':' · '+fmt(f.time)+(meta.unit_mode==='si'?' s':''))]),String(frame));
    $('#time-slider').max=meta.frames.length-1;for(const selector of ['#previous','#play','#next','#time-slider','#frame-select'])$(selector).disabled=meta.frames.length<2;
    domain();orient('xy');fieldUI();const geometryPromise=loadGeometry(id,epoch);await updateSlice();await geometryPromise;
  }catch(e){if(epoch===generation)notice(e.message);}
  finally{if(epoch===generation)$('#busy').hidden=true;}
}
async function changeFrame(i){if(!meta)return;frame=Math.max(0,Math.min(meta.frames.length-1,i));await updateSlice();}
async function play(){if(playing){stopPlayback();return;}playing=true;$('#play').textContent='暂停';const epoch=generation;while(playing&&meta&&epoch===generation){await changeFrame((frame+1)%meta.frames.length);await new Promise(r=>setTimeout(r,400));}}
function uploadState(message){$('#import-status').textContent=message;}
async function importFiles(files){
  if(uploading||!files.length)return;uploading=true;let id;
  try{
    const allowed=[...files].filter(f=>/\.(vtk|stl)$/i.test(f.name)||['effective-config.json','resolved-config.json','manifest.json'].includes(f.name));
    if(!allowed.some(f=>/\.vtk$/i.test(f.name)))throw Error('所选文件中没有 VTK 场数据。');
    if(allowed.reduce((n,f)=>n+f.size,0)>10*1024**3)throw Error('单次导入总量超过 10 GiB。可改用 Windows 目录读取。');
    const name=files[0].webkitRelativePath?.split('/')[0]||files[0].name;
    id=(await api('/results/import',{method:'POST',json:{name}})).id;
    for(let i=0;i<allowed.length;i++){
      const file=allowed[i];uploadState('上传 '+(i+1)+' / '+allowed.length+' · '+file.name+' ('+fmt(file.size/1024**2)+' MiB)');
      await api('/results/'+id+'/upload?path='+encodeURIComponent(file.webkitRelativePath||file.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
    }
    uploadState('校验网格与结果元数据…');await api('/results/'+id+'/finish',{method:'POST',json:{}});await refresh();$('#import-dialog').close();await loadSource(id);
  }catch(e){uploadState(e.message);if(id)try{await api('/results/'+id+'/cancel',{method:'POST',json:{}});}catch{}}
  finally{uploading=false;$('#folder-input').value=$('#files-input').value='';}
}
$('#refresh').onclick=async()=>{try{await refresh();if(selected)await loadSource(selected);}catch(e){notice(e.message);}};
$('#import').onclick=()=>{uploadState('');$('#import-dialog').showModal();};
$('#choose-folder').onclick=()=>$('#folder-input').click();$('#choose-files').onclick=()=>$('#files-input').click();
$('#folder-input').onchange=e=>importFiles(e.target.files);$('#files-input').onchange=e=>importFiles(e.target.files);
$('#import-dialog').addEventListener('cancel',e=>{if(uploading)e.preventDefault();});$('.dialog-head').onsubmit=e=>{if(uploading){e.preventDefault();uploadState('正在上传文件，请等待本次导入结束。');}};
$('#open-directory').onclick=async()=>{if(uploading)return;uploading=true;try{uploadState('读取 Windows 结果目录…');const {id}=await api('/results/import',{method:'POST',json:{name:$('#server-directory').value.split(/[\\/]/).at(-1),directory:$('#server-directory').value}});await refresh();$('#import-dialog').close();await loadSource(id);}catch(e){uploadState(e.message);}finally{uploading=false;}};
$$('[data-view]').forEach(b=>b.onclick=()=>orient(b.dataset.view));$('#fit').onclick=()=>orient();
$$('[data-axis]').forEach(b=>b.onclick=()=>{axis=Number(b.dataset.axis);index=Math.floor((meta.dimensions[axis]-1)/2);orient(['yz','xz','xy'][axis]);updateSlice();});
$('#field').onchange=()=>{fieldUI();updateSlice();};$('#component').onchange=updateSlice;
$('#slice-slider').onchange=e=>{index=Number(e.target.value);updateSlice();};$('#slice-slider').oninput=e=>{$('#position').value=fmt(meta.origin[axis]+Number(e.target.value)*meta.spacing[axis]);};
$('#position').onchange=e=>{const n=Number(e.target.value);if(!Number.isFinite(n)){sliceUI();return;}index=Math.max(0,Math.min(meta.dimensions[axis]-1,Math.round((n-meta.origin[axis])/meta.spacing[axis])));updateSlice();};
$('#auto-range').onchange=()=>{$('#range-min').disabled=$('#range-max').disabled=$('#auto-range').checked;applyRange();};$('#apply-range').onclick=applyRange;
$('#show-domain').onchange=()=>{domainObject?.actor.setVisibility($('#show-domain').checked);renderWindow.render();};$('#show-slice').onchange=()=>{sliceObject?.actor.setVisibility($('#show-slice').checked);renderWindow.render();};
$('#show-stl').onchange=()=>{geometryObjects.forEach(o=>o.actor.setVisibility($('#show-stl').checked));renderWindow.render();};$('#opacity').oninput=()=>{const opacity=Number($('#opacity').value);$('#opacity-value').textContent=Math.round(opacity*100)+'%';geometryObjects.forEach(o=>o.actor.getProperty().setOpacity(opacity));renderWindow.render();};
$('#previous').onclick=()=>{stopPlayback();changeFrame(frame-1);};$('#next').onclick=()=>{stopPlayback();changeFrame(frame+1);};$('#play').onclick=play;
$('#time-slider').onchange=e=>{stopPlayback();changeFrame(Number(e.target.value));};$('#frame-select').onchange=e=>{stopPlayback();changeFrame(Number(e.target.value));};
let polling=false;
async function poll(){if(polling||uploading)return;polling=true;try{const old=sources.find(s=>s.id===selected);await refresh();const current=sources.find(s=>s.id===selected);if(active.has(old?.status)&&current?.status==='succeeded')await loadSource(selected);$('#connection').textContent='已连接 · 只读后处理';}catch(e){$('#connection').textContent='服务连接中断';}finally{polling=false;}}
async function boot(){try{initRenderer();const session=await api('/session');token=session.token;await refresh();const q=new URLSearchParams(location.search),id=q.get('source')||(q.get('run')?'job-'+q.get('run'):null)||sources.find(s=>s.status==='succeeded'||s.kind!=='job')?.id;if(id)await loadSource(id);$('#connection').textContent='已连接 · 只读后处理';setInterval(poll,3000);}catch(e){notice('结果页面启动失败：'+e.message);}}
boot();
