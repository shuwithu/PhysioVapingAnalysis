"""Build descriptive participant-level comparison; no inferential group testing."""
from pathlib import Path
import argparse,json,hashlib,base64,re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image

def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);args=ap.parse_args();out=args.output
    p=pd.read_csv(out/'ppg_features.csv');q=pd.read_csv(out/'recording_qc.csv')
    common=pd.read_csv(out/'ppg_common_time_comparison.csv');eda=pd.read_csv(out/'eda_features.csv')
    sen=pd.read_csv(out/'eda_artifact_sensitivity.csv');order=['neutral','environmental','social']
    groups={5:'Non-vaper',10:'Non-vaper',15:'Non-vaper',105:'Vaper',115:'Vaper',120:'Vaper'}
    for filename in ['recording_qc','ppg_features','eda_features','detector_agreement','ppg_common_time_comparison','eda_artifact_sensitivity']:
        table=pd.read_csv(out/f'{filename}.csv');table.insert(1,'group',table.participant.map(groups));table.to_csv(out/f'{filename}.csv',index=False)
    rows=[]
    for pid in q.participant.unique():
        hr=common[(common.participant==pid)&(common.method=='elgendi')].set_index('condition')
        for scene in order:
            pp=p[(p.participant==pid)&(p.condition==scene)]
            ee=eda[(eda.participant==pid)&(eda.condition==scene)&(eda.scr_threshold_us==.05)].set_index('method')
            se=sen[(sen.participant==pid)&(sen.condition==scene)].set_index('method')
            rows.append(dict(participant=pid,group=groups[pid],condition=scene,
                shared_time_hr_bpm=hr.loc[scene,'common_time_mean_hr_bpm'],
                delta_hr_from_neutral=hr.loc[scene,'common_time_mean_hr_bpm']-hr.loc['neutral','common_time_mean_hr_bpm'],
                common_ppg_seconds=hr.loc[scene,'common_seconds'],
                ppg_coverage_min_pct=pp.coverage_pct.min(),ppg_coverage_max_pct=pp.coverage_pct.max(),
                hr_method_spread_bpm=pp.mean_hr_bpm.max()-pp.mean_hr_bpm.min(),
                highpass_scl_us=ee.loc['highpass','mean_scl_us'],cvxeda_scl_us=ee.loc['cvxeda','mean_scl_us'],
                highpass_scr_per_min=ee.loc['highpass','scr_per_min'],cvxeda_scr_per_min=ee.loc['cvxeda','scr_per_min'],
                sensitivity_eda_coverage_pct=se.loc['highpass','sensitivity_coverage_pct'],
                sensitivity_highpass_scl_us=se.loc['highpass','sensitivity_mean_scl_us'],
                sensitivity_cvxeda_scl_us=se.loc['cvxeda','sensitivity_mean_scl_us'],
                sensitivity_highpass_scr_per_min=se.loc['highpass','sensitivity_scr_per_min_005'],
                sensitivity_cvxeda_scr_per_min=se.loc['cvxeda','sensitivity_scr_per_min_005']))
    result=pd.DataFrame(rows);result.to_csv(out/'participant_comparison.csv',index=False)
    fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
    colors=['#2563eb','#059669','#a16207','#dc2626','#9333ea','#db2777']
    for pid,c in zip(groups,colors):
        r=result[result.participant==pid].set_index('condition').loc[order]
        for ax,col in zip(axes.flat,['shared_time_hr_bpm','highpass_scl_us','sensitivity_highpass_scl_us','sensitivity_eda_coverage_pct']):
            ax.plot(range(3),r[col],marker='o',color=c,label=f'P{pid} · {groups[pid]}',linestyle='-' if pid<100 else '--')
    for ax,title,ylabel in zip(axes.flat,['HR on time shared by all pulse methods','Tonic EDA: initial screen, high-pass','Tonic EDA: sharp-drop sensitivity, high-pass','EDA coverage after sensitivity screen'],['BPM','µS','µS','% of scene']):
        ax.set_title(title);ax.set_ylabel(ylabel);ax.set_xticks(range(3),['Neutral','Environmental','Social']);ax.grid(alpha=.2)
    axes[0,0].legend(fontsize=8,ncol=2);axes[1,1].set_ylim(0,105)
    fig.suptitle('Six-participant descriptive pilot — quality rules provisional',fontsize=16)
    fig.savefig(out/'participant_comparison.png',dpi=150);plt.close(fig)
    # Compact contact sheets for reviewing every scene and fixed-time beat overlay.
    for pid in groups:
        for kind in ['overview','beats','eda_sensitivity']:
            canvas=Image.new('RGB',(1800,900),'white')
            for j,scene in enumerate(order):
                im=Image.open(out/f'P{pid}_{scene}_{kind}.png');im.thumbnail((600,900));canvas.paste(im,(600*j,0))
            canvas.save(out/f'P{pid}_{kind}_review.png')
    hrtable=result.pivot(index=['group','participant'],columns='condition',values='shared_time_hr_bpm')[order]
    deltas=result[result.condition!='neutral'].pivot(index=['group','participant'],columns='condition',values='delta_hr_from_neutral')
    summary='<h2>Expanded descriptive comparison: 3 non-vapers and 3 vapers</h2><p>Group labels supplied by the user. Same fixed settings as the original pilot. Scene labels refer to content, not presentation order. No significance tests, final exclusions, or causal group conclusions.</p>'
    summary+='<img src="participant_comparison.png"><h3>HR on common retained time (BPM)</h3>'+hrtable.round(2).to_html()
    summary+='<h3>HR changes relative to neutral (BPM)</h3>'+deltas.round(2).to_html()
    summary+='<p>Common-time matching is between pulse methods within each scene; it does not guarantee representative or equivalent portions across scenes. EDA sensitivity screening changes the retained exposure. Absolute tonic levels depend on decomposition. PRV remains exploratory, especially with differing acquisition rates.</p>'
    summary+='<h3>Acquisition rates and quality</h3>'+q.round(2).to_html(index=False)
    summary+='<h3>All scene-level comparisons</h3>'+result.round(3).to_html(index=False)
    page=(out/'report.html').read_text();page=page.replace('<h2>Context from the original',summary+'<h2>Context from the original',1)
    (out/'report.html').write_text(page)
    provenance=json.loads((out/'provenance.json').read_text());provenance['groups']=groups
    provenance['scripts']={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in Path('src/physiovaping').glob('*signal*pilot.py')}
    assert all(hashlib.sha256(Path(s['file']).read_bytes()).hexdigest()==s['sha256'] for s in provenance['sources'])
    (out/'provenance.json').write_text(json.dumps(provenance,indent=2))
    (out/'requirements-pilot.txt').write_text('\n'.join(k+'=='+v for k,v in provenance['versions'].items())+'\n')
    page=re.sub(r'src="([^\"]+\.png)"',lambda m:'src="data:image/png;base64,'+base64.b64encode((out/m.group(1)).read_bytes()).decode()+'"',page)
    (out/'report_standalone.html').write_text(page)
    print(result.round(2).to_string(index=False));print(q.round(2).to_string(index=False));print('INPUT HASHES UNCHANGED')

if __name__=='__main__':main()
