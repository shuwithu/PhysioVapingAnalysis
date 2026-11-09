"""Exploratory Shimmer method comparison; no final participant exclusions.

Run with --data-root and --output. Raw participant data never enter source control.
Provisional heuristics are sensitivity checks, not validated artifact classifiers.
"""
from pathlib import Path
import argparse, hashlib, html, json, warnings, importlib.metadata
import numpy as np
import pandas as pd
import scipy.signal as ss
from scipy.ndimage import maximum_filter1d
import neurokit2 as nk
import heartpy as hp
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

CFG = dict(ppg_hz=120, eda_hz=10, gap_seconds=.1, edge_seconds=2,
           ppg_band_hz=[.5,8], eda_lowpass_hz=3, quality_threshold=.8,
           bpm_limits=[40,180], interval_relative_deviation=.30,
           eda_slope_flag_us_s=10, scr_thresholds_us=[.01,.05],
           minimum_segment_seconds=10, minimum_prv_pair_count=30,
           cvxeda_alpha=.0008, cvxeda_gamma=.01)

def runs(mask):
    d=np.diff(np.r_[False,mask,False].astype(int))
    return list(zip(np.where(d==1)[0],np.where(d==-1)[0]))

def dilate(mask, n):
    return maximum_filter1d(np.asarray(mask,dtype=np.uint8),size=2*n+1)>0

def longest(mask, fs):
    return max([b-a for a,b in runs(mask)]+[0])/fs

def interval_stats(peaks, time, valid):
    peaks=np.asarray(peaks,dtype=int)
    if len(peaks)<3: return {}, pd.DataFrame(), np.zeros(len(time),bool)
    ibi=np.diff(time[peaks]); median=pd.Series(ibi).rolling(11,center=True,min_periods=1).median().to_numpy()
    badsum=np.r_[0,np.cumsum(~valid)]
    complete=(badsum[peaks[1:]+1]-badsum[peaks[:-1]])==0
    physiological=(ibi>=60/CFG['bpm_limits'][1])&(ibi<=60/CFG['bpm_limits'][0])
    local=np.abs(ibi-median)<=CFG['interval_relative_deviation']*median
    accept=complete & physiological & local
    coverage=np.zeros(len(time),bool)
    for a,b in zip(peaks[:-1][accept],peaks[1:][accept]): coverage[a:b]=True
    adjacent=accept[:-1]&accept[1:]
    # Only truly consecutive accepted intervals contribute; never bridge rejected beats.
    diffs=np.diff(ibi)[adjacent]*1000
    rmssd=np.sqrt(np.mean(diffs**2)) if len(diffs)>=CFG['minimum_prv_pair_count'] else np.nan
    vals=dict(detected_beats=len(peaks),accepted_intervals=int(accept.sum()),
              rejected_interval_pct=100*(1-accept.mean()),valid_seconds=float(ibi[accept].sum()),
              coverage_pct=100*coverage.mean(),longest_valid_s=longest(coverage,CFG['ppg_hz']),
              mean_hr_bpm=60*accept.sum()/ibi[accept].sum() if accept.any() else np.nan,
              median_hr_bpm=np.median(60/ibi[accept]) if accept.any() else np.nan,
              prv_rmssd_ms=rmssd,rmssd_adjacent_pairs=int(adjacent.sum()))
    table=pd.DataFrame(dict(start_s=time[peaks[:-1]],end_s=time[peaks[1:]],ibi_ms=ibi*1000,
                            accepted=accept,complete_quality_interval=complete,
                            physiological_range=physiological,local_consistency=local))
    return vals,table,coverage

def detect(clean,fs,method):
    if method=='bishop':
        # This implementation is quadratic and intended for short windows.
        # Score 4s cores with 1s context on either side (6s total).
        result=[]
        for core in range(0,len(clean),4*fs):
            end=min(core+4*fs,len(clean));a=max(0,core-fs);b=min(len(clean),end+fs)
            if b-a<2*fs:continue
            pk=nk.ppg_findpeaks(clean[a:b],sampling_rate=fs,method='bishop')['PPG_Peaks']+a
            result.extend(pk[(pk>=core)&(pk<end)])
        return np.unique(result).astype(int)
    if method=='heartpy':
        wd,_=hp.process(clean, sample_rate=fs,bpmmin=40,bpmmax=180,
                        clean_rr=False,interp_clipping=False,high_precision=False)
        return np.asarray(wd['peaklist'],int)[np.asarray(wd['binary_peaklist'],bool)]
    return nk.ppg_findpeaks(clean,sampling_rate=fs,method=method)['PPG_Peaks']

def match_fraction(a,b,tolerance):
    if not len(a) or not len(b): return np.nan
    i=j=hits=0
    while i<len(a) and j<len(b):
        if abs(a[i]-b[j])<=tolerance: hits+=1;i+=1;j+=1
        elif a[i]<b[j]: i+=1
        else: j+=1
    return 2*hits/(len(a)+len(b))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data-root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--participants',nargs='+',default=['105','5'])
    args=ap.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
    ppgrows=[];edarows=[];qcrows=[];agreement=[];errors=[];sources=[];figures=[]
    for pid in args.participants:
      for tag,condition in [('Neutral','neutral'),('Cue1','environmental'),('Cue2','social')]:
        pathlist=list((args.data_root/f'Physio_P{pid}').glob(f'*_{tag}_*Calibrated_PC.csv'))
        if len(pathlist)!=1: raise ValueError(f'Expected exactly one input: {pid} {tag}: {pathlist}')
        path=pathlist[0];key=f'P{pid}_{condition}';print('Processing',key,flush=True)
        sources.append(dict(file=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        df=pd.read_csv(path,sep='\t',skiprows=[0,2]).iloc[:,:6]; df.columns=['timestamp','range','eda','resistance','ppg','vendor_hr']
        df=df.apply(pd.to_numeric,errors='coerce')
        t=(df.timestamp.to_numpy()-df.timestamp.iloc[0])/1000
        if not np.isfinite(t).all() or np.any(np.diff(t)<=0): raise ValueError(f'Nonmonotonic timestamps: {key}')
        duration=t[-1];nativefs=1/np.median(np.diff(t));fs=CFG['ppg_hz'];grid=np.arange(0,duration,1/fs)
        # Interpolate timestamp jitter only; >100ms gaps are excluded and segments processed separately.
        raw=np.interp(grid,t,df.ppg); eda_native=df.eda.to_numpy()
        gapmask=np.zeros(len(grid),bool)
        for i in np.where(np.diff(t)>CFG['gap_seconds'])[0]: gapmask|=(grid>t[i])&(grid<t[i+1])
        nonfinite=np.interp(grid,t,(~np.isfinite(df.ppg)).astype(float))>0
        flat=pd.Series(raw).rolling(2*fs,center=True,min_periods=fs).std().fillna(0).to_numpy()<.01
        basebad=gapmask|nonfinite|flat|(raw<=0)|(raw>=3000)
        clean=np.full(len(grid),np.nan)
        segmentlist=runs(~(gapmask|nonfinite))
        basevalid=~dilate(basebad,fs)
        for a,b in segmentlist:
            if b-a<CFG['minimum_segment_seconds']*fs:basevalid[a:b]=False;continue
            clean[a:b]=nk.ppg_clean(raw[a:b],sampling_rate=fs,method='elgendi')
            basevalid[a:a+2*fs]=False;basevalid[b-2*fs:b]=False
        qc=dict(participant=pid,condition=condition,duration_s=duration,samples=len(t),native_hz=nativefs,
                gaps_gt_100ms=int(np.sum(np.diff(t)>.1)),largest_gap_s=float(np.max(np.diff(t))),
                vendor_invalid_sample_pct=100*np.mean(~np.isfinite(df.vendor_hr)|(df.vendor_hr<=0)),
                ppg_base_flag_pct=100*np.mean(~basevalid),range_changes=int(np.sum(np.diff(df['range'])!=0)))
        traces=pd.DataFrame(dict(time_s=grid,ppg_raw_mv=raw,ppg_filtered=clean,base_valid=basevalid))
        allpeaks={};plotdata={}
        for method in ['elgendi','bishop','heartpy']:
            peaks=[];q=np.full(len(grid),np.nan)
            for a,b in segmentlist:
                if not np.isfinite(clean[a:b]).all():continue
                try:
                    pk=detect(clean[a:b],fs,method);peaks.extend(pk+a)
                    if len(pk)>3:q[a:b]=nk.ppg_quality(clean[a:b],peaks=pk,sampling_rate=fs,method='templatematch')
                except Exception as e: errors.append(dict(scene=key,stage=method,start_s=a/fs,error=str(e)))
            peaks=np.array(peaks,dtype=int);allpeaks[method]=peaks
            valid=basevalid&np.isfinite(q)&(q>=CFG['quality_threshold'])
            vals,beats,coverage=interval_stats(peaks,grid,valid)
            basevals,_,_=interval_stats(peaks,grid,basevalid)
            row=dict(participant=pid,condition=condition,method=method,**vals,
                     base_only_hr_bpm=basevals.get('mean_hr_bpm',np.nan),
                     base_only_rmssd_ms=basevals.get('prv_rmssd_ms',np.nan),
                     quality_pass_pct=100*valid.mean(),below_85pct_coverage=vals.get('coverage_pct',0)<85)
            ppgrows.append(row);beats.to_csv(out/f'{key}_{method}_intervals.csv',index=False)
            traces[f'{method}_quality']=q;traces[f'{method}_valid']=coverage
            plotdata[method]=(peaks,q,beats,coverage)
        for m1,m2 in [('elgendi','bishop'),('elgendi','heartpy'),('bishop','heartpy')]:
            pa=allpeaks[m1];pb=allpeaks[m2];pa=pa[basevalid[pa]];pb=pb[basevalid[pb]]
            agreement.append(dict(participant=pid,condition=condition,method_a=m1,method_b=m2,
                                  symmetric_match_50ms=match_fraction(pa,pb,.05*fs)))
        traces.to_csv(out/f'{key}_ppg_signals.csv.gz',index=False)
        # EDA: raw QC first. Range transitions are flags, not proof of contact failure.
        et=np.arange(0,duration,.1);en=np.interp(et,t,eda_native)
        ebad=~np.isfinite(en)|(en<=0)
        egap=np.zeros(len(et),bool)
        for i in np.where(np.diff(t)>.1)[0]:egap|=(et>t[i])&(et<t[i+1])
        slope=np.r_[0,np.abs(np.diff(en))/.1]>CFG['eda_slope_flag_us_s']
        eflat=pd.Series(en).rolling(20,center=True,min_periods=10).std().fillna(1).to_numpy()<1e-6
        changes=np.where(np.diff(df['range'])!=0)[0]
        rflag=np.zeros(len(et),bool)
        for i in changes:rflag|=np.abs(et-t[i+1])<=1
        evalid=~(dilate(ebad|slope|eflat|egap,10)|rflag)
        evalid[:20]=False;evalid[-20:]=False
        # Anti-alias lowpass at the higher rate before sampling on the 10Hz EDA grid.
        eg120=np.interp(grid,t,eda_native);ef120=np.full(len(grid),np.nan)
        for a,b in runs(~(gapmask|~np.isfinite(eg120))):
            if b-a<10*fs:continue
            ef120[a:b]=ss.sosfiltfilt(ss.butter(4,3,fs=fs,output='sos'),eg120[a:b])
        ec=np.interp(et,grid,ef120);evalid&=np.isfinite(ec)
        es=pd.DataFrame(dict(time_s=et,eda_raw_us=en,eda_filtered_us=ec,valid=evalid,range_transition_flag=rflag))
        decomp={}
        for method in ['highpass','cvxeda']:
            tonic=np.full(len(et),np.nan);phasic=tonic.copy()
            # Split at rejected periods; decomposition never bridges excluded intervals.
            for a,b in runs(evalid):
                if b-a<100:evalid[a:b]=False;continue
                try:
                    kw=dict(alpha=.0008,gamma=.01) if method=='cvxeda' else {}
                    d=nk.eda_phasic(ec[a:b],sampling_rate=10,method=method,**kw)
                    tonic[a:b]=d.EDA_Tonic;phasic[a:b]=d.EDA_Phasic
                except Exception as e:errors.append(dict(scene=key,stage=method,start_s=a/10,error=str(e)))
            usable=evalid&np.isfinite(tonic)&np.isfinite(phasic)
            # Additional 2s guard at every decomposition boundary.
            for a,b in runs(usable):usable[a:a+20]=False;usable[max(a,b-20):b]=False
            events=[]
            for a,b in runs(np.isfinite(phasic)):
                if b-a<100:continue
                try:
                    _,info=nk.eda_peaks(phasic[a:b],sampling_rate=10,method='neurokit',amplitude_min=0)
                    for onset,peak,amp in zip(info['SCR_Onsets'],info['SCR_Peaks'],info['SCR_Amplitude']):
                        if not np.isfinite(onset+peak+amp):continue
                        o=int(onset)+a;p=int(peak)+a
                        if p>=o and usable[o:p+1].all():events.append((et[o],et[p],float(amp)))
                except Exception as e:errors.append(dict(scene=key,stage=method+'_peaks',error=str(e)))
            ev=pd.DataFrame(events,columns=['onset_s','peak_s','amplitude_us']);ev.to_csv(out/f'{key}_{method}_scr.csv',index=False)
            for threshold in CFG['scr_thresholds_us']:
                selected=ev[ev.amplitude_us>=threshold];secs=usable.sum()/10
                edarows.append(dict(participant=pid,condition=condition,method=method,scr_threshold_us=threshold,
                                    valid_seconds=secs,coverage_pct=100*usable.mean(),
                                    mean_scl_us=np.mean(tonic[usable]) if usable.any() else np.nan,
                                    scr_count=len(selected),scr_per_min=len(selected)*60/secs if secs else np.nan,
                                    mean_scr_amplitude_us=selected.amplitude_us.mean(),
                                    below_85pct_coverage=100*usable.mean()<85))
            es[f'{method}_tonic_us']=tonic;es[f'{method}_phasic_us']=phasic;es[f'{method}_valid']=usable
            decomp[method]=(tonic,phasic,ev,usable)
        es['valid']=evalid;es.to_csv(out/f'{key}_eda_signals.csv.gz',index=False)
        qc['eda_initial_flag_pct']=100*np.mean(~evalid);qcrows.append(qc)
        # Full-scene diagnostic figure; HR points are accepted interval estimates.
        fig,ax=plt.subplots(5,1,figsize=(13,13),sharex=True,layout='constrained')
        fig.suptitle(f'{key} — exploratory processing, not final exclusions',fontsize=16)
        ax[0].plot(grid[::5],raw[::5],lw=.5,color='#6b7280');ax[0].set_ylabel('Raw PPG (mV)')
        ax[1].plot(t,np.where(df.vendor_hr>0,df.vendor_hr,np.nan),color='#aaa',lw=.7,label='Consensys (positive values)')
        colors=dict(elgendi='#2563eb',bishop='#b45309',heartpy='#059669')
        for method,(_,q,bt,cov) in plotdata.items():
            if not bt.empty:
                ok=bt.accepted;ax[1].plot(bt.end_s[ok],60000/bt.ibi_ms[ok],'.',ms=2,color=colors[method],label=method)
            ax[2].plot(grid[::12],q[::12],lw=.6,color=colors[method],label=method)
        ax[1].set_ylabel('HR (BPM)');ax[1].legend(ncol=4,fontsize=8)
        ax[2].axhline(.8,color='black',ls='--',lw=.7);ax[2].set_ylabel('Template similarity')
        ax[3].plot(et,en,color='#aaa',lw=.7,label='Raw conductance')
        for method,(tonic,phasic,ev,usable) in decomp.items():
            ax[3].plot(et,tonic,lw=1,label=method+' tonic')
            ax[4].plot(et,phasic,lw=.8,label=method+' phasic')
        ax[3].set_ylabel('EDA / tonic (µS)');ax[4].set_ylabel('Phasic (µS)');ax[4].set_xlabel('Seconds from scene start')
        for a,b in runs(~basevalid):ax[0].axvspan(grid[a],grid[min(b,len(grid)-1)],color='red',alpha=.15)
        for a,b in runs(~evalid):
            for axis in ax[3:]:axis.axvspan(et[a],et[min(b,len(et)-1)],color='red',alpha=.15)
        for axis in ax:axis.grid(alpha=.15)
        ax[3].legend(fontsize=8);ax[4].legend(fontsize=8)
        fname=f'{key}_overview.png';fig.savefig(out/fname,dpi=135);plt.close(fig);figures.append(fname)
        # Fixed-time windows allow visual beat verification without selecting for agreement.
        fig,axes=plt.subplots(3,1,figsize=(13,8),layout='constrained')
        for axis,start in zip(axes,[20,100,180]):
            sel=(grid>=start)&(grid<start+10);axis.plot(grid[sel],clean[sel],color='#444',lw=1)
            for j,method in enumerate(colors):
                pk=allpeaks[method];pk=pk[(grid[pk]>=start)&(grid[pk]<start+10)]
                axis.scatter(grid[pk],clean[pk],s=35+20*j,facecolors='none',edgecolors=colors[method],marker=['o','s','^'][j],label=method)
            axis.set_title(f'{start}–{start+10}s');axis.set_ylabel('Filtered PPG');axis.grid(alpha=.2)
        axes[0].legend(ncol=3);axes[-1].set_xlabel('Scene time (s)');fig.suptitle(key+' — fixed-time pulse overlays')
        fname=f'{key}_beats.png';fig.savefig(out/fname,dpi=135);plt.close(fig);figures.append(fname)
    tables={'recording_qc':pd.DataFrame(qcrows),'ppg_features':pd.DataFrame(ppgrows),
            'eda_features':pd.DataFrame(edarows),'detector_agreement':pd.DataFrame(agreement)}
    for name,table in tables.items():table.to_csv(out/f'{name}.csv',index=False)
    versions={x:importlib.metadata.version(x) for x in ['neurokit2','heartpy','cvxopt','numpy','scipy','pandas','matplotlib']}
    (out/'provenance.json').write_text(json.dumps(dict(config=CFG,versions=versions,sources=sources,errors=errors),indent=2))
    note='''<p>Scene-trimmed recordings. No group inference and no final participant exclusion.
    All signal-quality thresholds are provisional. No ECG or manual reference annotations: agreement is not accuracy.</p>
    <p>PPG: timestamp-aware resampling to 120 Hz, 0.5–8 Hz Elgendi filter shared by all detectors.
    Bishop runs in 4s cores with 1s context on each side, retaining only core detections.
    HeartPy contributes its internally accepted peaks (its rejection logic differs from the other detectors).
    Template similarity ≥0.8, 40–180 BPM, and ≤30% deviation from an 11-interval rolling median define exploratory acceptance.
    HR is 60 × accepted interval count / accepted interval duration (time-weighted).
    RMSSD uses only genuinely adjacent accepted intervals, minimum 30 pairs; it is exploratory and not a standard continuous-epoch estimate.
    Base-only columns omit the template-quality gate. Different method masks mean summaries may cover different times.</p>
    <p>EDA: 3 Hz low-pass before sampling at 10 Hz. Flags: nonpositive/nonfinite values, >10 µS/s slope,
    2s near-flat windows, >100ms gaps, range transitions ±1s. These do not detect every artifact and may flag real signal.
    Decompose valid stretches ≥10s with high-pass (0.05 Hz default) or cvxEDA (raw µS, alpha=0.0008, gamma=0.01).
    cvxEDA is NOT Ledalab CDA. Neither MATLAB nor Ledalab was available.
    Count phasic onset-to-peak amplitudes ≥0.01 or ≥0.05 µS; these are sensitivity settings, not finalized thresholds.
    No SCRs means zero rate but undefined mean amplitude. Gap/boundary guards reduce usable exposure.</p>
    <p>Red shading marks preliminary raw-signal exclusions. Quality-based PPG rejection appears in saved masks and interval tables.
    The 85% coverage indicator only shows sensitivity to the protocol's 15% rule; it does not adjudicate exclusions.
    These are offline, noncausal filters. Original files were unchanged. Full signals, masks, intervals, SCR events,
    parameters, hashes and dependency versions are saved alongside this report.</p>'''
    body='<h1>PhysioVaping: expanded method pilot</h1>'+note
    for name,table in tables.items():body+=f'<h2>{name.replace("_"," ")}</h2>'+table.round(3).to_html(index=False,border=0)
    body+='<h2>Processing errors</h2><pre>'+html.escape(json.dumps(errors,indent=2))+'</pre>'
    body+='<h2>Signal review</h2>'+''.join(f'<img src="{f}" loading="lazy">' for f in figures)
    body+='<h2>Sources and methods</h2><ul>'+''.join(f'<li><a href="{url}">{label}</a></li>' for label,url in [
        ('NeuroKit PPG','https://neuropsychology.github.io/NeuroKit/functions/ppg.html'),
        ('NeuroKit EDA','https://neuropsychology.github.io/NeuroKit/functions/eda.html'),
        ('HeartPy','https://python-heart-rate-analysis-toolkit.readthedocs.io/en/latest/heartpy.heartpy.html'),
        ('cvxEDA','https://github.com/lciti/cvxEDA')])+'</ul>'
    (out/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>PhysioVaping signal pilot</title><style>body{font:15px system-ui;margin:35px;max-width:1600px;color:#172033}p{max-width:1050px;line-height:1.6}table{display:block;overflow:auto;border-collapse:collapse;font-size:12px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:right}th{background:#e8eef5}img{width:100%;max-width:1400px;margin:20px 0}h2{margin-top:35px}</style>'+body)
    print('DONE',out,'errors',len(errors),flush=True)

if __name__=='__main__':
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always');main()
        # Emit distinct library warnings for audit, without overwhelming the terminal.
        for message in sorted(set(str(x.message) for x in caught)):print('LIBRARY WARNING:',message,flush=True)
