"""Atomic feature planning, plugin dispatch, provenance and bounded composition."""
import math
from dataclasses import dataclass
from .model import EvidenceMissing
from ..bedrock import material_block,ALLOWED_MATERIALS

@dataclass
class Context:
    sources:dict
    ground:object
    boundary:object
    vertical_datum:str|None=None
    allow_estimates:bool=False
    max_feature_voxels:int=100_000
    max_total_voxels:int=2_000_000
    occupied:object=None

class ReconstructionEngine:
    def __init__(self,registry):
        self.registry=dict(registry)

    def register(self,family,generator):
        if family in self.registry:raise ValueError('Generator already registered')
        self.registry[family]=generator

    def plan(self,features,context):
        if min(context.max_feature_voxels,context.max_total_voxels)<=0:raise ValueError('Positive budgets required')
        rows={};decisions=[];seen=set()
        for feature in features:
            if feature.id in seen:raise ValueError('Duplicate feature identity: '+feature.id)
            seen.add(feature.id);staged={}
            try:
                geometry=feature.validate(context.sources,context.vertical_datum)
                generator=self.registry.get(feature.family)
                if generator is None:raise EvidenceMissing('No generator for '+feature.family)
                for cell,material in generator(feature,geometry,context):
                    if len(staged)>=context.max_feature_voxels and cell not in staged:raise EvidenceMissing('Feature budget exceeded')
                    if not all(isinstance(v,int) for v in cell):raise ValueError('Integer voxel cells required')
                    from shapely.geometry import Point
                    if not context.boundary.covers(Point(cell[0]+.5,cell[2]+.5)):
                        raise EvidenceMissing('Geometry outside park boundary')
                    if material not in ALLOWED_MATERIALS:raise EvidenceMissing('Unsupported block material')
                    expected=material_block(material)
                    if expected.base_name=='air':raise ValueError('Geometry plugins cannot carve implicitly')
                    if context.occupied:
                        occupied=context.occupied(*cell)
                        floor_replacement=feature.family in ('paving','path','plaza') and occupied is not None and occupied.base_name in ('grass_block','dirt','stone','granite','gravel','sand') and cell[1]==math.floor(context.ground(cell[0]+.5,cell[2]+.5))
                        if occupied is not None and occupied.base_name!='air' and occupied!=expected and not floor_replacement:
                            raise EvidenceMissing('Existing world collision')
                    if cell in rows and rows[cell]['material']!=material:raise EvidenceMissing('Conflicting reconstruction material')
                    if cell in staged and staged[cell]!=material:raise EvidenceMissing('Conflicting feature member material')
                    staged[cell]=material
                if not staged:raise EvidenceMissing('No reconstructable cells')
            except (EvidenceMissing,ValueError,TypeError,OverflowError) as error:
                decisions.append({'id':feature.id,'family':feature.family,'status':'withheld','reason':str(error)})
                continue
            if len(rows)+sum(k not in rows for k in staged)>context.max_total_voxels:raise ValueError('Total reconstruction budget exceeded')
            evidence={'geometry_source':feature.geometry_source,'parameters':feature.parameters,'metadata':feature.metadata}
            for (x,y,z),material in staged.items():
                key=x,y,z
                if key in rows:
                    rows[key]['evidence'].append({'feature':feature.id,**evidence});continue
                rows[key]={'x':x,'y':y,'z':z,'kind':'structure','material':material,'feature':feature.id,
                           'source':feature.geometry_source,'evidence':[{'feature':feature.id,**evidence}]}
            decisions.append({'id':feature.id,'family':feature.family,'status':'planned','voxel_cells':len(staged),
                              'geometry_source':feature.geometry_source,'estimated_parameters':[k for k,v in feature.parameters.items() if v.get('status')=='estimated']})
        return list(rows.values()),{'features':len(seen),'unique_voxel_cells':len(rows),'decisions':decisions,
                                  'registered_generators':sorted(self.registry),'status':'geometry_plan; requires world composition and export validation'}
