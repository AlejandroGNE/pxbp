import importlib.util
import json
import threading
import time
from copy import deepcopy
from pathlib import Path

import pandas as pd
import numpy as np
import duckdb
import pytest
from bokeh.document import Document

from pxbp.analytics import (make_analysis,read_analysis,validate_analysis,validate_measure,calculate,build_analysis,export_analysis,
    split_time,time_group,weighted_quantiles,MEASURES,RECIPES)
from pxbp.app import make_document
from pxbp.sources import normalize,Source,Cancelled


def frame(identifier,values,starts=None,hours=None,objects=None):
    m=MEASURES[identifier];interval=m['period']=='Interval';starts=starts or ['2030-01-01']*len(values)
    rows=[]
    for i,value in enumerate(values):
        start=pd.Timestamp(starts[i]);end=start+pd.Timedelta((hours or [1]*len(values))[i],unit="h") if interval else pd.Timestamp(start.year,12,31)
        unit={'energy':'MWh','power':'MW','money':'$','price':'$/MWh','percent':'%','mass':'ton'}[m['family']]
        rows.append(dict(start_date=start,end_date=end,object_name=(objects or ['Object']*len(values))[i],category_name='Category',
            class_name=m['scope'],collection_name=m['collection'].removeprefix('System'),property_name=m['property'],unit=unit,value=value,
            period_type_name=m['period'],phase_name='LT',sample_name='Mean',timeslice_name='All Periods',model_name='Model',band_id=1))
    return validate_measure(normalize(rows,Source('Baseline',path='unused')),m)


class Store:
    def __init__(self,**kwargs):self.frames=kwargs
    def get(self,name):return self.frames[name].copy()


def config():return make_analysis([Source('Baseline',path='unused')],'Baseline',date_from='2030-01-31',date_to='2030-02-02',recipes=['monthly-load'])


def test_month_boundary_energy_and_reported_amount_conservation():
    load=frame('load',[100,200],['2030-01-31T23:00','2030-02-01T01:00'],[2,3])
    result=calculate(RECIPES['monthly-load'],Store(load=load),config())
    assert result.value.tolist()==pytest.approx([100/1e6,700/1e6])
    assert result.partial_month.all()
    money=frame('interval-system-cost',[200],['2030-01-31T23:00'],[2])
    result=calculate(RECIPES['monthly-interval-system-cost'],Store(**{'interval-system-cost':money}),config())
    assert result.value.tolist()==pytest.approx([100e-9,100e-9])
    assert result.value.sum()==pytest.approx(200e-9)


def test_duration_weights_and_load_weighted_price():
    starts=['2030-02-01T00:00','2030-02-01T01:00']
    price=frame('price',[-10,50],starts,[1,3]);load=frame('load',[100,300],starts,[1,3])
    store=Store(price=price,load=load)
    assert calculate(RECIPES['monthly-price'],store,config()).value.iloc[0]==35
    assert calculate(RECIPES['monthly-load-weighted-price'],store,config()).value.iloc[0]==44
    missing=Store(price=price,load=load.iloc[:1])
    assert calculate(RECIPES['monthly-load-weighted-price'],missing,config()).value.isna().all()
    store=Store(price=price,load=load.assign(value=0))
    assert calculate(RECIPES['monthly-load-weighted-price'],store,config()).value.isna().all()


def test_weighted_asset_metrics_and_calendar_hours():
    gen=frame('generation',[1000,9000],objects=['A','B']);cap=frame('capacity',[100,300],objects=['A','B'])
    cf=frame('capacity-factor',[10,50],objects=['A','B']);price=frame('levelized-cost',[20,60],objects=['A','B'])
    store=Store(generation=gen,capacity=cap,**{'capacity-factor':cf,'levelized-cost':price})
    assert calculate(RECIPES['reported-capacity-factor'],store,config()).value.iloc[0]==40
    assert calculate(RECIPES['weighted-levelized-cost'],store,config()).value.iloc[0]==56
    assert calculate(RECIPES['capacity-utilization'],store,config()).value.iloc[0]==pytest.approx(100*10000/(400*8760))
    store.frames['capacity']=cap.iloc[:1]
    assert calculate(RECIPES['reported-capacity-factor'],store,config()).value.isna().all()
    assert calculate(RECIPES['capacity-utilization'],store,config()).value.isna().all()


def test_zero_capacity_and_missing_operand_are_undefined():
    energy=frame('battery-energy',[4000]);power=frame('battery-power',[0])
    assert calculate(RECIPES['storage-duration'],Store(**{'battery-energy':energy,'battery-power':power}),config()).value.isna().all()
    assert calculate(RECIPES['storage-duration'],Store(**{'battery-energy':energy,'battery-power':power.iloc[:0]}),config()).value.isna().all()


def test_profiles_split_uneven_intervals_by_hour():
    load=frame('load',[100,300],['2030-02-01T00:30','2030-02-01T02:00'],[1.5,1])
    result=calculate(RECIPES['profile-load'],Store(load=load),config()).sort_values('hour')
    assert result.hour.tolist()==[0,1,2]
    assert result.value.tolist()==pytest.approx([.1,.1,.3])
    assert result.observed_hours.tolist()==[.5,1,1]


def test_duration_histogram_statistics_use_hours_not_counts():
    price=frame('price',[-10,50],['2030-02-01T00:00','2030-02-01T01:00'],[1,3]);store=Store(price=price)
    curve=calculate(RECIPES['duration-price'],store,config())
    assert len(curve)==101 and curve.value.iloc[0]==50 and curve.value.iloc[-1]==-10
    hist=calculate(RECIPES['price-distribution'],store,config())
    assert hist.value.sum()==4
    stats=calculate(RECIPES['price-statistics'],store,config()).set_index('property_name')
    assert stats.loc['Time-weighted mean','value']==35
    assert stats.loc['Negative-price hours','value']==1
    assert stats.loc['Median','value']==50


def test_observed_unserved_event_stops_at_gaps():
    data=frame('unserved-power',[10,10,10,0],['2030-02-01T00:00','2030-02-01T01:00','2030-02-01T04:00','2030-02-01T05:00'])
    result=calculate(RECIPES['unserved-statistics'],Store(**{'unserved-power':data}),config()).set_index('property_name')
    assert result.loc['Observed unserved energy','value']==.03
    assert result.loc['Observed unserved hours','value']==3
    assert result.loc['Longest observed event','value']==2


def test_native_mass_and_cross_region_ambiguity():
    mass=frame('emissions',[100]);gen=frame('region-generation',[1000])
    result=calculate(RECIPES['emission-intensity'],Store(emissions=mass,**{'region-generation':gen}),config())
    assert result.value.iloc[0]==.1 and result.unit.iloc[0]=='ton/MWh'
    gen=pd.concat([gen,gen.assign(object_name='Second region')])
    with pytest.raises(ValueError,match='exactly one region'):
        calculate(RECIPES['emission-intensity'],Store(emissions=mass,**{'region-generation':gen}),config())


def test_interval_duplicate_overlap_and_unit_guards():
    with pytest.raises(ValueError,match='Overlapping'):frame('load',[1,2],['2030-01-01','2030-01-01T01:00'],[2,1])
    with pytest.raises(ValueError,match='Duplicate'):frame('load',[1,2])
    data=frame('load',[1]);data['unit']='MWh'
    with pytest.raises(ValueError,match='Unexpected reported units'):validate_measure(data,MEASURES['load'])


def test_share_and_year_change_semantics():
    gen=pd.concat([frame('generation',[10],objects=['A']),frame('generation',[30],objects=['B']).assign(category_name='Other')])
    result=calculate(RECIPES['generation-share'],Store(generation=gen),config())
    assert result.value.tolist()==[25,75]
    cap=frame('capacity',[100,80],['2030-01-01','2031-01-01'])
    result=calculate(RECIPES['capacity-change'],Store(capacity=cap),config())
    assert pd.isna(result.value.iloc[0]) and result.value.iloc[1]==-.02


@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    path=Path(__file__).parents[1]/'examples/create-analysis-demo.py'
    spec=importlib.util.spec_from_file_location('analysis_demo',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.create_demo(tmp_path_factory.mktemp('analytical')/'demo',cases=2)


@pytest.fixture(scope='module')
def all_results(demo,tmp_path_factory):
    _,cfg=read_analysis(demo);return build_analysis(cfg,tmp_path_factory.mktemp('cache'))


def test_all_recipes_real_parquet_adapter_and_deltas(all_results):
    assert len(all_results['sections'])==len(RECIPES)==79
    assert all(s['status']=='complete' for s in all_results['sections'])
    for s in all_results['sections']:
        if 'Difference' not in s['views']:continue
        delta=s['views']['Difference']['table'];base=delta[delta.scenario=='Baseline']
        assert base.value.dropna().eq(0).all()
        assert not delta.comparison_status.str.startswith('missing').any()
    shares=next(s for s in all_results['sections'] if s['section']['preset']=='generation-share')['views']['Absolute']['table']
    assert shares.groupby(['scenario','year']).value.sum().eq(100).all()
    assert all(m['query']['band_id']==1 and m['query']['sample']=='Mean' for m in all_results['measurements'].values())


def test_query_dedup_cache_budget_cancel_and_no_fake_zeros(demo,all_results):
    _,cfg=read_analysis(demo)
    with pytest.raises(ValueError,match='Row limit|budget'):build_analysis(cfg,max_rows=1)
    cancel=threading.Event();cancel.set()
    with pytest.raises(Cancelled):build_analysis(cfg,cancel=cancel)
    queried=sum(sum(c.get('rows',0) for c in m['coverage']) for m in all_results['measurements'].values())
    assert queried==all_results['query_rows']
    cfg['sections']=[{'id':'load','preset':'monthly-load'}];cfg['region']='Unknown'
    result=build_analysis(cfg)
    assert result['sections'][0]['status']=='unavailable'


@pytest.mark.parametrize('change',[
    {'date_from':'2030-01-01Z'}, {'date_to':'2033-01-01'}, {'baseline':'Unknown'}, {'annual_from':2035,'annual_to':2030},
    {'query_filters':{'period':'Month'}}, {'sections':[{'id':'../escape','preset':'monthly-load'}]},
    {'sections':[{'id':'bad','preset':'custom','formula':{'left':'emissions','right':'region-load','operation':'ratio'}}]},
    {'sections':[{'id':'bad','preset':'custom','formula':{'left':'capacity','right':'generation','operation':'difference'}}]},
    {'sections':[{'id':'bad','preset':'load-price','views':['Difference']}]},
])
def test_configuration_rejects_ambiguous_or_unsafe_calculations(change):
    with pytest.raises((ValueError,KeyError)):validate_analysis({**config(),**change})


def test_safe_custom_annual_ratio_units():
    section=dict(id='custom',preset='custom',formula=dict(left='generator-cost',right='generation',operation='ratio',scope='category'))
    cfg={**config(),'sections':[section]};_,cfg=validate_analysis(cfg)
    from pxbp.analytics import section_recipe
    result=calculate(section_recipe(cfg['sections'][0]),Store(generation=frame('generation',[100]),**{'generator-cost':frame('generator-cost',[5000])}),cfg)
    assert result.value.iloc[0]==50 and result.unit.iloc[0]=='$/MWh'


def test_live_editor_reordering_colors_views_and_formula(demo,all_results):
    sources,cfg=read_analysis(demo);cfg['sections']=cfg['sections'][:3]
    app=make_document(Document(),sources,analysis=cfg)
    panel=app.analytics;assert app.tabs.active==5 and app.job is None
    result=deepcopy(all_results);result['sections']=result['sections'][:3];result['config']=cfg
    panel.ready(result);panel.title.value='Edited title';panel.chart_type.value='Dot-Line';panel.views.value=['Absolute','Difference','Ratio'];panel.edit()
    assert panel.selected()['title']=='Edited title',panel.status.text
    assert 'Ratio' in panel.result['sections'][0]['views']
    panel.color_label.value='Gas-CC';panel.color.color='#123456';panel.change_color(False)
    assert panel.config['colors']['Gas-CC']=='#123456'
    panel.baseline.value='Case 01'
    assert panel.result is not None and panel.result['config']['baseline']=='Case 01'
    delta=panel.result['sections'][0]['views']['Difference']['table']
    assert delta[delta.scenario=='Case 01'].value.eq(0).all()
    first=panel.section.value;panel.move(1);assert panel.config['sections'][1]['id']==first
    panel.copy_section();assert panel.selected()['title']=='Edited title (copy)'
    panel.remove_section();assert len(panel.config['sections'])==3
    panel.add_formula();assert panel.selected()['preset']=='custom'
    panel.save_config();saved=json.loads(panel.text.value)
    assert saved['colors']['Gas-CC']=='#123456'
    assert saved['sections'][-1]['formula']['operation']=='ratio'
    panel.load_config();assert panel.result is None and app.job is None
    app.doc.validate();app.doc.to_json()


def test_many_solutions_share_bounded_queries(demo):
    sources,_=read_analysis(demo)
    many=[Source(f'Case {i:02d}',path=sources[0].path) for i in range(36)]
    cfg=make_analysis(many,'Case 00',date_from='2030-01-30',date_to='2030-02-02',recipes=['duration-price','monthly-price','price-statistics'])
    result=build_analysis(cfg,max_rows=5000)
    assert result['query_rows']==36*96
    assert len(result['measurements'])==1 and all(s['status']=='complete' for s in result['sections'])
    delta=result['sections'][0]['views']['Difference']['table']
    assert len(delta)==36*101 and delta.value.eq(0).all()


def test_export_offline_html_pdf_audit_and_filtered_baseline(demo,tmp_path):
    _,cfg=read_analysis(demo)
    cfg['sections']=[s for s in cfg['sections'] if s['preset'] in {'monthly-load','duration-price','heatmap-price','load-price','capacity-utilization'}]
    cfg['sections'][0]['plot']={'filters':{'scenario':['Case 01']}}
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(cfg))
    output=export_analysis(spec,tmp_path/'output')
    assert (output/'analysis.pdf').read_bytes().startswith(b'%PDF')
    html=(output/'analysis.html').read_text()
    assert 'iframe' in html and 'srcdoc' in html and 'https://cdn.bokeh.org' not in html
    audit=json.loads((output/'audit.json').read_text())
    assert len(audit['sections'])==5 and 'calculated_table' not in audit['sections'][0]
    assert json.loads((output/'complete.json').read_text())['all_sections_available']
    with duckdb.connect() as con:table=con.execute('SELECT * FROM read_parquet(?)',[str(output/(cfg['sections'][0]['id']+'-difference.parquet'))]).df()
    assert set(table.scenario)=={'Case 01'} and table.comparison_status.eq('matched').all()
    with pytest.raises(ValueError,match='exists'):export_analysis(spec,output)


def test_live_analysis_worker_and_error_completion(demo,tmp_path):
    sources,cfg=read_analysis(demo);cfg['sections']=[{'id':'price','preset':'duration-price'}]
    app=make_document(Document(),sources,analysis=cfg,cache_dir=tmp_path/'cache')
    app.analytics.run();assert app.analytics.build.disabled
    for _ in range(800):
        app.pump()
        if app.job is None:break
        time.sleep(.01)
    assert app.job is None and app.analytics.result
    assert not app.analytics.build.disabled and app.analytics.cancel.disabled
    assert '1/1' in app.analytics.status.text
    app.analytics.budget.value=1;app.analytics.run()
    for _ in range(800):
        app.pump()
        if app.job is None:break
        time.sleep(.01)
    assert app.job is None and 'Stopped' in app.analytics.status.text


def test_analysis_cli_configuration_and_incompatible_launch_flags(demo,tmp_path,capsys):
    from pxbp.cli import main
    from pxbp.workspace import make_workspace
    sources,cfg=read_analysis(demo)
    workspace=make_workspace(sources,{'collection':'SystemGenerators','properties':['Generation'],'phase':'LTPlan','period':'Year','sample':'Mean','band_id':1},
        {'baseline':'Baseline','colors':{'UPV':'#123456'}},['Baseline','Case 01'])
    path=tmp_path/'workspace.json';path.write_text(json.dumps(workspace));target=tmp_path/'analysis.json'
    assert main(['analysis-config','--workspace',str(path),'--output',str(target),'--from','2030-01-30','--to','2030-02-02','--presets','duration-price,monthly-load'])==0
    _,saved=read_analysis(target)
    assert [s['preset'] for s in saved['sections']]==['duration-price','monthly-load']
    assert saved['colors']=={'UPV':'#123456'} and saved['query_filters']['band_id']==1
    assert main(['analysis-presets'])==0
    assert 'Price calendar heatmap' in capsys.readouterr().out
    assert main(['serve','--analysis',str(target),'--bundle','unused'])==2
    assert main(['serve','--analysis',str(target),'--workspace','unused'])==2
