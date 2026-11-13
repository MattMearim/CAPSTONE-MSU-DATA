"""Additional recorded generator and tabular-format demonstrations."""
from frib_ds.generator.registry import GeneratorRegistry
from frib_ds.ingestion import build_event


def demonstrate_generators(r, client):
    @r.case("GEN-01", "Three reproducible generators and operational metadata", "L1", ["three_generators", "deterministic_seed", "custom_overrides", "operational_metadata", "dataset_name"], "API TestClient and generator helper")
    def generators(c):
        registry=GeneratorRegistry()
        catalog=c.response(client.get('/generators'))
        c.check('three generator domains',sorted(item['domain'] for item in catalog),['mechanical','plc','rf'])
        for domain in ['rf','mechanical','plc']:
            a=registry.for_domain(domain).generate(42)
            b=registry.for_domain(domain).generate(42)
            c.check(domain+' seed reproduces measurements',[s.values for s in a.signals]==[s.values for s in b.signals])
            c.check(domain+' synthetic provenance',a.provenance.source,'synthetic_generator')
            stored=c.response(client.post('/events/generate',json={'domain':domain,'seed':42}))
            c.check(domain+' persisted domain',stored['domain'],domain)
            c.artifact(domain+'-event',stored)
        context={'cavity':'DEMO-CAVITY','cryomodule':'DEMO-CM','operating_mode':'synthetic','beam_state':'inhibited','configuration':{'purpose':'presentation'}}
        overrides={'duration_s':2.,'sample_rate_hz':100.,'trip_time_s':1.2,'pressure_rise_start_s':1.,'reflected_power_rise_start_s':1.1}
        result=c.response(client.post('/events/generate-custom',json={'generator':'rf_cavity_trip','seed':7,'overrides':overrides,'dataset_name':'Presentation generator','metadata':context}))
        c.check('custom sample count',len(result['signals'][0]['values']),200)
        c.near('custom trip time',result['metadata']['synthetic_ground_truth']['trip_time_s'],1.2)
        c.check('dataset name retained',result['metadata']['dataset_name'],'Presentation generator')
        for key,value in context.items():c.check('context '+key,result['metadata'][key],value)
        c.artifact('custom-event',result)

    @r.case("GEN-02", "Generator bounds and scenario-time validation", "L1", ["generator_bounds", "finite_parameters", "sample_count_bounds", "nyquist_bound", "ordered_scenario_times"], "deterministic generator helper")
    def bounds(c):
        registry=GeneratorRegistry()
        cases=[('unknown key','rf',{'unknown':1},'Unknown'),('nonfinite','rf',{'duration_s':float('inf')},'finite'),
         ('nonpositive rate','rf',{'sample_rate_hz':0},'positive'),('nonpositive duration','rf',{'duration_s':0},'positive'),
         ('minimum samples','rf',{'duration_s':3,'sample_rate_hz':1},'4 to 250,000'),('maximum samples','rf',{'duration_s':10,'sample_rate_hz':25001},'4 to 250,000'),
         ('maximum rate','rf',{'sample_rate_hz':100001},'100,000'),('negative noise','rf',{'noise_std':-1},'negative'),
         ('nonpositive decay','rf',{'field_decay_tau_s':0},'greater than zero'),('trip outside capture','rf',{'trip_time_s':100},'inside'),
         ('pressure ordering','rf',{'duration_s':3,'trip_time_s':1.2,'pressure_rise_start_s':1.3,'reflected_power_rise_start_s':1.1},'before'),
         ('reflected ordering','rf',{'duration_s':3,'trip_time_s':1.2,'pressure_rise_start_s':1.0,'reflected_power_rise_start_s':1.3},'before'),
         ('zero base frequency','mechanical',{'base_frequency_hz':0},'below half'),('fault above Nyquist','mechanical',{'fault_frequency_hz':50000},'below half'),
         ('mechanical onset outside capture','mechanical',{'anomaly_time_s':100},'inside'),('PLC state ordering','plc',{'warning_time_s':2,'interlock_time_s':1,'reset_time_s':3},'warning < interlock')]
        for label,domain,overrides,message in cases:
            c.reject(label,lambda d=domain,o=overrides:registry.for_domain(d).generate(42,o),message)

    @r.case("FORMAT-01", "BOM, delimiters, quoted cells and ignored columns", "L1", ["utf8_bom", "semicolon_csv", "tab_csv", "pipe_csv", "quoted_fields", "ignore_role"], "deterministic ingestion helper")
    def formats(c):
        for index,delimiter in enumerate([',',';','\t','|']):
            import csv,io
            stream=io.StringIO(newline='')
            writer=csv.writer(stream,delimiter=delimiter,lineterminator='\r\n')
            writer.writerows([['time [s]','sensor [V]','note','unused'],[0,1,'operator, note; preserved','ignore me'],[1,2,'quoted "text"','ignore me']])
            data=stream.getvalue().encode('utf-8-sig')
            c.input(f'delimiter_{index}.csv',data)
            event=build_event('delimited.csv',data,{'column_roles':{'sensor [V]':'numeric','note':'log','unused':'ignore'}})
            c.near(f'delimiter{index} measurements',event.signals[0].values,[1,2])
            c.check(f'delimiter{index} ignored column',len(event.signals),1)
            c.check(f'delimiter{index} text preserved',[log.message for log in event.logs],['operator, note; preserved','quoted "text"'])
        c.artifact('event',event)
