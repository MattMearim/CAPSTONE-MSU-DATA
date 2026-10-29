from abc import ABC, abstractmethod
from frib_ds.models import EngineeringEvent, AnalysisResult
class Processor(ABC):
    name: str; version: str="1.0"; domain: str
    @abstractmethod
    def process(self,event:EngineeringEvent)->AnalysisResult: raise NotImplementedError
