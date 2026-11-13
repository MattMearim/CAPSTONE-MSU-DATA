"""Execute and export real synthetic checks used by editable slide charts."""
import hashlib
import json
from pathlib import Path
import statistics
import sys

project=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(project/'src'))
from frib_ds.generator.registry import GeneratorRegistry
from frib_ds.processing.registry import ProcessorRegistry
from frib_ds.ingestion import build_event
from frib_ds.ingestion.quality import repair_upload
from frib_ds.quality import assess_event
from frib_ds.units import normalize_event_units

import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=project/'presentation_evidence')
out=parser.parse_args().output.expanduser().resolve()
artifact_dir=out/'slide_evidence'
artifact_dir.mkdir(parents=True,exist_ok=True)
def write(name,obj):
    (artifact_dir/name).write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8')

source=(project/'sample_data'/'quality_review.csv').read_bytes()
options={'event_id':'SLIDE-QUALITY','domain':'general','time_column':'time [s]','time_unit':'s',
 'column_roles':{'pressure [kPa]':'numeric','temperature [C]':'numeric','mode':'category','operator_note':'log'},
 'signal_names':{'pressure [kPa]':'pressure','temperature [C]':'temperature'}}
repairs=[{'operation':'drop_exact_duplicate_rows'}, {'operation':'mark_missing_tokens','columns':['pressure [kPa]']}, {'operation':'drop_invalid_numeric_cells','rows':[5],'columns':['pressure [kPa]']}]
reviewed,receipt=repair_upload('quality_review.csv',source,options,repairs)
event=normalize_event_units(build_event('quality_review.csv',reviewed,options))
settings={'expected_interval_s':1,'channels':{'pressure':{'expected_stable':True,'stability_tolerance':100,'min':0,'max':1500},'temperature':{'flatline_samples':5}}}
report=assess_event(event,settings)
codes={i['code'] for i in report['issues']}
assert {'RECORDING_GAP','STABILITY_EXCEEDED','BASELINE_CHANGE','OUT_OF_BOUNDS','FLATLINE_RUN'}<=codes,codes
assert receipt['input_rows']==11 and receipt['output_rows']==10
assert [change['count'] for change in receipt['changes']]==[1,1,1]
pressure=next(s for s in event.signals if s.name=='pressure')
assert pressure.unit=='Pa' and pressure.values==[1000]*4+[20000]*4
write('quality-event.json',event.model_dump(mode='json'));write('quality-report.json',report);write('repair-receipt.json',receipt)
(artifact_dir/'quality_review.original.csv').write_bytes(source)
(artifact_dir/'quality_review.reviewed.csv').write_bytes(reviewed)

def segments(signal):
    times,values=signal.timestamps_s,signal.values
    cadence=statistics.median(b-a for a,b in zip(times,times[1:]))
    chunks=[];start=0
    for i in range(1,len(times)):
        if times[i]-times[i-1]>=1.5:
            chunks.append({'name':f'{signal.name} segment {len(chunks)+1}','x':times[start:i],'y':values[start:i]});start=i
    chunks.append({'name':f'{signal.name} segment {len(chunks)+1}','x':times[start:],'y':values[start:]})
    return chunks

plots={
 'recording_gap':{'series':segments(pressure),'y_label':'Pressure (Pa)','annotation':'4 to 9 s between recorded samples.\nExpected cadence: 1 s.','source':['slide_evidence/quality-event.json','slide_evidence/quality-report.json']},
 'stability':{'series':segments(pressure),'y_label':'Pressure (Pa)','annotation':'1000 Pa to 20000 Pa.\nChosen tolerance: 100 Pa.','source':['slide_evidence/quality-event.json','slide_evidence/quality-report.json']},
}
for domain in ['rf','mechanical','plc']:
    capture=normalize_event_units(GeneratorRegistry().for_domain(domain).generate(42))
    result=ProcessorRegistry().analyze(capture)
    assert result.processor!='evidence_summary',(domain,result.processor)
    write(domain+'-event.json',capture.model_dump(mode='json'));write(domain+'-analysis.json',result.model_dump(mode='json'))
    if domain=='rf':
        ground=capture.metadata['synthetic_ground_truth']['trip_time_s']
        assert abs(result.features['trip_time_s']-ground)<1e-9
        assert result.features['pressure_delta']>0
        field=next(s for s in capture.signals if s.name=='cavity_field')
        # A bounded actual-data window, with every native sample retained.
        points=[(t,y) for t,y in zip(field.timestamps_s,field.values) if ground-.08<=t<=ground+.08]
        plots['rf']={'series':[{'name':'Cavity field','x':[t for t,y in points],'y':[y for t,y in points]}],
         'y_label':f'Cavity field ({field.unit})','annotation':f"Interlock reference: {ground:.4g} s.\n1/e crossing: {result.features['approx_decay_ms']:.4g} ms.",
         'source':['slide_evidence/rf-event.json','slide_evidence/rf-analysis.json']}
    elif domain=='mechanical':
        target=capture.metadata['synthetic_ground_truth']['fault_frequency_hz']
        peak=result.features['dominant_frequency_hz']
        assert abs(peak-target)<2 and result.features['rms_post']>result.features['rms_pre']
        spectrum=next(p for p in result.plot_specs if p['kind']=='fft')
        points=[(f,a) for f,a in zip(spectrum['frequencies_hz'],spectrum['amplitudes']) if f<=max(100,target*2)]
        assert abs(max(points,key=lambda point:point[1])[0]-peak)<2
        plots['mechanical']={'series':[{'name':'Post-event vibration','x':[f for f,a in points],'y':[a for f,a in points]}],
         'y_label':f"Amplitude ({spectrum['amplitude_unit']})",'annotation':f'Measured peak: {peak:.3g} Hz.\nSynthetic target: {target:.3g} Hz.',
         'source':['slide_evidence/mechanical-event.json','slide_evidence/mechanical-analysis.json']}
    else:
        assert result.features['sequence'][:3]==['RUNNING','WARNING','INTERLOCKED']

(out/'slide_plot_data.json').write_text(json.dumps(plots,indent=2,allow_nan=False),encoding='utf-8')
write('CHECKS.json',{'status':'passed','input_sha256':hashlib.sha256(source).hexdigest(),
 'checks':['Three explicit repairs count1 each','Original source11 records to reviewed10','Pressure8 accepted Pa samples with measured step',
 'Recording gap and declared stability/bounds flags','RF interlock ground truth and positive pressure change','Mechanical spectral target and increasing RMS','PLC observed initial sequence'],
 'scope':'Pure ingestion, normalization, quality and processor API on synthetic inputs. No application storage writes.'})
print(json.dumps({'status':'passed','quality_codes':sorted(codes),'charts':list(plots),'output':str(out/'slide_plot_data.json')}))
