"use strict";
const $ = id => document.getElementById(id);
let currentResult = null, currentForecast = null, csvRows = null, busy = false;
const token = sessionStorage.getItem("kronosApiToken");
if (token) $("token").value = token;
$("token").addEventListener("change", () => sessionStorage.setItem("kronosApiToken", $("token").value));
const colors = {text:"#cad5ce",grid:"#2d3c3d",green:"#c7f5b6",gold:"#e5b86e",blue:"#88bfe7"};
function layout(title = "") {return {title:{text:title,font:{size:12}},paper_bgcolor:"transparent",plot_bgcolor:"transparent",font:{color:colors.text,family:"system-ui",size:10},margin:{l:65,r:18,t:25,b:40},xaxis:{gridcolor:colors.grid},yaxis:{gridcolor:colors.grid,tickformat:",.2f"},legend:{orientation:"h",y:1.12,font:{size:10}},hovermode:"x unified"};}
const plotOptions={responsive:true,displaylogo:false,modeBarButtonsToRemove:["select2d","lasso2d"]};
function status(message,error=false){$("status").textContent=message;$("status").classList.toggle("error",error);}
function number(v,digits=2){return Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:digits,minimumFractionDigits:digits}):"—";}
function line(x,y,name,color,extra={}){return {x,y,name,type:"scatter",mode:"lines",line:{color,width:1.6},...extra};}
function band(x,lo,hi,name,color="rgba(199,245,182,.15)"){return [line(x,lo,name,"transparent",{showlegend:false,hoverinfo:"skip"}),line(x,hi,name,"transparent",{fill:"tonexty",fillcolor:color,hoverinfo:"skip"})];}
function renderForecast(f){
 currentForecast=f; if(!f)return; $("density").hidden=!$("density-toggle").checked;
 const s=f.summary;
 $("expected").textContent=`${s.expected_return_pct>=0?"+":""}${number(s.expected_return_pct,3)}%`;
 $("direction").textContent=`Mean path: ${s.direction}`;
 $("probability").textContent=`${number(s.p_up*100,1)}%`;
 $("range").textContent=`${number(f.quantiles.q10.at(-1))} – ${number(f.quantiles.q90.at(-1))}`;
 $("sample-count").textContent=`${f.trajectories.length} sample paths · raw model output`;
 const hx=f.history.map(r=>r.timestamps),hy=f.history.map(r=>r.close),x=f.timestamps;
 let traces=[line(hx,hy,"Historical close",colors.text,{line:{color:colors.text,width:2}})];
 for(const path of f.trajectories.slice(0,20))traces.push(line(x,path.map(r=>r[3]),"Sample path","rgba(199,245,182,.17)",{showlegend:false,hoverinfo:"skip",line:{color:"rgba(199,245,182,.17)",width:.8}}));
 traces.push(...band(x,f.quantiles.q10,f.quantiles.q90,"Raw q10–q90"));
 if(f.calibrated_quantiles)traces.push(...band(x,f.calibrated_quantiles.q10,f.calibrated_quantiles.q90,"Calibration expansion","rgba(229,184,110,.10)"));
 traces.push(line(x,f.quantiles.q50,"Sample median",colors.green),line(x,f.mean.map(r=>r[3]),"Sample mean",colors.gold));
 $("fan").classList.remove("empty"); if(!$("fan").data)$("fan").replaceChildren(); Plotly.react("fan",traces,layout(),plotOptions);
 $("metadata").textContent=JSON.stringify(f.metadata,null,2);
 if($("density-toggle").checked)renderDensity();
}
function renderDensity(){
 const f=currentForecast;if(!f)return;
 const paths=f.trajectories.map(path=>path.map(r=>r[3]));
 const all=paths.flat(),lo=Math.min(...all),hi=Math.max(...all),bins=24,width=(hi-lo||1)/bins;
 const y=Array.from({length:bins},(_,i)=>lo+(i+.5)*width);
 const z=Array.from({length:bins},()=>Array(f.timestamps.length).fill(0));
 for(const p of paths)p.forEach((v,h)=>{const b=Math.min(bins-1,Math.max(0,Math.floor((v-lo)/width)));z[b][h]+=1/(paths.length*width);});
 const l=layout();l.margin={l:5,r:5,t:15,b:10};l.scene={xaxis:{title:{text:"Forecast step"},gridcolor:colors.grid},yaxis:{title:{text:"Close"},gridcolor:colors.grid},zaxis:{title:{text:"Density"},gridcolor:colors.grid},bgcolor:"transparent"};
 Plotly.react("density",[{type:"surface",x:f.timestamps.map((_,i)=>i+1),y,z,colorscale:[[0,"#172224"],[.5,"#5f9b83"],[1,"#c7f5b6"]],showscale:false}],l,plotOptions);
}
function renderEvaluation(r){
 $("evaluation-panel").hidden=false;$("metrics").replaceChildren();
 const m=r.metrics;
 for(const [key,label,percent] of [["close_mae","Close MAE",false],["close_rmse","Close RMSE",false],["terminal_directional_accuracy","Terminal direction",true],["coverage80","q10–q90 coverage",true],["mean_interval_width","Mean interval width",false],["brier_score","Sample-vote Brier score",false]]){
  const row=document.createElement("tr");const heading=document.createElement("td");heading.textContent=label;row.append(heading);
  for(const name of ["baseline","model_raw","model_calibrated"]){const cell=document.createElement("td"),v=m[name]?.[key];cell.textContent=v==null?"—":number(percent?v*100:v,percent?1:3)+(percent?"%":"");row.append(cell);}$("metrics").append(row);
 }
 if(r.paper_trading){const p=r.paper_trading.summary;$("paper-summary").hidden=false;$("paper-summary").textContent=`Paper simulation: ${p.trade_count} LONG roundtrips, net ${number(p.net_return*100,3)}%, gross ${number(p.gross_return*100,3)}%, sampled max drawdown ${number(p.max_drawdown*100,3)}%. Fees and adverse slippage on entry and exit. No annualized claims.`;}else if(r.paper_trading_skipped){$("paper-summary").hidden=false;$("paper-summary").textContent=r.paper_trading_skipped;}else $("paper-summary").hidden=true;
 const c=r.calibration;$("calibration-note").textContent=`Calibration: ${c.calibration_windows} earlier windows. Expansion is frozen before test. ${c.rank_capped_for_small_sample?"Small-sample order statistic was capped. ":""}Serial dependence prevents a coverage guarantee. Persistence is a point baseline; it has no prediction band.`;
 const select=$("window");select.replaceChildren();r.per_window.forEach((w,i)=>{const o=document.createElement("option");o.value=i;o.textContent=`${w.split} · ${w.timestamps[0]} → ${w.timestamps.at(-1)}`;select.append(o);});
 select.value=String(Math.max(0,r.per_window.findIndex(w=>w.split==="test")));
 select.onchange=()=>renderWindow(r.per_window[Number(select.value)]);select.onchange();
 if(r.final_forecast)renderForecast(r.final_forecast);else $("metadata").textContent=JSON.stringify({settings:r.settings,split:r.split,final_forecast_error:r.final_forecast_error},null,2);
}
function renderWindow(w){let traces=[...band(w.timestamps,w.raw_lower,w.raw_upper,"Raw q10–q90")];if(w.calibrated_lower)traces.push(...band(w.timestamps,w.calibrated_lower,w.calibrated_upper,"Calibrated band","rgba(229,184,110,.12)"));traces.push(line(w.timestamps,w.actual_close,"Observed",colors.text),line(w.timestamps,w.forecast_close,"Kronos mean",colors.green),line(w.timestamps,w.timestamps.map(()=>w.last_close),"Last-close baseline",colors.gold));Plotly.react("window-chart",traces,layout(),plotOptions);}
function renderComparison(r){renderForecast(r.kronos);$("comparison-panel").hidden=false;$("comparison-note").textContent=`Kronos: ${r.kronos.summary.direction}; Chronos-2: ${r.chronos2.direction}. Directions ${r.directions_agree?"agree":"differ"}.`;const x=r.kronos.timestamps;Plotly.react("comparison-chart",[line(x,r.kronos.mean.map(r=>r[3]),"Kronos",colors.green),line(x,r.chronos2.close,"Chronos-2",colors.blue)],layout(),plotOptions);}
function clearForecast(){currentForecast=null;for(const id of ["expected","probability","range"])$(id).textContent="—";$("direction").textContent="No forward forecast available";$("sample-count").textContent="Inspect the held-out windows below";Plotly.purge("fan");$("fan").replaceChildren();$("fan").textContent="No forward forecast available for this result.";$("fan").classList.add("empty");Plotly.purge("density");$("density").hidden=true;$("metadata").textContent="";}
function showResult(r){if(!r||typeof r!=="object")throw Error("Expected a result object");clearForecast();currentResult=r;$("evaluation-panel").hidden=true;$("comparison-panel").hidden=true;if(r.metrics&&r.per_window)renderEvaluation(r);else if(r.kronos&&r.chronos2)renderComparison(r);else if(r.summary&&r.trajectories)renderForecast(r);else throw Error("Unrecognized result schema");$("export").disabled=false;}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{"Content-Type":"application/json",Authorization:"Bearer "+$("token").value,...options.headers}});let value;try{value=await response.json();}catch{throw Error(`HTTP ${response.status}`);}if(!response.ok)throw Error(typeof value.detail==="string"?value.detail:JSON.stringify(value.detail));return value;}
function requestBody(){const r={symbol:$("symbol").value,interval:$("interval").value,lookback:Number($("lookback").value),horizon:Number($("horizon").value),sample_count:Number($("samples").value),seed:Number($("seed").value),limit:500,max_windows:8};if(csvRows){r.source="history";r.history=csvRows;}if($("future").value.trim())r.future_timestamps=JSON.parse($("future").value);return r;}
async function run(kind){if(busy)return;busy=true;["forecast","evaluate","compare"].forEach(id=>$(id).disabled=true);try{sessionStorage.setItem("kronosApiToken",$("token").value);const job=await api("/api/jobs",{method:"POST",body:JSON.stringify({kind,request:requestBody()})});let result;for(let n=0;n<1800;n++){result=await api(`/api/jobs/${job.job_id}`);status(`${kind}: ${result.status} · ${job.job_id.slice(0,8)}`);if(result.status==="completed"){showResult(result.result);status(`${kind} completed. Inspect the paths, held-out results and provenance below.`);return;}if(result.status==="failed")throw Error(result.error+". Check input length, session timestamps and backend setup.");await new Promise(resolve=>setTimeout(resolve,1000));}throw Error("Job still running; query its ID through the API.");}catch(error){status(error.message,true);}finally{busy=false;["forecast","evaluate","compare"].forEach(id=>$(id).disabled=false);}}
$("forecast").onclick=()=>run("forecast");$("evaluate").onclick=()=>run("evaluate");$("compare").onclick=()=>run("compare");
$("density-toggle").onchange=()=>{$("density").hidden=!$("density-toggle").checked;if(!$("density").hidden)renderDensity();};
$("export").onclick=()=>{if(!currentResult)return;const url=URL.createObjectURL(new Blob([JSON.stringify(currentResult,null,2)],{type:"application/json"})),a=document.createElement("a");a.href=url;a.download="kronos-experiment.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$("saved").onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>20_000_000)throw Error("Result file must be under 20 MB");showResult(JSON.parse(await file.text()));status("Loaded saved experiment. No request was sent to a model.");}catch(error){status(error.message,true);}};
function parseCSV(text){const rows=[];let row=[],field="",quoted=false;for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===","&&!quoted){row.push(field);field="";}else if((c==="\n"||c==="\r")&&!quoted){if(c==="\r"&&text[i+1]==="\n")i++;row.push(field);if(row.some(v=>v.trim()))rows.push(row);row=[];field="";}else field+=c;}if(quoted)throw Error("Unclosed CSV quote");row.push(field);if(row.some(v=>v.trim()))rows.push(row);const header=rows.shift()?.map(v=>v.trim().toLowerCase());if(header&&new Set(header).size!==header.length)throw Error("Duplicate CSV columns");if(!header?.includes("timestamps"))throw Error("CSV requires a timestamps column");return rows.map(row=>Object.fromEntries(header.map((name,i)=>[name,name==="timestamps"?row[i]:(row[i]?.trim()?Number(row[i]):null)])));}
$("csv").onchange=async event=>{try{const f=event.target.files[0];if(!f){csvRows=null;return;}if(f.size>1_500_000)throw Error("CSV must be under 1.5 MB");csvRows=parseCSV(await f.text());if(csvRows.length>4096)throw Error("CSV is limited to 4096 rows");$("csv-status").textContent=`${csvRows.length} rows loaded; backend will validate OHLCVA.`;}catch(error){csvRows=null;status(error.message,true);}};
