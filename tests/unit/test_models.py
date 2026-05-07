def test_tenant_model_has_required_fields():
    from core.models.platform import Tenant
    cols = {c.name for c in Tenant.__table__.columns}
    assert {"id","name","slug","db_url_encrypted","plan","created_at"} <= cols

def test_tenant_user_model_has_required_fields():
    from core.models.platform import TenantUser
    cols = {c.name for c in TenantUser.__table__.columns}
    assert {"id","tenant_id","email","hashed_password","role","created_at"} <= cols

def test_pipeline_run_model_has_required_fields():
    from core.models.tenant import PipelineRun
    cols = {c.name for c in PipelineRun.__table__.columns}
    assert {"id","status","current_stage","input_payload","created_by","created_at","updated_at"} <= cols

def test_gate_event_model_has_required_fields():
    from core.models.tenant import GateEvent
    cols = {c.name for c in GateEvent.__table__.columns}
    assert {"id","run_id","stage","status","reviewer_email","notes","decided_at"} <= cols
