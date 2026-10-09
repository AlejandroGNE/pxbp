"""Reported measurements and explicit analytical recipes; no inferred geography."""
from copy import deepcopy

MEASURES = {}


def measure(identifier, scope, prop, family, period="Year", aggregate="none"):
    collection = {"Generator":"SystemGenerators", "Battery":"SystemBatteries", "Region":"SystemRegions", "Emission":"SystemEmissions"}[scope]
    MEASURES[identifier] = dict(scope=scope, collection=collection, property=prop, family=family, period=period, aggregate=aggregate)


for identifier, scope, prop, family in [
    ("generation","Generator","Generation","energy"),
    ("capacity","Generator","Installed Capacity","power"),
    ("build","Generator","Capacity Built","power"),
    ("firm-capacity","Generator","Firm Capacity","power"),
    ("capacity-factor","Generator","Capacity Factor","percent"),
    ("generator-cost","Generator","Total Cost","money"),
    ("build-cost","Generator","Build Cost","money"),
    ("annualized-build-cost","Generator","Annualized Build Cost","money"),
    ("fixed-cost","Generator","Fixed Costs","money"),
    ("fom-cost","Generator","FO&M Cost","money"),
    ("levelized-cost","Generator","Levelized Cost","price"),
    ("srmc","Generator","SRMC","price"),
    ("battery-power","Battery","Generation Capacity","power"),
    ("battery-energy","Battery","Installed Capacity","energy"),
    ("battery-build-power","Battery","Generation Capacity Built","power"),
    ("battery-build-energy","Battery","Capacity Built","energy"),
    ("battery-discharge","Battery","Generation","energy"),
    ("battery-charge","Battery","Load","energy"),
    ("battery-net","Battery","Net Generation","energy"),
    ("region-load","Region","Load","energy"),
    ("region-generation","Region","Generation","energy"),
    ("curtailment","Region","Generation Curtailed","energy"),
    ("unserved-energy","Region","Unserved Energy","energy"),
    ("dump-energy","Region","Dump Energy","energy"),
    ("net-interchange","Region","Net Interchange","energy"),
    ("peak-load","Region","Planning Peak Load","power"),
    ("reserves","Region","Capacity Reserves","power"),
    ("region-capacity","Region","Generation Capacity","power"),
    ("system-cost","Region","Total System Cost","money"),
    ("generation-cost","Region","Total Generation Cost","money"),
    ("emissions","Emission","Production","mass"),
]:
    measure(identifier,scope,prop,family)

for identifier, scope, prop, family in [
    ("dispatch","Generator","Generation","power"),
    ("load","Region","Load","power"),
    ("regional-output","Region","Generation","power"),
    ("price","Region","Price","price"),
    ("curtailed-power","Region","Generation Curtailed","power"),
    ("unserved-power","Region","Unserved Energy","power"),
    ("battery-output","Battery","Generation","power"),
    ("battery-input","Battery","Load","power"),
    ("battery-net-power","Battery","Net Generation","power"),
    ("soc","Battery","SoC","percent"),
    ("interval-emissions","Emission","Production","mass"),
    ("interval-system-cost","Region","Total System Cost","money"),
    ("interval-generation-cost","Region","Total Generation Cost","money"),
]:
    measure(identifier,scope,prop,family,"Interval","category" if scope=="Generator" else "none")

FACTORS = {"power":({"MW":1,"GW":1000},"MW"),
           "energy":({"MWh":1,"GWh":1000,"TWh":1000000},"MWh"),
           "money":({"$":1,"$000":1000},"$"),
           "price":({"$/MWh":1},"$/MWh"), "percent":({"%":1},"%")}
RECIPES = {}


def recipe(identifier,title,inputs,operation="reported", *, scope="object", resolution="annual", unit="",scale=1,
           chart="Dot-Line",series="scenario",facet="object_name",note="",stack=False):
    RECIPES[identifier] = dict(title=title,inputs=inputs,operation=operation,scope=scope,resolution=resolution,
        unit=unit,scale=scale,chart=chart,series=series,facet=facet,note=note,stack=stack)


for identifier,title,inputs,unit,scale in [
    ("generation","Annual generation",["generation"],"TWh",1e-6),
    ("capacity","Installed generator capacity",["capacity"],"GW",.001),
    ("build","New generator capacity",["build"],"GW",.001),
    ("firm-capacity","Reported firm capacity",["firm-capacity"],"GW",.001),
    ("generator-cost","Reported generator total cost",["generator-cost"],"$B (reported)",1e-9),
    ("build-cost","Generator build cost",["build-cost"],"$B (reported)",1e-9),
    ("annualized-build-cost","Reported annualized build cost",["annualized-build-cost"],"$B (reported)",1e-9),
    ("fixed-cost","Reported generator fixed costs",["fixed-cost"],"$B (reported)",1e-9),
    ("fom-cost","Reported generator fixed O&M cost",["fom-cost"],"$B (reported)",1e-9),
]:
    recipe("annual-"+identifier,title,inputs,scope="category",unit=unit,scale=scale,chart="Stacked Bar",series="category_name",facet="scenario",stack=True,
           note="Annual reported measure. Distinct cost measures are not added to each other.")

for identifier,title,unit,scale in [
    ("battery-power","Battery power capacity","GW",.001),("battery-energy","Battery energy capacity","GWh",.001),
    ("battery-build-power","New battery power capacity","GW",.001),("battery-build-energy","New battery energy capacity","GWh",.001),
    ("battery-discharge","Annual battery discharge","TWh",1e-6),("battery-charge","Annual battery charging","TWh",1e-6),
    ("battery-net","Reported annual battery net energy","TWh",1e-6),
    ("region-load","Annual regional load","TWh",1e-6),("region-generation","Annual regional generation","TWh",1e-6),
    ("curtailment","Annual curtailment","TWh",1e-6),("unserved-energy","Reported annual unserved energy","GWh",.001),
    ("dump-energy","Reported annual dump energy","GWh",.001),("net-interchange","Reported annual net interchange","TWh",1e-6),
    ("peak-load","Planning peak load","GW",.001),("reserves","Reported capacity reserves","GW",.001),
    ("region-capacity","Reported regional generation capacity","GW",.001),
    ("system-cost","Reported total system cost","$B (reported)",1e-9),
    ("generation-cost","Reported total generation cost","$B (reported)",1e-9),("emissions","Reported annual emissions","",1),
]:
    recipe("annual-"+identifier,title,[identifier],unit=unit,scale=scale,note="Objects remain separate. Native emission mass units and reported cost conventions are preserved.")

recipe("generation-share","Generation shares",["generation"],"share",scope="category",unit="%",chart="Stacked Bar",series="category_name",facet="scenario",stack=True,
       note="Category generation / total reported generator generation. Differences are percentage points; this does not infer renewable classifications.")
recipe("capacity-utilization","Nominal annual capacity utilization",["generation","capacity"],"utilization",scope="category",unit="%",series="scenario",facet="category_name",
       note="Generation MWh / (reported installed MW × calendar-year hours). This is a nominal utilization metric, distinct from a reported capacity factor.")
recipe("reported-capacity-factor","Capacity-weighted reported capacity factor",["capacity-factor","capacity"],"weighted",scope="category",unit="%",facet="category_name",
       note="Sum(reported capacity factor × installed MW) / sum(installed MW). Zero capacity is undefined.")
recipe("weighted-levelized-cost","Generation-weighted reported levelized cost",["levelized-cost","generation"],"weighted",scope="category",unit="$/MWh",facet="category_name",
       note="Sum(reported levelized cost × generator MWh) / sum(generator MWh). This retains the reported cost definition.")
recipe("weighted-srmc","Generation-weighted reported short-run cost",["srmc","generation"],"weighted",scope="category",unit="$/MWh",facet="category_name")
recipe("storage-duration","Battery storage duration",["battery-energy","battery-power"],"ratio",unit="hours",note="Reported installed MWh / reported generation MW; zero power is undefined.")
recipe("battery-cycles","Battery discharge-equivalent cycles",["battery-discharge","battery-energy"],"ratio",unit="equivalent cycles",note="Annual discharged MWh / reported installed MWh. This is a throughput measure, not counted physical cycling events.")
recipe("system-cost-intensity","Reported system cost per load MWh",["system-cost","region-load"],"ratio",unit="$/MWh")
recipe("generation-cost-intensity","Reported generation cost per generated MWh",["generation-cost","region-generation"],"ratio",unit="$/MWh")
recipe("curtailment-share","Curtailment share of generation plus curtailment",["curtailment","region-generation"],"fraction",unit="%",
       note="100 × reported curtailed energy / (reported generation + reported curtailed energy).")
recipe("emission-intensity","Reported emission mass per generated MWh",["emissions","region-generation"],"cross-ratio",note="Emission objects stay separate. The denominator is the selected region's reported generation; no mass-unit conversion is inferred.")
recipe("capacity-change","Year-to-year installed capacity change",["capacity"],"change",scope="category",unit="GW",scale=.001,facet="category_name",
       note="Current installed capacity minus the preceding calendar year's capacity. This is net change, not an inferred retirement measure.")

for identifier,title,unit,scale in [
    ("dispatch","Generator dispatch","GW",.001),("load","Regional load","GW",.001),
    ("regional-output","Regional generation","GW",.001),("price","Regional price","$/MWh",1),
    ("curtailed-power","Curtailed power","GW",.001),("unserved-power","Unserved load","GW",.001),
    ("battery-output","Battery discharge power","GW",.001),("battery-input","Battery charging power","GW",.001),
    ("battery-net-power","Reported battery net power","GW",.001),("soc","Battery state of charge","%",1),
]:
    recipe("interval-"+identifier,title,[identifier],resolution="interval",scope="category" if identifier=="dispatch" else "object",
        unit=unit,scale=scale,chart="Stacked Area" if identifier=="dispatch" else "Line",series="category_name" if identifier=="dispatch" else "scenario",facet="scenario" if identifier=="dispatch" else "object_name",stack=identifier=="dispatch",
        note="Reported intervals within the selected date range; missing observations are not zero.")
recipe("battery-balance","Battery discharge and charging balance",["battery-output","battery-input"],"balance",resolution="interval",unit="GW",scale=.001,
       chart="Stacked Area",series="category_name",facet="scenario",stack=True,note="Discharge is positive; charging is negative. Objects are retained in the series labels. Net dots show the selected balance.")

for identifier,title,unit,scale in [
    ("dispatch","Monthly generator energy","TWh",1e-6),("load","Monthly load energy","TWh",1e-6),
    ("regional-output","Monthly regional generation","TWh",1e-6),("curtailed-power","Monthly curtailed energy","GWh",.001),
    ("unserved-power","Monthly unserved energy","GWh",.001),("battery-output","Monthly battery discharge","GWh",.001),
    ("battery-input","Monthly battery charging","GWh",.001),("interval-emissions","Monthly reported emissions","",1),
    ("interval-system-cost","Monthly reported system cost","$B (reported)",1e-9),
    ("interval-generation-cost","Monthly reported generation cost","$B (reported)",1e-9),
]:
    recipe("monthly-"+identifier,title,[identifier],"monthly-sum",resolution="monthly",scope="category" if identifier=="dispatch" else "object",unit=unit,scale=scale,
           chart="Stacked Bar" if identifier=="dispatch" else "Bar",series="category_name" if identifier=="dispatch" else "scenario",facet="scenario" if identifier=="dispatch" else "object_name",stack=identifier=="dispatch",
           note="Selected-window monthly subtotal. MW is integrated using each interval's duration; already reported money/mass amounts are summed once. Partial months are identified in the audit.")
recipe("monthly-price","Time-weighted monthly price",["price"],"monthly-mean",resolution="monthly",unit="$/MWh",note="Sum(price × interval hours) / observed hours, within the selected window.")
recipe("monthly-load-weighted-price","Load-weighted monthly price",["price","load"],"monthly-weighted",resolution="monthly",unit="$/MWh",note="Sum(price × load MW × interval hours) / sum(load MW × interval hours). Zero demand is undefined.")

for identifier,title,unit,scale in [("load","Load duration curve","GW",.001),("price","Price duration curve","$/MWh",1),("dispatch","Generation duration curves","GW",.001),("battery-net-power","Battery net power duration curves","GW",.001)]:
    recipe("duration-"+identifier,title,[identifier],"duration",resolution="duration",scope="category" if identifier=="dispatch" else "object",unit=unit,scale=scale,
           facet="category_name" if identifier=="dispatch" else "object_name",chart="Line",note="Duration-weighted descending distribution. Differences compare ordinates at the same exceedance percentage, not simultaneous hourly changes.")
for identifier,title,unit,scale in [("price","Price calendar heatmap","$/MWh",1),("load","Load calendar heatmap","GW",.001),("soc","Battery state-of-charge heatmap","%",1),("curtailed-power","Curtailment calendar heatmap","GW",.001)]:
    recipe("heatmap-"+identifier,title,[identifier],resolution="heatmap",unit=unit,scale=scale,chart="Heatmap",facet="scenario",note="Hour/date cells use duration-weighted means. Missing hours remain blank; objects are separate.")
for identifier,title,unit,scale in [("price","Mean daily price profile","$/MWh",1),("load","Mean daily load profile","GW",.001),("dispatch","Mean daily generation profile","GW",.001)]:
    recipe("profile-"+identifier,title,[identifier],"profile",resolution="profile",scope="category" if identifier=="dispatch" else "object",unit=unit,scale=scale,
        facet="category_name" if identifier=="dispatch" else "object_name",chart="Line",note="Duration-weighted mean for each hour of day over observed selected-window intervals.")
recipe("price-distribution","Price duration histogram",["price"],"histogram",resolution="histogram",unit="hours",chart="Bar",note="Common price bins across selected cases; bin heights are observed interval hours, not row counts.")
recipe("load-price","Load versus price",["price","load"],"scatter",resolution="scatter",unit="$/MWh",chart="Scatter",note="Prices and loads aligned by object and timestamp. Absolute view only; correlation does not establish causation.")
recipe("price-statistics","Selected-window price statistics",["price"],"statistics",resolution="statistics",unit="",chart="Bar",facet="property_name",note="Observed time-weighted mean, duration-weighted quantiles, and negative-price hours. Hours are conditional on the selected observations.")
recipe("load-statistics","Selected-window load statistics",["load"],"statistics",resolution="statistics",unit="",chart="Bar",facet="property_name",note="Observed peak, time-weighted mean, energy, and duration-weighted quantiles. Partial coverage is explicit.")
recipe("unserved-statistics","Observed unserved-load summary",["unserved-power"],"reliability",resolution="statistics",unit="",chart="Bar",facet="property_name",note="Reported unserved energy, observed positive-unserved hours, and longest contiguous observed event. These are not probabilistic reliability estimates.")

DEFAULT_ANALYSIS = ["interval-dispatch","interval-load","interval-price","battery-balance","interval-soc",
    "monthly-dispatch","monthly-load","monthly-load-weighted-price","duration-load","duration-price",
    "heatmap-price","heatmap-load","profile-load","price-distribution","load-price","price-statistics",
    "unserved-statistics","generation-share","capacity-utilization","reported-capacity-factor",
    "weighted-levelized-cost","storage-duration","battery-cycles","system-cost-intensity",
    "generation-cost-intensity","curtailment-share","emission-intensity","capacity-change"]


def get_recipe(identifier):
    if identifier not in RECIPES: raise ValueError("Unknown analysis recipe: "+str(identifier))
    return deepcopy(RECIPES[identifier])
