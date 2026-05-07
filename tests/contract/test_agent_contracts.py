from pydantic import BaseModel

def test_agent_1_has_run(): from agents.agent_1_requirements import RequirementsAgent; assert hasattr(RequirementsAgent,"run")
def test_agent_2_has_run(): from agents.agent_2_mapping import MappingAgent; assert hasattr(MappingAgent,"run")
def test_agent_3_has_run(): from agents.agent_3_orchestrator import EngineeringOrchestrator; assert hasattr(EngineeringOrchestrator,"run")
def test_agent_4_has_run(): from agents.agent_4_qa import QAAgent; assert hasattr(QAAgent,"run")

def test_requirements_doc_fields():
    from core.schemas import RequirementsDoc
    fields = RequirementsDoc.model_fields
    assert "summary" in fields and "acceptance_criteria" in fields and "task_breakdown" in fields

def test_schemas_are_pydantic_v2():
    import inspect, core.schemas as schemas
    for name in dir(schemas):
        obj = getattr(schemas, name)
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel:
            assert hasattr(obj,"model_fields"), f"{name} not Pydantic v2"
