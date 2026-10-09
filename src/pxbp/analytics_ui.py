"""Analytical report controls; workers never construct Bokeh models."""
from copy import deepcopy
import base64
import html
import json
import datetime

from bokeh.layouts import column,row
from bokeh.models import Button,CheckboxGroup,ColorPicker,CustomJS,DatePicker,Div,FileInput,MultiChoice,Select,Spinner,TextAreaInput,TextInput

from .analytics import make_analysis,validate_analysis,analysis_plot,section_recipe,build_analysis
from .analytics_catalog import RECIPES,MEASURES,DEFAULT_ANALYSIS
from .analytics_plotting import section_layout
from .comparison import MODES,compare
from .plotting import color_for
from .workspace import CHART_TYPES


class AnalyticsPanel:
    def __init__(self,app,config=None):
        self.app=app;self.result=None;self.loading=False
        labels=[s.label for s in app.sources]
        self.config=make_analysis(app.sources,labels[0])
        self.status=Div(text="Choose recipes and dates, then Build analysis. Annual reports use separate year bounds.")
        self.sources=MultiChoice(title="Analysis solutions",options=labels,value=labels,width=600)
        self.baseline=Select(title="Analysis baseline",options=labels,value=labels[0],width=300)
        self.baseline.on_change("value",self.rebaseline)
        self.start=DatePicker(title="Interval start date",value="2030-01-01",width=200)
        self.end=DatePicker(title="Interval last date (included)",value="2030-01-14",width=200)
        self.first_year=TextInput(title="Annual first year (blank = all)",width=200)
        self.last_year=TextInput(title="Annual last year (blank = all)",width=200)
        self.region=TextInput(title="Exact region object (blank = each reported region)",width=400)
        self.recipes=MultiChoice(title="Recipes to include",options=[(k,v["title"]) for k,v in RECIPES.items()],value=DEFAULT_ANALYSIS,width=700)
        self.all_button=Button(label="Select all recipes",width=170)
        self.all_button.on_click(lambda:setattr(self.recipes,"value",list(RECIPES)))
        self.budget=Spinner(title="Maximum unique queried rows",low=1,high=10000000,step=10000,value=2000000,width=300)
        self.build=Button(label="Build analysis",button_type="primary",width=200)
        self.build.on_click(self.run)
        self.cancel=Button(label="Cancel analysis",disabled=True,width=180);self.cancel.on_click(app.cancel)
        self.section=Select(title="Analysis section",options=[],value="",width=500)
        self.display=MultiChoice(title="Display cases (empty = all queried)",options=labels,value=[],width=600)
        self.chart=column(Div(text="Build an analysis to see its charts."),sizing_mode="stretch_width")
        self.section.on_change("value",self.changed);self.display.on_change("value",self.changed)
        self.title=TextInput(title="Section title",width=500)
        self.chart_type=Select(title="Section chart",options=CHART_TYPES,value="Line",width=220)
        self.panel_layout=Select(title="Section layout",options=["Recipe default"],value="Recipe default",width=280)
        self.views=MultiChoice(title="Comparison views",options=MODES,value=["Absolute","Difference"],width=500)
        self.columns=Spinner(title="Panels per row",low=1,high=6,value=1,step=1,width=180)
        self.options=CheckboxGroup(labels=["Net-total dots on stacks","Shared Y scales"],active=[1])
        self.apply=Button(label="Apply section styling",button_type="primary",width=220);self.apply.on_click(self.edit)
        self.up=Button(label="Move section up",width=160);self.down=Button(label="Move section down",width=170)
        self.duplicate=Button(label="Duplicate section",width=170);self.remove=Button(label="Remove section",width=170)
        self.up.on_click(lambda:self.move(-1));self.down.on_click(lambda:self.move(1))
        self.duplicate.on_click(self.copy_section);self.remove.on_click(self.remove_section)
        self.color_label=Select(title="Series color",options=[],value="",width=300)
        self.color=ColorPicker(title="Color",color="#0072B2",width=150)
        self.color_label.on_change("value",self.pick_color)
        self.set_color=Button(label="Set color",width=130);self.clear_color=Button(label="Use default color",width=160)
        self.set_color.on_click(lambda:self.change_color(False));self.clear_color.on_click(lambda:self.change_color(True))
        self.order=TextAreaInput(title="Preferred series order (one exact label per line)",rows=3,width=500)
        self.order_button=Button(label="Apply series order",width=180);self.order_button.on_click(self.change_order)
        annual=[(k,v["scope"]+" / "+v["property"]) for k,v in MEASURES.items() if v["period"]=="Year"]
        self.left=Select(title="Formula numerator / value",options=annual,value="generation",width=350)
        self.right=Select(title="Formula denominator / weight",options=annual,value="capacity",width=350)
        self.formula_op=Select(title="Calculation",options=[("ratio","A / B"),("difference","A - B"),("fraction","100 × A / (A + B)"),("weighted","Weighted mean of A using B")],value="ratio",width=300)
        self.scope=Select(title="Formula scope",options=["object","category"],value="category",width=180)
        self.formula_title=TextInput(title="Calculated section title",value="Calculated annual measure",width=500)
        self.formula_add=Button(label="Add calculated section",width=220);self.formula_add.on_click(self.add_formula)
        self.text=TextAreaInput(title="Analysis configuration (private paths / IDs)",rows=8,sizing_mode="stretch_width")
        self.save=Button(label="Prepare analysis configuration",width=250);self.save.on_click(self.save_config)
        self.download=Button(label="Download analysis configuration",width=260)
        self.download.js_on_click(CustomJS(args={"text":self.text},code="""
            if(!text.value.trim())return;const url=URL.createObjectURL(new Blob([text.value],{type:'application/json'}));
            const a=document.createElement('a');a.href=url;a.download='analysis.private.json';a.click();URL.revokeObjectURL(url);
        """))
        self.file=FileInput(accept=".json",width=500);self.file.on_change("value",self.upload)
        self.load=Button(label="Apply analysis configuration",width=250);self.load.on_click(self.load_config)
        self.summary=Div(text="Interval and annual selections are independent. Open Query settings to choose inputs.")
        self.query_box=column(self.sources,self.budget,row(self.start,self.end,self.first_year,self.last_year),self.region,
            column(self.recipes,height=170,styles={"overflow-y":"auto"}),self.all_button,visible=config is None)
        self.editor_box=column(
            Div(text="<h3>Report editor</h3><p>Style, colors, ordering, and comparison views update loaded data without queries. Adding recipes or changing inputs requires Build analysis.</p>"),
            self.title,row(self.chart_type,self.panel_layout,self.columns),self.views,self.options,row(self.apply,self.up,self.down,self.duplicate,self.remove),
            row(self.color_label,self.color,self.set_color,self.clear_color),self.order,self.order_button,visible=False)
        self.formula_box=column(
            Div(text="<h3>Calculated annual section</h3><p>Choose reported inputs from the same class. No code is executed. Formulas keep native base units; incomplete operand sets and zero denominators remain undefined.</p>"),
            row(self.left,self.right),row(self.formula_op,self.scope),self.formula_title,self.formula_add,visible=False)
        self.save_box=column(
            Div(text="<h3>Save and reopen</h3><p>Download the configuration to preserve sources, baseline, recipes, colors, section order, and chart settings. Keep it private. The command-line analysis export creates offline HTML, PDF, and complete audited values.</p>"),
            self.file,row(self.save,self.download,self.load),self.text,visible=False,sizing_mode="stretch_width")
        self.toggles=[]
        for label,box in [("Query settings",self.query_box),("Report editor",self.editor_box),("Calculated measures",self.formula_box),("Save / open",self.save_box)]:
            button=Button(label=label,width=165)
            button.on_click(lambda box=box:setattr(box,"visible",not box.visible))
            self.toggles.append(button)
        self.layout=column(self.status,self.summary,row(self.build,self.cancel,*self.toggles),row(self.baseline,self.section),self.display,
            self.query_box,self.editor_box,self.formula_box,self.save_box,self.chart,sizing_mode="stretch_width")
        if config:self.apply_config(config)

    def message(self,message):self.status.text=html.escape(str(message))

    def busy(self,value):
        for widget in (self.build,self.baseline,self.sources,self.start,self.end,self.first_year,self.last_year,self.region,self.recipes,self.all_button,self.budget):widget.disabled=value
        self.cancel.disabled=not value

    def current(self):
        cfg=deepcopy(self.config)
        cfg.update(selected_sources=list(dict.fromkeys([self.baseline.value,*self.sources.value])),baseline=self.baseline.value,
            date_from=str(self.start.value),date_to=str(self.end.value),region=self.region.value.strip(),
            annual_from=int(self.first_year.value) if self.first_year.value.strip() else None,
            annual_to=int(self.last_year.value) if self.last_year.value.strip() else None)
        wanted=set(self.recipes.value)
        cfg["sections"]=[s for s in cfg["sections"] if s["preset"]=="custom" or s["preset"] in wanted]
        existing={s["preset"] for s in cfg["sections"]}
        cfg["sections"].extend({"id":self.new_id(k,cfg),"preset":k} for k in self.recipes.value if k not in existing)
        return validate_analysis(cfg)[1]

    @staticmethod
    def new_id(base,cfg):
        ids={s["id"] for s in cfg["sections"]};ident=base;n=2
        while ident in ids:ident=f"{base}-{n}";n+=1
        return ident

    def apply_config(self,config):
        sources,cfg=validate_analysis(config);self.loading=True
        try:
            labels=[s.label for s in sources];self.config=cfg;self.app.sources=sources
            self.app.source_choice.options=labels;self.app.source_choice.value=cfg["selected_sources"]
            self.app.baseline.options=labels;self.app.baseline.value=cfg["baseline"]
            self.app.bundle_baseline.options=labels;self.app.bundle_baseline.value=cfg["baseline"]
            self.app.bundle_scenarios.options=labels;self.app.bundle_scenarios.value=[]
            self.app.bundle_configuration=None;self.app.bundle_result=None
            self.sources.options=labels;self.sources.value=cfg["selected_sources"]
            self.baseline.options=labels;self.baseline.value=cfg["baseline"]
            self.display.options=labels;self.display.value=[]
            self.start.value=pd_date(cfg["date_from"]);self.end.value=pd_date(cfg["date_to"])
            self.first_year.value=str(cfg["annual_from"] or "");self.last_year.value=str(cfg["annual_to"] or "");self.region.value=cfg["region"]
            self.recipes.value=list(dict.fromkeys(s["preset"] for s in cfg["sections"] if s["preset"]!="custom"))
            self.order.value="\n".join(cfg.get("series_order",[]));self.result=None
            self.refresh_sections();self.chart.children=[Div(text="Configuration loaded. Press Build analysis.")]
        finally:self.loading=False
        self.changed(None,None,None);self.message("Analysis configuration loaded; no queries ran automatically.")

    def run(self):
        if self.app.job:return
        try:cfg=self.current()
        except Exception as exc:self.message("Cannot build analysis: "+str(exc));return
        self.config=cfg;self.result=None;self.chart.children=[Div(text="Building analysis…")]
        self.message("Querying unique measurements and calculating selected recipes…")
        max_rows=int(self.budget.value);refresh=0 not in self.app.cache_options.active
        def work(cancel,emit):
            result=build_analysis(cfg,self.app.cache_dir,max_rows=max_rows,cancel=cancel,progress=lambda m:emit("analysis_progress",m),refresh=refresh)
            emit("analysis_result",result)
        self.app.start_job(work,kind="analysis")

    def ready(self,result):
        self.result=result;self.config=deepcopy(result["config"]);self.refresh_sections();self.changed(None,None,None)
        self.summary.text=f"{len(self.config['selected_sources'])} queried cases; interval dates {html.escape(self.config['date_from'])} through {html.escape(self.config['date_to'])}; annual years {self.config['annual_from'] or 'first reported'} through {self.config['annual_to'] or 'last reported'}. Open Query settings to change inputs."
        n=sum(s["status"]=="complete" for s in result["sections"])
        self.message(f"Analysis ready. {n}/{len(result['sections'])} sections fully available; {result['query_rows']:,} unique queried rows.")

    def refresh_sections(self):
        old=self.section.value;options=[(s["id"],s["title"]) for s in self.config["sections"]]
        self.section.options=options;self.section.value=old if old in {k for k,_ in options} else options[0][0]

    def selected(self):return next(s for s in self.config["sections"] if s["id"]==self.section.value)

    def changed(self,attr,old,new):
        if self.loading or not self.section.value:return
        s=self.selected();recipe=section_recipe(s);plot=analysis_plot(recipe,self.config,s.get("plot"))
        self.title.value=s["title"];self.views.value=s["views"]
        choices=["Scatter"] if recipe["operation"]=="scatter" else [*CHART_TYPES,*(["Heatmap"] if recipe["resolution"]=="heatmap" else [])]
        self.chart_type.options=choices;self.chart_type.value=plot["chart_type"]
        self.panel_layout.options=["Recipe default","Scenario panels","Technology panels"] if recipe["scope"]=="category" and recipe["resolution"] not in {"duration","profile"} else ["Recipe default"]
        self.panel_layout.value="Technology panels" if len(self.panel_layout.options)>1 and plot["facet"]=="category_name" else "Scenario panels" if len(self.panel_layout.options)>1 and plot["facet"]=="scenario" else "Recipe default"
        self.columns.value=plot["columns"];self.options.active=[i for i,key in enumerate(["net_total","shared_axes"]) if plot[key]]
        labels=set(self.config.get("colors",{}))|set(self.config["selected_sources"])
        if self.result:
            section=next((r for r in self.result["sections"] if r["section"]["id"]==s["id"]),None)
            if section:
                for view in section["views"].values():
                    if view["status"]=="available":labels.update(str(v) for v in view["table"][plot["series"]].unique())
                self.chart.children=[section_layout(section,self.display.value)]
            else:self.chart.children=[Div(text="New section. Press Build analysis to load its measurements.")]
        self.color_label.options=sorted(labels);self.color_label.value=self.color_label.value if self.color_label.value in labels else sorted(labels)[0] if labels else ""
        self.pick_color(None,None,None)

    def restyle(self):
        if not self.result:return
        if set(self.config["selected_sources"])!=set(self.result["config"]["selected_sources"]) or any(self.config.get(k)!=self.result["config"].get(k) for k in ("date_from","date_to","annual_from","annual_to","region","query_filters")):
            self.message("Query inputs changed. Build analysis to load the new measurements.")
            self.result=None;self.chart.children=[Div(text="Query inputs changed. Press Build analysis.")];return
        self.result["config"]=deepcopy(self.config)
        byid={s["id"]:s for s in self.config["sections"]};updated=[]
        for result in self.result["sections"]:
            ident=result["section"]["id"]
            if ident not in byid:continue
            s=byid[ident];plot=analysis_plot(result["definition"],self.config,s.get("plot"))
            result.update(section=s,plot=plot)
            if "calculated_table" in result:
                result["views"]={}
                for mode in s["views"]:
                    try:result["views"][mode]=dict(table=compare(result["calculated_table"],self.config["baseline"],mode,visible=plot["filters"].get("scenario") or None),plot={**plot,"comparison":mode},status="available")
                    except ValueError as exc:result["views"][mode]=dict(status="unavailable",reason=str(exc))
            else:
                for mode,view in result["views"].items():view["plot"]={**plot,"comparison":mode}
            updated.append(result)
        self.result["sections"]=sorted(updated,key=lambda r:list(byid).index(r["section"]["id"]))

    def rebaseline(self,attr,old,new):
        if self.loading or not self.result or self.app.job:return
        self.config=self.current();self.restyle();self.changed(None,None,None)
        if self.result:self.message("Baseline updated from loaded measurements; no queries ran.")

    def edit(self):
        if self.app.job:self.message("Wait for the current job before editing.");return
        try:
            cfg=self.current();s=next(s for s in cfg["sections"] if s["id"]==self.section.value)
            s.update(title=self.title.value,views=list(self.views.value))
            s["plot"]={**s.get("plot",{}),"chart_type":self.chart_type.value,"columns":int(self.columns.value),"net_total":0 in self.options.active,"shared_axes":1 in self.options.active}
            if self.panel_layout.value=="Scenario panels":s["plot"].update(series="category_name",facet="scenario")
            elif self.panel_layout.value=="Technology panels":s["plot"].update(series="scenario",facet="category_name")
            self.config=validate_analysis(cfg)[1];self.restyle();self.refresh_sections();self.changed(None,None,None)
            self.message("Section updated using loaded data; no queries ran.")
        except Exception as exc:self.message("Cannot edit section: "+str(exc))

    def move(self,direction):
        if self.app.job:return
        self.config=self.current();sections=self.config["sections"];index=next(i for i,s in enumerate(sections) if s["id"]==self.section.value)
        target=index+direction
        if 0<=target<len(sections):sections[index],sections[target]=sections[target],sections[index]
        self.restyle();self.refresh_sections();self.changed(None,None,None)

    def copy_section(self):
        if self.app.job:return
        self.config=self.current();s=deepcopy(self.selected());s["id"]=self.new_id(s["id"],self.config);s["title"]+=" (copy)"
        self.config["sections"].append(s)
        if self.result:
            original=next((r for r in self.result["sections"] if r["section"]["id"]==self.section.value),None)
            if original:clone=deepcopy(original);clone["section"]=s;self.result["sections"].append(clone)
        self.refresh_sections();self.section.value=s["id"];self.changed(None,None,None)

    def remove_section(self):
        if self.app.job:return
        cfg=self.current()
        if len(cfg["sections"])==1:self.message("Keep at least one section.");return
        cfg["sections"]=[s for s in cfg["sections"] if s["id"]!=self.section.value];self.config=cfg
        self.recipes.value=list(dict.fromkeys(s["preset"] for s in cfg["sections"] if s["preset"]!="custom"))
        self.restyle();self.refresh_sections();self.changed(None,None,None)

    def pick_color(self,attr,old,new):
        if self.color_label.value:self.color.color=color_for(self.color_label.value,self.config.get("colors",{}))

    def change_color(self,clear):
        if self.app.job or not self.color_label.value:return
        self.config=self.current();colors=self.config.setdefault("colors",{})
        if clear:colors.pop(self.color_label.value,None)
        else:colors[self.color_label.value]=self.color.color
        # Global color edits supersede any section-specific color override.
        for s in self.config["sections"]:s.get("plot",{}).pop("colors",None)
        self.restyle();self.changed(None,None,None);self.message("Series colors updated; no queries ran.")

    def change_order(self):
        if self.app.job:return
        self.config=self.current();self.config["series_order"]=list(dict.fromkeys(v.strip() for v in self.order.value.splitlines() if v.strip()))
        for s in self.config["sections"]:s.get("plot",{}).pop("series_order",None)
        self.restyle();self.changed(None,None,None)

    def add_formula(self):
        if self.app.job:return
        try:
            cfg=self.current();ident=self.new_id("calculated",cfg)
            cfg["sections"].append(dict(id=ident,preset="custom",title=self.formula_title.value,formula=dict(left=self.left.value,right=self.right.value,operation=self.formula_op.value,scope=self.scope.value)))
            self.config=validate_analysis(cfg)[1];self.refresh_sections();self.section.value=ident
            self.message("Calculated section added. Press Build analysis to calculate it.")
        except Exception as exc:self.message("Cannot add formula: "+str(exc))

    def save_config(self):
        try:self.text.value=json.dumps(self.current(),indent=2);self.message("Configuration ready to download. Keep source paths and IDs private.")
        except Exception as exc:self.message("Cannot save configuration: "+str(exc))

    def load_config(self):
        if self.app.job:self.message("Wait for the current job before loading.");return
        try:self.apply_config(json.loads(self.text.value))
        except Exception as exc:self.message("Cannot load configuration: "+str(exc))

    def upload(self,attr,old,new):
        if not new:return
        try:self.text.value=base64.b64decode(new).decode("utf-8-sig");self.load_config()
        except Exception as exc:self.message("Cannot open configuration: "+str(exc))


def pd_date(value):return datetime.date.fromisoformat(str(value)[:10])
