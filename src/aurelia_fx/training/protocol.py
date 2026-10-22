"""Fixed pilot criteria, recorded before reading any training outcome."""
from .proof import SOURCE_MODEL,SOURCE_REVISION,SDK_REVISION

PROTOCOL=dict(version='eurusd-head-pilot-v1',model=SOURCE_MODEL,revision=SOURCE_REVISION,
    sdk_revision=SDK_REVISION,context=256,horizon=12,stride=12,epochs=3,
    optimizer='AdamW',learning_rate=1e-5,batch_size=32,seed=31,
    trainable='head only',selection='lowest validation pinball, including epoch zero',
    split='chronological 70/15/15; target boundary purge; historical data previously researched',
    forecast_gate=dict(min_windows=200,min_pinball_improvement_pct=2,
        paired_day_ci95_lower_above_zero=True,max_mae_degradation_pct=2,
        max_direction_degradation_pp=3,coverage_10_90_range_pct=[70,90]),
    financial_gate=dict(strategy='Timestral confirmed pullback; mandatory H4/H1 trend alignment',
        min_closed_trades_per_arm=20,net_positive=True,net_at_least_source=True,
        drawdown_no_worse_than_source=True,lot=.01,max_holding_bars=12,
        costs='existing execution simulator spread/slippage/commission'),
    prospective_gate=dict(min_days=7,min_closed_trades_per_arm=20),
    activation='Never automatic from this pilot. All gates and independent prospective evidence required.')

def register(memory,run_id,dataset_id):
    from datetime import datetime,timezone
    from aurelia_fx.agent_model import fingerprint
    payload=dict(run_id=run_id,dataset_id=dataset_id,protocol=PROTOCOL)
    key=fingerprint(payload)
    with memory.pool.connection() as c:
        row=c.execute("SELECT payload_json FROM project_records WHERE record_type='agent_training_lab_protocol' AND record_key=%s LIMIT 1",(key,)).fetchone()
    if not row:
        payload['registered_at']=datetime.now(timezone.utc).isoformat()
        memory.record_project_data('agent_training_lab_protocol',key,payload)
    return key
