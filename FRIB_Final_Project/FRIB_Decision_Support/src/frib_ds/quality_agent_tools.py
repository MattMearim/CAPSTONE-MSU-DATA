"""Bounded read-only dataset tools. No SQL, file paths, RAG, or mutation tools."""
from __future__ import annotations
import hashlib
import json
import math
import numpy as np

from frib_ds.storage.reset import DataLifecycleLock
from frib_ds.units import normalize_event_units


def fingerprint(event):
    return hashlib.sha256(event.model_dump_json().encode()).hexdigest()


def _text(value, limit=180):
    return str(value)[:limit]


def _finite(value):
    return float(value) if math.isfinite(float(value)) else None


class ReadOnlyDataTools:
    def __init__(self, services, event):
        self.services, self.event = services, event
        self.signals = {f's{index}': signal for index, signal in enumerate(event.signals)}
        self.observed = {key: set() for key in self.signals}
        self.summarized = set()
        self.windows = []
        self.related = {row['event_id']: row for row in services.repo.list_events(limit=6) if row['event_id'] != event.event_id}
        self.compared = set()

    def overview(self):
        metadata = {key: _text(self.event.metadata[key], 240) for key in ('dataset_name','operating_mode','configuration','beam_state','cavity','cryomodule') if key in self.event.metadata}
        return {'event_id': self.event.event_id, 'domain': _text(self.event.domain), 'event_type': _text(self.event.event_type),
                'recorded_at': self.event.timestamp.isoformat(), 'metadata': metadata,
                'channel_fields':['signal_name','label_excerpt','unit_excerpt','sample_count'],
                'channels': [[key,_text(signal.name,32),_text(signal.unit,20),len(signal.values)] for key,signal in self.signals.items()],
                'initial_summaries': [self.signal_summary(key) for key in list(self.signals)[:1]],
                'state_examples': [[item.timestamp_s,_text(item.name,80),_text(item.value,120)] for item in self.event.states[:8]],
                'log_examples': [[item.timestamp_s,_text(item.message,240)] for item in self.event.logs[:6]],
                'other_dataset_ids': list(self.related),
                'coverage_note': 'Summaries cover all values of summarized channels; only the listed sample indices and requested windows are directly inspected. Unseen data is not cleared.'}

    def signal_summary(self, key):
        if key not in self.signals: raise ValueError('Choose a listed signal_name such as s0.')
        signal = self.signals[key]
        values = np.asarray(signal.values, dtype=float)
        edges = np.linspace(0,len(values), min(16,len(values))+1, dtype=int)
        bins=[]; indices={0,len(values)-1}
        for left,right in zip(edges[:-1],edges[1:]):
            chunk=values[left:right]
            low,high=int(left+np.argmin(chunk)),int(left+np.argmax(chunk))
            scale=float(np.max(np.abs(chunk))) or 1.0
            scaled=chunk/scale
            with np.errstate(over='ignore',invalid='ignore'):
                mean=_finite(float(np.mean(scaled))*scale)
                spread=_finite(float(np.std(scaled))*scale)
            bins.append([int(left),int(right-1),low,high,mean,spread])
            indices.update((low,high))
        self.observed[key].update(indices); self.summarized.add(key)
        return {'signal_name':key,'label':_text(signal.name),'unit':_text(signal.unit,80),'sample_count':len(values),
                'bin_fields':['first_index','last_index','min_value_index','max_value_index','mean','stddev'],
                'bins':bins,'sample_fields':['index','time_s','value'],
                'observed_samples':[[index,signal.timestamps_s[index],signal.values[index]] for index in sorted(indices)]}

    def read_window(self,key,start,count):
        if key not in self.signals: raise ValueError('Unknown signal_name.')
        signal=self.signals[key]
        if start >= len(signal.values): raise ValueError('Window starts outside this channel.')
        stop=min(len(signal.values),start+min(96,count))
        self.observed[key].update(range(start,stop)); self.windows.append({'signal_name':key,'first_index':start,'last_index':stop-1})
        return {'signal_name':key,'sample_fields':['index','time_s','value'],
                'samples':[[index,signal.timestamps_s[index],signal.values[index]] for index in range(start,stop)]}

    def compare_dataset(self,event_id):
        if event_id not in self.related: raise ValueError('Choose an event_id from other_dataset_ids.')
        with DataLifecycleLock(self.services.config.data_dir):
            other=self.services.repo.get_event(event_id)
            if other is None: raise ValueError('The related dataset is no longer available.')
            other=normalize_event_units(other)
        self.compared.add(event_id)
        return {'event_id':event_id,'fingerprint':fingerprint(other),'domain':_text(other.domain),'event_type':_text(other.event_type),
                'metadata':{key:_text(other.metadata[key],180) for key in ('dataset_name','operating_mode','configuration') if key in other.metadata},
                'channels':[{'label':_text(signal.name),'unit':_text(signal.unit,80),'sample_count':len(signal.values),
                             'minimum':min(signal.values),'maximum':max(signal.values)} for signal in other.signals[:16]]}

    def execute(self,request):
        if request.tool=='signal_summary': return self.signal_summary(request.signal_name)
        if request.tool=='read_window': return self.read_window(request.signal_name,request.start_index,request.count)
        if request.tool=='compare_dataset': return self.compare_dataset(request.event_id)
        raise ValueError('This is not a read-only data-quality tool.')

    def validate_finding(self,finding):
        data=finding.model_dump(mode='json')
        key=finding.signal_name
        if finding.related_event_id and finding.related_event_id not in self.compared:
            raise ValueError('A related dataset must be read before citing it.')
        if key is None:
            if finding.start_index is not None or finding.end_index is not None:
                raise ValueError('Sample coordinates require a signal_name.')
            if finding.repair.action!='review_only': raise ValueError('A data repair requires a specific channel.')
            data['anchors']=[]
        else:
            if key not in self.signals: raise ValueError('Finding references an unknown channel.')
            signal=self.signals[key]
            first,last=finding.start_index,finding.end_index
            if (first is None)!=(last is None): raise ValueError('Supply both sample endpoints or neither.')
            anchors=[]
            if first is not None:
                if last < first or first not in self.observed[key] or last not in self.observed[key]:
                    raise ValueError('Flag endpoints must be actual sample indices inspected by the agent.')
                if not finding.evidence: raise ValueError('Numeric flags require evidence with exact inspected sample index/value pairs; bin means are not raw samples.')
                for evidence in finding.evidence:
                    if (evidence.index not in self.observed[key] or not first<=evidence.index<=last
                            or not math.isclose(evidence.value,signal.values[evidence.index],rel_tol=1e-6,abs_tol=1e-9)):
                        raise ValueError('The claimed evidence value/index does not match a directly inspected raw sample. Copy actual observed values, not bin means.')
                anchors=[{'index':index,'time_s':signal.timestamps_s[index],'value':signal.values[index]} for index in sorted({first,last,*[item.index for item in finding.evidence]})]
                data['verified_evidence']=[{'index':item.index,'time_s':signal.timestamps_s[item.index],'value':signal.values[item.index]} for item in finding.evidence]
            action=finding.repair.action
            if action=='replace_sample' and (first is None or first!=last or finding.repair.value is None):
                raise ValueError('Replacement proposals require one inspected sample and a finite replacement value.')
            if action=='exclude_samples' and (first is None or last-first>=96 or any(index not in self.observed[key] for index in range(first,last+1))):
                raise ValueError('Exclusion proposals must cover at most 96 directly inspected samples.')
            if action=='set_display_label' and not (finding.repair.label or '').strip():
                raise ValueError('A display-label proposal needs a nonempty label.')
            data.update(signal_name=signal.name,signal_key=key,anchors=anchors)
        data['proposal_hash']=hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()
        return data

    def coverage(self):
        total=sum(len(signal.values) for signal in self.signals.values())
        inspected=sum(len(indices) for indices in self.observed.values())
        return {'total_samples':total,'directly_inspected_samples':inspected,'all_samples_directly_inspected':inspected==total,
                'summarized_channels':[self.signals[key].name for key in sorted(self.summarized)],
                'total_channels':len(self.signals),'windows':self.windows,'compared_dataset_ids':sorted(self.compared),
                'limitation':'A bounded AI review is not a full-data integrity certificate. No findings does not mean all samples are correct.'}
